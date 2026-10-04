"""Вход в LMS через Telegram.

Ключ аккаунта — почта. Telegram — привязанный способ входа, а не
идентификатор пользователя: один Telegram привязывается к одному
аккаунту, у аккаунта при этом остаётся и пароль.

Три пути входа, все ведут в один аккаунт:
  1. почта + пароль — штатная регистрация Frappe;
  2. код: сайт показывает 6 цифр, ученица отправляет их боту, браузер
     опрашивает статус и входит сам (start → confirm → poll);
  3. одноразовая ссылка из бота (magic_link → magic).
"""

import re
import secrets
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_url, now_datetime

from rca_sso.security import make_token, read_token, verify_bot_request

CODE_TTL_MINUTES = 10
MAGIC_TTL_MINUTES = 15
PENDING_LIMIT_PER_HOUR = 30
DEFAULT_NEXT = "/lms"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Zа-яА-Я]{2,}$")


# ---------------------------------------------------------------- браузер


@frappe.whitelist(allow_guest=True, methods=["POST"])
def start(purpose: str = "login", next: str | None = None):
    """Начать вход. Возвращаем код для бота и токен опроса для браузера.

    Код показывается человеку и живёт 10 минут. Токен опроса остаётся в
    браузере и по нему страница узнаёт, что вход подтверждён — он не
    показывается никому, поэтому подобрать чужой вход нельзя.
    """
    if purpose not in ("login", "bind"):
        frappe.throw(_("Неизвестная цель входа"))

    if purpose == "bind" and frappe.session.user == "Guest":
        frappe.throw(_("Привязать Telegram можно только из личного кабинета"), frappe.PermissionError)

    _throttle()

    doc = frappe.get_doc(
        {
            "doctype": "Telegram Login Request",
            "code": _free_code(),
            "request_token": secrets.token_urlsafe(32),
            "purpose": purpose,
            "status": "pending",
            "user": frappe.session.user if purpose == "bind" else None,
            "expires_at": add_to_date(now_datetime(), minutes=CODE_TTL_MINUTES),
            "request_ip": frappe.local.request_ip,
            "next_url": next or "",
        }
    )
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "code": doc.code,
        "request_token": doc.request_token,
        "expires_in": CODE_TTL_MINUTES * 60,
        "bot_username": frappe.conf.get("rca_sso_bot_username") or "rca_school_bot",
    }


@frappe.whitelist(allow_guest=True, methods=["POST"])
def poll(request_token: str):
    """Проверить, подтверждён ли вход. При подтверждении — войти в этом браузере."""
    doc = frappe.db.get_value(
        "Telegram Login Request", {"request_token": request_token}, "name"
    )
    if not doc:
        return {"status": "unknown"}

    doc = frappe.get_doc("Telegram Login Request", doc)

    if doc.status == "used":
        return {"status": "used"}

    if doc.status == "confirmed":
        if not doc.user or not frappe.db.exists("User", doc.user):
            return {"status": "error", "message": _("Аккаунт не найден")}

        doc.db_set("status", "used", update_modified=False)
        frappe.db.commit()

        # Сессия выдаётся именно этому браузеру: логин происходит внутри
        # его же запроса, поэтому cookie sid уезжает тому, кто опрашивал.
        frappe.local.login_manager.login_as(doc.user)
        return {"status": "confirmed", "redirect": doc.next_url or DEFAULT_NEXT}

    if _expired(doc):
        doc.db_set("status", "expired", update_modified=False)
        frappe.db.commit()
        return {"status": "expired"}

    return {"status": "pending"}


# ------------------------------------------------------------------- бот


@frappe.whitelist(allow_guest=True, methods=["POST"])
def confirm(code: str, telegram_id: str, telegram_username: str | None = None, email: str | None = None):
    """Подтверждение кода, который ученица прислала боту.

    Если Telegram ещё не привязан к аккаунту и почты нет — просим почту:
    она нужна для чека и для входа паролем.
    """
    verify_bot_request()

    telegram_id = str(telegram_id or "").strip()
    if not telegram_id:
        return {"ok": False, "message": _("Не передан Telegram ID")}

    doc_name = frappe.db.get_value(
        "Telegram Login Request",
        {"code": str(code or "").strip(), "status": "pending"},
        "name",
    )
    if not doc_name:
        return {"ok": False, "message": _("Код не найден или уже использован. Возьмите новый на сайте.")}

    doc = frappe.get_doc("Telegram Login Request", doc_name)
    if _expired(doc):
        doc.db_set("status", "expired", update_modified=False)
        frappe.db.commit()
        return {"ok": False, "message": _("Код истёк. Возьмите новый на сайте.")}

    if doc.purpose == "bind":
        return _confirm_bind(doc, telegram_id, telegram_username)

    return _confirm_login(doc, telegram_id, telegram_username, email)


def _confirm_bind(doc, telegram_id: str, telegram_username: str | None):
    owner = _user_by_telegram(telegram_id)
    if owner and owner != doc.user:
        return {
            "ok": False,
            "message": _("Этот Telegram уже привязан к аккаунту {0}.").format(_mask_email(owner)),
        }

    _set_telegram(doc.user, telegram_id, telegram_username)
    doc.db_set({"status": "confirmed", "telegram_id": telegram_id, "confirmed_at": now_datetime()})
    frappe.db.commit()
    return {"ok": True, "purpose": "bind", "email": doc.user, "redirect": doc.next_url or DEFAULT_NEXT}


def _confirm_login(doc, telegram_id: str, telegram_username: str | None, email: str | None):
    user = _user_by_telegram(telegram_id)

    if not user:
        if not email:
            return {
                "ok": False,
                "needs_email": True,
                "message": _("Этот Telegram ещё не привязан. Пришлите почту, на которую зарегистрировать аккаунт."),
            }
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            return {"ok": False, "needs_email": True, "message": _("Похоже, в адресе опечатка. Пришлите почту ещё раз.")}

        if frappe.db.exists("User", email):
            # Аккаунт с такой почтой есть, но Telegram к нему не привязан —
            # привязывать по одному лишь коду нельзя, это был бы угон аккаунта.
            return {
                "ok": False,
                "message": _(
                    "Аккаунт с этой почтой уже есть. Войдите на сайте по почте и привяжите Telegram в личном кабинете."
                ),
            }

        user = _create_student(email, telegram_username)
        _set_telegram(user, telegram_id, telegram_username)

    doc.db_set(
        {
            "status": "confirmed",
            "user": user,
            "telegram_id": telegram_id,
            "confirmed_at": now_datetime(),
        }
    )
    frappe.db.commit()
    return {"ok": True, "purpose": "login", "email": user, "redirect": doc.next_url or DEFAULT_NEXT}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def whoami(telegram_id: str):
    """Привязан ли этот Telegram к аккаунту — для приветствия в боте."""
    verify_bot_request()
    user = _user_by_telegram(str(telegram_id or "").strip())
    return {"linked": bool(user), "email": _mask_email(user) if user else None}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def magic_link(telegram_id: str, telegram_username: str | None = None, next: str | None = None):
    """Одноразовая ссылка входа для ученицы — для тёплых лидов из воронки."""
    verify_bot_request()

    user = _user_by_telegram(str(telegram_id or "").strip())
    if not user:
        frappe.throw(_("Telegram не привязан к аккаунту школы"))

    nonce = secrets.token_urlsafe(16)
    frappe.cache.set_value(f"rca_sso_magic:{nonce}", user, expires_in_sec=MAGIC_TTL_MINUTES * 60)

    token = make_token({"n": nonce, "u": user, "next": next or DEFAULT_NEXT})
    return {"url": get_url(f"/api/method/rca_sso.api.magic?token={token}")}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def magic(token: str):
    """Вход по одноразовой ссылке."""
    payload = read_token(token or "")
    if not payload:
        frappe.throw(_("Ссылка недействительна"))

    nonce = payload.get("n")
    user = frappe.cache.get_value(f"rca_sso_magic:{nonce}")
    if not user or user != payload.get("u"):
        frappe.throw(_("Ссылка уже использована или истекла"))
    frappe.cache.delete_value(f"rca_sso_magic:{nonce}")

    if not frappe.db.exists("User", user):
        frappe.throw(_("Аккаунт не найден"))

    frappe.local.login_manager.login_as(user)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = payload.get("next") or DEFAULT_NEXT


# --------------------------------------------------------- вспомогательное


def _expired(doc) -> bool:
    return bool(doc.expires_at and doc.expires_at < now_datetime())


def _free_code() -> str:
    """Шестизначный код, который сейчас ни у кого не висит."""
    for _ in range(20):
        code = f"{secrets.randbelow(1_000_000):06d}"
        taken = frappe.db.exists(
            "Telegram Login Request",
            {"code": code, "status": "pending", "expires_at": [">", now_datetime()]},
        )
        if not taken:
            return code
    frappe.throw(_("Не удалось выдать код, попробуйте ещё раз"))


def _throttle() -> None:
    """Ограничиваем число незавершённых попыток входа с одного адреса."""
    ip = frappe.local.request_ip
    if not ip:
        return
    since = add_to_date(now_datetime(), hours=-1)
    count = frappe.db.count(
        "Telegram Login Request",
        {"request_ip": ip, "creation": [">", since]},
    )
    if count >= PENDING_LIMIT_PER_HOUR:
        frappe.throw(_("Слишком много попыток входа. Попробуйте через час."), frappe.ValidationError)


def _user_by_telegram(telegram_id: str) -> str | None:
    if not telegram_id:
        return None
    return frappe.db.get_value("User", {"telegram_id": telegram_id}, "name")


def _create_student(email: str, telegram_username: str | None) -> str:
    first_name = (telegram_username or "").strip() or "Ученица"
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": first_name[:140],
            "enabled": 1,
            "user_type": "Website User",
            "send_welcome_email": 0,
        }
    )
    user.flags.ignore_permissions = True
    user.insert(ignore_permissions=True)
    user.append_roles("LMS Student")
    frappe.db.commit()
    return user.name


def _set_telegram(user: str, telegram_id: str, telegram_username: str | None) -> None:
    frappe.db.set_value(
        "User",
        user,
        {"telegram_id": telegram_id, "telegram_username": (telegram_username or "")[:140]},
        update_modified=False,
    )
    frappe.db.commit()


def _mask_email(email: str | None) -> str | None:
    """В боте показываем почту частично — целиком её знать незачем."""
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        return f"{name[0]}***@{domain}"
    return f"{name[:2]}***@{domain}"

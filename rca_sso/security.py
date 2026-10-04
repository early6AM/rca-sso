"""Общая защита эндпоинтов: подпись запросов от бота и служебные утилиты.

Эндпоинты, которые вызывает Telegram-бот, открыты гостю (бот не умеет
логиниться в Frappe), поэтому единственная защита — HMAC-подпись тела
запроса общим секретом. Секрет живёт в конфиге сайта, не в коде.
"""

import hashlib
import hmac

import frappe
from frappe import _

SECRET_KEY = "rca_sso_secret"


def get_secret() -> str:
    secret = frappe.conf.get(SECRET_KEY)
    if not secret:
        frappe.throw(
            _("Не задан {0} в конфиге сайта — вход через Telegram не настроен.").format(SECRET_KEY)
        )
    return str(secret)


def sign(payload: str) -> str:
    return hmac.new(get_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify(raw_body: str, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(raw_body), signature)


def verify_bot_request() -> None:
    """Проверяем подпись тела запроса. Вызывается в начале метода для бота."""
    raw_body = frappe.request.get_data(as_text=True) if frappe.request else ""
    signature = frappe.get_request_header("X-SSO-Signature")
    if not verify(raw_body, signature):
        frappe.throw(_("Неверная подпись запроса"), frappe.AuthenticationError)


def make_token(payload: dict) -> str:
    """Подписанный токен для одноразовой ссылки входа."""
    import base64
    import json

    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    return f"{body}.{sign(body)}"


def read_token(token: str) -> dict | None:
    import base64
    import json

    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not verify(body, signature):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(body.encode()).decode())
    except Exception:
        return None

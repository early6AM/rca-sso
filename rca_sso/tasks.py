"""Периодические задачи приложения."""

import frappe
from frappe.utils import add_to_date, now_datetime


def cleanup_expired_requests():
    """Убираем заявки на вход, которым больше суток.

    Коды живут 10 минут, но строки остаются — по ним потом видно историю
    входов. Через сутки история уже не нужна, а таблица растёт.
    """
    cutoff = add_to_date(now_datetime(), days=-1)
    old = frappe.get_all(
        "Telegram Login Request",
        filters={"creation": ["<", cutoff]},
        pluck="name",
        limit=5000,
    )
    for name in old:
        frappe.delete_doc("Telegram Login Request", name, ignore_permissions=True, delete_permanently=True)
    if old:
        frappe.db.commit()
        print(f"rca_sso: удалено просроченных заявок — {len(old)}")

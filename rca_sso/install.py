"""Установка приложения: поля Telegram на User и запись в настройках сайта."""

import frappe


def after_install():
    create_custom_fields()
    print("rca_sso: поля Telegram на User заведены")


def create_custom_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(
        {
            "User": [
                {
                    "fieldname": "telegram_id",
                    "fieldtype": "Data",
                    "label": "Telegram ID",
                    "unique": 1,
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "username",
                    "description": "Привязанный Telegram. Один Telegram — один аккаунт.",
                },
                {
                    "fieldname": "telegram_username",
                    "fieldtype": "Data",
                    "label": "Telegram username",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "telegram_id",
                },
            ],
        },
        ignore_validate=True,
    )

app_name = "rca_sso"
app_title = "RCA SSO"
app_publisher = "RCA Yachts"
app_description = "Вход в LMS через Telegram: коды входа, привязка аккаунта, magic link"
app_email = "hello@rca.yachts"
app_license = "mit"

# Свой доктайп заводим при установке.
after_install = "rca_sso.install.after_install"

# Кнопка «Войти через Telegram» на странице входа.
# Страница входа — это ядро frappe (data-path="login"), а не фронтенд lms,
# поэтому кнопку добавляет скрипт приложения, а не пересборка Vue.
web_include_js = "/assets/rca_sso/js/telegram_login.js"

# Раз в сутки убираем просроченные заявки на вход, чтобы таблица не росла.
scheduler_events = {
    "daily": ["rca_sso.tasks.cleanup_expired_requests"],
}

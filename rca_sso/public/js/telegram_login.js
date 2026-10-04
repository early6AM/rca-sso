/**
 * Кнопка «Войти через Telegram» на странице входа.
 *
 * Страница входа — это ядро Frappe, а не фронтенд lms, поэтому кнопка
 * добавляется скриптом приложения. Поток: сайт показывает код → ученица
 * отправляет его боту → страница сама входит в том же окне браузера.
 */

(function () {
	"use strict";

	var POLL_MS = 2000;
	var STYLE_ID = "rca-sso-style";

	function isLoginPage() {
		return document.body && document.body.getAttribute("data-path") === "login";
	}

	function csrfToken() {
		return (window.frappe && window.frappe.csrf_token) || "";
	}

	function serverMessage(json) {
		try {
			var raw = JSON.parse(json._server_messages || "[]");
			var first = JSON.parse(raw[0]);
			return first.message || "";
		} catch (e) {
			return json.exc_type || "Не получилось выполнить запрос";
		}
	}

	function api(method, params) {
		var body = new URLSearchParams(params || {}).toString();
		return fetch("/api/method/" + method, {
			method: "POST",
			credentials: "same-origin",
			headers: {
				"Content-Type": "application/x-www-form-urlencoded",
				"X-Frappe-CSRF-Token": csrfToken(),
			},
			body: body,
		}).then(function (response) {
			return response.json().then(function (json) {
				if (json.exc_type) throw new Error(serverMessage(json));
				return json.message;
			});
		});
	}

	function injectStyles() {
		if (document.getElementById(STYLE_ID)) return;
		var style = document.createElement("style");
		style.id = STYLE_ID;
		style.textContent = [
			".rca-sso-block{margin-top:18px;padding-top:18px;border-top:1px solid #e2e2e2;text-align:center}",
			".rca-sso-btn{display:inline-flex;align-items:center;gap:8px;justify-content:center;width:100%;",
			"padding:10px 16px;border:1px solid #d0d5dd;border-radius:8px;background:#fff;color:#1f2937;",
			"font-size:15px;font-weight:500;cursor:pointer;transition:background .15s}",
			".rca-sso-btn:hover{background:#f7f8fa}",
			".rca-sso-hint{margin-top:10px;font-size:12px;color:#6b7280;line-height:1.5}",
			".rca-sso-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;",
			"align-items:center;justify-content:center;z-index:9999;padding:16px}",
			".rca-sso-modal{background:#fff;border-radius:14px;max-width:420px;width:100%;padding:28px;",
			"text-align:center;box-shadow:0 20px 50px rgba(15,23,42,.25);font-family:inherit}",
			".rca-sso-title{font-size:19px;font-weight:600;color:#111827;margin:0 0 6px}",
			".rca-sso-sub{font-size:14px;color:#6b7280;line-height:1.55;margin:0 0 20px}",
			".rca-sso-code{font-size:38px;font-weight:700;letter-spacing:.16em;color:#111827;",
			"background:#f4f5f7;border-radius:10px;padding:16px 8px;margin-bottom:20px;user-select:all}",
			".rca-sso-open{display:inline-block;width:100%;padding:11px 16px;border-radius:8px;",
			"background:#229ED9;color:#fff;font-size:15px;font-weight:600;text-decoration:none;box-sizing:border-box}",
			".rca-sso-open:hover{background:#1d8ec4;color:#fff;text-decoration:none}",
			".rca-sso-status{margin-top:16px;font-size:13px;color:#6b7280;min-height:18px}",
			".rca-sso-cancel{margin-top:12px;background:none;border:none;color:#6b7280;font-size:13px;",
			"cursor:pointer;text-decoration:underline}",
			".rca-sso-error{color:#b42318}",
		].join("");
		document.head.appendChild(style);
	}

	function openModal(state) {
		injectStyles();

		var overlay = document.createElement("div");
		overlay.className = "rca-sso-overlay";

		var modal = document.createElement("div");
		modal.className = "rca-sso-modal";
		modal.innerHTML = [
			'<h3 class="rca-sso-title">Вход через Telegram</h3>',
			'<p class="rca-sso-sub">Отправьте этот код боту — вход произойдёт в этом же окне.</p>',
			'<div class="rca-sso-code">' + state.code + "</div>",
			'<a class="rca-sso-open" target="_blank" rel="noopener" href="https://t.me/' +
				state.bot_username +
				'?start=login">Открыть Telegram</a>',
			'<div class="rca-sso-status">Ждём подтверждения…</div>',
			'<button class="rca-sso-cancel" type="button">Отменить</button>',
		].join("");

		var status = modal.querySelector(".rca-sso-status");
		var cancel = modal.querySelector(".rca-sso-cancel");

		cancel.addEventListener("click", function () {
			state.stopped = true;
			document.body.removeChild(overlay);
		});

		overlay.appendChild(modal);
		document.body.appendChild(overlay);

		state.setStatus = function (text, isError) {
			status.textContent = text;
			status.className = "rca-sso-status" + (isError ? " rca-sso-error" : "");
		};
		state.close = function () {
			if (overlay.parentNode) document.body.removeChild(overlay);
		};

		return state;
	}

	function poll(state) {
		if (state.stopped) return;

		api("rca_sso.api.poll", { request_token: state.request_token })
			.then(function (result) {
				if (state.stopped) return;

				if (result.status === "confirmed") {
					state.setStatus("Готово! Входим…");
					window.location.href = result.redirect || "/lms";
					return;
				}
				if (result.status === "expired" || result.status === "unknown" || result.status === "used") {
					state.setStatus("Код истёк. Закройте окно и попробуйте снова.", true);
					return;
				}
				setTimeout(function () {
					poll(state);
				}, POLL_MS);
			})
			.catch(function (error) {
				if (state.stopped) return;
				state.setStatus(error.message || "Не удалось проверить вход", true);
			});
	}

	function beginLogin(button) {
		button.disabled = true;
		button.textContent = "Готовим код…";

		api("rca_sso.api.start", { purpose: "login" })
			.then(function (data) {
				var state = openModal(data);
				poll(state);
			})
			.catch(function (error) {
				window.alert(error.message || "Не удалось начать вход через Telegram");
			})
			.finally(function () {
				button.disabled = false;
				button.textContent = "Войти через Telegram";
			});
	}

	function buildBlock() {
		var block = document.createElement("div");
		block.className = "rca-sso-block";

		var button = document.createElement("button");
		button.type = "button";
		button.className = "rca-sso-btn";
		button.textContent = "Войти через Telegram";
		button.addEventListener("click", function () {
			beginLogin(button);
		});

		var hint = document.createElement("p");
		hint.className = "rca-sso-hint";
		hint.textContent =
			"Вход без пароля: сайт покажет код, вы отправите его боту. " +
			"Если вы уже заходили по почте, тем же способом Telegram привяжется к вашему аккаунту.";

		block.appendChild(button);
		block.appendChild(hint);
		return block;
	}

	function mount() {
		if (!isLoginPage()) return;

		var form = document.querySelector("form.form-signin, form[data-testid='login-form'], .login-content form");
		var container = form ? form.parentNode : document.querySelector(".login-content, .page_content");
		if (!container) return;
		if (container.querySelector(".rca-sso-block")) return;

		container.appendChild(buildBlock());
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", mount);
	} else {
		mount();
	}
})();

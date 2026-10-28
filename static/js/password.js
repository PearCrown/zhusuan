"use strict";
(() => {
  const form = document.getElementById("password-form");
  const status = document.getElementById("password-status");
  const button = document.getElementById("password-submit");
  let busy = false;
  let epoch = 0;
  function clear() { form.querySelectorAll("input").forEach(input => { input.value = ""; }); }
  function message(text, error = false) { status.textContent = text; status.classList.toggle("error", error); }
  async function request(path, payload, token) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal };
      if (payload) Object.assign(options, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token }, body: JSON.stringify(payload) });
      const response = await fetch(path, options);
      const body = await response.json();
      if (!response.ok || body.ok !== true) {
        const error = new Error("操作失败");
        error.code = body.error?.code;
        error.text = body.error?.message;
        error.fields = body.error?.fields;
        error.wait = response.headers.get("Retry-After");
        throw error;
      }
      return body.data;
    } finally { clearTimeout(timer); }
  }
  function showLogin() {
    const back = document.getElementById("password-back");
    if (back) back.hidden = true;
    document.getElementById("password-login").hidden = false;
  }
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (busy) return;
    const payload = Object.fromEntries(new FormData(form));
    clear();
    if (payload.newPassword !== payload.confirm) {
      message("两次新密码不一致。输入已清空，请重新填写。", true);
      return;
    }
    delete payload.confirm;
    busy = true;
    const started = epoch;
    button.disabled = true;
    form.querySelectorAll("input").forEach(input => { input.disabled = true; });
    message("正在更新，请勿重复提交…");
    (async () => {
      try {
        const csrf = await request("/auth/csrf");
        if (started !== epoch) return;
        await request(`/auth/password/${form.dataset.mode}`, payload, csrf.csrfToken);
        if (started !== epoch) return;
        form.hidden = true;
        showLogin();
        message("密码已更新，所有旧登录已失效。请重新登录。");
      } catch (error) {
        if (started !== epoch) return;
        const known = ["validation_error", "current_password_invalid", "reset_invalid", "invalid_fields"];
        if (known.includes(error.code)) {
          const fields = Object.values(error.fields || {}).flat().join(" ");
          message(`${error.text || "请检查输入。"} ${fields} 输入已清空，请重新填写。`, true);
        } else if (error.code === "csrf_failed") message("安全校验已变化，请重新填写后提交。", true);
        else if (error.code === "authentication_required") {
          form.hidden = true;
          showLogin();
          message("登录已失效，请重新登录。", true);
        } else if (error.code === "rate_limited") message(`操作过于频繁，请稍后重试${error.wait ? `（约${error.wait}秒）` : ""}。`, true);
        else {
          showLogin();
          message("结果未确认，请尝试使用新密码登录；若仍失败，再联系维护人员。不要连续重复提交。", true);
        }
      } finally {
        payload.newPassword = "";
        payload.currentPassword = "";
        payload.credential = "";
        busy = false;
        button.disabled = false;
        form.querySelectorAll("input").forEach(input => { input.disabled = false; });
      }
    })();
  });
  function hide() { epoch += 1; clear(); message("输入已清空。若刚才已提交，请先尝试新密码登录。"); }
  window.addEventListener("pagehide", hide);
  window.addEventListener("pageshow", () => clear());
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); });
})();

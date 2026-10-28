/* Same-origin account UI. Credentials and identity are never persisted by this code. */
"use strict";
(() => {
  const byId = (id) => document.getElementById(id);
  const forms = { login: byId("login-form"), register: byId("register-form") };
  let busy = false;
  let pendingRefresh = false;
  let epoch = 0;
  let mode = "login";

  class RequestError extends Error {
    constructor(code, message, fields = {}, retryAfter = null) {
      super(message);
      this.code = code;
      this.fields = fields;
      this.retryAfter = retryAfter;
    }
  }

  function message(text, error = false) {
    byId("status").textContent = text;
    byId("status").classList.toggle("error", error);
  }

  function clearPasswords() {
    document.querySelectorAll('input[type="password"]').forEach((input) => { input.value = ""; });
  }

  function clearIdentity() {
    byId("identity").hidden = true;
    byId("teacher-link").hidden = true;
    ["welcome", "identity-username", "identity-roles", "identity-class", "identity-teaching"].forEach((id) => {
      byId(id).textContent = "";
    });
    byId("teaching-row").hidden = true;
  }

  function clearErrors() {
    document.querySelectorAll(".field-error").forEach((item) => { item.textContent = ""; });
    document.querySelectorAll("input").forEach((input) => { input.removeAttribute("aria-invalid"); });
  }

  function selectMode(next, focus = false) {
    mode = next;
    clearPasswords();
    clearErrors();
    for (const name of ["login", "register"]) {
      forms[name].hidden = name !== mode;
      byId(`show-${name}`).setAttribute("aria-pressed", String(name === mode));
    }
    if (focus) byId(`${mode}-username`).focus();
  }

  function showGuest() {
    clearIdentity();
    byId("guest").hidden = false;
    byId("retry").hidden = true;
  }

  function showIdentity(user) {
    // Render all server/user-controlled text with textContent, never HTML.
    clearIdentity();
    clearPasswords();
    byId("guest").hidden = true;
    byId("retry").hidden = true;
    byId("welcome").textContent = `你好，${user.displayName}`;
    byId("identity-username").textContent = user.username;
    const names = { student: "学生", teacher: "教师", maintainer: "维护人员" };
    byId("identity-roles").textContent = user.roles.map((role) => names[role] || "未识别身份").join("、") || "暂未分配";
    byId("identity-class").textContent = user.classId || "暂未分班";
    if (user.roles.includes("teacher")) {
      byId("teacher-link").hidden = false;
      byId("teaching-row").hidden = false;
      byId("identity-teaching").textContent = user.teachingClassIds.join("、") || "暂未授权班级";
    }
    byId("identity").hidden = false;
  }

  function unknownState(text) {
    clearIdentity();
    clearPasswords();
    byId("guest").hidden = true;
    byId("retry").hidden = false;
    message(text, true);
  }

  async function request(path, payload, token) {
    const started = epoch;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" } };
      if (payload !== undefined) {
        options.method = "POST";
        options.headers["Content-Type"] = "application/json";
        options.headers["X-CSRFToken"] = token;
        options.body = JSON.stringify(payload);
      }
      const response = await fetch(path, options);
      const body = await response.json();
      if (started !== epoch) throw new RequestError("stale", "页面状态已变化。");
      if (!response.ok || body.ok !== true) {
        throw new RequestError(body.error?.code || "response_error", body.error?.message || "服务暂不可用。", body.error?.fields, response.headers.get("Retry-After"));
      }
      return body.data;
    } catch (error) {
      if (started !== epoch) throw new RequestError("stale", "页面状态已变化。");
      if (error instanceof RequestError) throw error;
      throw new RequestError("network", "连接中断或服务响应异常，请检查连接后重试。");
    } finally {
      clearTimeout(timeout);
    }
  }

  async function post(path, payload) {
    // Refresh before every mutation: another tab may have rotated the CSRF cookie.
    // Do not replay mutations automatically after a timeout or CSRF failure.
    const csrf = await request("/auth/csrf");
    return request(path, payload, csrf.csrfToken);
  }

  async function reconcile(note = "", warning = false, anonymousNote = "") {
    clearIdentity();
    byId("guest").hidden = true;
    byId("retry").hidden = true;
    try {
      const user = await request("/auth/me");
      showIdentity(user);
      message(note || "已登录，身份信息已同步。", warning);
    } catch (error) {
      if (error.code === "stale") return;
      if (error.code === "authentication_required") {
        selectMode("login");
        showGuest();
        message(anonymousNote || (note ? `${note} 当前未登录，请重新登录。` : "当前未登录。你可以登录，或注册学生账号。"), warning || Boolean(anonymousNote));
      } else {
        unknownState(`${note ? `${note} ` : ""}暂时无法确认登录状态，请重新确认。`);
      }
    }
  }

  async function run(action) {
    if (busy) return;
    busy = true;
    document.querySelectorAll("button, input").forEach((item) => { item.disabled = true; });
    try {
      await action();
    } catch (error) {
      if (error.code !== "stale") unknownState("操作未能完成，请重新确认当前状态。");
    } finally {
      busy = false;
      document.querySelectorAll("button, input").forEach((item) => { item.disabled = false; });
      const invalid = document.querySelector('form:not([hidden]) input[aria-invalid="true"]');
      if (invalid) invalid.focus();
      if (pendingRefresh && !document.hidden) {
        pendingRefresh = false;
        void run(() => reconcile());
      }
    }
  }

  function fieldErrors(formMode, fields) {
    for (const [key, errors] of Object.entries(fields || {})) {
      const input = byId(`${formMode}-${key}`);
      const target = byId(`${formMode}-${key}-error`);
      if (input && target && Array.isArray(errors)) {
        input.setAttribute("aria-invalid", "true");
        target.textContent = errors.join(" ");
      }
    }
  }

  function failure(error, formMode) {
    fieldErrors(formMode, error.fields);
    if (error.code === "username_taken") fieldErrors(formMode, { username: [error.message] });
    let text = error.message;
    if (error.code === "rate_limited") {
      const seconds = Number(error.retryAfter);
      text = Number.isFinite(seconds) && seconds > 0 ? `操作过于频繁，请在约${Math.ceil(seconds)}秒后重试。` : text;
    }
    if (error.code === "csrf_failed") text = "安全校验已更新，请重新填写密码后提交。若反复出现，请检查浏览器是否允许本站 Cookie。";
    message(text, true);
  }

  for (const name of ["login", "register"]) {
    byId(`show-${name}`).addEventListener("click", () => {
      if (busy) return;
      selectMode(name, true);
      message(name === "login" ? "请输入用户名和密码。" : "新账号将注册为学生，教师身份由维护人员分配。");
    });
    forms[name].addEventListener("submit", (event) => {
      event.preventDefault();
      if (busy) return;
      clearErrors();
      const data = Object.fromEntries(new FormData(forms[name]));
      const missing = {};
      for (const [key, value] of Object.entries(data)) {
        if (!value) missing[key] = ["请填写此字段。"];
      }
      if (name === "register" && data.password !== data.confirm) missing.confirm = ["两次密码不一致，请重新输入。"];
      if (Object.keys(missing).length) {
        clearPasswords();
        fieldErrors(name, missing);
        message("请检查填写内容；密码已清空，请重新输入。", true);
        document.querySelector('input[aria-invalid="true"]')?.focus();
        return;
      }
      delete data.confirm; // Confirmation is UI-only; the API accepts a strict whitelist.
      clearPasswords();
      void run(async () => {
        message(name === "login" ? "正在登录…" : "正在创建账号…");
        try {
          const result = await post(`/auth/${name}`, data);
          if (name === "register") {
            forms.register.reset();
            selectMode("login");
            byId("login-username").value = result.username;
            message("注册成功！请使用刚才设置的密码登录。");
          } else {
            // Verify that the browser actually retained the HttpOnly session cookie.
            await reconcile("", false, "当前未登录：未能保留登录会话，或会话已失效。请检查本站 Cookie 是否被禁用，再重新登录。");
          }
        } catch (error) {
          if (error.code === "stale") return;
          if (["network", "service_unavailable", "internal_error", "response_error", "authentication_required"].includes(error.code)) {
            const note = name === "register" ? "注册结果尚未确认；如再次提交提示用户名已使用，请尝试登录。" : "登录结果尚未确认。";
            await reconcile(note, true);
          } else {
            failure(error, name);
          }
        } finally {
          // Drop the captured password as soon as the request finishes, too.
          data.password = "";
        }
      });
    });
  }

  byId("refresh").addEventListener("click", () => { void run(() => reconcile()); });
  byId("retry").addEventListener("click", () => { void run(() => reconcile()); });
  byId("logout").addEventListener("click", () => {
    void run(async () => {
      clearIdentity();
      message("正在退出登录…");
      try {
        await post("/auth/logout", {});
        await reconcile("退出请求已完成。");
      } catch (error) {
        if (error.code !== "stale") await reconcile("退出结果尚未确认，请核对当前状态；若仍登录，可再次退出。", true);
      }
    });
  });

  function refreshOnReturn() {
    if (document.hidden) return;
    if (busy) pendingRefresh = true;
    else void run(() => reconcile());
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      epoch += 1;
      clearIdentity();
      clearPasswords();
      byId("guest").hidden = true;
      message("返回页面时将重新确认身份。");
    } else refreshOnReturn();
  });
  window.addEventListener("pagehide", () => {
    epoch += 1;
    clearIdentity();
    clearPasswords();
    byId("guest").hidden = true;
  });
  window.addEventListener("pageshow", refreshOnReturn);
  // pageshow covers the initial page and back/forward cache restoration.
})();

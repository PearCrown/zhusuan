"use strict";
(() => {
  const id = x => document.getElementById(x);
  let challenge = null, busy = false, epoch = 0;
  function message(text) { id("code-status").textContent = text; }
  function clearSecrets() { for (const name of ["code-password", "code-value", "code-new-password", "code-confirm"]) id(name).value = ""; }
  function reset() { epoch++; challenge = null; clearSecrets(); id("code-destination").value = ""; id("code-verify").hidden = true; id("code-request").hidden = false; }
  function mode() { reset(); id("code-reauth").hidden = id("code-purpose").value !== "bind"; id("code-new").hidden = id("code-purpose").value !== "reset"; message("请选择联系方式后申请验证码。"); }
  async function request(path, payload, csrf) {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal };
      if (payload) Object.assign(options, {method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":csrf},body:JSON.stringify(payload)});
      const response = await fetch(path, options); const body = await response.json();
      if (!response.ok || !body.ok) throw Object.assign(new Error("请求未确认"), {code:body.error?.code, text:body.error?.message});
      return body.data;
    } finally { clearTimeout(timer); }
  }
  async function run(stage, payload) {
    if (busy) return; busy = true; const started = epoch, purpose = id("code-purpose").value;
    document.querySelectorAll("button,input,select").forEach(x => {x.disabled=true;}); clearSecrets(); message("正在处理，请勿重复提交…");
    try {
      const csrf = await request("/auth/csrf"); if (started !== epoch) return;
      const result = await request(`/auth/code/${purpose}/${stage}`, payload, csrf.csrfToken); if (started !== epoch) return;
      if (stage === "request") { challenge = result.challengeId; id("code-verify").hidden=false; message("若此操作可用，验证码将发送至指定地址。5分钟有效；重新申请会替换本浏览器旧验证码。"); }
      else { challenge=null; id("code-verify").hidden=true; message(purpose === "login" ? "已登录。请返回账号中心确认身份。" : "操作已完成，所有旧登录已失效，请返回账号中心重新登录。"); }
    } catch (error) {
      if (started !== epoch) return;
      message(error.code ? error.text : "操作结果未确认。请先返回账号中心检查登录状态；若刚才重置密码，请尝试新密码登录。不要连续重复提交。");
      if (!error.code) { challenge=null; id("code-verify").hidden=true; }
    } finally { busy=false; document.querySelectorAll("button,input,select").forEach(x => {x.disabled=false;}); }
  }
  id("code-request").addEventListener("submit", event => {
    event.preventDefault(); if (busy) return;
    challenge=null; id("code-verify").hidden=true;
    const payload = {kind:id("code-kind").value,destination:id("code-destination").value};
    if (id("code-purpose").value === "bind") payload.currentPassword=id("code-password").value;
    void run("request",payload);
  });
  id("code-verify").addEventListener("submit", event => {
    event.preventDefault(); if (busy || !challenge) return;
    const payload = {challengeId:challenge,code:id("code-value").value};
    if (id("code-purpose").value === "reset") {
      if (id("code-new-password").value !== id("code-confirm").value) {clearSecrets();message("两次新密码不一致，请重新填写。");return;}
      payload.newPassword=id("code-new-password").value;
    }
    void run("verify",payload);
  });
  id("code-purpose").addEventListener("change",mode);
  function changedAddress() {challenge=null;clearSecrets();id("code-verify").hidden=true;message("联系方式已变化，请重新申请验证码。");}
  id("code-destination").addEventListener("input",changedAddress);
  id("code-kind").addEventListener("change",changedAddress);
  function hide() {reset();message("输入与验证进度已清空，请重新申请。");}
  document.addEventListener("visibilitychange",() => {if (document.hidden) hide();});
  window.addEventListener("pagehide",hide); window.addEventListener("pageshow",hide);
  mode();
})();

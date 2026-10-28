"use strict";
(() => {
  const id = (name) => document.getElementById(name);
  let busy = false;
  let pending = false;
  let epoch = 0;
  let classPage = 1;
  let studentPage = 1;
  let selected = null;

  function status(text, error = false) {
    id("teacher-status").textContent = text;
    id("teacher-status").classList.toggle("error", error);
  }
  function clearRoster() {
    id("roster").hidden = true;
    id("roster-title").textContent = "";
    id("roster-summary").textContent = "";
    id("students-body").replaceChildren();
    id("students-prev").hidden = true;
    id("students-next").hidden = true;
  }
  function clearAll() {
    clearRoster();
    selected = null;
    id("class-list").replaceChildren();
    id("classes-prev").hidden = true;
    id("classes-next").hidden = true;
  }
  async function fetchData(url, csv = false) {
    const started = epoch;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: csv ? "text/csv, application/json" : "application/json" } });
      const contentType = response.headers.get("Content-Type") || "";
      let data;
      if (csv && response.ok && contentType.startsWith("text/csv")) data = await response.blob();
      else {
        const body = await response.json();
        if (!response.ok || body.ok !== true) throw Object.assign(new Error("请求未完成"), { code: body.error?.code });
        if (csv) throw new Error("导出响应无效，请刷新授权班级后重试。");
        data = body.data;
      }
      if (started !== epoch) throw Object.assign(new Error("页面状态已变化"), { stale: true });
      return data;
    } catch (error) {
      if (started !== epoch) throw Object.assign(new Error("页面状态已变化"), { stale: true });
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function run(action) {
    if (busy) return;
    busy = true;
    document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    try { await action(); }
    catch (error) {
      if (!error.stale) {
        clearAll();
        const messages = {
          authentication_required: "登录已失效，请返回账号中心重新登录。",
          teacher_access_required: "当前没有此操作所需的教师权限，请联系维护人员。",
          class_not_found: "此班级不存在或授权已变更，请刷新授权班级。",
          export_too_large: "班级超过单次2000人导出上限，请联系维护人员。",
        };
        status(messages[error.code] || "无法读取授权数据。请确认连接后，点击刷新授权班级重试。", true);
      }
    } finally {
      busy = false;
      document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      if (pending && !document.hidden) { pending = false; void run(() => loadClasses(1)); }
    }
  }
  async function loadClasses(page) {
    clearAll();
    status("正在检查班级访问权限…");
    const data = await fetchData(`/teacher/api/classes?page=${page}`);
    classPage = data.page;
    for (const classroom of data.items) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = `${classroom.name}（${classroom.code}）`;
      button.disabled = busy;
      button.addEventListener("click", () => { void run(() => loadStudents(classroom.classId, 1)); });
      li.append(button);
      id("class-list").append(li);
    }
    id("classes-prev").hidden = classPage <= 1;
    id("classes-next").hidden = !data.hasNext;
    status(data.total ? `共${data.total}个授权班级，当前第${data.page}页。请选择班级查看名单。` : "你当前没有有效的班级授权，请联系维护人员。");
  }
  async function loadStudents(classId, page) {
    clearRoster();
    selected = null;
    status("正在读取授权班级名单…");
    const data = await fetchData(`/teacher/api/classes/${encodeURIComponent(classId)}/students?page=${page}`);
    selected = data.classroom.classId;
    studentPage = data.page;
    id("roster-title").textContent = data.classroom.name;
    id("roster-summary").textContent = `共${data.total}名启用账号，当前第${data.page}页，每页最多${data.pageSize}人。`;
    for (const student of data.items) {
      const row = document.createElement("tr");
      for (const value of [student.username, student.displayName]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      id("students-body").append(row);
    }
    id("students-prev").hidden = studentPage <= 1;
    id("students-next").hidden = !data.hasNext;
    id("roster").hidden = false;
    status(data.total ? "名单已按当前授权更新。" : "此班级暂无启用账号。");
  }
  id("reload-classes").addEventListener("click", () => { void run(() => loadClasses(1)); });
  id("classes-prev").addEventListener("click", () => { void run(() => loadClasses(classPage - 1)); });
  id("classes-next").addEventListener("click", () => { void run(() => loadClasses(classPage + 1)); });
  id("students-prev").addEventListener("click", () => { if (selected) void run(() => loadStudents(selected, studentPage - 1)); });
  id("students-next").addEventListener("click", () => { if (selected) void run(() => loadStudents(selected, studentPage + 1)); });
  id("export-roster").addEventListener("click", () => {
    if (!selected) return;
    const classId = selected;
    void run(async () => {
      status("正在重新验证导出权限…");
      const blob = await fetchData(`/teacher/api/classes/${encodeURIComponent(classId)}/students.csv`, true);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `class-${classId}-students.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      status("名单已生成并交给浏览器下载，不包含成绩数据。");
    });
  });
  function returnToPage() {
    if (document.hidden) return;
    if (busy) pending = true;
    else void run(() => loadClasses(1));
  }
  function hidePage() { epoch += 1; clearAll(); status("返回页面时将重新检查授权。"); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) hidePage(); else returnToPage(); });
  window.addEventListener("pagehide", hidePage);
  window.addEventListener("pageshow", returnToPage);
})();

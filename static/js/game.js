"use strict";
(() => {
  const id = name => document.getElementById(name);
  let questions = [];
  let busy = false;
  let opened = false;
  let pending = false;
  const client = new window.HuaxiaChapterClient("sample-counting", { onProgress: render, onScore: result => {
    id("result").hidden = false;
    id("score").textContent = `成绩：${result.score} / ${result.maxScore}，已保存至服务器。`;
  } });
  function status(text, error = false) { id("game-status").textContent = text; id("game-status").classList.toggle("error", error); }
  function clear() {
    client.invalidate(); opened = false; questions = [];
    for (const name of ["play", "chapter-map", "npc", "practice", "result"]) id(name).hidden = true;
    for (const name of ["questions", "scene-title", "quest-status", "dialogue", "score", "chapter-title"]) id(name).replaceChildren();
  }
  function render(progress) {
    const story = progress.state.story;
    id("play").hidden = !opened;
    id("scene-title").textContent = story.scene === "gate" ? "场景：城门" : "场景：算坊";
    const names = { not_started: "尚未接任务", accepted: "任务进行中", submitted: "任务已提交" };
    id("quest-status").textContent = `${names[story.quest]} · 存档版本 ${progress.revision} · 题库版本 ${progress.questionBank.version}`;
    id("npc").hidden = story.scene !== "gate" || Boolean(progress.result);
    id("practice").hidden = story.scene !== "workshop" || story.quest !== "accepted" || Boolean(progress.result);
    id("dialogue").textContent = story.talkedToNpc ? "守门人：请去算坊体验练习分支，再回到这里提交。本段剧情之后可以替换。" : "先与守门人对话。";
    id("questions").replaceChildren();
    questions.forEach((q, index) => {
      const form = document.createElement("form"); form.className = "sample-answer";
      const label = document.createElement("label"); label.textContent = q.prompt; label.htmlFor = `answer-${index}`;
      const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.max = "10000"; input.step = "1"; input.required = true; input.id = `answer-${index}`;
      input.value = progress.state.practice.answers[index] ?? "";
      const button = document.createElement("button"); button.type = "submit"; button.className = "secondary"; button.textContent = `保存第${index + 1}题答案`;
      const hint = document.createElement("p"); hint.className = "hint"; hint.textContent = progress.state.practice.answers[index] === null ? "尚未保存" : "此答案已保存";
      form.append(label, input, button, hint);
      form.addEventListener("submit", event => { event.preventDefault(); const answer = Number(input.value); if (!Number.isInteger(answer) || input.value === "" || answer < 0 || answer > 10000) { status("请填写0至10000的整数。", true); return; } void run(() => client.dispatch("answer", { questionIndex: index, answer })); });
      id("questions").append(form);
    });
    id("result").hidden = !progress.result;
    id("move-gate").hidden = Boolean(progress.result);
    id("move-workshop").hidden = Boolean(progress.result);
    id("accept").hidden = story.quest !== "not_started" || !story.talkedToNpc;
    id("submit-quest").hidden = story.quest !== "accepted";
    status("服务器存档已同步。请按任务步骤操作。");
  }
  async function run(action) {
    if (busy) return;
    busy = true; document.querySelectorAll("button, input").forEach(el => { el.disabled = true; });
    try { await action(); }
    catch (error) { if (!error.stale) { clear(); status(error.code === "authentication_required" ? "登录已失效，请返回账号中心重新登录。" : "操作结果未确认或存档发生冲突。请重新载入服务器存档，勿连续重复提交。", true); } }
    finally {
      busy = false; document.querySelectorAll("button, input").forEach(el => { el.disabled = false; });
      if (pending && !document.hidden) { pending = false; void run(load); }
    }
  }
  async function load() {
    clear(); status("正在读取章节与服务器存档…");
    const started = client.epoch;
    const listing = await client.request("/game/api/chapters");
    if (started !== client.epoch) throw Object.assign(new Error("页面状态已变化"), { stale: true });
    const chapter = listing.chapters.find(item => item.chapterId === client.chapterId);
    if (!chapter) throw new Error("样例章节未注册");
    const data = await client.load(); questions = data.questions; render(data.progress);
    if (data.progress.result) client.callbacks.onScore(data.progress.result);
    id("chapter-title").textContent = chapter.title;
    id("chapter-map").hidden = false;
  }
  id("reload-game").addEventListener("click", () => { void run(load); });
  id("enter-chapter").addEventListener("click", () => { if (busy || !client.progress) return; opened = true; render(client.progress); if (client.progress.result) client.callbacks.onScore(client.progress.result); });
  for (const [element, action, payload] of [["move-gate", "move", { scene: "gate" }], ["move-workshop", "move", { scene: "workshop" }], ["talk", "talk", {}], ["accept", "accept", {}], ["submit-quest", "submit", {}]]) {
    id(element).addEventListener("click", () => { void run(() => client.dispatch(action, payload)); });
  }
  function hide() { clear(); status("返回时会重新读取身份与存档，未保存的输入已清空。"); }
  function restore() { if (!document.hidden) { if (busy) pending = true; else void run(load); } }
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); else restore(); });
  window.addEventListener("pagehide", hide); window.addEventListener("pageshow", restore);
})();

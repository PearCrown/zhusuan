"use strict";
(() => {
  const id = name => document.getElementById(name);
  let questions = [];
  let busy = false;
  let opened = false;
  let pending = false;
  // 对话状态：服务端一次返回整条 pages，这里拍平成「一次一句」的步骤。
  // 翻页是纯本地动作，只有选项里的 command 才会打服务器——对话轮次不该放大成请求数。
  let steps = [];
  let stepIndex = 0;
  let dialogueKey = null;
  let dialogueDismissed = false;
  // 任务栏由 static/js/quest.js 负责，页面只提供挂载点并推存档过去。
  let questBar = null;
  const client = new window.HuaxiaChapterClient("sample-counting", { onProgress: render, onScore: result => {
    id("result").hidden = false;
    id("score").textContent = `成绩：${result.score} / ${result.maxScore}，已保存至服务器。`;
  } });
  function status(text, error = false) { id("game-status").textContent = text; id("game-status").classList.toggle("error", error); }
  function clear() {
    client.invalidate(); opened = false; questions = [];
    steps = []; stepIndex = 0; dialogueKey = null; dialogueDismissed = false;
    for (const name of ["play", "chapter-map", "npc", "practice", "result", "quest-bar"]) id(name).hidden = true;
    for (const name of ["questions", "scene-title", "quest-status", "score", "chapter-title",
      "npc-line", "npc-name", "npc-title", "npc-portrait", "npc-choices"]) id(name).replaceChildren();
  }
  function render(progress) {
    const story = progress.state.story;
    id("play").hidden = !opened;
    id("scene-title").textContent = story.scene === "gate" ? "场景：城门" : "场景：算坊";
    const names = { not_started: "尚未接任务", accepted: "任务进行中", submitted: "任务已提交" };
    id("quest-status").textContent = `${names[story.quest]} · 存档版本 ${progress.revision} · 题库版本 ${progress.questionBank.version}`;
    id("npc").hidden = story.scene !== "gate" || Boolean(progress.result);
    id("practice").hidden = story.scene !== "workshop" || story.quest !== "accepted" || Boolean(progress.result);
    renderDialogue(story.dialogue);
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
    id("submit-quest").hidden = story.quest !== "accepted" || Boolean(progress.result);
    showQuest(progress);
    status("服务器存档已同步。请按任务步骤操作。");
  }

  // ---------- 任务栏（组件在 static/js/quest.js） ----------
  /** 组件不认识本页面：这里只给挂载点，并把已经读到的存档推过去，省一次往返。 */
  function showQuest(progress) {
    if (!window.HuaxiaQuestBar) return;
    if (!questBar) questBar = window.HuaxiaQuestBar.mountQuestBar(id("quest-bar"), client.chapterId);
    if (!questBar) return;
    questBar.render(progress);
  }

  /** 提交开始/结束时改状态胶囊：核验中 → 已通过 / 未通过。 */
  function questPending(pending) {
    if (questBar) questBar.setPending(pending);
  }

  /** 提交：先显式进入「核验中」，再按结果落到通过/未通过。 */
  async function submitQuest() {
    if (busy || !client.progress) return;
    questPending(true);
    const ok = await run(() => client.dispatch("submit"));
    questPending(false);
    // 成功时 dispatch 已经把新存档经 render 推给任务栏了，这里不再重复推。
    // 提交成功与否无法从断网中判定，所以既不宣称失败、也不自动重试。
    if (!ok) status("提交结果未确认：请点「重新载入服务器存档」核对，界面不会自动重试。", true);
  }

  // ---------- 底部对话（@deprecated） ----------
  /**
   * @deprecated 底部对话条（npc-bar / npc-next / npc-choices）。
   * 对话的正式入口是全屏剧情页 /game/story/<chapterId>/<npcId>（templates/story.html），
   * 那段代码与本文件这段并存是临时状态：等 A 确认大地图归属后整体删除，
   * 在此之前保留是因为 /game/ 仍是对 A 的接入样例，删掉会改变它的行为。
   */
  /** 把服务端展开好的 pages 拍平成「一句一步、选项单独一步」。 */
  function flattenSteps(pages) {
    const list = [];
    for (const page of pages) {
      for (const line of page.lines || []) list.push({ line });
      if (page.choices && page.choices.length) list.push({ choices: page.choices });
    }
    return list;
  }

  function renderDialogue(dialogue) {
    const pages = dialogue && Array.isArray(dialogue.pages) ? dialogue.pages : [];
    // 对话内容换了就重新开始（比如接完任务后服务端换成了 on-task 那段话）。
    const key = pages.map(page => page.nodeId).join(">") || null;
    if (key !== dialogueKey) { dialogueKey = key; dialogueDismissed = false; }
    steps = flattenSteps(pages);
    stepIndex = 0;
    const speaker = (dialogue && dialogue.speaker) || {};
    id("npc-name").textContent = speaker.name || "";
    id("npc-title").textContent = speaker.title || "";
    const portrait = id("npc-portrait");
    portrait.style.borderColor = speaker.color || "";
    portrait.style.color = speaker.color || "";
    portrait.replaceChildren();
    if (speaker.portrait) {
      // 有立绘就用立绘；图片加载失败自动退回印章单字，不至于留一个空框。
      const image = document.createElement("img");
      image.src = speaker.portrait;
      image.alt = speaker.name || "";
      image.addEventListener("error", () => { portrait.textContent = speaker.seal || ""; });
      portrait.appendChild(image);
    } else {
      portrait.textContent = speaker.seal || "";
    }
    renderStep();
  }

  function renderStep() {
    const visible = steps.length > 0 && !dialogueDismissed;
    id("npc-bar").hidden = !visible;
    id("talk").hidden = visible;
    id("npc-choices").replaceChildren();
    if (!visible) {
      id("npc-line").textContent = "";
      id("npc-next").hidden = true;
      return;
    }
    const step = steps[stepIndex];
    if (step.line) id("npc-line").textContent = step.line;
    // 有选项时不显示「继续」——先让玩家作出选择，避免跳过选项。
    id("npc-next").hidden = Boolean(step.choices) || stepIndex >= steps.length - 1;
    for (const choice of step.choices || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = choice.command ? "primary" : "secondary";
      button.textContent = choice.text;
      button.addEventListener("click", () => chooseOption(choice));
      id("npc-choices").appendChild(button);
    }
  }

  function chooseOption(choice) {
    const action = choice.command && choice.command.action;
    // 不带 command 的选项只是关闭对话，不产生任何永久状态。
    if (!action) { dialogueDismissed = true; renderStep(); return; }
    void run(() => client.dispatch(action));
  }
  async function run(action) {
    if (busy) return false;
    busy = true; document.querySelectorAll("button, input").forEach(el => { el.disabled = true; });
    let ok = true;
    try { await action(); }
    catch (error) {
      ok = false;
      if (!error.stale) { clear(); status(error.code === "authentication_required" ? "登录已失效，请返回账号中心重新登录。" : "操作结果未确认或存档发生冲突。请重新载入服务器存档，勿连续重复提交。", true); }
    }
    finally {
      busy = false; document.querySelectorAll("button, input").forEach(el => { el.disabled = false; });
      if (pending && !document.hidden) { pending = false; void run(load); }
    }
    return ok;
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
  for (const [element, action, payload] of [["move-gate", "move", { scene: "gate" }], ["move-workshop", "move", { scene: "workshop" }], ["talk", "talk", {}]]) {
    id(element).addEventListener("click", () => { void run(() => client.dispatch(action, payload)); });
  }
  id("submit-quest").addEventListener("click", () => { void submitQuest(); });
  id("npc-next").addEventListener("click", () => {
    if (stepIndex < steps.length - 1) { stepIndex += 1; renderStep(); }
  });
  function hide() { clear(); status("返回时会重新读取身份与存档，未保存的输入已清空。"); }
  function restore() { if (!document.hidden) { if (busy) pending = true; else void run(load); } }
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); else restore(); });
  window.addEventListener("pagehide", hide); window.addEventListener("pageshow", restore);
})();

/* 全屏剧情演出（参考明日方舟剧情）。
 *
 * 分工要点：
 * - 剧情文案、背景、立绘全部来自数据（服务端 json_script 下发），前端不写死台词。
 * - 只有「选项里的 command」会打服务器并改变存档；翻页、打字机、记录、跳过
 *   都是纯本地动作，不产生请求，也不产生永久状态。
 * - 跳过只能跳到「第一个选项」或结尾：选项会改存档，不能替玩家做决定。
 */
"use strict";
(() => {
  const id = name => document.getElementById(name);

  const stage = id("story-stage");
  const body = document.body;
  const chapterId = body.dataset.chapter;
  const nextUrl = body.dataset.next || "/game/";
  const backUrl = body.dataset.back || "/game/";

  let data = {};
  try { data = JSON.parse(id("story-data").textContent || "{}") || {}; } catch { data = {}; }
  const npc = data.npc || {};
  // 多 NPC 章节的 talk 要带 npcId，这个字段由数据声明（talkFields），前端不猜。
  const talkFields = data.talkFields || {};

  const client = new window.HuaxiaChapterClient(chapterId, {});

  // 任务栏（精简版）：接任务后才在角落出现。组件自己去读同一份进度，
  // 这里把我已经读到的存档推过去，省掉一次对 /progress 的往返。
  const questBar = window.HuaxiaQuestBar
    ? window.HuaxiaQuestBar.mountQuestBar(id("quest-slot"), chapterId)
    : null;

  function showQuest(progress) {
    if (questBar && progress) questBar.render(progress);
  }

  let steps = [];        // [{line, name}] 或 [{choices}]
  let stepIndex = 0;
  let typing = false;
  let typeTimer = null;
  let autoMode = false;
  let autoTimer = null;
  let busy = false;
  let records = [];      // 对话记录

  // ---------- 布景 ----------
  function staticUrl(path) {
    if (!path) return "";
    return path.startsWith("/") ? path : `/static/${path}`;
  }

  function paintBackground() {
    const url = staticUrl(data.background);
    if (!url) return;                       // 留空则保留渐变底，不报错
    const probe = new Image();
    probe.addEventListener("load", () => { id("story-bg").style.backgroundImage = `url("${url}")`; });
    probe.src = url;                        // 加载失败就继续用渐变底
  }

  function renderSeal() {
    const box = id("story-portrait");
    box.replaceChildren();
    box.classList.add("seal-panel");
    box.style.color = npc.color || "#b79b65";
    const glyph = document.createElement("div");
    glyph.className = "seal-glyph";
    glyph.textContent = npc.seal || "？";
    box.appendChild(glyph);
  }

  function renderPortrait() {
    const box = id("story-portrait");
    box.replaceChildren();
    box.classList.remove("seal-panel");
    box.style.color = npc.color || "";
    if (!npc.portrait) { renderSeal(); return; }   // 没有立绘就用印章兜底，不留空白
    const image = document.createElement("img");
    image.alt = npc.name || "";
    image.addEventListener("error", renderSeal);
    image.src = staticUrl(npc.portrait);
    box.appendChild(image);
  }

  /** 从存档里取"当前这名 NPC 的对话快照"。
   *
   * 约定：单 NPC 章节放在 state.story.dialogue；多 NPC 章节放在
   * state.npcs[<npcId>].dialogue。这里只做"取出来"，不做任何状态推断，
   * 具体哪一段该演是由服务端下发的 pages 决定的。
   */
  function dialogueFrom(progress) {
    const state = (progress && progress.state) || {};
    if (state.story && state.story.dialogue) return state.story.dialogue;
    const npcs = state.npcs;
    const npcId = body.dataset.npc;
    const entry = npcs && npcId ? npcs[npcId] : null;
    return (entry && entry.dialogue) || null;
  }

  // ---------- 剧本 ----------
  /** 把服务端展开好的 pages 拍平成「一句一步、选项单独一步」。 */
  function flatten(pages) {
    const list = [];
    for (const page of pages) {
      for (const line of page.lines || []) list.push({ line, name: npc.name || "" });
      if (page.choices && page.choices.length) list.push({ choices: page.choices });
    }
    return list;
  }

  function renderDialogue(dialogue) {
    steps = flatten(dialogue.pages || []);
    stepIndex = 0;
    records = [];
    renderSealIfMissing();
    id("story-dialogue").classList.add("visible");
    id("story-end").hidden = true;
    showStep();
  }

  function renderSealIfMissing() {
    if (id("story-portrait").childElementCount === 0) renderPortrait();
  }

  function showStep() {
    const step = steps[stepIndex];
    id("story-choices").replaceChildren();
    id("story-cursor").classList.remove("ready");
    if (!step) { finish(); return; }
    if (step.choices) { showChoices(step.choices); return; }
    id("story-speaker-name").textContent = step.name || "";
    records.push({ name: step.name || "", text: step.line });
    typeOut(step.line);
  }

  function showChoices(choices) {
    const box = id("story-choices");
    box.replaceChildren();
    for (const choice of choices) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "story-choice";
      button.textContent = choice.text;
      button.addEventListener("click", event => { event.stopPropagation(); chooseOption(choice); });
      box.appendChild(button);
    }
  }

  // ---------- 打字机 ----------
  function typeOut(text) {
    clearInterval(typeTimer);
    typing = true;
    const target = id("story-text");
    target.textContent = "";
    let shown = 0;
    typeTimer = setInterval(() => {
      shown += 1;
      target.textContent = text.slice(0, shown);
      if (shown >= text.length) settleText(text);
    }, 26);
  }

  function settleText(text) {
    clearInterval(typeTimer);
    typeTimer = null;
    id("story-text").textContent = text;
    typing = false;
    id("story-cursor").classList.add("ready");
    scheduleAuto();
  }

  function scheduleAuto() {
    clearTimeout(autoTimer);
    if (!autoMode || !id("story-skip-modal").hidden || !id("story-log").hidden) return;
    if (!id("story-end").hidden) return;
    const step = steps[stepIndex];
    if (!step || step.choices) return;
    autoTimer = setTimeout(advance, 1400);
  }

  // ---------- 推进 ----------
  function overlayOpen() {
    return !id("story-skip-modal").hidden || !id("story-end").hidden;
  }

  function advance() {
    if (busy || overlayOpen()) return;
    if (!id("story-log").hidden) return;
    const step = steps[stepIndex];
    if (step && step.choices) return;            // 等玩家作出选择
    if (typing) { settleText(step.line); return; } // 第一次点击先把这句显示完
    stepIndex += 1;
    if (stepIndex >= steps.length) { finish(); return; }
    showStep();
  }

  function finish(note) {
    clearInterval(typeTimer); clearTimeout(autoTimer);
    typing = false;
    id("story-dialogue").classList.remove("visible");
    id("story-choices").replaceChildren();
    id("story-cursor").classList.remove("ready");
    const episode = data.episode || {};
    id("story-end-note").textContent = note
      || (episode.title ? `《${episode.title}》· ${episode.operation || ""}` : "本段剧情结束。");
    id("story-end").hidden = false;
    const next = id("story-next");
    next.href = nextUrl;
    if (data.then && data.then.label) next.textContent = `${data.then.label} ▸`;
  }

  // ---------- 选项 ----------
  async function chooseOption(choice) {
    const action = choice.command && choice.command.action;
    // 不带 command 的选项只是结束本段、回到宿主页面，不产生任何永久状态。
    if (!action) { leave(); return; }
    if (busy) return;
    busy = true;
    setChoicesEnabled(false);
    status("正在记录…");
    // 选项里的 command 可以带字段（多 NPC 章节要 npcId，旗标要 flag），
    // 除 action 之外一律原样转给服务端；字段集合仍由章节的 actions 白名单校验。
    const fields = Object.fromEntries(
      Object.entries(choice.command).filter(([key]) => key !== "action"));
    try {
      const result = await client.dispatch(action, fields);
      status("");
      showQuest(result.progress);
      const dialogue = dialogueFrom(result.progress);
      if (dialogue) renderDialogue(dialogue);
      else finish();
    } catch (error) {
      status(error.code === "authentication_required"
        ? "登录已失效，请重新登录后重看这段剧情。"
        : (error.message || "操作未完成，请重试。"), true);
      setChoicesEnabled(true);
    } finally {
      busy = false;
    }
  }

  function setChoicesEnabled(enabled) {
    for (const button of id("story-choices").querySelectorAll("button")) button.disabled = !enabled;
  }

  function leave() {
    stage.classList.add("leaving");
    window.location.href = backUrl;
  }

  // ---------- 跳过 ----------
  function openSkip() {
    if (overlayOpen()) return;
    id("story-skip-modal").hidden = false;
  }

  function closeSkip() {
    id("story-skip-modal").hidden = true;
    scheduleAuto();
  }

  function doSkip() {
    id("story-skip-modal").hidden = true;
    // 跳过只能停在第一个选项之前：选项会改存档，必须由玩家自己选。
    let target = steps.findIndex(step => step.choices);
    if (target < 0) target = steps.length;
    for (let index = stepIndex; index < target && index < steps.length; index += 1) {
      const step = steps[index];
      if (step.line) records.push({ name: step.name || "", text: step.line });
    }
    stepIndex = target;
    if (stepIndex >= steps.length) { finish(); return; }
    showStep();
  }

  // ---------- 记录 ----------
  function renderLog() {
    const list = id("story-log-list");
    list.replaceChildren();
    for (const record of records) {
      const item = document.createElement("li");
      if (!record.name) item.className = "narration";
      if (record.name) {
        const who = document.createElement("strong");
        who.textContent = record.name;
        item.appendChild(who);
      }
      item.appendChild(document.createTextNode(record.text));
      list.appendChild(item);
    }
    if (!records.length) {
      const item = document.createElement("li");
      item.className = "narration";
      item.textContent = "还没有对话。";
      list.appendChild(item);
    }
  }

  function openLog() {
    renderLog();
    id("story-log").hidden = false;
    clearTimeout(autoTimer);
  }

  function closeLog() {
    id("story-log").hidden = true;
    scheduleAuto();
  }

  // ---------- 杂项 ----------
  function status(message, error = false) {
    const node = id("story-status");
    node.textContent = message;
    node.classList.toggle("error", Boolean(error));
  }

  function setAuto(on) {
    autoMode = on;
    id("story-auto").setAttribute("aria-pressed", String(on));
    id("story-auto").textContent = on ? "自动 ON" : "自动 OFF";
    if (on) scheduleAuto(); else clearTimeout(autoTimer);
  }

  function toggleHidden() {
    stage.classList.toggle("ui-hidden");
    id("story-hide").textContent = stage.classList.contains("ui-hidden") ? "显示" : "隐藏";
  }

  // ---------- 启动 ----------
  async function boot() {
    paintBackground();
    renderPortrait();
    status("正在读取存档…");
    try {
      const loaded = await client.load();
      showQuest(loaded.progress);
      let dialogue = dialogueFrom(loaded.progress);
      if (!dialogue) {
        // 已结算的章节不能再 talk（服务端会拒绝），此时只显示归档提示。
        if (loaded.progress.result) { status(""); finish("本章已结算，剧情已成定局。"); return; }
        const after = await client.dispatch("talk", talkFields);
        showQuest(after.progress);
        dialogue = dialogueFrom(after.progress);
      }
      status("");
      if (dialogue) renderDialogue(dialogue);
      else finish();
    } catch (error) {
      status(error.code === "authentication_required"
        ? "登录已失效，请返回账号中心重新登录。"
        : (error.message || "剧情读取失败，请刷新重试。"), true);
    }
  }

  // ---------- 事件 ----------
  stage.addEventListener("click", event => {
    if (event.target.closest("button, a, .story-log, .story-modal, .story-end")) return;
    if (stage.classList.contains("ui-hidden")) { toggleHidden(); return; }
    advance();
  });
  id("story-skip").addEventListener("click", openSkip);
  id("story-skip-no").addEventListener("click", closeSkip);
  id("story-skip-yes").addEventListener("click", doSkip);
  id("story-auto").addEventListener("click", () => setAuto(!autoMode));
  id("story-log-btn").addEventListener("click", openLog);
  id("story-log-close").addEventListener("click", closeLog);
  id("story-hide").addEventListener("click", toggleHidden);
  id("story-back").addEventListener("click", leave);
  id("story-replay").addEventListener("click", () => { id("story-end").hidden = true; void boot(); });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      if (!id("story-skip-modal").hidden) { closeSkip(); return; }
      if (!id("story-log").hidden) { closeLog(); return; }
    }
    if (!id("story-log").hidden || overlayOpen()) return;
    if (event.key === " " || event.key === "Enter") { event.preventDefault(); advance(); }
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { void boot(); });
  else void boot();
})();

"use strict";
(() => {
  const id = name => document.getElementById(name), data = window.HuaxiaSceneDemo;
  const client = new window.HuaxiaChapterClient(data.chapterId);
  const locks = new window.HuaxiaInputLocks();
  const keys = new Set();
  let progress, questions = [], model, view, host, token, runnerController, dialogueLock, pauseLock, nextExitAction = "return";
  const heldActions = new Set();
  let busy = false, pending = false, epoch = 0, taskNumber = 0, lastFrame = null, frame, focusAfter;
  const status = (message, error = false) => {id("status").textContent = message; id("status").classList.toggle("error", error);};
  const clearInput = () => {keys.clear(); model?.clearInput();};
  function closeDialogue() {
    locks.release(dialogueLock); dialogueLock = null;
    id("dialogue").hidden = true; clearInput();
  }
  function reset() {
    epoch++; focusAfter = null; client.invalidate(); closeDialogue();
    locks.release(pauseLock); pauseLock = null; id("pause").hidden = true; id("save-choice").hidden = true;
    try {host?.dispose();} finally {host = null; token = null; runnerController = null;}
    view?.dispose(); view = null; model = null; progress = null; questions = []; lastFrame = null;
    for (const name of ["chapters", "locations", "scene", "runner"]) id(name).hidden = true;
    for (const name of ["quest-state", "runner-content", "runner-status", "dialogue-text", "level-state"]) id(name).replaceChildren();
  }
  function acceptProgress(value) {
    if (!value || value.chapterId !== data.chapterId || !Number.isSafeInteger(value.revision) || value.revision < 0 ||
        !["gate", "workshop"].includes(value.state?.story?.scene) || !["not_started", "accepted", "submitted"].includes(value.state.story.quest) ||
        !Array.isArray(value.state?.practice?.answers) || value.state.practice.answers.length !== questions.length) throw Error("INVALID_PROGRESS");
    progress = value;
    const labels = {not_started: "与守门人交谈，接取委托", accepted: "前往算坊任务点，完成后回守门人处交付", submitted: "样例任务已交付"};
    id("quest-state").textContent = labels[value.state.story.quest] + (value.result ? ` · 服务器成绩 ${value.result.score} / ${value.result.maxScore}` : "");
    id("level-state").textContent = value.result ? "样例已结算，可进入查看场景。" : labels[value.state.story.quest];
    id("dialogue-text").textContent = value.result ? "守门人：委托已交付，感谢相助。" : "守门人：请到前方算坊完成练习，再回来交付。";
    id("accept").hidden = value.state.story.quest !== "not_started";
    id("submit").hidden = value.state.story.quest !== "accepted";
  }
  function controls() {
    document.querySelectorAll("button, #runner-content input").forEach(el => {el.disabled = busy;});
    const mode = context();
    id("viewport").inert = mode !== "scene";
    id("taskbar").inert = mode !== "scene";
    id("open-menu").inert = !["scene", "map"].includes(mode);
    id("chapters").inert = mode !== "map"; id("locations").inert = mode !== "map";
    id("runner").inert = mode !== "task";
    id("back-map").disabled = busy || Boolean(token);
    id("scene").classList.toggle("dialogue-open", !id("dialogue").hidden);
    id("scene").classList.toggle("task-open", !id("runner").hidden);
    if (model) {
      const nearby = model.nearby();
      const text = nearby ? `E ${nearby.label}${model.targets().length > 1 ? " · Q切换目标" : ""}` : "靠近人物或任务点后，按 E 交互";
      if (id("nearby").textContent !== text) id("nearby").textContent = text;
    }
  }
  async function run(fn) {
    if (busy) return;
    busy = true; clearInput();
    const lock = locks.acquire("network"); controls();
    try {await fn();}
    catch (error) {
      if (!error.stale) {
        reset();
        status(error.code === "authentication_required" ? "登录已失效，请返回账号中心重新登录。" : "操作结果尚未确认。请重新读取进度，勿重复提交。", true);
      }
    } finally {
      busy = false; locks.release(lock); clearInput(); controls();
      if (!document.hidden && focusAfter?.isConnected) {focusAfter.focus(); focusAfter = null;}
      else if (!document.hidden && !id("scene").hidden && !token) {
        (id("dialogue").hidden ? id("viewport") : focusables(id("dialogue"))[0]).focus();
      }
      if (pending && !document.hidden) {pending = false; void run(load);}
    }
  }
  function assertCurrent(started) {if (started !== epoch) throw Object.assign(Error("STALE"), {stale: true});}
  async function load() {
    reset(); const started = epoch;
    status("正在读取章节与服务器进度…");
    const listing = await client.request("/game/api/chapters"); assertCurrent(started);
    const chapter = listing.chapters.find(item => item.chapterId === data.chapterId);
    if (!chapter) throw Error("CHAPTER_UNAVAILABLE");
    const result = await client.load(); assertCurrent(started);
    if (!Array.isArray(result.questions) || result.questions.some(q => typeof q.prompt !== "string")) throw Error("INVALID_QUESTIONS");
    questions = result.questions; acceptProgress(result.progress);
    id("chapter-name").textContent = chapter.title;
    id("location-name").textContent = data.locationTitle; id("level-name").textContent = data.levelTitle;
    id("chapters").hidden = false; focusAfter = id("choose-chapter"); status("进度已读取，请选择章节。");
  }
  async function action(name, fields = {}) {
    const started = epoch;
    const result = await client.dispatch(name, fields); assertCurrent(started);
    acceptProgress(result.progress);
  }
  async function enterScene() {
    // Re-read on entry to catch changes made in the original sample or another tab.
    const started = epoch, result = await client.load(); assertCurrent(started);
    questions = result.questions; acceptProgress(result.progress);
    closeDialogue(); host?.dispose(); view?.dispose();
    model = new window.HuaxiaSceneModel(data, locks);
    view = new window.HuaxiaSceneView(id("viewport"), data, entityId => {
      if (!busy && !locks.locked && model.targets().some(entity => entity.id === entityId)) void run(() => interact(entityId));
    });
    host = new window.HuaxiaSceneHost({
      context: {chapterId: data.chapterId, levelSessionId: `preview-${epoch}`, sceneId: data.sceneId, sessionEpoch: `page-${epoch}`},
      scene: data.scene, locks, clearInput,
      readProgress: async ({signal}) => {
        const result = await client.load(); signal.throwIfAborted();
        questions = result.questions; acceptProgress(result.progress); return result.progress;
      },
      restoreScene: ({snapshot, signal}) => {signal.throwIfAborted(); model.restore(snapshot); view.draw(model);},
      callbacks: {submitRequested: report => {void run(() => saveAnswer(report.value));}},
    });
    id("locations").hidden = true; id("scene").hidden = false;
    id("scene-name").textContent = data.levelTitle; view.draw(model); id("viewport").focus();
    status("沿道路走近守门人。场景位置为本页临时状态。");
  }
  function legacyRunner() {
    return {mount(element, options, callbacks) {
      const answers = [...progress.state.practice.answers], saved = [...answers], inputs = [], hints = [];
      const abort = new AbortController();
      const dispose = () => {abort.abort(); element.replaceChildren();};
      options.signal.addEventListener("abort", dispose, {once: true, signal: abort.signal});
      questions.forEach((question, index) => {
        const form = document.createElement("form"); form.className = "question";
        const label = document.createElement("label"); label.textContent = question.prompt; label.htmlFor = `scene-answer-${index}`;
        const input = document.createElement("input"); input.id = label.htmlFor; input.type = "number"; input.min = "0"; input.max = "10000"; input.step = "1"; input.required = true; input.value = answers[index] ?? "";
        const button = document.createElement("button"); button.type = "submit"; button.textContent = `保存第${index + 1}题`;
        const hint = document.createElement("span"); hint.className = "muted"; hint.textContent = saved[index] === null ? "尚未保存" : "已保存";
        input.addEventListener("input", () => {answers[index] = input.value; hint.textContent = "修改尚未保存";}, {signal: abort.signal});
        form.addEventListener("submit", event => {
          event.preventDefault(); const answer = Number(input.value);
          if (input.value === "" || !Number.isInteger(answer) || answer < 0 || answer > 10000) {id("runner-status").textContent = "请填写0至10000的整数。"; return;}
          callbacks.submitRequested({questionIndex: index, answer});
        }, {signal: abort.signal});
        form.append(label, input, button, hint); element.append(form); inputs.push(input); hints.push(hint);
      });
      runnerController = {
        exportDraft: () => ({answers: inputs.map(el => el.value)}), pause: () => {}, dispose,
        dirty: () => inputs.some((input, index) => input.value !== String(saved[index] ?? "")),
        dirtyEntries: () => inputs.flatMap((input, index) => input.value === String(saved[index] ?? "") ? [] : [{questionIndex: index, answer: input.value}]),
        markSaved: index => {saved[index] = progress.state.practice.answers[index]; hints[index].textContent = "已保存";},
      };
      return runnerController;
    }};
  }
  async function saveAnswer({questionIndex, answer}) {
    await action("answer", {questionIndex, answer});
    runnerController.markSaved(questionIndex); id("runner-status").textContent = "本题已保存至服务器。";
    focusAfter = id(`scene-answer-${questionIndex}`);
  }
  async function openTask() {
    if (progress.result) {status("样例已结算，请到守门人或出口查看。"); return;}
    if (progress.state.story.quest !== "accepted") {status("请先向守门人接取委托。"); return;}
    if (progress.state.story.scene !== "workshop") await action("move", {scene: "workshop"});
    id("runner-content").replaceChildren(); id("runner-status").textContent = "答案只有确认保存后才写入服务器。";
    id("retry-return").hidden = true; id("exit-runner").hidden = false;
    // This ID is a presentation-only legacy bridge, never sent as a server task instance.
    token = host.beginTask({instanceId: `legacy-preview-${++taskNumber}`, runner: legacyRunner(), host: id("runner-content"), snapshot: model.capture()});
    id("runner").hidden = false; focusAfter = id("runner-content").querySelector("input");
  }
  async function returnFromTask() {
    runnerController = null;
    try {
      await host.returnToScene(token); host.finishReturn(token); token = null; runnerController = null;
      id("runner").hidden = true; id("viewport").focus(); status("已读取服务器进度，返回进入任务前的位置。");
    } catch (error) {
      if (error.code === "RETURN_CONTEXT_EXPIRED") return;
      id("runner-status").textContent = "尚未恢复场景，请重试读取；也可重新读取进度返回地图。";
      id("exit-runner").hidden = true; id("retry-return").hidden = false;
      focusAfter = id("retry-return");
    }
  }
  async function interact(entityId) {
    const entity = entityId ? model?.targets().find(item => item.id === entityId) : model?.nearby(); if (!entity || token || dialogueLock || pauseLock) return;
    if (entity.kind === "npc") {
      if (!progress.result) {
        if (progress.state.story.scene !== "gate") await action("move", {scene: "gate"});
        await action("talk");
      }
      dialogueLock = locks.acquire("dialogue"); clearInput(); id("dialogue").hidden = false; id("close-dialogue").focus();
    } else if (entity.kind === "task") await openTask();
    else if (!progress.result) status("出口：请先回守门人处交付。操作成功或保存答案都不等于已结算。");
    else {status("服务器已确认样例结算。返回地点地图。"); backMap();}
  }
  function backMap() {
    if (token) return;
    closeDialogue(); host?.dispose(); host = null; view?.dispose(); view = null; model = null;
    id("scene").hidden = true; id("locations").hidden = false;
    controls();
    if (busy) focusAfter = id("enter-level"); else id("enter-level").focus();
  }
  function dirty() {return Boolean(runnerController?.dirty());}
  function focusables(root) {return [...root.querySelectorAll("button,a[href],input,select,textarea,[tabindex='0']")].filter(el => !el.disabled && !el.closest("[hidden]") && el.tabIndex >= 0);}
  function context() {
    if (!id("save-choice").hidden) return "confirm";
    if (!id("pause").hidden) return "menu";
    if (token) return "task";
    if (!id("dialogue").hidden) return "dialogue";
    return model ? "scene" : "map";
  }
  function closePause(focus = true) {
    id("pause").hidden = true; locks.release(pauseLock); pauseLock = null; clearInput();
    controls();
    if (focus) (model ? id("viewport") : id("chapters").hidden ? id("enter-level") : id("choose-chapter")).focus();
  }
  function openPause() {
    if (busy || token || dialogueLock) return;
    clearInput(); pauseLock = locks.acquire("pause"); id("pause").hidden = false; id("back-map").hidden = !model;
    controls(); id("resume").focus();
  }
  function requestExit(action = "return") {
    if (busy) return;
    nextExitAction = action;
    if (dirty()) {
      clearInput(); id("save-choice").hidden = false; controls(); id("save-choice-status").textContent = "请选择保存、放弃修改或继续编辑。"; id("save-and-return").focus();
    } else void run(action === "reload" ? load : returnFromTask);
  }
  function closeSaveChoice() {id("save-choice").hidden = true; clearInput(); controls();}
  id("save-and-return").addEventListener("click", () => {void run(async () => {
    const entries = runnerController.dirtyEntries();
    if (entries.some(entry => entry.answer === "" || !Number.isInteger(Number(entry.answer)) || Number(entry.answer) < 0 || Number(entry.answer) > 10000)) {
      id("save-choice-status").textContent = "有答案未填写或不是0至10000的整数，请继续编辑后保存。"; focusAfter = id("stay-in-task"); return;
    }
    for (const entry of entries) await saveAnswer({...entry, answer: Number(entry.answer)});
    closeSaveChoice(); if (nextExitAction === "reload") await load(); else await returnFromTask();
  });});
  id("discard-and-return").addEventListener("click", () => {closeSaveChoice(); void run(nextExitAction === "reload" ? load : returnFromTask);});
  id("stay-in-task").addEventListener("click", () => {closeSaveChoice(); id("runner-content").querySelector("input")?.focus();});
  id("reload").addEventListener("click", () => {if (dirty()) requestExit("reload"); else void run(load);});
  id("choose-chapter").addEventListener("click", () => {id("chapters").hidden = true; id("locations").hidden = false; id("enter-level").focus();});
  id("back-chapters").addEventListener("click", () => {id("locations").hidden = true; id("chapters").hidden = false; id("choose-chapter").focus();});
  id("enter-level").addEventListener("click", () => {void run(enterScene);});
  id("back-map").addEventListener("click", () => {closePause(false); backMap(); id("enter-level").focus();});
  id("open-menu").addEventListener("click", openPause);
  id("resume").addEventListener("click", closePause);
  id("toggle-taskbar").addEventListener("click", () => {
    id("quest-state").hidden = !id("quest-state").hidden; id("toggle-taskbar").setAttribute("aria-expanded", String(!id("quest-state").hidden));
    if (model && !locks.locked) id("viewport").focus();
  });
  id("close-dialogue").addEventListener("click", () => {closeDialogue(); controls(); id("viewport").focus();});
  id("accept").addEventListener("click", () => {void run(async () => {await action("accept"); closeDialogue(); status("委托已接取，请沿道路前往算坊任务点。");});});
  id("submit").addEventListener("click", () => {void run(async () => {
    if (progress.state.practice.answers.some(answer => answer === null)) {status("还有答案未保存，请回算坊完成。"); return;}
    await action("submit"); closeDialogue(); status("服务器已确认样例结算，可前往出口。");
  });});
  id("exit-runner").addEventListener("click", () => requestExit());
  id("retry-return").addEventListener("click", () => {void run(returnFromTask);});
  function releaseKeys() {keys.clear(); heldActions.clear(); clearInput();}
  window.addEventListener("keydown", event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    const mode = context();
    const editable = event.target.closest?.("input,textarea,select,[contenteditable='true']");
    const root = mode === "confirm" ? id("save-choice") : mode === "menu" ? id("pause") : mode === "dialogue" ? id("dialogue") : mode === "task" ? id("runner") : null;
    if (key === "tab" && root) {
      const items = focusables(root), index = items.indexOf(document.activeElement);
      if (items.length && (index < 0 || (!event.shiftKey && index === items.length - 1) || (event.shiftKey && index === 0))) {
        event.preventDefault(); (event.shiftKey ? items.at(-1) : items[0]).focus();
      }
      return;
    }
    if (editable && key !== "escape") {if (key === "enter" && event.repeat) event.preventDefault(); return;}
    const discrete = ["escape", "enter", " ", "e", "q", "tab"].includes(key);
    if (discrete && (event.repeat || heldActions.has(key))) {event.preventDefault(); return;}
    if (key === "escape") {
      event.preventDefault(); heldActions.add(key); if (busy) return;
      if (mode === "confirm") id("stay-in-task").click();
      else if (mode === "task") requestExit();
      else if (mode === "dialogue") id("close-dialogue").click();
      else if (mode === "menu") closePause();
      else if (mode === "map" && !id("locations").hidden) id("back-chapters").click();
      else openPause(); return;
    }
    if (["dialogue", "menu", "confirm", "map"].includes(mode)) {
      const scope = root || (id("locations").hidden ? id("chapters") : id("locations"));
      const items = focusables(scope), index = items.indexOf(document.activeElement);
      if (["arrowup", "arrowdown"].includes(key) && items.length) {event.preventDefault(); items[(index + (key === "arrowdown" ? 1 : -1) + items.length) % items.length].focus();}
      if (["enter", " "].includes(key) && items.length) {event.preventDefault(); heldActions.add(key); if (!busy) (items[index] || items[0]).click();}
      return;
    }
    if (mode !== "scene" || event.target.closest?.("button:not(.scene-entity),a")) return;
    if (["arrowleft", "arrowright", "arrowup", "arrowdown", "a", "d", "e", "q", "tab", " "].includes(key)) event.preventDefault();
    if (key === "tab") {heldActions.add(key); id("toggle-taskbar").click(); return;}
    if (locks.locked || busy) return;
    if (key === "e") {heldActions.add(key); void run(() => interact()); return;}
    if (key === "q") {heldActions.add(key); model.cycleTarget(); return;}
    if (["arrowleft", "arrowright", "a", "d"].includes(key)) {
      keys.add(key); model.direction = Number(keys.has("arrowright") || keys.has("d")) - Number(keys.has("arrowleft") || keys.has("a"));
    }
  });
  window.addEventListener("keyup", event => {keys.delete(event.key.toLowerCase()); heldActions.delete(event.key.toLowerCase()); if (model && !locks.locked) model.direction = Number(keys.has("arrowright") || keys.has("d")) - Number(keys.has("arrowleft") || keys.has("a")); else clearInput();});
  window.addEventListener("blur", releaseKeys);
  function hide() {releaseKeys(); reset(); status("返回时将重新验证身份并读取进度。未保存输入已清空。");}
  function restore() {if (!document.hidden) {if (busy) pending = true; else void run(load);}}
  document.addEventListener("visibilitychange", () => {if (document.hidden) hide(); else restore();});
  window.addEventListener("pagehide", hide); window.addEventListener("pageshow", restore);
  window.addEventListener("beforeunload", event => {if (dirty()) {event.preventDefault(); event.returnValue = "";}});
  function animate(time) {
    if (model && view) {model.step(lastFrame === null ? 0 : Math.max(0, (time - lastFrame) / 1000)); view.draw(model); controls();}
    lastFrame = time; frame = requestAnimationFrame(animate);
  }
  frame = requestAnimationFrame(animate);
  window.addEventListener("pagehide", () => {cancelAnimationFrame(frame); frame = null;});
  window.addEventListener("pageshow", () => {if (frame === null) frame = requestAnimationFrame(animate);});
})();

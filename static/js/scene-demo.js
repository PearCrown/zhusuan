"use strict";
(() => {
  const id = name => document.getElementById(name), data = window.HuaxiaSceneDemo;
  const client = new window.HuaxiaChapterClient(data.chapterId);
  const locks = new window.HuaxiaInputLocks();
  const keys = new Set();
  // Volatile only. Never render an entry until an authenticated read returns its context.
  const suspensions = new Map();
  let progress, questions = [], model, view, host, token, runnerController, dialogueLock, pauseLock, nextExitAction = "return";
  let taskSaveContext = null;
  const regions = window.HuaxiaMapRegions, mapEvents = window.HuaxiaMapEvents;
  const selectedPlaces = new Map();
  let chapterEntry, regionEntry, levelEntry, gateNote;
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
    try {host?.dispose();} finally {host = null; token = null; taskSaveContext = null; runnerController = null;}
    view?.dispose(); view = null; model = null; progress = null; questions = []; lastFrame = null;
    for (const name of ["chapters", "locations", "scene", "runner"]) id(name).hidden = true;
    id("region-event-index").open = false;
    chapterEntry = regionEntry = levelEntry = null;
    gateNote = ""; selectedPlaces.clear();
    for (const name of ["chapter-nodes", "level-nodes", "quest-state", "runner-content", "runner-status", "dialogue-text", "level-state"]) id(name).replaceChildren();
  }
  function acceptProgress(value) {
    if (!value || value.chapterId !== data.chapterId || !Number.isSafeInteger(value.revision) || value.revision < 0 ||
        !["gate", "workshop"].includes(value.state?.story?.scene) || !["not_started", "accepted", "submitted"].includes(value.state.story.quest) ||
        !Array.isArray(value.state?.practice?.answers) || value.state.practice.answers.length !== questions.length) throw Error("INVALID_PROGRESS");
    progress = value;
    const labels = {not_started: "与守门人交谈，接取委托", accepted: "前往算坊任务点，完成后回守门人处交付", submitted: "样例任务已交付"};
    id("quest-state").textContent = labels[value.state.story.quest] + (value.result ? ` · 服务器成绩 ${value.result.score} / ${value.result.maxScore}` : "");
    gateNote = value.result ? "样例已结算，可进入查看场景。" : labels[value.state.story.quest];
    if (levelEntry) showLevelNote("亳 · " + data.levelTitle, gateNote);
    id("dialogue-text").textContent = value.result ? "守门人：委托已交付，感谢相助。" : "守门人：请到前方算坊完成练习，再回来交付。";
    id("accept").hidden = value.state.story.quest !== "not_started";
    id("submit").hidden = value.state.story.quest !== "accepted";
  }
  function controls() {
    document.querySelectorAll("button, #runner-content input").forEach(el => {el.disabled = busy || el.hasAttribute("data-unavailable");});
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
  async function run(fn, {mapRecovery = false} = {}) {
    if (busy) return;
    busy = true; clearInput();
    const lock = locks.acquire("network"); controls();
    try {await fn();}
    catch (error) {
      if (!error.stale) {
        remember();
        reset();
        if (error.code === "authentication_required") status("登录已失效，请返回账号中心重新登录。", true);
        else if (mapRecovery) status("暂时无法读取地图。请打开菜单，重新读取进度。", true);
        else status("操作结果尚未确认。请重新读取进度，勿重复提交。", true);
        if (mapRecovery) focusAfter = id("open-menu");
      }
    } finally {
      busy = false; locks.release(lock); clearInput(); controls();
      if (!document.hidden && focusAfter?.isConnected) {focusAfter.focus(); focusAfter = null;}
      else if (!document.hidden && !id("scene").hidden && !token) {
        (id("dialogue").hidden ? id("viewport") : focusables(id("dialogue"))[0]).focus();
      }
      if (pending && !document.hidden) {pending = false; void run(() => load(true));}
    }
  }
  function assertCurrent(started) {if (started !== epoch) throw Object.assign(Error("STALE"), {stale: true});}
  function showLevelNote(title, description, slotButton = null) {
    id("map-note-title").textContent = title;
    id("level-state").textContent = description;
    for (const button of id("level-nodes").querySelectorAll("[aria-pressed]")) {
      button.setAttribute("aria-pressed", String(button === slotButton));
    }
  }
  const worldCrop = [0, 90, 1540, 900];
  function setPoint(element, x, y, [left, top, width, height]) {
    element.style.setProperty("--map-x", `${(x - left) / width * 100}%`);
    element.style.setProperty("--map-y", `${(y - top) / height * 100}%`);
  }
  function renderMaps(listing) {
    const sample = listing.chapters.find(chapter => chapter?.chapterId === data.chapterId && typeof chapter.title === "string");
    for (const region of regions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "atlas-region";
      button.dataset.regionId = region.id;
      button.textContent = region.title;
      setPoint(button, ...region.center, worldCrop);
      if (sample && region.id === "central-plains") {
        button.dataset.chapterId = data.chapterId;
        chapterEntry = button;
      }
      button.addEventListener("click", () => {
        if (!busy && !id("chapters").hidden && id("pause").hidden) openRegion(region, button);
      });
      id("chapter-nodes").append(button);
    }
  }
  function landmarkIcon(type) {
    const icon = document.createElement("span");
    icon.className = "atlas-landmark";
    icon.dataset.kind = type;
    icon.setAttribute("aria-hidden", "true");
    return icon;
  }
  function openRegion(region, source, focus = true) {
    regionEntry = source;
    levelEntry = null;
    const [left, top, width, height] = region.crop;
    const crop = id("region-crop");
    crop.style.left = `${-left / width * 100}%`;
    crop.style.top = `${(worldCrop[1] - top) / height * 100}%`;
    crop.style.width = `${worldCrop[2] / width * 100}%`;
    crop.style.height = `${worldCrop[3] / height * 100}%`;
    id("location-name").textContent = region.title;
    id("map-count").textContent = region.places.length;
    id("region-event-index").open = false;
    for (const [index, row] of [...id("region-event-index").querySelectorAll("li")].entries()) {
      row.value = index + 1;
      row.hidden = !region.events.includes(index + 1);
    }
    const events = id("region-event-points");
    events.replaceChildren(...region.events.map(number => {
      const dot = document.createElement("span");
      dot.className = "atlas-event-dot";
      dot.dataset.event = number;
      dot.textContent = String(number).padStart(2, "0");
      setPoint(dot, ...mapEvents[number - 1], region.crop);
      return dot;
    }));

    const levelNodes = id("level-nodes");
    levelNodes.replaceChildren();
    const boundLevels = chapterEntry && region.id === "central-plains" ? data.mapLevels : [];
    for (const [placeId, name, x, y, type] of region.places) {
      const level = boundLevels.find(item => item.placeId === placeId);
      const playable = level?.levelId === data.levelId && level.sceneId === data.sceneId;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "atlas-place";
      button.dataset.placeId = placeId;
      if (level) button.dataset.levelId = level.levelId;
      button.setAttribute("aria-label", `${name} · ${playable ? "进入城门样例" : "查看地点"}`);
      const caption = document.createElement("span");
      caption.className = "atlas-place-name";
      caption.textContent = name;
      button.append(landmarkIcon(type), caption);
      setPoint(button, x, y, region.crop);
      if (playable) levelEntry = button;
      else button.setAttribute("aria-pressed", "false");
      function showPlace() {
        const note = level?.kind === "content-slot"
          ? "关卡内容待开发者 B 接入。"
          : "可查看这个地点。关卡内容待接入。";
        showLevelNote(name, note, button);
        selectedPlaces.set(region.id, placeId);
      }
      button.addEventListener("click", () => {
        if (busy || id("locations").hidden || !id("pause").hidden) return;
        if (playable) {
          selectedPlaces.delete(region.id);
          void run(enterScene);
        } else showPlace();
      });
      levelNodes.append(button);
      if (selectedPlaces.get(region.id) === placeId) showPlace();
    }
    const selected = levelNodes.querySelector('[aria-pressed="true"]');
    if (!selected) {
      if (levelEntry) showLevelNote("亳 · " + data.levelTitle, gateNote);
      else showLevelNote(region.title + "地志", "点选图上的城邑或地形，查看该处关卡。");
    }
    id("chapters").hidden = true;
    id("locations").hidden = false;
    id("region-map-scroll").scrollLeft = 0;
    status("请选择地点。");
    if (focus) (selected || levelEntry || levelNodes.firstElementChild).focus();
  }
  async function load(resume = false) {
    reset(); const started = epoch;
    status("正在读取章节与服务器进度…");
    const listing = await client.request("/game/api/chapters"); assertCurrent(started);
    renderMaps(listing);
    if (!chapterEntry) {
      id("chapters").hidden = false;
      focusAfter = id("chapter-nodes").firstElementChild;
      status("可展开地区详图。暂无已接入的关卡。");
      return;
    }
    const result = await client.load(); assertCurrent(started);
    if (!Array.isArray(result.questions) || result.questions.some(q => typeof q.prompt !== "string")) throw Error("INVALID_QUESTIONS");
    questions = result.questions; acceptProgress(result.progress);
    id("chapters").hidden = false; focusAfter = chapterEntry; status("进度已读取，请选择章节。");
    const checkpoint = resume ? suspensions.get(client.saveContext) : null;
    if (checkpoint) {
      openRegion(regions.find(region => region.id === chapterEntry.dataset.regionId), chapterEntry, false);
      focusAfter = null;
      if (await enterScene(checkpoint)) suspensions.delete(checkpoint.saveContext);
      else if (!model) {
        id("locations").hidden = true;
        id("chapters").hidden = false;
        focusAfter = chapterEntry;
      }
    }
  }
  async function action(name, fields = {}) {
    const started = epoch;
    const result = await client.dispatch(name, fields); assertCurrent(started);
    acceptProgress(result.progress);
  }
  async function enterScene(checkpoint = null) {
    if (!levelEntry) return;
    // Re-read on entry to catch changes made in the original sample or another tab.
    const started = epoch, result = await client.load(); assertCurrent(started);
    questions = result.questions; acceptProgress(result.progress);
    if (checkpoint && checkpoint.saveContext !== client.saveContext) {
      status("会话或题目已变化，旧输入未应用。请重新选择关卡。", true); return;
    }
    closeDialogue(); host?.dispose(); view?.dispose();
    model = new window.HuaxiaSceneModel(data, locks);
    if (checkpoint) model.restore(checkpoint.snapshot);
    view = new window.HuaxiaSceneView(id("viewport"), data, entityId => {
      if (!busy && !locks.locked && model.targets().some(entity => entity.id === entityId)) void run(() => interact(entityId));
    });
    host = new window.HuaxiaSceneHost({
      context: {chapterId: data.chapterId, levelSessionId: `preview-${epoch}`, sceneId: data.sceneId, sessionEpoch: `page-${epoch}`},
      scene: data.scene, locks, clearInput,
      readProgress: async ({signal}) => {
        // Keep an unchecked response out of the active client's cache.
        const reader = new window.HuaxiaChapterClient(data.chapterId);
        const result = await reader.load();
        signal.throwIfAborted();
        if (!taskSaveContext || result.saveContext !== taskSaveContext) {
          throw Object.assign(Error("Save context changed during return"), {code: "save_context_changed"});
        }
        questions = result.questions;
        acceptProgress(result.progress);
        client.accept(result);
        return result.progress;
      },
      restoreScene: ({snapshot, signal}) => {signal.throwIfAborted(); model.restore(snapshot); view.draw(model);},
      callbacks: {submitRequested: report => {void run(() => saveAnswer(report.value));}},
    });
    id("locations").hidden = true; id("scene").hidden = false;
    id("scene-name").textContent = data.levelTitle; view.draw(model); id("viewport").focus();
    status("沿道路走近守门人。场景位置为本页临时状态。");
    if (checkpoint) {
      id("quest-state").hidden = checkpoint.taskbarCollapsed;
      id("toggle-taskbar").setAttribute("aria-expanded", String(!checkpoint.taskbarCollapsed));
      if (checkpoint.wasTask && progress.state.story.quest === "accepted" && progress.state.story.scene === "workshop" && !progress.result) {
        await openTask(checkpoint);
        status("已重新读取服务器进度并恢复任务界面；请按各题提示确认保存状态。");
      } else status(checkpoint.wasTask ? "已恢复场景；任务状态已变化，未自动应用旧任务输入或写入服务器。" : "已重新读取服务器进度，恢复场景位置。移动按键已清空。");
    }
    return !checkpoint?.wasTask || Boolean(token && runnerController);
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
      const draft = options.draft;
      if (draft && Array.isArray(draft.answers) && Array.isArray(draft.baseAnswers) && draft.answers.length === inputs.length && draft.baseAnswers.length === inputs.length) {
        inputs.forEach((input, index) => {
          const local = draft.answers[index], base = String(draft.baseAnswers[index] ?? "");
          if (typeof local !== "string" || local === base) return;
          input.value = local;
          hints[index].textContent = local === String(saved[index] ?? "") ? "已由服务器保存" :
            saved[index] !== draft.baseAnswers[index] ? `本地输入尚未保存；云端当前为：${saved[index] ?? "未填写"}。确认后可保存本地值。` : "已恢复本页未保存输入";
        });
      }
      return runnerController;
    }};
  }
  async function saveAnswer({questionIndex, answer}) {
    await action("answer", {questionIndex, answer});
    runnerController.markSaved(questionIndex); id("runner-status").textContent = "本题已保存至服务器。";
    focusAfter = id(`scene-answer-${questionIndex}`);
  }
  async function openTask(checkpoint = null) {
    if (progress.result) {status("样例已结算，请到守门人或出口查看。"); return;}
    if (progress.state.story.quest !== "accepted") {status("请先向守门人接取委托。"); return;}
    if (progress.state.story.scene !== "workshop") {
      if (checkpoint) return;
      await action("move", {scene: "workshop"});
    }
    checkpoint ||= suspensions.get(client.saveContext);
    id("runner-content").replaceChildren(); id("runner-status").textContent = "答案只有确认保存后才写入服务器。";
    id("retry-return").hidden = true; id("return-to-map").hidden = true; id("exit-runner").hidden = false;
    taskSaveContext = client.saveContext;
    // This ID is a presentation-only legacy bridge, never sent as a server task instance.
    token = host.beginTask({instanceId: `legacy-preview-${++taskNumber}`, runner: legacyRunner(), host: id("runner-content"), snapshot: model.capture(), draft: checkpoint?.draft});
    if (checkpoint) suspensions.delete(checkpoint.saveContext);
    id("runner").hidden = false; focusAfter = id("runner-content").querySelector("input");
  }
  async function returnFromTask() {
    const returningToken = token;
    runnerController = null;
    try {
      await host.returnToScene(returningToken);
      if (token !== returningToken) return;
      host.finishReturn(returningToken);
      token = null; taskSaveContext = null;
      id("runner").hidden = true; id("viewport").focus(); status("已读取服务器进度，返回进入任务前的位置。");
    } catch (error) {
      if (token !== returningToken || error.code === "RETURN_CONTEXT_EXPIRED") return;
      if (error.code === "save_context_changed") {
        reset();
        status("会话或题目已变化。请从菜单重新读取进度，再选择关卡。", true);
        focusAfter = id("open-menu");
        return;
      }
      if (error.code === "authentication_required") throw error;
      id("runner-status").textContent = "尚未恢复场景。请重试，或重新读取进度后返回地图。";
      id("exit-runner").hidden = true; id("retry-return").hidden = false; id("return-to-map").hidden = false;
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
    if (busy) focusAfter = levelEntry; else levelEntry?.focus();
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
    if (focus) {
      const target = model ? id("viewport") : !id("locations").hidden ? (levelEntry || id("level-nodes").firstElementChild) : regionEntry || chapterEntry;
      (target || id("open-menu")).focus();
    }
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
  id("reload").addEventListener("click", () => {if (dirty()) requestExit("reload"); else void run(() => load(true));});
  id("back-chapters").addEventListener("click", () => {
    if (busy || id("locations").hidden) return;
    id("locations").hidden = true;
    id("chapters").hidden = false;
    status("请选择章节。");
    id("region-event-index").open = false;
    regionEntry?.focus();
  });
  id("back-map").addEventListener("click", () => {closePause(false); backMap();});
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
  id("return-to-map").addEventListener("click", () => {void run(load, {mapRecovery: true});});
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
      else if (mode === "map" && id("region-event-index").open) {
        id("region-event-index").open = false; id("region-event-index").querySelector("summary").focus();
      } else if (mode === "map" && !id("locations").hidden) id("back-chapters").click();
      else openPause(); return;
    }
    if (["dialogue", "menu", "confirm", "map"].includes(mode)) {
      if (mode === "map" && event.target.closest?.("summary")) return;
      const scope = root || (id("locations").hidden ? id("chapters") : id("locations"));
      const items = focusables(scope), index = items.indexOf(document.activeElement);
      const previous = key === "arrowup" || (mode === "map" && key === "arrowleft");
      const next = key === "arrowdown" || (mode === "map" && key === "arrowright");
      if (event.target === id("region-map-scroll") && (previous || next)) return;
      if ((previous || next) && items.length) {event.preventDefault(); items[(index + (next ? 1 : -1) + items.length) % items.length].focus();}
      if (["enter", " "].includes(key) && items.length && document.activeElement !== id("open-menu")) {
        event.preventDefault(); heldActions.add(key); if (!busy) (items[index] || items[0]).click();
      }
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
  function remember() {
    if (!model || !progress || !client.saveContext) return;
    const checkpoint = {
      saveContext: client.saveContext, snapshot: model.capture(), taskbarCollapsed: id("quest-state").hidden,
      wasTask: Boolean(token && runnerController),
      draft: runnerController ? {...runnerController.exportDraft(), baseAnswers: [...progress.state.practice.answers]} : null,
    };
    const previous = suspensions.get(checkpoint.saveContext);
    if (!previous?.draft || checkpoint.draft) suspensions.set(checkpoint.saveContext, checkpoint);
  }
  function suspendedDirty() {return [...suspensions.values()].some(entry => entry.draft?.answers.some((answer, index) => answer !== String(entry.draft.baseAnswers[index] ?? "")));}
  function hide() {releaseKeys(); remember(); reset(); status("返回时将重新读取进度；未保存输入暂存于本页内存，不会自动提交。");}
  function restore() {if (!document.hidden) {if (busy) pending = true; else void run(() => load(true));}}
  document.addEventListener("visibilitychange", () => {if (document.hidden) hide(); else restore();});
  window.addEventListener("pagehide", hide); window.addEventListener("pageshow", restore);
  window.addEventListener("beforeunload", event => {if (dirty() || suspendedDirty()) {event.preventDefault(); event.returnValue = "";}});
  function animate(time) {
    if (model && view) {model.step(lastFrame === null ? 0 : Math.max(0, (time - lastFrame) / 1000)); view.draw(model); controls();}
    lastFrame = time; frame = requestAnimationFrame(animate);
  }
  frame = requestAnimationFrame(animate);
  window.addEventListener("pagehide", () => {cancelAnimationFrame(frame); frame = null;});
  window.addEventListener("pageshow", () => {if (frame === null) frame = requestAnimationFrame(animate);});
})();

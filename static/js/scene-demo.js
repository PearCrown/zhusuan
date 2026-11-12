"use strict";
(() => {
  const id = name => document.getElementById(name), data = window.HuaxiaSceneDemo;
  // 正式入口先到亳的行动选择；保留直接场景入口供独立预览。
  const STAGE_MODE = window.HUAXIA_STAGE_MODE !== false;
  const client = new window.HuaxiaChapterClient(data.chapterId);
  const locks = new window.HuaxiaInputLocks();
  const keys = new Set();
  let checkpoint, model, view, dialogueLock, pauseLock, conversation;
  const regions = window.HuaxiaMapRegions, mapEvents = window.HuaxiaMapEvents;
  const campNote = "走访营前，听守门人与妇好说起河谷往事。";
  const selectedPlaces = new Map();
  let chapterEntry, regionEntry, levelEntry;
  const heldActions = new Set();
  let busy = false, pending = false, epoch = 0, lastFrame = null, frame, focusAfter;
  const status = (message, error = false) => {id("status").textContent = message; id("status").classList.toggle("error", error);};
  const clearInput = () => {keys.clear(); model?.clearInput();};
  function closeDialogue() {
    locks.release(dialogueLock);
    dialogueLock = null;
    conversation = null;
    id("dialogue").hidden = true;
    clearInput();
  }
  function reset() {
    epoch++; focusAfter = null; client.invalidate(); closeDialogue();
    locks.release(pauseLock); pauseLock = null; id("pause").hidden = true;
    view?.dispose(); view = null; model = null; lastFrame = null;
    for (const name of ["chapters", "locations", "scene", "stages"]) id(name).hidden = true;
    window.HuaxiaStageSelect?.close();
    id("region-event-index").open = false;
    chapterEntry = regionEntry = levelEntry = null;
    selectedPlaces.clear();
    for (const name of ["chapter-nodes", "level-nodes", "level-state"]) id(name).replaceChildren();
  }
  function updateNearby() {
    const target = model?.nearby();
    const hint = id("nearby");
    hint.hidden = !target;
    if (target) {
      const label = `与${target.label}交谈`;
      if (hint.textContent !== label) hint.textContent = label;
    }
  }
  function controls() {
    document.querySelectorAll("button").forEach(el => {el.disabled = busy || el.hasAttribute("data-unavailable");});
    const mode = context();
    id("viewport").inert = mode !== "scene";
    id("camp-back").inert = mode !== "scene";
    id("camp-left").inert = mode !== "scene";
    id("camp-right").inert = mode !== "scene";
    id("open-menu").inert = mode !== "map";
    id("chapters").inert = mode !== "map"; id("locations").inert = mode !== "map";
    id("stages").inert = mode !== "map";
    id("scene").classList.toggle("dialogue-open", mode === "dialogue");
    updateNearby();
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
        else status("暂时无法进入营前，请重新读取。", true);
        if (mapRecovery) focusAfter = id("open-menu");
      }
    } finally {
      busy = false; locks.release(lock); clearInput(); controls();
      if (!document.hidden && focusAfter?.isConnected) {focusAfter.focus(); focusAfter = null;}
      else if (!document.hidden && !id("scene").hidden) {
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
      const chapter = window.HuaxiaCurriculum && window.HuaxiaCurriculum.chapterOf(region.id);
      if (chapter) button.setAttribute("aria-label", `${chapter.no} ${chapter.title} · ${region.title}`);
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
    renderChapterGuide();
  }

  /** 地区图左侧的小节指引：这一章有哪几节、哪一节能进。 */
  function renderSectionGuide(region) {
    const guide = id("section-guide");
    if (!guide) return;
    guide.replaceChildren();
    const curriculum = window.HuaxiaCurriculum;
    const chapter = curriculum && curriculum.chapterOf(region.id);
    const head = document.createElement("p");
    head.className = "map-guide-title";
    head.textContent = "本章小节";
    guide.append(head);
    if (!chapter) {
      const empty = document.createElement("p");
      empty.className = "map-guide-region";
      empty.textContent = "本章暂无课程数据。";
      guide.append(empty);
      return;
    }
    const meta = document.createElement("div");
    meta.className = "map-guide-item is-locked";
    const no = document.createElement("span");
    no.className = "map-guide-no";
    no.textContent = chapter.no;
    const name = document.createElement("span");
    name.className = "map-guide-name";
    name.textContent = chapter.title;
    meta.append(no, name);
    guide.append(meta);

    let shown = 0;
    for (const [placeId] of region.places) {
      const place = curriculum.placeOf(region.id, placeId);
      if (!place) continue;
      shown += 1;
      const playable = Boolean(region.id === "central-plains" && chapterEntry);
      const item = document.createElement(playable ? "button" : "div");
      if (playable) item.type = "button";
      item.className = `map-guide-item${playable ? " is-open" : " is-locked"}`;
      const sec = document.createElement("span");
      sec.className = "map-guide-no";
      sec.textContent = place.no;
      const title = document.createElement("span");
      title.className = "map-guide-name";
      title.textContent = place.title;
      const state = document.createElement("span");
      state.className = "map-guide-region";
      state.textContent = playable ? "进入本节行动" : "未开放";
      item.append(sec, title, state);
      if (playable) {
        item.addEventListener("click", () => {
          if (busy || id("locations").hidden || !id("pause").hidden) return;
          openStages();
        });
      }
      guide.append(item);
    }
    if (!shown) {
      const empty = document.createElement("p");
      empty.className = "map-guide-region";
      empty.textContent = "本章暂无关卡内容。";
      guide.append(empty);
    }
  }

  /** 左侧课程指引：第几章、章名、对应哪个地区、是否已开放。 */
  function renderChapterGuide() {
    const guide = id("chapter-guide");
    if (!guide) return;
    guide.replaceChildren();
    const title = document.createElement("p");
    title.className = "map-guide-title";
    title.textContent = "课程指引";
    guide.append(title);
    const curriculum = window.HuaxiaCurriculum;
    const ordered = curriculum
      ? [...regions].sort((a, b) => curriculum.chapterOrder(a.id) - curriculum.chapterOrder(b.id))
      : regions;
    for (const region of ordered) {
      const chapter = curriculum && curriculum.chapterOf(region.id);
      const playable = Boolean(region.id === "central-plains" && chapterEntry);
      const item = document.createElement(playable ? "button" : "div");
      if (playable) item.type = "button";
      item.className = `map-guide-item${playable ? " is-open" : " is-locked"}`;
      const no = document.createElement("span");
      no.className = "map-guide-no";
      no.textContent = chapter ? chapter.no : "—";
      const name = document.createElement("span");
      name.className = "map-guide-name";
      name.textContent = chapter ? chapter.title : region.title;
      const meta = document.createElement("span");
      meta.className = "map-guide-region";
      meta.textContent = `${region.title}${playable ? " · 可进入" : " · 未开放"}`;
      item.append(no, name, meta);
      if (playable) {
        item.addEventListener("click", () => {
          // 只在"总图正显示、没有暂停"时响应；写反会导致永远点不动。
          if (busy || id("chapters").hidden || !id("pause").hidden) return;
          const node = id("chapter-nodes").querySelector(`[data-region-id="${region.id}"]`);
          openRegion(region, node || chapterEntry);
        });
      }
      guide.append(item);
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
    const surface = id("region-crop").parentElement;
    surface.style.setProperty("--region-ratio", width / height);
    surface.style.setProperty("--crop-x", (worldCrop[0] - left) / width);
    surface.style.setProperty("--crop-y", (worldCrop[1] - top) / height);
    surface.style.setProperty("--crop-width", worldCrop[2] / width);
    surface.style.setProperty("--crop-height", worldCrop[3] / height);
    id("location-name").textContent = region.title;
    const chapter = window.HuaxiaCurriculum && window.HuaxiaCurriculum.chapterOf(region.id);
    if (chapter) id("location-kicker").textContent = `${chapter.no} · ${chapter.title}`;
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
      button.setAttribute("aria-label", `${name} · ${playable ? "进入关卡选择" : "查看地点"}`);
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
          showLevelNote(data.levelTitle, campNote);
          void run(STAGE_MODE ? openStages : enterScene);
        } else showPlace();
      });
      levelNodes.append(button);
      if (selectedPlaces.get(region.id) === placeId) showPlace();
    }
    const selected = levelNodes.querySelector('[aria-pressed="true"]');
    if (!selected) {
      if (levelEntry) showLevelNote(data.levelTitle, campNote);
      else showLevelNote(region.title + "地志", "点选图上的城邑或地形，查看该处关卡。");
    }
    renderSectionGuide(region);
    id("chapters").hidden = true;
    id("locations").hidden = false;
    id("region-map-scroll").scrollLeft = 0;
    status("请选择地点。");
    if (focus) (selected || levelEntry || levelNodes.firstElementChild).focus();
  }
  async function load(resume = false) {
    reset(); const started = epoch;
    status("正在读取章节…");
    const listing = await client.request("/game/api/chapters"); assertCurrent(started);
    renderMaps(listing);
    if (!chapterEntry) {
      id("chapters").hidden = false;
      focusAfter = id("chapter-nodes").firstElementChild;
      status("可展开地区详图。暂无已接入的关卡。");
      return;
    }
    const saved = resume ? checkpoint : null;
    checkpoint = null;
    id("chapters").hidden = false;
    focusAfter = chapterEntry;
    status("请选择章节。");
    if (saved) {
      openRegion(regions.find(region => region.id === chapterEntry.dataset.regionId), chapterEntry, false);
      if (await enterScene(saved)) return;
      id("locations").hidden = true;
      id("chapters").hidden = false;
    }
    if (STAGE_MODE) await applyDeepLink();
  }

  // /game/#stage-select：从关卡页结算后返回时，直接落在亳 的关卡选择上，
  // 而不是回到总图让玩家重新点一遍"中原 → 亳"。
  let deepLinkDone = false;
  async function applyDeepLink() {
    if (deepLinkDone || !["#stage-select", "#camp"].includes(location.hash)) return;
    const region = regions.find(item => item.id === "central-plains");
    if (!region || !chapterEntry) return;
    deepLinkDone = true;
    openRegion(region, chapterEntry, false);
    focusAfter = null;
    if (location.hash === "#camp") await enterScene();
    else openStages();
  }

  function openStages() {
    id("locations").hidden = true;
    id("stages").hidden = false;
    status("选择一处行动。");
    void window.HuaxiaStageSelect.open(id("stage-app"), {
      onBack: closeStages,
      onCamp: () => void run(enterScene),
    });
  }

  function closeStages() {
    if (window.HuaxiaStageSelect) window.HuaxiaStageSelect.close();
    id("stages").hidden = true;
    id("locations").hidden = false;
    controls();
    levelEntry?.focus();
  }

  function stagesOpen() {
    return !id("stages").hidden;
  }

  function fitCamp() {
    const viewport = id("viewport");
    if (!model || !viewport.clientWidth || !viewport.clientHeight) return;
    const span = viewport.clientWidth / (viewport.clientHeight * data.art.aspectRatio);
    model.setViewportSpan(Math.min(data.viewportSpan, span));
    view.draw(model);
  }

  async function enterScene(saved = null) {
    if (!levelEntry) return false;
    const started = epoch;
    await client.load();
    assertCurrent(started);
    if (saved && saved.saveContext !== client.saveContext) return false;

    closeDialogue();
    view?.dispose();
    model = new window.HuaxiaSceneModel(data, locks);
    if (saved) model.restore(saved.snapshot);
    view = new window.HuaxiaSceneView(id("viewport"), data, interact);
    if (stagesOpen()) {
      window.HuaxiaStageSelect.close();
      id("stages").hidden = true;
    }
    focusAfter = null;
    id("locations").hidden = true;
    id("scene").hidden = false;
    id("scene-name").textContent = data.levelTitle;
    fitCamp();
    view.draw(model);
    status("");
    id("viewport").focus();
    return true;
  }

  function showDialogueLine() {
    const {entity, index} = conversation;
    const lastLine = index === entity.lines.length - 1;
    id("dialogue-text").textContent = entity.lines[index];
    id("close-dialogue").hidden = lastLine;
    id("advance-dialogue").textContent = lastLine ? "结束对话" : "继续 ›";
  }

  function interact(entityId) {
    if (!model || busy || locks.locked) return;
    const entity = entityId ? model.targets().find(item => item.id === entityId) : model.nearby();
    if (!entity) return;
    dialogueLock = locks.acquire("dialogue");
    clearInput();
    conversation = {entity, index: 0};
    id("dialogue-title").textContent = entity.label;
    id("dialogue-portrait").src = entity.art;
    showDialogueLine();
    id("dialogue").hidden = false;
    controls();
    id("advance-dialogue").focus();
  }

  function finishDialogue() {
    closeDialogue();
    controls();
    id("viewport").focus();
  }

  function backMap() {
    closeDialogue();
    view?.dispose(); view = null; model = null;
    id("scene").hidden = true;
    if (STAGE_MODE) {
      if (location.hash === "#camp") history.replaceState(history.state, "", "#stage-select");
      openStages();
      controls();
      return;
    }
    id("locations").hidden = false;
    controls();
    levelEntry?.focus();
  }

  function focusables(root) {return [...root.querySelectorAll("button,a[href],input,select,textarea,[tabindex='0']")].filter(el => !el.disabled && !el.closest("[hidden]") && el.tabIndex >= 0);}
  function context() {
    if (!id("pause").hidden) return "menu";
    if (!id("dialogue").hidden) return "dialogue";
    return model ? "scene" : "map";
  }
  function closePause(focus = true) {
    id("pause").hidden = true; locks.release(pauseLock); pauseLock = null; clearInput();
    controls();
    if (focus) {
      const target = model ? id("viewport") : stagesOpen() ? id("stage-app").querySelector("[data-stage-id='camp']")
        : !id("locations").hidden ? (levelEntry || id("level-nodes").firstElementChild) : regionEntry || chapterEntry;
      (target || id("open-menu")).focus();
    }
  }
  function openPause() {
    if (busy || model) return;
    clearInput(); pauseLock = locks.acquire("pause"); id("pause").hidden = false;
    controls(); id("resume").focus();
  }
  id("reload").addEventListener("click", () => void run(() => load(true), {mapRecovery: true}));
  const mapSidebarToggles = document.querySelectorAll(".map-sidebar-toggle");
  for (const toggle of mapSidebarToggles) {
    toggle.addEventListener("click", () => {
      const expand = toggle.getAttribute("aria-expanded") === "false";
      for (const button of mapSidebarToggles) {
        button.setAttribute("aria-expanded", String(expand));
        button.textContent = expand ? "收起侧栏" : "展开侧栏";
        id(button.getAttribute("aria-controls")).hidden = !expand;
      }
      if (!expand) id("region-event-index").open = false;
    });
  }
  id("back-chapters").addEventListener("click", () => {
    if (busy || id("locations").hidden) return;
    id("locations").hidden = true;
    id("chapters").hidden = false;
    status("请选择章节。");
    id("region-event-index").open = false;
    regionEntry?.focus();
  });
  id("camp-back").addEventListener("click", backMap);
  id("open-menu").addEventListener("click", openPause);
  id("resume").addEventListener("click", closePause);
  id("close-dialogue").addEventListener("click", finishDialogue);
  id("advance-dialogue").addEventListener("click", () => {
    if (!conversation) return;
    conversation.index++;
    if (conversation.index < conversation.entity.lines.length) showDialogueLine();
    else finishDialogue();
  });
  for (const [name, direction] of [["camp-left", -1], ["camp-right", 1]]) {
    const button = id(name);
    button.addEventListener("pointerdown", event => {
      if (!event.isPrimary || busy || !model || locks.locked) return;
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      model.direction = direction;
      model.move(direction, 0.06);
    });
    button.addEventListener("click", event => {
      if (event.detail === 0 && !busy && model && !locks.locked) model.move(direction, 0.1);
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      button.addEventListener(type, clearInput);
    }
  }
  window.addEventListener("resize", fitCamp);
  function releaseKeys() {keys.clear(); heldActions.clear(); clearInput();}
  window.addEventListener("keydown", event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    const mode = context();
    const editable = event.target.closest?.("input,textarea,select,[contenteditable='true']");
    const root = mode === "menu" ? id("pause") : mode === "dialogue" ? id("dialogue") : null;
    if (key === "tab" && root) {
      const items = focusables(root), index = items.indexOf(document.activeElement);
      if (items.length && (index < 0 || (!event.shiftKey && index === items.length - 1) || (event.shiftKey && index === 0))) {
        event.preventDefault(); (event.shiftKey ? items.at(-1) : items[0]).focus();
      }
      return;
    }
    if (editable && key !== "escape") {if (key === "enter" && event.repeat) event.preventDefault(); return;}
    const discrete = ["escape", "enter", " ", "e", "tab"].includes(key);
    if (discrete && (event.repeat || heldActions.has(key))) {event.preventDefault(); return;}
    if (key === "escape") {
      event.preventDefault(); heldActions.add(key); if (busy) return;
      if (mode === "scene") backMap();
      else if (mode === "dialogue") id("close-dialogue").click();
      else if (mode === "menu") closePause();
      else if (mode === "map" && id("region-event-index").open) {
        id("region-event-index").open = false; id("region-event-index").querySelector("summary").focus();
      } else if (mode === "map" && stagesOpen()) closeStages();
      else if (mode === "map" && !id("locations").hidden) id("back-chapters").click();
      else openPause(); return;
    }
    if (mode === "map" && stagesOpen()) {
      // 关卡选择屏自己管焦点：方向键在关卡之间移动，Enter 进入。
      const stageItems = focusables(id("stage-app"));
      const stageIndex = stageItems.indexOf(document.activeElement);
      const stagePrev = key === "arrowup" || key === "arrowleft";
      const stageNext = key === "arrowdown" || key === "arrowright";
      if ((stagePrev || stageNext) && stageItems.length) {
        event.preventDefault();
        stageItems[(stageIndex + (stageNext ? 1 : -1) + stageItems.length) % stageItems.length].focus();
      }
      if (["enter", " "].includes(key) && stageItems.length && document.activeElement !== id("open-menu")) {
        event.preventDefault(); heldActions.add(key);
        if (!busy) (stageItems[stageIndex] || stageItems[0]).click();
      }
      return;
    }
    if (["dialogue", "menu", "map"].includes(mode)) {
      if (mode === "map" && event.target.closest?.("summary")) return;
      const scope = root || (id("locations").hidden ? id("chapters") : id("locations"));
      const items = focusables(scope).filter(item => !item.classList.contains("map-viewport"));
      const index = items.indexOf(document.activeElement);
      const previous = key === "arrowup" || (mode === "map" && key === "arrowleft");
      const next = key === "arrowdown" || (mode === "map" && key === "arrowright");
      if (event.target.classList?.contains("map-viewport") && (previous || next)) return;
      if ((previous || next) && items.length) {event.preventDefault(); items[(index + (next ? 1 : -1) + items.length) % items.length].focus();}
      if (["enter", " "].includes(key) && items.length && document.activeElement !== id("open-menu")) {
        event.preventDefault(); heldActions.add(key); if (!busy) (items[index] || items[0]).click();
      }
      return;
    }
    if (mode !== "scene" || event.target.closest?.("button:not(.scene-entity),a")) return;
    if (["arrowleft", "arrowright", "a", "d", "e"].includes(key)) event.preventDefault();
    if (locks.locked || busy) return;
    if (key === "e") {heldActions.add(key); interact(); return;}
    if (["arrowleft", "arrowright", "a", "d"].includes(key)) {
      keys.add(key); model.direction = Number(keys.has("arrowright") || keys.has("d")) - Number(keys.has("arrowleft") || keys.has("a"));
    }
  });
  window.addEventListener("keyup", event => {keys.delete(event.key.toLowerCase()); heldActions.delete(event.key.toLowerCase()); if (model && !locks.locked) model.direction = Number(keys.has("arrowright") || keys.has("d")) - Number(keys.has("arrowleft") || keys.has("a")); else clearInput();});
  window.addEventListener("blur", releaseKeys);
  function remember() {
    if (model && client.saveContext) checkpoint = {saveContext: client.saveContext, snapshot: model.capture()};
  }
  function hide() { releaseKeys(); remember(); reset(); }
  function restore() {if (!document.hidden) {if (busy) pending = true; else void run(() => load(true));}}
  document.addEventListener("visibilitychange", () => {if (document.hidden) hide(); else restore();});
  window.addEventListener("pagehide", hide); window.addEventListener("pageshow", restore);
  function animate(time) {
    if (model && view) {model.step(lastFrame === null ? 0 : Math.max(0, (time - lastFrame) / 1000)); view.draw(model); updateNearby();}
    lastFrame = time; frame = requestAnimationFrame(animate);
  }
  frame = requestAnimationFrame(animate);
  window.addEventListener("pagehide", () => {cancelAnimationFrame(frame); frame = null;});
  window.addEventListener("pageshow", () => {if (frame === null) frame = requestAnimationFrame(animate);});
})();

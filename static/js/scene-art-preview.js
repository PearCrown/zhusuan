"use strict";
(() => {
  const id = name => document.getElementById(name);
  const width = 1672, height = 941;
  // Independent single-screen composition; never registered as a chapter or saved.
  const data = {
    viewportSpan: 1, speed: 0.13,
    scene: {walkRange: [0.07, 0.94], spawn: {x: 0.4, facing: "right", cameraX: 0}},
    entities: [
      {id: "gate-preview", kind: "exit", label: "门道", x: 0.16, range: 0.085},
      {id: "gatekeeper-preview", kind: "npc", label: "守门人 · 占位", x: 0.62, range: 0.11},
      {id: "vessels-preview", kind: "task", label: "棚下陶器", x: 0.84, range: 0.07},
    ],
    art: {footLine: 0.88, playerWidth: 139, playerHeight: height * 0.48, npcWidth: 134, npcHeight: height * 0.46},
  };
  const locks = new window.HuaxiaInputLocks();
  const model = new window.HuaxiaSceneModel(data, locks);
  const keys = new Set(), held = new Set();
  let dialogueLock = null, ready = false, lastTime = null, frame = null;
  const view = new window.HuaxiaSceneView(id("art-canvas"), data, interact);
  const image = document.createElement("img"); image.alt = ""; image.draggable = false;
  image.src = "assets/preview/gate-road-concept-v01.png";
  view.world.querySelector(".scene-backdrop").append(image);
  const playerLabel = document.createElement("span");
  playerLabel.className = "actor-name";
  playerLabel.textContent = "学徒 · 占位";
  view.player.append(playerLabel);
  const hudLabel = document.querySelector(".preview-hud p");

  // Source bounds come from the C-003-V alpha measurement.
  const apprentice = {
    src: "assets/preview/apprentice-standing-right-v01.png",
    width: 1024, height: 1536, visibleHeight: 1453,
    footX: 512, footY: 1496,
  };
  const sprite = document.createElement("img");
  sprite.className = "apprentice-sprite";
  sprite.alt = "";
  sprite.draggable = false;
  sprite.hidden = true;
  const spriteScale = data.art.playerHeight / apprentice.visibleHeight;
  sprite.style.width = `${apprentice.width * spriteScale}px`;
  sprite.style.height = `${apprentice.height * spriteScale}px`;
  sprite.style.setProperty("--foot-x", `${apprentice.footX * spriteScale}px`);
  sprite.style.setProperty("--foot-y", `${apprentice.footY * spriteScale}px`);

  function keepPlaceholder() {
    hudLabel.textContent = "美术试放 / 学徒素材未载入";
    sprite.remove();
  }

  sprite.addEventListener("load", () => {
    if (sprite.naturalWidth !== apprentice.width || sprite.naturalHeight !== apprentice.height) {
      keepPlaceholder();
      return;
    }
    sprite.hidden = false;
    view.player.classList.add("sprite-ready");
    playerLabel.textContent = "学徒";
    hudLabel.textContent = "美术试放 / 学徒站姿候选";
  }, {once: true});
  sprite.addEventListener("error", keepPlaceholder, {once: true});
  view.player.prepend(sprite);
  sprite.src = apprentice.src;
  function clearInput() {keys.clear(); model.clearInput(); lastTime = null;}
  function fit() {
    const stage = id("art-stage");
    const bounds = stage.getBoundingClientRect();
    const scale = Math.min((bounds.width || window.innerWidth) / width, (bounds.height || window.innerHeight) / height);
    id("art-canvas").style.setProperty("--art-scale", String(scale));
  }
  function draw() {
    view.draw(model);
    const target = model.nearby();
    const text = target ? `E ${target.label}${model.targets().length > 1 ? " · Q切换" : ""}` : "靠近人物或陶器后，按 E 交互";
    if (id("preview-target").textContent !== text) id("preview-target").textContent = text;
  }
  function closeDialogue() {
    locks.release(dialogueLock); dialogueLock = null; clearInput();
    id("preview-dialogue").hidden = true; id("art-preview").classList.remove("dialogue-open");
    id("art-canvas").inert = false; fit(); draw(); if (ready) id("art-canvas").focus();
  }
  function interact(entityId) {
    if (!ready || locks.locked) return;
    const target = typeof entityId === "string" ? model.targets().find(entity => entity.id === entityId) : model.nearby();
    if (!target) return;
    clearInput(); dialogueLock = locks.acquire("art-dialogue");
    const content = {
      "gatekeeper-preview": ["守门人", "路从城门边经过。到棚下看看，回来时再聊。"],
      "vessels-preview": ["棚下陶器", "两只陶器静置在棚影里，前方的土路依旧畅通。"],
      "gate-preview": ["门道", "门道外的路，留待下次探看。"],
    }[target.id];
    id("preview-speaker").textContent = content[0]; id("preview-dialogue-text").textContent = content[1];
    id("preview-dialogue").hidden = false; id("art-preview").classList.add("dialogue-open");
    id("art-canvas").inert = true; fit(); draw(); id("preview-close").focus();
  }
  id("preview-close").addEventListener("click", closeDialogue);
  image.addEventListener("load", () => {ready = true; id("preview-status").hidden = true; fit(); draw(); id("art-canvas").focus();}, {once: true});
  image.addEventListener("error", () => {ready = false; clearInput(); id("preview-status").hidden = false; id("preview-status").textContent = "背景暂时无法载入，请重新打开试放。";}, {once: true});
  window.addEventListener("keydown", event => {
    if (event.ctrlKey || event.metaKey || event.altKey || !ready) return;
    const key = event.key.toLowerCase();
    if (event.target.closest?.("input,textarea,select,[contenteditable='true']")) return;
    if (dialogueLock) {
      if (key === "tab") {event.preventDefault(); id("preview-close").focus(); return;}
      if (["escape", "enter", " "].includes(key)) {
        event.preventDefault(); if (!event.repeat && !held.has(key)) {held.add(key); closeDialogue();}
      } else if (key.startsWith("arrow") || ["a", "d", "e"].includes(key)) event.preventDefault();
      return;
    }
    if (["a", "d", "arrowleft", "arrowright", "arrowup", "arrowdown", " ", "e", "q", "escape"].includes(key)) event.preventDefault();
    if (["e", "q", "escape"].includes(key)) {
      if (event.repeat || held.has(key)) return;
      held.add(key); if (key === "e") interact(); else if (key === "q") {model.cycleTarget(); draw();} else clearInput();
      return;
    }
    if (["a", "d", "arrowleft", "arrowright"].includes(key)) {
      keys.add(key); model.direction = Number(keys.has("d") || keys.has("arrowright")) - Number(keys.has("a") || keys.has("arrowleft"));
    }
  });
  window.addEventListener("keyup", event => {
    const key = event.key.toLowerCase(); keys.delete(key); held.delete(key);
    model.direction = locks.locked ? 0 : Number(keys.has("d") || keys.has("arrowright")) - Number(keys.has("a") || keys.has("arrowleft"));
  });
  function suspend() {clearInput(); held.clear();}
  window.addEventListener("blur", suspend);
  document.addEventListener("visibilitychange", () => {suspend();});
  window.addEventListener("resize", fit);
  if (window.ResizeObserver) {const observer = new ResizeObserver(fit); observer.observe(id("art-stage"));}
  function animate(time) {
    if (ready && !document.hidden) {model.step(lastTime === null ? 0 : Math.max(0, (time - lastTime) / 1000)); draw();}
    lastTime = time; frame = requestAnimationFrame(animate);
  }
  window.addEventListener("pagehide", () => {suspend(); cancelAnimationFrame(frame); frame = null;});
  window.addEventListener("pageshow", () => {suspend(); fit(); if (frame === null) frame = requestAnimationFrame(animate);});
  fit(); draw(); frame = requestAnimationFrame(animate);
})();

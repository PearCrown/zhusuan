"use strict";
(() => {
  // Replace this renderer/CSS when artwork changes; keep model and API adapters.
  class SceneView {
    constructor(root, data, onInteract = () => {}) {
      this.root = root; this.data = data;
      this.world = document.createElement("div"); this.world.className = "scene-world";
      this.world.style.width = `${100 / data.viewportSpan}%`;
      this.world.style.setProperty("--foot-line", `${data.art.footLine * 100}%`);
      const backdrop = document.createElement("div"); backdrop.className = "scene-backdrop"; backdrop.setAttribute("aria-hidden", "true");
      // 有背景图就用图；没有时退回 CSS 画的渐变，测试和旧数据都不受影响。
      if (data.art.backdrop) {backdrop.style.backgroundImage = `url("${data.art.backdrop}")`; backdrop.classList.add("has-art");}
      this.world.append(backdrop);
      this.entities = new Map();
      for (const entity of data.entities) {
        const el = document.createElement("button"); el.type = "button"; el.tabIndex = -1; el.className = `scene-entity scene-${entity.kind}`;
        el.setAttribute("aria-label", entity.label); el.addEventListener("click", () => onInteract(entity.id));
        el.style.left = `${entity.x * 100}%`; el.dataset.entityId = entity.id;
        const shape = document.createElement("span"); shape.className = "entity-shape"; shape.setAttribute("aria-hidden", "true");
        // 立绘：NPC 用各自的人物图；没有图但有印章字时，照剧情页的做法用印章兜底。
        if (entity.art) {shape.style.backgroundImage = `url("${entity.art}")`; shape.classList.add("has-art");}
        else if (entity.seal) {shape.textContent = entity.seal; shape.classList.add("has-seal");}
        const label = document.createElement("span"); label.className = "entity-label"; label.textContent = entity.label;
        el.append(shape, label); this.world.append(el); this.entities.set(entity.id, el);
      }
      this.player = document.createElement("div"); this.player.className = "scene-player";
      this.player.setAttribute("aria-label", data.art.playerLabel || "学徒"); this.player.style.width = `${data.art.playerWidth}px`;
      this.player.style.height = `${data.art.playerHeight}px`;
      if (data.art.playerArt) {this.player.style.backgroundImage = `url("${data.art.playerArt}")`; this.player.classList.add("has-art");}
      this.world.style.setProperty("--npc-width", `${data.art.npcWidth}px`);
      this.world.style.setProperty("--npc-height", `${data.art.npcHeight}px`);
      this.world.append(this.player); root.replaceChildren(this.world);
    }
    draw(model) {
      this.world.style.width = `${100 / model.viewportSpan}%`;
      this.world.style.transform = `translateX(${-model.cameraX * 100}%)`;
      this.player.style.left = `${model.x * 100}%`; this.player.dataset.facing = model.facing;
      this.player.classList.toggle("walking", model.direction !== 0 && !model.locks.locked);
      const nearby = model.nearby();
      const available = new Set(model.locks.locked ? [] : model.targets().map(e => e.id));
      for (const [id, el] of this.entities) {
        el.classList.toggle("in-range", available.has(id)); el.classList.toggle("selected-target", id === nearby?.id);
        el.setAttribute("aria-disabled", String(!available.has(id)));
      }
    }
    dispose() {this.root.replaceChildren(); this.entities.clear();}
  }
  window.HuaxiaSceneView = SceneView;
})();

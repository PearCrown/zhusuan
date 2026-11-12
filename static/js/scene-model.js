"use strict";
(() => {
  // Model has no DOM, image dimensions, pixel coordinates or permanent completion flags.
  class SceneModel {
    constructor(data, locks) {
      const finite = Number.isFinite;
      if (!data || !Array.isArray(data.scene?.walkRange) || data.scene.walkRange.length !== 2 ||
          !data.scene.walkRange.every(finite) || data.scene.walkRange[0] < 0 || data.scene.walkRange[1] > 1 ||
          data.scene.walkRange[0] >= data.scene.walkRange[1] || !finite(data.speed) || data.speed <= 0 ||
          !data.scene.spawn || !finite(data.scene.spawn.x) || data.scene.spawn.x < data.scene.walkRange[0] || data.scene.spawn.x > data.scene.walkRange[1] ||
          !finite(data.scene.spawn.cameraX) || data.scene.spawn.cameraX < 0 || data.scene.spawn.cameraX > 1 || !["left", "right"].includes(data.scene.spawn.facing) ||
          !finite(data.viewportSpan) || data.viewportSpan <= 0 || data.viewportSpan > 1 || !Array.isArray(data.entities) ||
          data.entities.some(e => !e || typeof e.id !== "string" || !e.id || !["npc", "task", "exit"].includes(e.kind) ||
            !finite(e.x) || e.x < data.scene.walkRange[0] || e.x > data.scene.walkRange[1] || !finite(e.range) || e.range <= 0 || e.range > 1) ||
          new Set(data.entities.map(e => e.id)).size !== data.entities.length || !locks || typeof locks.locked !== "boolean") throw Error("INVALID_SCENE");
      this.data = data; this.locks = locks; this.direction = 0;
      this.viewportSpan = data.viewportSpan;
      this.restore(data.scene.spawn);
    }
    clearInput() { this.direction = 0; }
    move(direction, seconds) {
      if (![-1, 0, 1].includes(direction) || !Number.isFinite(seconds) || seconds < 0) throw Error("INVALID_MOVEMENT");
      if (this.locks.locked) {this.clearInput(); return;}
      if (!direction) return;
      const [min, max] = this.data.scene.walkRange;
      this.x = Math.min(max, Math.max(min, this.x + direction * Math.min(seconds, 0.1) * this.data.speed));
      this.facing = direction < 0 ? "left" : "right";
      this.centerCamera();
    }
    centerCamera() { this.cameraX = Math.max(0, Math.min(1 - this.viewportSpan, this.x - this.viewportSpan / 2)); }
    setViewportSpan(span) {
      if (span === this.viewportSpan) return;
      this.viewportSpan = span;
      this.centerCamera();
    }
    step(seconds) { this.move(this.direction, seconds); }
    targets() { return this.data.entities.filter(e => Math.abs(e.x - this.x) <= e.range).sort((a, b) => Math.abs(a.x - this.x) - Math.abs(b.x - this.x) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)); }
    nearby() {const targets = this.targets(); return targets.find(e => e.id === this.targetId) || targets[0] || null;}
    cycleTarget() {const targets = this.targets(); if (targets.length) this.targetId = targets[(targets.findIndex(e => e.id === this.nearby()?.id) + 1) % targets.length].id;}
    capture() {return {x: this.x, facing: this.facing, cameraX: this.cameraX};}
    restore(snapshot) {
      const [min, max] = this.data.scene.walkRange;
      if (!snapshot || !Number.isFinite(snapshot.x) || !Number.isFinite(snapshot.cameraX) || !["left", "right"].includes(snapshot.facing)) throw Error("INVALID_POSITION");
      const saved = snapshot.x >= min && snapshot.x <= max ? snapshot : this.data.scene.spawn;
      this.x = saved.x; this.facing = saved.facing;
      this.cameraX = Math.max(0, Math.min(1 - this.viewportSpan, saved.cameraX));
      this.clearInput();
    }
  }
  window.HuaxiaSceneModel = SceneModel;
})();

/* SceneHost v1: transient presentation only; never writes scores or progress. */
"use strict";
(() => {
  const failure = code => Object.assign(new Error(code), { code });
  const text = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const position = value => value && finite(value.x) && finite(value.cameraX) && ["left", "right"].includes(value.facing);

  class InputLocks {
    #tokens = new Set();
    acquire(owner) {
      if (!text(owner)) throw failure("INVALID_LOCK_OWNER");
      const token = Object.freeze({ owner });
      this.#tokens.add(token);
      return token;
    }
    release(token) { return this.#tokens.delete(token); }
    get locked() { return this.#tokens.size > 0; }
    get size() { return this.#tokens.size; }
  }

  class SceneHost {
    constructor({ context, scene, locks, readProgress, restoreScene, clearInput, callbacks = {}, timeoutMs = 12000 }) {
      if (!context || ![context.chapterId, context.levelSessionId, context.sceneId, context.sessionEpoch].every(text) ||
          !scene || !Array.isArray(scene.walkRange) || scene.walkRange.length !== 2 ||
          !scene.walkRange.every(finite) || scene.walkRange[0] < 0 || scene.walkRange[1] > 1 || scene.walkRange[0] >= scene.walkRange[1] ||
          !position(scene.spawn) || scene.spawn.x < scene.walkRange[0] || scene.spawn.x > scene.walkRange[1] || scene.spawn.cameraX < 0 || scene.spawn.cameraX > 1 ||
          !(locks instanceof InputLocks) || ![readProgress, restoreScene, clearInput].every(fn => typeof fn === "function") ||
          !Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000 || !callbacks ||
          Object.values(callbacks).some(fn => typeof fn !== "function")) throw failure("INVALID_HOST_CONFIG");
      this.context = Object.freeze(Object.fromEntries(["chapterId", "levelSessionId", "sceneId", "sessionEpoch"].map(key => [key, context[key]])));
      this.scene = Object.freeze({ walkRange: Object.freeze([...scene.walkRange]), spawn: Object.freeze({ ...scene.spawn }) });
      this.locks = locks;
      this.readProgress = readProgress;
      this.restoreScene = restoreScene;
      this.clearInput = clearInput;
      this.callbacks = { ...callbacks };
      this.timeoutMs = timeoutMs;
      this.generation = 0;
      this.active = null;
      this.disposed = false;
      this.onHide = () => this.invalidate();
      this.onVisibility = () => { if (document.hidden) this.invalidate(); };
      window.addEventListener("pagehide", this.onHide);
      document.addEventListener("visibilitychange", this.onVisibility);
    }

    beginTask({ instanceId, runner, host, config, draft, snapshot }) {
      if (this.disposed) throw failure("HOST_DISPOSED");
      if (!text(instanceId) || !runner || typeof runner.mount !== "function" || !host || host.nodeType !== 1 || !position(snapshot)) throw failure("INVALID_TASK");
      if (this.active) {
        if (this.active.instanceId === instanceId && !this.active.returning && this.active.controller) return this.active.token;
        throw failure("HOST_BUSY");
      }
      this.clearInput();
      const active = {
        instanceId, generation: ++this.generation, abort: new AbortController(), runnerAbort: new AbortController(), closed: false,
        token: Object.freeze({}), snapshot: Object.freeze({ x: snapshot.x, facing: snapshot.facing, cameraX: snapshot.cameraX }),
        lock: this.locks.acquire("task"), controller: null, returning: null, restored: null,
      };
      this.active = active;
      const callbacks = {};
      for (const name of ["draftChanged", "operationCompleted", "submitRequested", "exitRequested", "fatalError"]) {
        callbacks[name] = value => {
          if (this.active !== active || active.abort.signal.aborted || active.returning || active.closed || !active.lock) return;
          this.callbacks[name]?.({ instanceId, generation: active.generation, value });
        };
      }
      try {
        const controller = runner.mount(host, { instanceId, config, draft, signal: active.runnerAbort.signal }, callbacks);
        if (controller && typeof controller.then === "function") {
          // v1 mount is synchronous. Still consume and clean up an invalid async mount.
          Promise.resolve(controller).then(late => { if (typeof late?.dispose === "function") late.dispose(); }).catch(() => {});
          throw failure("INVALID_RUNNER");
        }
        if (!controller || !["exportDraft", "pause", "dispose"].every(name => typeof controller[name] === "function")) {
          controller?.dispose?.();
          throw failure("INVALID_RUNNER");
        }
        // A synchronous mount callback may have invalidated this host.
        if (this.active !== active || active.abort.signal.aborted) {
          controller.dispose();
          throw failure("RETURN_CONTEXT_EXPIRED");
        }
        active.controller = controller;
        return active.token;
      } catch (error) {
        if (this.active === active) this.invalidate();
        throw error;
      }
    }

    exportDraft(token) {
      const active = this.check(token);
      if (active.returning || !active.controller) throw failure("RUNNER_CLOSED");
      return active.controller.exportDraft();
    }

    check(token) {
      if (this.disposed || !this.active || this.active.token !== token) throw failure("RETURN_CONTEXT_EXPIRED");
      return this.active;
    }

    returnToScene(token) {
      const active = this.check(token);
      if (active.restored) return Promise.resolve(active.restored);
      if (active.returning) return active.returning;
      // Defer hooks until returning is assigned, preventing reentrant duplicate returns.
      active.returning = Promise.resolve().then(() => this.restore(active));
      return active.returning;
    }

    async restore(active) {
      const attempt = new AbortController();
      const cancel = () => attempt.abort(failure("RETURN_CONTEXT_EXPIRED"));
      active.abort.signal.addEventListener("abort", cancel, { once: true });
      if (active.abort.signal.aborted) cancel();
      const timer = setTimeout(() => attempt.abort(failure("RETURN_TIMEOUT")), this.timeoutMs);
      const current = () => {
        if (attempt.signal.aborted) throw attempt.signal.reason;
        if (this.active !== active) throw failure("RETURN_CONTEXT_EXPIRED");
      };
      const aborted = new Promise((_, reject) => {
        if (attempt.signal.aborted) reject(attempt.signal.reason);
        else attempt.signal.addEventListener("abort", () => reject(attempt.signal.reason), { once: true });
      });
      // Cleanup hooks can throw before the first race has subscribed.
      aborted.catch(() => {});
      // Race each hook so even a non-cooperating provider cannot hold the host forever.
      const invoke = fn => Promise.race([Promise.resolve().then(() => { current(); return fn(); }), aborted]);
      try {
        current();
        this.clearInput();
        active.closed = true;
        active.runnerAbort.abort();
        const controller = active.controller;
        active.controller = null;
        if (controller) {
          try { controller.pause(); } finally { controller.dispose(); }
        }
        const progress = await invoke(() => this.readProgress({ context: this.context, signal: attempt.signal }));
        current();
        if (!progress || progress.chapterId !== this.context.chapterId || !Number.isSafeInteger(progress.revision) || progress.revision < 0) throw failure("INVALID_PROGRESS");
        const saved = active.snapshot;
        const valid = saved.x >= this.scene.walkRange[0] && saved.x <= this.scene.walkRange[1] && saved.cameraX >= 0 && saved.cameraX <= 1;
        const snapshot = Object.freeze({ ...(valid ? saved : this.scene.spawn) });
        await invoke(() => this.restoreScene({ context: this.context, snapshot, progress, signal: attempt.signal }));
        current();
        this.clearInput();
        this.locks.release(active.lock);
        active.lock = null;
        active.restored = Object.freeze({ restored: true, revision: progress.revision, snapshot });
        return active.restored;
      } finally {
        clearTimeout(timer);
        active.abort.signal.removeEventListener("abort", cancel);
        attempt.abort();
        active.returning = null;
      }
    }

    // Call after handling a successful return, before starting another instance.
    finishReturn(token) {
      const active = this.check(token);
      if (!active.restored) throw failure("RETURN_NOT_RESTORED");
      this.invalidate();
    }

    invalidate() {
      const active = this.active;
      this.active = null;
      this.generation++;
      if (!active) return;
      active.abort.abort();
      active.closed = true;
      active.runnerAbort.abort();
      this.locks.release(active.lock);
      try { active.controller?.dispose(); } finally { this.clearInput(); }
    }

    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      window.removeEventListener("pagehide", this.onHide);
      document.removeEventListener("visibilitychange", this.onVisibility);
      this.invalidate();
    }
  }

  window.HuaxiaInputLocks = InputLocks;
  window.HuaxiaSceneHost = SceneHost;
})();

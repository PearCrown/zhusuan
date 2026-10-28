/* Integration SDK. All scores/identity/save versions come from the server. */
"use strict";
(() => {
  class ChapterClient {
    constructor(chapterId, callbacks = {}) {
      this.chapterId = chapterId;
      this.callbacks = callbacks;
      this.progress = null;
      this.saveContext = null;
      this.busy = false;
      this.epoch = 0;
    }
    invalidate() { this.epoch++; this.progress = null; this.saveContext = null; }
    async request(path, payload, csrf) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12000);
      try {
        const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal };
        if (payload) Object.assign(options, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(payload) });
        const response = await fetch(path, options);
        const body = await response.json();
        if (!response.ok || body.ok !== true) throw Object.assign(new Error(body.error?.message || "服务不可用"), { code: body.error?.code });
        return body.data;
      } finally { clearTimeout(timeout); }
    }
    accept(data) {
      this.progress = data.progress;
      this.saveContext = data.saveContext;
      this.callbacks.onProgress?.(data.progress);
      if (data.progress.result) this.callbacks.onScore?.(data.progress.result);
      return data;
    }
    async load() {
      if (this.busy) throw new Error("操作尚未结束");
      this.busy = true;
      const started = this.epoch;
      try {
        const data = await this.request(`/game/api/chapters/${encodeURIComponent(this.chapterId)}/progress`);
        if (started !== this.epoch) throw Object.assign(new Error("页面状态已变化"), { stale: true });
        return this.accept(data);
      } finally { this.busy = false; }
    }
    async dispatch(action, fields = {}) {
      if (this.busy || !this.progress || !this.saveContext) throw new Error("请先载入章节并等待当前操作完成");
      this.busy = true;
      const started = this.epoch;
      const payload = { ...fields, action, revision: this.progress.revision, saveContext: this.saveContext };
      try {
        const csrf = await this.request("/auth/csrf");
        if (started !== this.epoch) throw Object.assign(new Error("页面状态已变化"), { stale: true });
        const data = await this.request(`/game/api/chapters/${encodeURIComponent(this.chapterId)}/action`, payload, csrf.csrfToken);
        if (started !== this.epoch) throw Object.assign(new Error("页面状态已变化"), { stale: true });
        return this.accept(data);
      } finally { this.busy = false; }
    }
  }
  window.HuaxiaChapterClient = ChapterClient;
})();

/* Standalone SceneHost adapter. All state in this page is a preview fixture. */
"use strict";
(() => {
  const intro = document.querySelector("[data-intro]");
  const status = document.querySelector("[data-intro-status]");
  const start = document.querySelector("[data-start]");
  const reset = document.querySelector("[data-reset]");
  const hostElement = document.querySelector("[data-runner-host]");
  const runner = window.HuaxiaNandPreviewRunner;
  const spawn = { x: 0.5, facing: "right", cameraX: 0 };
  let draft = null;
  let token = null;
  let instanceId = null;
  let serial = 0;
  let returning = false;

  function showStart(message, focus = true) {
    token = null;
    instanceId = null;
    returning = false;
    hostElement.hidden = true;
    intro.hidden = false;
    start.textContent = draft ? "继续接线" : "开始接线";
    reset.hidden = !draft;
    status.textContent = message;
    if (focus) start.focus();
  }

  const host = new window.HuaxiaSceneHost({
    context: { chapterId: "nand-preview", levelSessionId: "local-fixture", sceneId: "workbench", sessionEpoch: "preview-only" },
    scene: { walkRange: [0, 1], spawn },
    locks: new window.HuaxiaInputLocks(),
    clearInput() {}, // No moving scene in this sample.
    async readProgress({ signal }) {
      signal.throwIfAborted();
      return { chapterId: "nand-preview", revision: 0 }; // Required fixture metadata, never a progress read.
    },
    async restoreScene({ signal }) { signal.throwIfAborted(); },
    callbacks: {
      draftChanged(report) { if (report.instanceId === instanceId) draft = report.value; },
      exitRequested(report) {
        if (report.instanceId !== instanceId || !token || returning) return;
        const current = token;
        draft = host.exportDraft(current);
        returning = true;
        host.returnToScene(current).then(() => {
          if (token !== current) return;
          host.finishReturn(current);
          showStart("草稿保留在本页。可继续接线，或从空白开始。");
        }).catch(() => {
          if (token !== current) return;
          host.invalidate();
          showStart("练习已关闭。本页草稿仍可恢复。");
        });
      },
    },
  });

  function begin(useDraft) {
    if (token) return;
    if (!useDraft) draft = null;
    intro.hidden = true;
    hostElement.hidden = false;
    instanceId = "nand-preview-fixture-" + (++serial);
    try {
      token = host.beginTask({ instanceId, runner, host: hostElement, config: runner.config, draft, snapshot: spawn });
    } catch {
      showStart("无法打开练习。可选择从空白开始。");
    }
  }

  start.addEventListener("click", () => begin(true));
  reset.addEventListener("click", () => begin(false));
  // The host already invalidates its runner on hide. Keep only this page's last JSON draft.
  const hide = () => {
    if (instanceId) showStart("练习已暂停。可继续本页草稿。", false);
  };
  window.addEventListener("pagehide", hide);
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); });
})();

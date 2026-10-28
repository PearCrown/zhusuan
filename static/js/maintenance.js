"use strict";
(() => {
  let cleared = false;
  function hide() {
    document.querySelector("main").replaceChildren();
    cleared = true;
  }
  function restore(event) {
    if (!document.hidden && (cleared || event?.persisted)) window.location.reload();
  }
  window.addEventListener("pagehide", hide);
  window.addEventListener("pageshow", restore);
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); else restore(); });
})();

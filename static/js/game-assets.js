"use strict";
(() => {
  // Central, replaceable presentation resources; no account or save logic belongs here.
  const loginBackground = Object.freeze({
    src: document.body.dataset.loginBackground || null, position: "left center",
    fallback: "linear-gradient(125deg, #ead9b3, #eed9ad 55%, #cfa46c)",
  });
  function applyLoginBackground(resource = loginBackground) {
    const value = resource.src ? `url("${encodeURI(resource.src).replace(/"/g, '%22')}")` : resource.fallback;
    document.documentElement.style.setProperty("--login-background", value);
    document.documentElement.style.setProperty("--login-background-position", resource.position || "center");
  }
  window.HuaxiaGameAssets = Object.freeze({loginBackground, applyLoginBackground});
  applyLoginBackground();
})();

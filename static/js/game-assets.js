"use strict";
(() => {
  // Central, replaceable presentation resources; no account or save logic belongs here.
  const loginBackground = Object.freeze({
    src: null, position: "center",
    fallback: "linear-gradient(125deg, #203d38, #41574a 55%, #233b35)",
  });
  function applyLoginBackground(resource = loginBackground) {
    const value = resource.src ? `url("${encodeURI(resource.src).replace(/"/g, '%22')}")` : resource.fallback;
    document.documentElement.style.setProperty("--login-background", value);
    document.documentElement.style.setProperty("--login-background-position", resource.position || "center");
  }
  window.HuaxiaGameAssets = Object.freeze({loginBackground, applyLoginBackground});
  applyLoginBackground();
})();

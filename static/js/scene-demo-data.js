"use strict";
// Stable content/interaction data. Presentation values never enter server saves.
const sampleGateLevel = Object.freeze({
  levelId: "sample-gate", sceneId: "sample-gate-road", levelTitle: "城门旁的委托", placeId: "bo",
});
// Map metadata only. B can reference these IDs when supplying chapter content.
const contentSlots = [
  {levelId: "hewan-village", placeId: "zhenxun"},
  {levelId: "linshui-workshop", placeId: "yangcheng"},
  {levelId: "dongyuan-earthworks", placeId: "mengze"},
].map(level => Object.freeze({...level, kind: "content-slot"}));
window.HuaxiaSceneDemo = Object.freeze({
  chapterId: "sample-counting", ...sampleGateLevel,
  title: "算坊初试",
  mapLevels: Object.freeze([sampleGateLevel, ...contentSlots]),
  scene: Object.freeze({walkRange: Object.freeze([0.06, 0.95]), spawn: Object.freeze({x: 0.12, facing: "right", cameraX: 0})}),
  speed: 0.18, viewportSpan: 0.58,
  entities: Object.freeze([
    Object.freeze({id: "gatekeeper", kind: "npc", label: "守门人", x: 0.25, range: 0.07}),
    Object.freeze({id: "workshop", kind: "task", label: "算坊任务点", x: 0.64, range: 0.07}),
    Object.freeze({id: "east-exit", kind: "exit", label: "东侧出口", x: 0.9, range: 0.05}),
  ]),
  art: Object.freeze({footLine: 0.88, playerWidth: 40, playerHeight: 86, npcWidth: 44, npcHeight: 90}),
});

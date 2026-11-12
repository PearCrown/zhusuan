"use strict";
// Stable content/interaction data. Presentation values never enter server saves.
//
const sampleGateLevel = Object.freeze({
  levelId: "tc-nand", sceneId: "xiacourt-camp", levelTitle: "亳城营前", placeId: "bo",
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
  scene: Object.freeze({walkRange: Object.freeze([0.06, 0.95]), spawn: Object.freeze({x: 0.13, facing: "right", cameraX: 0})}),
  speed: 0.12, viewportSpan: 0.56,
  entities: Object.freeze([
    Object.freeze({id: "gate.keeper", kind: "npc", label: "守门人", x: 0.23, range: 0.073,
      art: "/static/img/camp/gatekeeper.png", lines: Object.freeze([
        "慢些走。河边起了雾，过了这道门，沿着有灯的路往前。",
        "看见那顶赭色帐子了吗？妇好在那儿。她从河边回来，还没歇脚。",
      ])}),
    Object.freeze({id: "fu-hao", kind: "npc", label: "妇好", x: 0.78, range: 0.08,
      art: "/static/img/camp/fu-hao.png", lines: Object.freeze([
        "你也听见河声了？我小时候夜里睡不着，便数它打在岸上的次数。",
        "后来才知道，河水每回都打在不一样的地方。倒是铜炉里的火，守得住，便有准头。",
        "天要黑了。再站一会儿吧，营里很少有这样安静的时候。",
      ])}),
  ]),
  art: Object.freeze({
    backdrop: "/static/img/camp/bo-camp.png", aspectRatio: 3,
    footLine: 0.84, playerWidth: 138, playerHeight: 205, npcWidth: 151, npcHeight: 226,
    playerArt: "/static/img/camp/apprentice.png",
    playerLabel: "学徒",
  }),
});

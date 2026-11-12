/* 课程结构：把地图上的地名对应到"第几章、第几节、学什么"。
 *
 * 为什么单独一份数据：地图上的"中原""亳"是地理名称，学生看不出教学含义。
 * 这里按课程大纲把区域映射成章、把地点映射成节，并写清知识点与本节目标；
 * 界面只在左侧展示，判分与存档完全不依赖它。
 *
 * 章节名称取自课程大纲（第一章：从逻辑门到存算器件）。
 */
"use strict";
(() => {
  const CHAPTERS = {
    "central-plains": {
      no: "第一章",
      title: "从逻辑门到存算器件",
      summary: "从一枚与非门开始，认识真值表、逻辑门组合，直到最简单的存储单元。",
      places: {
        bo: {
          no: "第一节",
          title: "亳 · 与非门初识",
          knowledge: ["逻辑门", "与非门 NAND", "真值表"],
          goal: "用一个与非门接出四行真值表，并说出输出为 0 的唯一一种输入。",
        },
      },
    },
    guanzhong: {
      no: "第二章",
      title: "从存算器件到简单 CPU（预告）",
      summary: "本章尚未开放，先把第一章的逻辑门练熟。",
    },
    jinnan: {
      no: "第三章",
      title: "指令集与汇编（预告）",
      summary: "本章尚未开放。",
    },
    eastlands: {
      no: "第四章",
      title: "GPU 与 AI 基础（预告）",
      summary: "本章尚未开放。",
    },
  };

  function chapterOf(regionId) {
    return CHAPTERS[regionId] || null;
  }

  function placeOf(regionId, placeId) {
    const chapter = chapterOf(regionId);
    return (chapter && chapter.places && chapter.places[placeId]) || null;
  }

  const ORDER = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10};

  /** 章节排序键：把"第一章"换算成 1，保证一→四按顺序排。 */
  function chapterOrder(regionId) {
    const chapter = chapterOf(regionId);
    const match = chapter && /^第([一二三四五六七八九十])章$/.exec(chapter.no);
    return match ? ORDER[match[1]] : 99;
  }

  window.HuaxiaCurriculum = {chapterOf, placeOf, chapterOrder, chapters: CHAPTERS};
})();

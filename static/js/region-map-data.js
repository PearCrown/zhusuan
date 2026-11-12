"use strict";
// Coordinates use the background figure's plot (x 0–1540, y 90–990).
window.HuaxiaMapRegions = [
  {
    id: "guanzhong", title: "关中", center: [443, 811], crop: [235, 660, 430, 315],
    places: [
      ["longdong", "陇东", 347, 771, "ridge"], ["qizhou", "岐周", 435, 885, "city"],
      ["fenghao", "丰镐", 534, 895, "city"], ["huyi", "鄠邑", 504, 922, "village"],
    ],
    events: [4, 10, 14, 15, 16, 17],
  },
  {
    id: "jinnan", title: "晋地", center: [787, 590], crop: [590, 392, 370, 496],
    places: [
      ["taiyuan", "太原", 886, 442, "city"], ["zhi", "彘", 808, 607, "village"],
      ["taosi", "陶寺", 778, 695, "terrace"], ["jin", "晋", 808, 721, "city"],
      ["anyi", "安邑", 759, 797, "city"], ["mingtiao", "鸣条", 742, 805, "ridge"],
      ["guirui", "妫汭", 682, 819, "village"],
    ],
    events: [1, 2, 5, 7],
  },
  {
    id: "central-plains", title: "中原", center: [1004, 864], crop: [810, 712, 464, 276],
    places: [
      ["bo", "亳", 993, 846, "city"], ["chengzhou", "成周", 877, 861, "city"],
      ["zhenxun", "斟鄩", 918, 849, "city"], ["yangcheng", "阳城", 934, 876, "terrace"],
      ["yangdi", "阳翟", 984, 910, "village"], ["mengze", "蒙泽", 1188, 857, "village"],
      ["jingbo", "景亳", 1200, 885, "city"],
    ],
    events: [3, 6, 8, 13, 18],
  },
  {
    id: "eastlands", title: "东方", center: [1235, 651], crop: [968, 480, 568, 345],
    places: [
      ["xing", "邢", 1082, 544, "city"], ["qi", "齐", 1454, 581, "city"],
      ["yin", "殷", 1073, 667, "city"], ["xiang", "相", 1121, 695, "village"],
      ["chaoge", "朝歌", 1054, 730, "terrace"], ["muye", "牧野", 1041, 757, "ridge"],
      ["yan", "奄", 1327, 733, "city"],
    ],
    events: [9, 11, 12],
  },
];
window.HuaxiaMapEvents = [
  [775, 703], [683, 817], [934, 876], [504, 922], [763, 790], [918, 850],
  [741, 806], [1188, 855], [1074, 666], [347, 771], [1041, 757], [1054, 729],
  [877, 861], [535, 895], [415, 870], [475, 818], [524, 913], [893, 867],
];

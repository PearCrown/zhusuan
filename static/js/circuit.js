/**
 * 铸算·华夏纪 —— 电路工坊
 * 参考 Turing Complete 玩法的电路搭建游戏
 */
"use strict";

(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const CANVAS_W = 800;
  const CANVAS_H = 560;
  const GATE_W = 80;
  const GATE_H = 50;
  const PORT_R = 7;

  // 门的 SVG 符号（简易逻辑门形状）
  const GATE_SHAPES = {
    NAND:  { label: "NAND", symbol: "NAND", color: "#a65437", inputs: 2 },
    AND:   { label: "AND",  symbol: "AND",  color: "#285548", inputs: 2 },
    OR:    { label: "OR",   symbol: "OR",   color: "#80613d", inputs: 2 },
    NOT:   { label: "NOT",  symbol: "NOT",  color: "#5a4a7c", inputs: 1 },
    XOR:   { label: "XOR",  symbol: "XOR",  color: "#3a6b8a", inputs: 2 },
    NOR:   { label: "NOR",  symbol: "NOR",  color: "#6b4a3a", inputs: 2 },
  };

  // 游戏状态
  const state = {
    puzzles: [],        // 谜题列表，只有 id/title/description
    puzzle: null,       // 当前谜题的完整定义（含 truthTable、components、inputs、outputs）
    currentPuzzleId: null,
    gates: [],          // [{id, type, x, y}]
    wires: [],          // [{fromGateId, fromPort, toGateId, toGatePort}]
    nextGateId: 1,
    nextWireId: 1,
    connecting: null,   // {gateId, port} 正在连线的起点
    simIndex: 0,        // 当前模拟的真值表行索引
    simValues: {},      // 模拟结果缓存 gateId -> 输出值
  };

  const $ = id => document.getElementById(id);
  const svg = $("circuit-canvas");
  const wiresLayer = $("wires-layer");
  const gatesLayer = $("gates-layer");
  const portsLayer = $("ports-layer");
  const tempWireLayer = $("temp-wire-layer");

  // 章节客户端：判分、存档、成绩回传都走既有的章节接口，
  // 不另开一条只会返回结果、不入库的旁路。
  const CHAPTER_ID = "xia-circuit";
  let chapter = null;

  // 剧情来自 /game/api/circuit/story（数据在 gameplay/data/circuit_story.json），
  // 前端只负责渲染，不写死任何台词。
  let story = null;
  let catalog = null;      // 关卡结构：主线/支线/前置/区域（数据在 level_meta.json）
  let npcSpeaker = null;
  let npcQueue = [];
  // 任务栏（static/js/quest.js）。与下面 refreshQuest 的「委托」是两回事：
  // 委托来自 circuit_story.json，讲本关要做什么；任务栏讲整条任务走到哪一步、结算结果。
  let questBar = null;

  /** 把章节存档推给任务栏。组件自己只管渲染，不认识电路页面。 */
  function showQuest() {
    if (!window.HuaxiaQuestBar || !chapter || !chapter.progress) return;
    const slot = $("quest-slot");
    if (!slot) return;
    if (!questBar) questBar = window.HuaxiaQuestBar.mountQuestBar(slot, CHAPTER_ID);
    if (questBar) questBar.render(chapter.progress);
  }

  /** 结算期间把状态胶囊切到「核验中」；结果由随后的进度自行落到已通过/未通过。 */
  function questPending(pending) {
    if (questBar) questBar.setPending(pending);
  }

  // ---------- 初始化 ----------
  async function init() {
    try {
      const res = await fetch("/game/api/circuit/puzzles");
      const body = await res.json();
      if (!res.ok || body.ok !== true) {
        throw new Error((body.error && body.error.message) || "关卡列表读取失败");
      }
      // 后端统一返回 {ok, data} 信封，这里必须先拆开。
      state.puzzles = (body.data && body.data.puzzles) || [];

      await loadStory();

      // 先取存档，这样第一关就能带着已有进度打开。
      chapter = new window.HuaxiaChapterClient(CHAPTER_ID, { onProgress: syncChapterUi, onScore: syncChapterUi });
      try {
        await chapter.load();
      } catch (error) {
        chapter = null;
        $("chapter-status").textContent = `存档读取失败：${error.message || "未知错误"}`;
      }

      // 关卡页（/game/level/<id>）会指定从哪一关进来；没有指定就照旧开第一关。
      // 指定了并且认识这一关时，只把这一关留在列表里：场景里只接了一个入口，
      // 下拉里还摆着其余四关，会让人以为这一章有五个入口。
      const wanted = document.body.dataset.initialPuzzle || "";
      const known = state.puzzles.some(item => item.id === wanted);
      if (known) state.puzzles = state.puzzles.filter(item => item.id === wanted);

      renderPuzzleSelect();
      if (state.puzzles.length) await loadPuzzle(known ? wanted : state.puzzles[0].id);
      bindEvents();
      syncChapterUi();
      render();
    } catch (e) {
      console.error("初始化失败:", e);
      alert("加载关卡失败，请登录后重试。");
    }
  }

  function renderPuzzleSelect() {
    const sel = $("puzzle-select");
    sel.innerHTML = state.puzzles.map(p =>
      `<option value="${p.id}">${p.title}</option>`
    ).join("");
    // 只有一关时选择器没有意义，标题已经写着是哪一关。
    sel.hidden = state.puzzles.length <= 1;
    sel.addEventListener("change", e => loadPuzzle(e.target.value));
  }

  async function loadPuzzle(puzzleId) {
    state.currentPuzzleId = puzzleId;
    state.gates = [];
    state.wires = [];
    state.simValues = {};
    state.simIndex = 0;
    state.connecting = null;

    const res = await fetch(`/game/api/circuit/puzzles/${puzzleId}`);
    const body = await res.json();
    if (!res.ok || body.ok !== true) {
      throw new Error((body.error && body.error.message) || "关卡读取失败");
    }
    const p = body.data && body.data.puzzle;
    if (!p) {
      throw new Error("关卡数据不完整");
    }
    // 列表接口只返回 id/title/description，完整定义要留在这里，
    // 否则模拟与真值表翻页会在 state.puzzles 里找不到 truthTable。
    state.puzzle = p;

    $("puzzle-title").textContent = p.title;
    $("puzzle-desc").textContent = p.description;

    renderPalette(p.components);
    renderTruthTable(p);
    renderSimPanel(p);
    $("result-panel").hidden = true;

    // 放置输入端点和输出端点
    placeIOGates(p);
    restoreSavedCircuit(p);
    render();
    refreshQuest(p);
    refreshNpc();
  }

  /** 还原本关已通关时存下的电路，让"云端存档"真的能接着做。 */
  function restoreSavedCircuit(p) {
    // 关卡 id 以 currentPuzzleId 为准：详情响应不保证自带 id，
    // 依赖 p.id 会在调用方拿到 undefined 时静默失效。
    const level = chapterLevels()[state.currentPuzzleId];
    if (!level || !level.passed || !Array.isArray(level.gates) || !level.gates.length) return;
    let highest = 0;
    level.gates.forEach(saved => {
      const match = /^g(\d+)$/.exec(saved.id);
      if (match) highest = Math.max(highest, Number(match[1]));
      state.gates.push({
        id: saved.id,
        type: saved.type,
        x: typeof saved.x === "number" ? saved.x : 240,
        y: typeof saved.y === "number" ? saved.y : 160,
        fixed: false,
      });
    });
    state.nextGateId = Math.max(state.nextGateId, highest + 1);
    (level.wires || []).forEach(wire => {
      state.wires.push({
        id: state.nextWireId++,
        fromGateId: wire.from.gateId,
        fromPort: wire.from.port,
        toGateId: wire.to.gateId,
        toGatePort: wire.to.port,
      });
    });
  }

  // 输入端点和输出端点作为固定在画布上的"虚拟门"
  function placeIOGates(p) {
    let y = 40;
    const GAP = 80;
    p.inputs.forEach((name, i) => {
      state.gates.push({
        id: `__in_${name}`,
        type: "INPUT",
        x: 30,
        y: y,
        name: name,
        fixed: true,
      });
      y += GAP;
    });
    y = 40;
    p.outputs.forEach((name, i) => {
      state.gates.push({
        id: `__out_${name}`,
        type: "OUTPUT",
        x: CANVAS_W - 110,
        y: y,
        name: name,
        fixed: true,
      });
      y += GAP;
    });
  }

  function renderPalette(components) {
    const palette = $("palette-gates");
    palette.innerHTML = components.map(type => {
      const g = GATE_SHAPES[type];
      return `<button class="palette-gate" data-type="${type}" style="border-color:var(--gate-accent,${g.color});color:var(--gate-accent,${g.color})">
        ${g.label}
      </button>`;
    }).join("");
    palette.querySelectorAll(".palette-gate").forEach(btn => {
      btn.addEventListener("click", () => addGate(btn.dataset.type));
    });
  }

  function renderTruthTable(p) {
    // $ 是 getElementById 的别名，id 里不能带空格；thead/tbody 必须从表格上查。
    const table = $("truth-table");
    if (!table) return;
    const thead = table.querySelector("thead");
    const tbody = table.querySelector("tbody");
    if (!thead || !tbody) return;
    const cols = [...p.inputs, ...p.outputs.map(name => `${name}（期望）`)];
    // 第一列是卦象：把这一行的输入与输出合起来画成阴阳爻。
    const yaoHeader = (table.getAttribute("data-yao-header") || "").trim();
    thead.innerHTML = `<tr>${yaoHeader ? `<th title="此行输入与输出合为一卦">${yaoHeader}</th>` : ""}${cols.map(c => `<th>${c}</th>`).join("")}</tr>`;
    tbody.innerHTML = p.truthTable.map((row, index) => {
      const yao = [...row.inputs, ...row.outputs].map(yaoCell).join("");
      return `<tr>
        ${yaoHeader ? `<td class="yao"><button type="button" class="sim-case-button" data-sim-case="${index}" aria-label="试演第 ${index + 1} 组">${yao}</button></td>` : ""}
        ${row.inputs.map(v => `<td class="in-val">${v}</td>`).join("")}
        ${row.outputs.map(v => `<td class="out-val expected">${v}</td>`).join("")}
      </tr>`;
    }).join("");
  }

  /** 阳爻一整横，阴爻断开——纯 CSS 画出，不依赖字体是否有卦象字符。 */
  function yaoCell(bit) {
    const one = bit === 1 || bit === true;
    return `<span class="yao yao-${one ? 1 : 0}"><span class="yao-bar${one ? "" : " split"}"></span></span>`;
  }

  function renderSimPanel(p) {
    const inputsDiv = $("sim-inputs");
    const outputsDiv = $("sim-outputs");
    const row = p.truthTable[state.simIndex] || p.truthTable[0];
    state.currentInputValues = Object.fromEntries(p.inputs.map((name, i) => [name, row.inputs[i]]));
    $("sim-case").textContent = `${state.simIndex + 1} / ${p.truthTable.length}`;
    $("truth-table").querySelectorAll("[data-sim-case]").forEach((button, index) => {
      button.setAttribute("aria-current", String(index === state.simIndex));
    });

    inputsDiv.innerHTML = `<div class="sim-row"><span class="sim-label">输入:</span>
      ${p.inputs.map((n, i) =>
        `<span class="led led-${row.inputs[i]}" data-input="${n}">${n}=${row.inputs[i]}</span>`
      ).join("")}</div>`;

    outputsDiv.innerHTML = `<div class="sim-row"><span class="sim-label">期望:</span>
      ${p.outputs.map((n, i) =>
        `<span class="led led-${row.outputs[i]}">${n}=${row.outputs[i]}</span>`
      ).join("")}
      <span class="sim-label">实际:</span>
      <span id="actual-outs" class="actual-outs">等待模拟…</span>
    </div>`;
  }

  function selectSimulationRow(index) {
    const puzzle = state.puzzle;
    if (!puzzle) return;
    state.simIndex = (index + puzzle.truthTable.length) % puzzle.truthTable.length;
    renderSimPanel(puzzle);
    if (Object.keys(state.simValues).length) runSimulation();
    else render();
  }

  // ---------- 事件绑定 ----------
  function bindEvents() {
    $("btn-clear").addEventListener("click", () => {
      state.gates = state.gates.filter(g => g.fixed);
      state.wires = [];
      state.connecting = null;
      state.simValues = {};
      if (state.puzzle) renderSimPanel(state.puzzle);
      $("result-panel").hidden = true;
      render();
    });
    $("btn-sim").addEventListener("click", runSimulation);
    $("btn-stop").addEventListener("click", () => {
      state.simValues = {};
      if (state.puzzle) renderSimPanel(state.puzzle);
      render();
    });
    $("btn-submit").addEventListener("click", submitCircuit);
    $("btn-settle").addEventListener("click", settleChapter);
    const npcNext = $("npc-next");
    if (npcNext) npcNext.addEventListener("click", advanceNpc);
    $("sim-prev").addEventListener("click", () => selectSimulationRow(state.simIndex - 1));
    $("sim-next").addEventListener("click", () => selectSimulationRow(state.simIndex + 1));
    $("truth-table").addEventListener("click", event => {
      const choice = event.target.closest("[data-sim-case]");
      if (choice) selectSimulationRow(Number(choice.dataset.simCase));
    });

    svg.addEventListener("click", e => {
      if (e.target === svg || e.target.tagName === "rect") {
        state.connecting = null;
        render();
      }
    });

    svg.addEventListener("mousemove", updateTempWire);
    window.addEventListener("mousemove", onDragMove);
    window.addEventListener("mouseup", onDragEnd);
  }

  // ---------- 剧情与人物 ----------
  async function loadStory() {
    try {
      const res = await fetch("/game/api/circuit/story");
      const body = await res.json();
      if (!res.ok || body.ok !== true) throw new Error((body.error && body.error.message) || "剧情读取失败");
      story = body.data.story;
      catalog = body.data.catalog || null;
      if (story.chapterTitle) $("chapter-title").textContent = story.chapterTitle;
      if (story.chapterSubtitle) $("chapter-subtitle").textContent = story.chapterSubtitle;
    } catch (error) {
      // 剧情坏了不该让整个工坊不能用，退回无名对话条即可。
      story = null;
      $("npc-line").textContent = `剧情未载入：${error.message || "未知原因"}`;
    }
  }

  function levelStory(puzzleId) {
    return (story && story.levels && story.levels[puzzleId]) || null;
  }

  function npcOf(npcId) {
    return (story && story.npcs && story.npcs[npcId]) || null;
  }

  function speak(lines, speakerId) {
    npcSpeaker = speakerId || npcSpeaker;
    npcQueue = Array.isArray(lines) ? lines.slice() : [];
    renderNpc();
  }

  function renderNpc() {
    const npc = npcOf(npcSpeaker);
    const portrait = $("npc-portrait");
    const nextButton = $("npc-next");
    if (!npc) {
      $("npc-name").textContent = "";
      $("npc-title").textContent = "";
      $("npc-line").textContent = "";
      if (nextButton) nextButton.hidden = true;
      return;
    }
    $("npc-name").textContent = npc.name;
    $("npc-title").textContent = npc.title || "";
    portrait.style.borderColor = npc.color || "";
    portrait.style.color = npc.color || "";
    if (npc.portrait) {
      // 有立绘就用立绘；图片 404 时自动退回印章字，不至于空白。
      portrait.innerHTML = "";
      const image = document.createElement("img");
      image.src = npc.portrait;
      image.alt = npc.name;
      image.addEventListener("error", () => { portrait.textContent = npc.seal; });
      portrait.appendChild(image);
    } else {
      portrait.textContent = npc.seal;
    }
    $("npc-line").textContent = npcQueue.length ? npcQueue[0] : "";
    if (nextButton) nextButton.hidden = npcQueue.length <= 1;
  }

  function advanceNpc() {
    if (npcQueue.length <= 1) return;
    npcQueue.shift();
    renderNpc();
  }

  /** 按当前进度挑选该说哪一段话（数据驱动的分支顺序）。 */
  function refreshNpc() {
    const id = state.currentPuzzleId;
    const level = levelStory(id);
    const levels = chapterLevels();
    const solved = Object.keys(levels).filter(key => levels[key].passed).length;
    if (chapterResult() && story && story.closing) {
      speak(story.closing.lines, story.closing.speaker);
      return;
    }
    if (!level) return;
    if (solved === 0 && story && story.opening) {
      speak(story.opening.lines, story.opening.speaker);
      return;
    }
    const saved = levels[id];
    if (saved && saved.passed) {
      speak(level.cleared, level.speaker);
    } else if (saved && saved.attempts > 0 && level.hint) {
      speak(level.hint, level.speaker);
    } else {
      speak(level.intro, level.speaker);
    }
  }

  /** 委托栏与任务下拉：文案全部来自剧情数据。 */
  function refreshQuest(puzzle) {
    const id = state.currentPuzzleId;
    const level = levelStory(id);
    if (level) {
      $("quest-objective").textContent = level.objective || "";
      const title = level.quest || (puzzle && puzzle.title) || "";
      if (title) $("puzzle-title").textContent = title;
    } else {
      $("quest-objective").textContent = "";
    }
    // 主线/支线：结构来自 level_meta.json，将来加大地图时同样读这里。
    const routeTag = $("quest-route");
    if (routeTag) {
      const meta = catalog && catalog.levels && catalog.levels[id];
      if (meta && meta.route) {
        routeTag.textContent = meta.route === "side" ? "支线" : "主线";
        routeTag.hidden = false;
      } else {
        routeTag.hidden = true;
      }
    }
    const select = $("puzzle-select");
    if (select && state.puzzles.length) {
      Array.from(select.options).forEach(option => {
        const puzzleItem = state.puzzles.find(item => item.id === option.value);
        const itemLevel = levelStory(option.value);
        const passed = chapterLevels()[option.value] && chapterLevels()[option.value].passed;
        const label = (itemLevel && itemLevel.quest) || (puzzleItem ? puzzleItem.title : option.value);
        option.textContent = `${passed ? "✓ " : ""}${label}`;
      });
      if (id) select.value = id;
    }
  }

  // ---------- 章节进度 ----------
  function chapterLevels() {
    const progress = chapter && chapter.progress;
    const circuit = progress && progress.state && progress.state.circuit;
    return (circuit && circuit.levels) || {};
  }

  function chapterResult() {
    const progress = chapter && chapter.progress;
    return (progress && progress.result) || null;
  }

  /** 本章的结算尝试记录（只增不改，失败的也留着）。 */
  function chapterAttempts() {
    const progress = chapter && chapter.progress;
    const circuit = progress && progress.state && progress.state.circuit;
    const attempts = circuit && circuit.attempts;
    return Array.isArray(attempts) ? attempts : [];
  }

  /** 上一次尝试已通过、正等结算。老存档没有这个键时按 false 处理。 */
  function pendingSettle() {
    const progress = chapter && chapter.progress;
    const circuit = progress && progress.state && progress.state.circuit;
    return Boolean(circuit && circuit.pendingSettle);
  }

  function syncChapterUi() {
    const levels = chapterLevels();
    const total = state.puzzles.length;
    const solved = Object.keys(levels).filter(id => levels[id].passed).length;
    const result = chapterResult();
    const status = $("chapter-status");
    const settle = $("btn-settle");
    const attempts = chapterAttempts();
    const last = attempts[attempts.length - 1];

    if (!chapter) {
      // 存档读不到时保留 init 里写下的原因，不覆盖它。
    } else if (result) {
      const when = new Date(result.submittedAt).toLocaleString();
      status.textContent = `已结算：${result.score} / ${result.maxScore} 分（${when}）· 可重做，取最高分`;
      // 结算之后仍然保留这个按钮：玩家可以再做一遍，通过了就把更好的成绩提交上去。
      settle.hidden = total === 0;
    } else {
      // 未结算就能一直试：失败的尝试不影响章节状态，只有通过才会写成成绩。
      const tried = attempts.length ? ` · 已尝试 ${attempts.length} 次` : "";
      const tail = last && !last.passed ? `（上次 ${last.score} / ${last.maxScore}，可再试）` : "";
      status.textContent = `已通关 ${solved} / ${total} 关 · 尚未结算${tried}${tail}`;
      settle.hidden = total === 0 || pendingSettle();
    }

    const pill = $("chapter-progress");
    if (pill) pill.textContent = `${solved} / ${total}`;
    refreshQuest(state.puzzle);
    showQuest();
  }

  async function settleChapter() {
    if (!chapter || !chapter.progress) return;
    // 已结算的章节也允许再结算：重做只为拿更高分，成绩由服务端取最大值。
    if (pendingSettle()) {
      // 上一次尝试已通过但结算请求没发出去（例如断网）：这里只补发结算。
      await completeSettlement();
      return;
    }
    const total = state.puzzles.length;
    const solved = Object.keys(chapterLevels()).filter(id => chapterLevels()[id].passed).length;
    const warn = solved === total
      ? ""
      : `还有 ${total - solved} 关没通关，这次结算会记为未通过（之后还能再做）。\n`;
    if (!window.confirm(`${warn}结算后成绩入库、不能再改写，确定结算吗？`)) return;

    questPending(true);
    try {
      // 一次尝试：判分并留档。不通过就到此为止，不写成绩，可以再来。
      await chapter.dispatch("settle");
      syncChapterUi();
      if (pendingSettle()) {
        await completeSettlement();
      } else {
        const attempts = chapterAttempts();
        const last = attempts[attempts.length - 1] || { score: 0, maxScore: 100 };
        $("result-panel").hidden = false;
        $("result-panel").className = "panel-block result-block result-fail";
        $("result-text").innerHTML = `❌ <b>本次结算未通过</b>，得 ${last.score} / ${last.maxScore} 分`
          + `<br><small>成绩没有入库。接着把没通过的关卡做出来，再点「结算工数」重试（已尝试 ${attempts.length} 次）。</small>`;
        $("result-details").innerHTML = "";
      }
    } catch (error) {
      if (error.code === "chapter_completed") alert("本章已结算，不能再挑战。");
      else alert(error.message || "结算失败，请重试。");
    } finally {
      questPending(false);
    }
  }

  /** 通过之后的最后一步：真正写成绩。失败时保留「待结算」，让玩家能补发。 */
  async function completeSettlement() {
    questPending(true);
    try {
      await chapter.dispatch("submit");
      const settled = chapterResult();
      syncChapterUi();
      refreshNpc();
      if (settled) {
        $("result-panel").hidden = false;
        $("result-panel").className = "panel-block result-block result-pass";
        $("result-text").innerHTML = `🏁 <b>最高成绩 ${settled.score} / ${settled.maxScore}</b>`
          + `<br><small>成绩取历史最高，重做不会把它改小。</small>`;
        $("result-details").innerHTML = "";
        offerReturnToCamp();
      }
    } catch (error) {
      // 结算请求没成功：章节仍是「待结算」，再点一次就能补发，不会重复计分。
      alert(error.message || "结算没有完成，请再点一次「结算工数」。");
    } finally {
      questPending(false);
    }
  }

  // ---------- 结束关卡：回亳 ----------
  // 具体关卡结算后返回来源；工坊索引只给手动返回按钮。
  let returnTimer = null;

  function returnUrl() {
    const url = document.body.dataset.returnUrl;
    return url === "/game/#camp" ? url : "/game/#stage-select";
  }

  function returnToCamp() {
    if (returnTimer) {clearTimeout(returnTimer); returnTimer = null;}
    const url = returnUrl();
    // 测试缝：jsdom 不能导航，测试替换 window.HuaxiaReturnToScene 即可断言目标地址。
    if (typeof window.HuaxiaReturnToScene === "function") {window.HuaxiaReturnToScene(url); return;}
    window.location.assign(url);
  }

  function offerReturnToCamp() {
    const box = $("result-return");
    if (!box) return;
    box.hidden = false;
    const link = $("return-to-camp");
    if (link) link.onclick = event => {event.preventDefault(); returnToCamp();};
    if (!document.body.dataset.initialPuzzle) return;   // 工坊索引页不自动跳走
    if (returnTimer) clearTimeout(returnTimer);
    const label = returnUrl() === "/game/#camp" ? "返回营前" : "返回关卡选择";
    let left = Math.max(1, Math.round(Number(document.body.dataset.returnDelay || 6000) / 1000));
    const countdown = () => {
      if (left <= 0) {returnToCamp(); return;}
      if (link) link.textContent = `${label}（${left}s）`;
      left -= 1;
      returnTimer = setTimeout(countdown, 1000);
    };
    countdown();
  }

  // ---------- 门操作 ----------
  function addGate(type) {
    const id = `g${state.nextGateId++}`;
    const x = 200 + Math.random() * 200;
    const y = 100 + Math.random() * 300;
    state.gates.push({ id, type, x, y, fixed: false });
    render();
  }

  function deleteGate(id) {
    state.gates = state.gates.filter(g => g.id !== id);
    state.wires = state.wires.filter(w =>
      w.fromGateId !== id && w.toGateId !== id
    );
    delete state.simValues[id];
    render();
  }

  // ---------- 拖拽 ----------
  // 拖动状态与监听器都放在模块级：渲染再多次，window 上也只有一对监听器。
  let dragging = null;

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  function canvasPoint(e) {
    const transform = svg.getScreenCTM?.();
    if (transform && svg.createSVGPoint) {
      const point = svg.createSVGPoint();
      point.x = e.clientX;
      point.y = e.clientY;
      return point.matrixTransform(transform.inverse());
    }
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: (e.clientX - rect.left) * CANVAS_W / rect.width,
      y: (e.clientY - rect.top) * CANVAS_H / rect.height,
    };
  }

  function startDrag(e, gate) {
    if (e.target && e.target.classList && e.target.classList.contains("port-circle")) return;
    const start = canvasPoint(e);
    if (!start) return;
    dragging = { gate, start, gx: gate.x, gy: gate.y };
    if (e.preventDefault) e.preventDefault();
  }

  function onDragMove(e) {
    if (!dragging) return;
    const point = canvasPoint(e);
    if (!point) return;
    const dx = point.x - dragging.start.x;
    const dy = point.y - dragging.start.y;
    dragging.gate.x = clamp(dragging.gx + dx, 0, CANVAS_W - GATE_W);
    dragging.gate.y = clamp(dragging.gy + dy, 0, CANVAS_H - GATE_H);
    render();
  }

  function onDragEnd() {
    dragging = null;
  }

  // ---------- 渲染 ----------
  function gatePorts(gate) {
    // 返回 [{port: "in1"/"in2"/"out", x, y}]
    const result = [];
    if (gate.type === "INPUT") {
      // 输入源：只有输出
      result.push({ port: "out", x: gate.x + GATE_W, y: gate.y + GATE_H / 2, kind: "out" });
    } else if (gate.type === "OUTPUT") {
      // 输出接收：只有输入
      result.push({ port: "in1", x: gate.x, y: gate.y + GATE_H / 2, kind: "in" });
    } else {
      const g = GATE_SHAPES[gate.type];
      const numIn = g ? g.inputs : 2;
      // 输入端口在左边
      for (let i = 0; i < numIn; i++) {
        const y = gate.y + GATE_H * (i + 1) / (numIn + 1);
        result.push({ port: `in${i + 1}`, x: gate.x, y, kind: "in" });
      }
      // 输出端口在右边
      result.push({ port: "out", x: gate.x + GATE_W, y: gate.y + GATE_H / 2, kind: "out" });
    }
    return result;
  }

  function getPort(gateId, portName) {
    const gate = state.gates.find(g => g.id === gateId);
    if (!gate) return null;
    return gatePorts(gate).find(p => p.port === portName);
  }

  function render() {
    gatesLayer.innerHTML = "";
    wiresLayer.innerHTML = "";
    portsLayer.innerHTML = "";
    if (!state.connecting) tempWireLayer.replaceChildren();

    // 渲染连线
    state.wires.forEach(w => {
      const from = getPort(w.fromGateId, w.fromPort);
      const to = getPort(w.toGateId, w.toGatePort);
      if (!from || !to) return;
      const path = bezierPath(from.x, from.y, to.x, to.y);
      const val = state.simValues[w.fromGateId];
      const cls = val === 1 ? "wire-on" : "wire-off";
      const line = el("path", { d: path, class: `wire ${cls}`, "data-wire": w.id });
      line.addEventListener("click", e => {
        e.stopPropagation();
        deleteWire(w.id);
      });
      wiresLayer.appendChild(line);
    });

    // 渲染门
    state.gates.forEach(gate => {
      const g = GATE_SHAPES[gate.type];
      const group = el("g", { class: "gate", "data-gate-id": gate.id, "data-type": gate.type, "transform": `translate(${gate.x}, ${gate.y})` });

      if (gate.type === "INPUT") {
        // 输入源：绿色圆 + 标签
        const val = state.currentInputValues
          ? state.currentInputValues[gate.name] ?? 0
          : 0;
        group.appendChild(el("rect", { width: GATE_W, height: GATE_H, rx: 6, class: "gate-rect input-gate" }));
        group.appendChild(el("text", { x: GATE_W/2, y: GATE_H/2 - 4, class: "gate-label" }, gate.name));
        group.appendChild(el("text", { x: GATE_W/2, y: GATE_H/2 + 14, class: `gate-value value-${val}` }, String(val)));
      } else if (gate.type === "OUTPUT") {
        // 输出：琥珀色圆 + LED
        const outVal = state.simValues[`__out_${gate.name}`];
        group.appendChild(el("rect", { width: GATE_W, height: GATE_H, rx: 6, class: "gate-rect output-gate" }));
        group.appendChild(el("text", { x: GATE_W/2, y: GATE_H/2 - 4, class: "gate-label" }, gate.name));
        if (outVal !== undefined) {
          group.appendChild(el("text", { x: GATE_W/2, y: GATE_H/2 + 14, class: `gate-value value-${outVal}` }, String(outVal)));
        } else {
          group.appendChild(el("text", { x: GATE_W/2, y: GATE_H/2 + 14, class: "gate-value value-?" }, "?"));
        }
      } else {
        // 逻辑门
        const color = g.color;
        group.appendChild(el("rect", { width: GATE_W, height: GATE_H, rx: 6,
          class: "gate-rect", style: `stroke:var(--gate-accent,${color});fill:var(--gate-fill,${color}22)` }));
        group.appendChild(el("text", { x: GATE_W/2, y: GATE_H/2 + 6, class: "gate-label", style: `fill:var(--gate-accent,${color})` }, gate.type));
      }

      // 拖拽移动：这里只挂 mousedown，移动与松手由模块级监听器统一处理，
      // 否则每次 render 都会往 window 上再堆一对监听器（拖拽会越拖越卡）。
      if (!gate.fixed) {
        group.style.cursor = "move";
        group.addEventListener("mousedown", e => startDrag(e, gate));

        // 双击删除
        group.addEventListener("dblclick", e => {
          e.stopPropagation();
          deleteGate(gate.id);
        });
      }

      gatesLayer.appendChild(group);

      // 渲染端口：坐标是相对门的，所以这个 <g> 必须平移到门的位置，
      // 否则圆圈会飘到离门 (gate.x, gate.y) 那么远的地方，点不到。
      gatePorts(gate).forEach(port => {
        const pGroup = el("g", {
          class: "port",
          "data-gate": gate.id,
          "data-port": port.port,
          transform: `translate(${gate.x}, ${gate.y})`,
        });
        const circle = el("circle", { cx: port.x - gate.x, cy: port.y - gate.y, r: PORT_R,
          class: `port-circle port-${port.kind}` });
        const focused = state.connecting && state.connecting.gateId === gate.id && state.connecting.port === port.port;
        if (focused) circle.setAttribute("class", `port-circle port-${port.kind} port-active`);
        circle.addEventListener("click", e => {
          e.stopPropagation();
          handlePortClick(gate.id, port.port, port.kind);
        });
        pGroup.appendChild(circle);
        gatesLayer.appendChild(pGroup);
      });
    });
  }

  function bezierPath(x1, y1, x2, y2) {
    const dx = Math.abs(x2 - x1) * 0.5;
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

  function el(tag, attrs = {}, text) {
    const n = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.setAttribute("class", v);
      else if (k === "style") n.setAttribute("style", v);
      else n.setAttribute(k, v);
    }
    if (text) n.textContent = text;
    return n;
  }

  function handlePortClick(gateId, port, kind) {
    if (!state.connecting) {
      if (kind === "out") {
        state.connecting = { gateId, port };
      }
    } else {
      // 检查是否是反向操作（从 in 点 out）
      if (kind === "in" && state.connecting.gateId !== gateId) {
        addWire(state.connecting.gateId, state.connecting.port, gateId, port);
      }
      state.connecting = null;
    }
    render();
  }

  function addWire(fromGateId, fromPort, toGateId, toPort) {
    // 防重复
    const exists = state.wires.find(w =>
      w.fromGateId === fromGateId && w.fromPort === fromPort &&
      w.toGateId === toGateId && w.toGatePort === toPort
    );
    if (exists) return;
    // 输入端点只能连一个来源
    state.wires = state.wires.filter(w => !(w.toGateId === toGateId && w.toGatePort === toPort));
    state.wires.push({ id: state.nextWireId++, fromGateId, fromPort, toGateId, toGatePort: toPort });
  }

  function deleteWire(id) {
    state.wires = state.wires.filter(w => w.id !== id);
    render();
  }

  // 临时连线（鼠标拖动时）
  function updateTempWire(e) {
    if (!state.connecting) return;
    const point = canvasPoint(e);
    const from = getPort(state.connecting.gateId, state.connecting.port);
    if (!from || !point) return;
    tempWireLayer.replaceChildren(el("path", {
      d: bezierPath(from.x, from.y, point.x, point.y),
      class: "wire temp-wire"
    }));
  }

  // ---------- 模拟 ----------
  async function runSimulation() {
    const p = state.puzzle;
    if (!p) return;
    const row = p.truthTable[state.simIndex];
    state.currentInputValues = Object.fromEntries(p.inputs.map((n, i) => [n, row.inputs[i]]));

    // 构建 gates/wires 供后端模拟
    const gates = state.gates.filter(g => !g.fixed).map(g => ({
      id: g.id, type: g.type, x: g.x, y: g.y
    }));
    const wires = state.wires.map(w => ({
      from: { gateId: w.fromGateId, port: w.fromPort },
      to: { gateId: w.toGateId, port: w.toGatePort },
    }));

    // 前端直接模拟（快，不用请求）
    const result = simulateLocal(p, row.inputs);
    if (result === null) {
      alert("电路有环或连接不完整，无法模拟。请检查连线。");
      return;
    }
    state.simValues = result.gateValues;
    state.currentInputValues = Object.fromEntries(p.inputs.map((n, i) => [n, row.inputs[i]]));
    render();

    // 更新模拟面板"实际"值
    const actualOuts = $("actual-outs");
    if (actualOuts) {
      actualOuts.innerHTML = p.outputs.map((n, i) => {
        const outVal = result.outputs[i];
        const expected = row.outputs[i];
        const cls = outVal === expected ? "led led-pass" : "led led-fail";
        return `<span class="${cls}">${n}=${outVal ?? "?"}</span>`;
      }).join("");
    }
  }

  /** 前端本地电路模拟 */
  function simulateLocal(puzzle, inputVals) {
    // 拓扑排序 + 求值（简化版）
    const gateMap = Object.fromEntries(state.gates.map(g => [g.id, g]));

    // 连线查找
    const connMap = {}; // (toGateId, toPort) -> {fromGateId, fromPort}
    state.wires.forEach(w => {
      connMap[`${w.toGateId}|${w.toGatePort}`] = { fromGateId: w.fromGateId, fromPort: w.fromPort };
    });

    const outputCache = {}; // gateId -> 0/1

    function evalGate(gateId, depth = 0) {
      if (depth > 50) return null; // 环检测
      if (outputCache[gateId] !== undefined) return outputCache[gateId];

      const gate = gateMap[gateId];
      if (!gate) return null;
      if (gate.type === "INPUT") {
        const idx = puzzle.inputs.indexOf(gate.name);
        const v = idx >= 0 ? inputVals[idx] : 0;
        outputCache[gateId] = v;
        return v;
      }

      const g = GATE_SHAPES[gate.type];
      const numIn = g ? g.inputs : 2;
      const inputs = [];
      for (let i = 0; i < numIn; i++) {
        const portName = `in${i + 1}`;
        const conn = connMap[`${gateId}|${portName}`];
        if (conn) {
          const v = evalGate(conn.fromGateId, depth + 1);
          if (v === null) return null;
          inputs.push(v);
        } else {
          inputs.push(0);
        }
      }

      let result = 0;
      if (gate.type === "NAND") result = !(inputs[0] && inputs[1]) ? 1 : 0;
      else if (gate.type === "AND") result = (inputs[0] && inputs[1]) ? 1 : 0;
      else if (gate.type === "OR") result = (inputs[0] || inputs[1]) ? 1 : 0;
      else if (gate.type === "NOT") result = 1 - inputs[0];
      else if (gate.type === "XOR") result = (inputs[0] ^ inputs[1]) ? 1 : 0;
      else if (gate.type === "NOR") result = !(inputs[0] || inputs[1]) ? 1 : 0;
      else result = inputs[0]; // OUTPUT 类型直接透传

      outputCache[gateId] = result;
      return result;
    }

    // 计算所有门
    state.gates.forEach(g => evalGate(g.id));

    // 收集输出端点
    const outputs = puzzle.outputs.map(name => {
      const gateId = `__out_${name}`;
      const conn = state.wires.find(w => w.toGateId === gateId);
      if (!conn) return null;
      return outputCache[conn.fromGateId] ?? null;
    });

    return { gateValues: outputCache, outputs };
  }

  // ---------- 提交本关 ----------
  async function submitCircuit() {
    const p = state.puzzle;
    if (!p) return;
    if (!chapter || !chapter.progress) {
      alert("尚未读取到章节存档，请刷新页面后重试。");
      return;
    }

    const gates = state.gates.filter(g => !g.fixed).map(g => ({
      id: g.id,
      type: g.type,
      x: Math.round(g.x),
      y: Math.round(g.y),
    }));
    const wires = state.wires.map(w => ({
      from: { gateId: w.fromGateId, port: w.fromPort },
      to: { gateId: w.toGateId, port: w.toGatePort },
    }));

    try {
      // 判分、存档、成绩回传都在这一个动作里完成，服务端是唯一裁判。
      // 关卡 id 以 currentPuzzleId 为准：详情响应不保证自带 id，
      // 依赖 p.id 会在拿到 undefined 时静默漏掉字段（服务端报 invalid_fields）。
      await chapter.dispatch("solve", { puzzleId: state.currentPuzzleId, gates, wires });
      const level = chapterLevels()[state.currentPuzzleId];
      syncChapterUi();
      refreshNpc();
      if (level && level.lastResult) showResult(level.lastResult);
    } catch (error) {
      if (error.code === "chapter_completed") alert("本章已结算，不能再挑战。");
      else if (error.code === "authentication_required") alert("登录已失效，请重新登录。");
      else alert(error.message || "提交失败，请重试。");
    }
  }

  function showResult(data) {
    const panel = $("result-panel");
    const text = $("result-text");
    const details = $("result-details");
    panel.hidden = false;

    if (!data || !Array.isArray(data.cases) || !data.cases.length) {
      text.textContent = "验收结果为空，请重试。";
      details.innerHTML = "";
      return;
    }

    if (data.passed) {
      text.innerHTML = `🎉 <b>验收通过！</b> 得 ${data.points} 分<br><small>四个真值表行全部匹配。</small>`;
      panel.className = "panel-block result-block result-pass";
    } else {
      text.innerHTML = `❌ <b>未通过</b>，得 ${data.points} 分<br><small>请检查未匹配的行。</small>`;
      panel.className = "panel-block result-block result-fail";
    }
    details.innerHTML = `<table class="truth-table mini">
      <thead><tr>
        ${data.cases[0].inputs.map((_, i) => `<th>${String.fromCharCode(65 + i)}</th>`).join("")}
        ${data.cases[0].expected.map((_, i) => `<th>期望${i}</th>`).join("")}
        ${data.cases[0].actual.map((_, i) => `<th>实际${i}</th>`).join("")}
        <th>?</th>
      </tr></thead>
      <tbody>${data.cases.map(c =>
        `<tr class="${c.pass ? "pass" : "fail"}">
          ${c.inputs.map(v => `<td>${v}</td>`).join("")}
          ${c.expected.map(v => `<td>${v}</td>`).join("")}
          ${c.actual.map(v => `<td>${v ?? "—"}</td>`).join("")}
          <td>${c.pass ? "✓" : "✗"}</td>
        </tr>`).join("")}</tbody>
    </table>`;
  }

  document.addEventListener("DOMContentLoaded", init);
})();

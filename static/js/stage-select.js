/* 亳的行动入口与电路行动记录。 */
"use strict";
(() => {
  const CHAPTER = "xia-circuit";
  const MAX_SCORE = 100;

  let root = null;
  let renderVersion = 0;

  function circuitUrl(row) {
    return `/game/level/${encodeURIComponent(row.id)}`;
  }

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };

  function navigate(url) {
    // 测试缝：jsdom 不能导航。
    if (typeof window.HuaxiaStageNavigate === "function") return window.HuaxiaStageNavigate(url);
    window.location.assign(url);
  }

  async function readJson(url) {
    const response = await fetch(url);
    const body = await response.json();
    if (!response.ok || body.ok !== true) {
      throw new Error((body.error && body.error.message) || "读取失败");
    }
    return body.data;
  }

  function clockText(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    const pad = n => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function stageState(puzzles, progress) {
    const circuit = (progress.state && progress.state.circuit) || {};
    const levels = circuit.levels || {};
    const attempts = Array.isArray(circuit.attempts) ? circuit.attempts : [];
    const rows = puzzles.map((puzzle, index) => {
      const level = levels[puzzle.id] || {passed: false, points: 0, attempts: 0};
      return {
        id: puzzle.id,
        index: index + 1,
        title: puzzle.title,
        description: puzzle.description || "",
        passed: Boolean(level.passed),
        points: level.points || 0,
        attempts: level.attempts || 0,
      };
    });
    const score = progress.result?.score ?? rows.reduce((sum, row) => sum + (row.passed ? row.points : 0), 0);
    const startedAt = attempts.length ? attempts[0].at : null;
    return {
      rows,
      attempts,
      score,
      max: MAX_SCORE,
      startedAt,
      submittedAt: progress.result ? progress.result.submittedAt : null,
      settled: Boolean(progress.result),
    };
  }

  function header(state, onBack) {
    const box = el("div", "ark-head");
    const left = el("div", "ark-head-main");
    left.append(
      el("p", "ark-kicker", "中原 · 亳"),
      el("h2", "ark-title", "行动选择"),
      el("p", "ark-sub", state.rows.length ? `电路已通关 ${state.rows.filter(r => r.passed).length} / ${state.rows.length} 关 · ${state.settled ? `已提交 ${state.score} / ${state.max}` : "成绩待提交"}` : ""),
    );
    const right = el("div", "ark-head-actions");
    // 战绩页是服务端直出，直接给链接，不需要额外脚本。
    const record = el("a", "ark-btn", "战绩 · 成就");
    record.href = "/game/profile";
    const back = el("button", "ark-btn ghost", "返回地图");
    back.type = "button";
    back.addEventListener("click", () => onBack());
    right.append(record, back);
    box.append(left, right);
    return box;
  }

  /** 左侧课程指引：第几章、第几节、本节知识点与目标。 */
  function buildGuide() {
    const curriculum = window.HuaxiaCurriculum;
    const chapter = curriculum && curriculum.chapterOf("central-plains");
    const place = curriculum && curriculum.placeOf("central-plains", "bo");
    const guide = el("aside", "ark-guide");
    guide.setAttribute("aria-label", "本节学习指引");
    if (!chapter || !place) {
      guide.append(el("p", "ark-guide-no", "课程指引"), el("p", "ark-guide-summary", "暂无课程数据。"));
      return guide;
    }
    guide.append(
      el("p", "ark-guide-no", chapter.no),
      el("p", "ark-guide-chapter", chapter.title),
      el("p", "ark-guide-section", `${place.no} · ${place.title}`),
    );
    const known = el("div", "ark-guide-block");
    known.append(el("p", "ark-guide-label", "本节知识点"));
    const tags = el("div", "ark-guide-tags");
    for (const item of place.knowledge) tags.append(el("span", "ark-guide-tag", item));
    known.append(tags);
    const goal = el("div", "ark-guide-block");
    goal.append(el("p", "ark-guide-label", "本节目标"), el("p", "ark-guide-summary", place.goal));
    guide.append(known, goal);
    return guide;
  }

  function stageCard(state) {
    const list = el("div", "ark-stages");
    for (const row of state.rows) {
      const card = el("button", "ark-stage");
      card.type = "button";
      card.dataset.stageId = row.id;
      card.dataset.stageKind = "circuit";

      const emblem = el("span", "ark-stage-emblem", row.id === "tc-nand" ? "NAND" : "符");
      emblem.setAttribute("aria-hidden", "true");
      const body = el("span", "ark-stage-body");
      body.append(
        el("span", "ark-stage-title", row.title),
        el("span", "ark-stage-desc", row.description),
      );
      const tail = el("span", "ark-stage-tail");
      tail.append(
        el("span", `ark-stage-state${row.passed ? " done" : ""}`, row.passed ? `已通关 ${row.points}/${MAX_SCORE}` : "未通关"),
        el("span", "ark-stage-tries", row.attempts ? `尝试 ${row.attempts} 次` : "未尝试"),
        el("span", "ark-stage-action", row.passed ? "查看记录 ›" : "进入工坊 ›"),
      );
      card.append(emblem, body, tail);
      card.addEventListener("click", () => (row.passed ? openRecord(state, row, card) : navigate(circuitUrl(row))));
      list.append(card);
    }
    if (!state.rows.length) list.append(el("p", "ark-empty", "本章暂无关卡。"));
    return list;
  }

  /** 第二节：代码关不在电路章节里，单独给一张卡。 */
  function extraStage(progress) {
    const wrap = el("div", "ark-stages");
    const card = el("a", "ark-stage");
    card.href = "/game/code";
    card.dataset.stageKind = "code";
    const emblem = el("span", "ark-stage-emblem", "a · b");
    emblem.setAttribute("aria-hidden", "true");
    const body = el("span", "ark-stage-body");
    body.append(
      el("span", "ark-stage-title", "铸言 · 代码关"),
      el("span", "ark-stage-desc", "用 a、b、and、or、not 写一个表达式，让与非门的四行真值表全对。"),
    );
    const tail = el("span", "ark-stage-tail");
    const code = progress?.state?.code;
    const submitted = progress?.result;
    const label = submitted ? `已提交 ${submitted.score} / ${submitted.maxScore}`
      : code?.passed ? "已验算 · 待提交" : code?.attempts ? "已开始" : "独立计分";
    tail.append(el("span", `ark-stage-state${submitted ? " done" : ""}`, label), el("span", "ark-stage-action", "进入铸言 ›"));
    card.append(emblem, body, tail);
    wrap.append(card);
    return wrap;
  }

  function campStage(onCamp) {
    const list = el("div", "ark-stages");
    const card = el("button", "ark-stage");
    card.type = "button";
    card.dataset.stageId = "camp";
    card.dataset.stageKind = "camp";
    const body = el("span", "ark-stage-body");
    body.append(el("span", "ark-stage-title", "亳城营前"),
      el("span", "ark-stage-desc", "沿河谷营道走访守门人与妇好。"));
    const emblem = el("span", "ark-stage-emblem");
    emblem.setAttribute("aria-hidden", "true");
    const tail = el("span", "ark-stage-tail");
    tail.append(el("span", "ark-stage-action", "走进营前 ›"));
    card.append(emblem, body, tail);
    card.addEventListener("click", onCamp);
    list.append(card);
    return list;
  }

  function progressBar(value, max) {
    const wrap = el("div", "ark-bar");
    const fill = el("div", "ark-bar-fill");
    const pct = max > 0 ? Math.max(0, Math.min(100, Math.round((value / max) * 100))) : 0;
    fill.style.width = `${pct}%`;
    const label = el("span", "ark-bar-label", `${pct}%`);
    fill.append(label);
    wrap.append(fill);
    return wrap;
  }

  function openRecord(state, focusRow, trigger) {
    const shell = root.querySelector(".ark-shell");
    const overlay = el("div", "ark-record");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "行动记录");
    function dismiss() {
      overlay.remove();
      shell.inert = false;
      trigger.focus();
    }

    const panel = el("div", "ark-record-panel");
    const head = el("div", "ark-record-head");
    head.append(
      el("p", "ark-kicker", "行动记录"),
      el("h3", "ark-record-title", focusRow.title),
    );
    const close = el("button", "ark-btn ghost", "关闭");
    close.type = "button";
    close.addEventListener("click", dismiss);
    head.append(close);

    const facts = el("div", "ark-facts");
    const first = state.startedAt || (state.attempts[0] && state.attempts[0].at) || null;
    for (const [label, value] of [
      ["开始时间", clockText(first)],
      ["结束时间", clockText(state.submittedAt)],
      ["提交次数", String(state.attempts.length)],
      ["关卡数", String(state.rows.length)],
      ["最高成绩", `${state.score} / ${state.max}`],
    ]) {
      const cell = el("div", "ark-fact");
      cell.append(el("span", "ark-fact-label", label), el("span", "ark-fact-value", value));
      facts.append(cell);
    }

    panel.append(head, facts, progressBar(state.score, state.max));

    const table = el("table", "ark-table");
    const thead = el("thead");
    const hr = el("tr");
    for (const text of ["编号", "关卡", "得分"]) hr.append(el("th", null, text));
    thead.append(hr);
    const tbody = el("tbody");
    for (const row of state.rows) {
      const tr = el("tr");
      tr.dataset.stageId = row.id;
      tr.append(
        el("td", "ark-cell-num", String(row.index).padStart(3, "0")),
        el("td", null, row.title),
        el("td", `ark-cell-score${row.passed ? "" : " miss"}`, `${row.points} / ${MAX_SCORE}`),
      );
      tbody.append(tr);
    }
    table.append(thead, tbody);
    panel.append(table);

    const actions = el("div", "ark-record-actions");
    const again = el("button", "ark-btn primary", "重做本关");
    again.type = "button";
    again.addEventListener("click", () => navigate(circuitUrl(focusRow)));
    const back = el("button", "ark-btn ghost", "返回选择");
    back.type = "button";
    back.addEventListener("click", dismiss);
    actions.append(again, back);
    panel.append(actions);

    overlay.append(panel);
    overlay.addEventListener("click", event => {if (event.target === overlay) dismiss();});
    overlay.addEventListener("keydown", event => {
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
      } else if (event.key === "Tab") {
        const boundary = event.shiftKey ? close : back;
        if (document.activeElement === boundary) {
          event.preventDefault();
          (event.shiftKey ? back : close).focus();
        }
      }
    });
    shell.inert = true;
    root.append(overlay);
    close.focus();
  }

  async function open(container, options = {}) {
    root = container;
    const version = ++renderVersion;
    const onBack = options.onBack || (() => {});
    root.replaceChildren(el("p", "ark-loading", "正在读取行动记录…"));
    const [circuit, code] = await Promise.allSettled([
      Promise.all([readJson("/game/api/circuit/puzzles"), readJson(`/game/api/chapters/${CHAPTER}/progress`)]),
      readJson("/game/api/chapters/xia-code/progress"),
    ]);
    if (version !== renderVersion) return;
    const shell = el("div", "ark-shell");
    const main = el("div", "ark-main");
    const state = circuit.status === "fulfilled" ? stageState(circuit.value[0].puzzles, circuit.value[1].progress) : stageState([], {});
    main.append(header(state, onBack));
    if (options.onCamp) main.append(campStage(options.onCamp));
    if (circuit.status === "fulfilled") main.append(stageCard(state));
    else {
      const box = el("div", "ark-error");
      box.append(el("p", null, "暂时读不到电路关卡。"));
      const retry = el("button", "ark-btn ghost", "重新读取");
      retry.type = "button";
      retry.addEventListener("click", () => void open(container, options));
      box.append(retry);
      main.append(box);
    }
    main.append(extraStage(code.value?.progress));
    shell.append(buildGuide(), main);
    container.replaceChildren(shell);
  }

  function close() {
    renderVersion++;
    if (root) root.replaceChildren();
    root = null;
  }

  window.HuaxiaStageSelect = {open, close};
})();

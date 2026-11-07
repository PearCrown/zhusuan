/* Isolated single-gate exercise; local feedback only. */
"use strict";
(() => {
  const config = Object.freeze({ inputs: 2, allowedGates: Object.freeze(["NAND"]), target: "NAND" });
  const sources = ["A", "B", "Q"];
  const sinks = ["IN1", "IN2", "Y"];
  const points = { A: [105, 105], B: [105, 215], IN1: [306, 105], IN2: [306, 215], Q: [553, 160], Y: [691, 160] };
  const vectors = [[0, 0, 1], [0, 1, 1], [1, 0, 1], [1, 1, 0]];
  const mounted = new WeakMap();
  const error = code => Object.assign(new Error(code), { code });
  const hasKeys = (value, keys) => value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
  const bit = value => value === 0 || value === 1;
  const allowed = (from, to) => sources.includes(from) && sinks.includes(to) && (from !== "Q" || to === "Y");

  function readDraft(draft) {
    if (draft == null) return { a: 0, b: 0, wires: new Map() };
    if (!hasKeys(draft, ["version", "inputs", "wires"]) || draft.version !== 1 ||
        !hasKeys(draft.inputs, ["A", "B"]) || !bit(draft.inputs.A) || !bit(draft.inputs.B) ||
        !Array.isArray(draft.wires) || draft.wires.length > sinks.length) throw error("INVALID_NAND_DRAFT");
    const wires = new Map();
    for (const wire of draft.wires) {
      if (!hasKeys(wire, ["from", "to"]) || !allowed(wire.from, wire.to) || wires.has(wire.to)) {
        throw error("INVALID_NAND_DRAFT");
      }
      wires.set(wire.to, wire.from);
    }
    return { a: draft.inputs.A, b: draft.inputs.B, wires };
  }

  function evaluate(a, b, wires) {
    const values = { A: a, B: b };
    const left = values[wires.get("IN1")], right = values[wires.get("IN2")];
    values.Q = left == null || right == null ? null : Number(!(left && right));
    const problems = sinks.filter(to => !wires.has(to)).map(to => to + " 未接线");
    if (wires.has("Y") && wires.get("Y") !== "Q") problems.push("Y 直接接了输入，应接门输出 Q");
    if (left != null && right != null && wires.get("IN1") === wires.get("IN2")) {
      problems.push("两个门输入接了同一信号，应分别接 A 和 B");
    }
    const actual = values[wires.get("Y")] ?? null;
    const expected = Number(!(a && b));
    return { actual, expected, problems, ok: !problems.length && actual === expected };
  }

  const template = `
    <div class="nand-titlebar">
      <div><p class="nand-eyebrow">逻辑门练习 / 01</p><h1>NAND 接线台</h1>
        <p class="nand-subtitle">将 A、B 分别接到门输入，再将 Q 接到 Y。</p>
      </div>
      <button type="button" data-exit>退出练习 <kbd>Esc</kbd></button>
    </div>
    <div class="nand-workspace">
      <section class="nand-panel nand-circuit" aria-label="接线板">
        <div class="nand-panel-heading"><h2>接线板</h2><span data-count>0 / 3 条连接</span></div>
        <div class="nand-board" data-board>
          <svg viewBox="0 0 800 320" aria-hidden="true">
            <path class="nand-gate" d="M326 65H404a95 95 0 0 1 0 190H326Z"/>
            <path class="nand-pin" d="M306 105H326M306 215H326M513 160H553"/>
            <circle class="nand-bubble" cx="505" cy="160" r="8"/>
            <g data-traces></g>
            <text class="nand-gate-name" x="395" y="161">NAND</text>
            <text class="nand-gate-note" x="394" y="190">与非门</text>
          </svg>
        </div>
        <p class="nand-wiring-message" role="status" data-wiring>先选信号源 A、B 或 Q，再选目标端口。</p>
        <div class="nand-board-help">
          <span>未选择源时，操作已连线的目标即可拆线。</span>
          <span><kbd>Tab</kbd> 切换 · <kbd>Enter</kbd> / <kbd>Space</kbd> 操作</span>
        </div>
      </section>
      <section class="nand-panel nand-check" aria-label="真值验证">
        <div class="nand-panel-heading"><h2>真值验证</h2><span data-tested>0 / 4 组已试</span></div>
        <div class="nand-controls" aria-label="试运行输入">
          <button type="button" data-bit="A"></button><button type="button" data-bit="B"></button>
          <button type="button" class="nand-primary" data-run>试运行</button>
        </div>
        <table class="nand-table">
          <caption class="nand-sr-only">四组 NAND 真值</caption>
          <thead><tr><th scope="col">A</th><th scope="col">B</th><th scope="col">预期 Y</th><th scope="col">实测 Y</th><th scope="col">结果</th></tr></thead>
          <tbody>${vectors.map(([a,b,expected], index) => `<tr data-row="${index}"><td>${a}</td><td>${b}</td><td>${expected}</td><td data-actual>—</td><td data-result>待试</td></tr>`).join("")}</tbody>
        </table>
        <div class="nand-feedback" role="status" aria-atomic="true" data-feedback>
          <strong data-feedback-title>等待试运行</strong>
          <p data-feedback-detail>切换 A、B 后逐组试运行，实测值会填进表格。</p>
        </div>
      </section>
    </div>`;

  function mount(host, options, callbacks = {}) {
    const { instanceId, config: provided, draft, signal } = options || {};
    if (host?.nodeType !== 1 || typeof instanceId !== "string" || !instanceId.trim() || instanceId.length > 128 ||
        !signal || typeof signal.addEventListener !== "function" || typeof signal.removeEventListener !== "function") {
      throw error("INVALID_NAND_MOUNT");
    }
    if (signal.aborted) throw error("NAND_MOUNT_ABORTED");
    if (provided?.inputs !== 2 || provided.target !== "NAND" || !Array.isArray(provided.allowedGates) ||
        provided.allowedGates.length !== 1 || provided.allowedGates[0] !== "NAND") throw error("INVALID_NAND_CONFIG");
    const { a, b, wires } = readDraft(draft);
    const inputs = { A: a, B: b };
    mounted.get(host)?.dispose();

    const doc = host.ownerDocument;
    const listeners = new doc.defaultView.AbortController();
    const root = doc.createElement("section");
    root.className = "nand-runner";
    root.innerHTML = template;
    const $ = selector => root.querySelector(selector);
    const all = selector => [...root.querySelectorAll(selector)];
    const board = $("[data-board]");
    const rows = all("[data-row]");
    const ports = new Map();
    const trials = new Map();
    let selected = null;
    let paused = false;
    let disposed = false;
    let completed = false;

    function exportDraft() {
      if (disposed) throw error("NAND_RUNNER_CLOSED");
      return { version: 1, inputs: { ...inputs }, wires: sinks.filter(to => wires.has(to)).map(to => ({ from: wires.get(to), to })) };
    }
    const active = () => !disposed && !paused && !signal.aborted;
    const notify = (name, value) => { if (active()) callbacks[name]?.(value); };
    const on = (element, type, handler) => element.addEventListener(type, handler, { signal: listeners.signal });
    const message = text => { $("[data-wiring]").textContent = text; };

    function drawWiring() {
      const traces = $("[data-traces]");
      traces.replaceChildren();
      for (const [to, from] of wires) {
        const [x1, y1] = points[from], [x2, y2] = points[to], mid = (x1 + x2) / 2;
        const path = doc.createElementNS("http://www.w3.org/2000/svg", "path");
        // Bypass lines go below the gate, so they remain distinguishable from Q → Y.
        path.setAttribute("d", to === "Y" && from !== "Q"
          ? `M${x1} ${y1}C190 ${y1} 150 287 250 287H590Q${x2} 287 ${x2} ${y2}`
          : `M${x1} ${y1}C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`);
        path.setAttribute("class", "nand-trace nand-trace-" + from);
        traces.append(path);
      }
      for (const [id, button] of ports) {
        const source = sources.includes(id);
        const from = wires.get(id);
        button.dataset.selected = String(selected === id);
        button.dataset.connected = String(source ? [...wires.values()].includes(id) : !!from);
        if (source) button.setAttribute("aria-pressed", String(selected === id));
        button.setAttribute("aria-label", source ? id + " 信号源" : id + " 目标端口" + (from ? "，已接 " + from : "，未连接"));
      }
      $("[data-count]").textContent = wires.size + " / 3 条连接";
    }

    function drawTrials() {
      const index = inputs.A * 2 + inputs.B;
      rows.forEach((row, i) => {
        const result = trials.get(i);
        row.dataset.current = String(i === index);
        row.dataset.state = result ? (result.ok ? "match" : "mismatch") : "pending";
        row.querySelector("[data-actual]").textContent = result?.actual ?? "—";
        row.querySelector("[data-result]").textContent = !result ? "待试" : result.ok ? "一致" : "需修正";
      });
      $("[data-tested]").textContent = trials.size + " / 4 组已试";
      for (const key of ["A", "B"]) {
        const button = $(`[data-bit="${key}"]`);
        button.textContent = key + " = " + inputs[key];
        button.setAttribute("aria-pressed", String(inputs[key] === 1));
        button.setAttribute("aria-label", "切换输入 " + key + "，当前 " + inputs[key]);
      }
    }

    function feedback(state, title, detail) {
      $("[data-feedback]").dataset.state = state;
      $("[data-feedback-title]").textContent = title;
      $("[data-feedback-detail]").textContent = detail;
    }

    function changedWiring() {
      trials.clear();
      completed = false;
      drawWiring();
      drawTrials();
      feedback("pending", "接线已修改", "试运行记录已清空，请用新接线逐组验证。");
      notify("draftChanged", exportDraft());
    }

    function choose(id) {
      if (!active()) return;
      if (sources.includes(id)) {
        selected = selected === id ? null : id;
        drawWiring();
        message(selected ? "已选择 " + selected + "，请选择目标端口。Esc 取消。" : "已取消选择。");
      } else if (selected) {
        if (!allowed(selected, id)) { message("不能把门输出 Q 接回门输入；请选择 Y，或按 Esc 取消。"); return; }
        if (wires.has(id)) {
          message(id + " 已接 " + wires.get(id) + "；先取消选择，再点 " + id + " 拆线。");
          return;
        }
        const from = selected;
        selected = null;
        wires.set(id, from);
        message("已连接 " + from + " → " + id + "。");
        changedWiring();
      } else if (wires.has(id)) {
        const from = wires.get(id);
        wires.delete(id);
        message("已拆除 " + from + " → " + id + "。");
        changedWiring();
      } else {
        message(id + " 未接线，请先选择 A、B 或 Q。");
      }
    }

    for (const id of ["A", "B", "IN1", "IN2", "Q", "Y"]) {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = "nand-port";
      button.dataset.port = id;
      button.dataset.direction = sources.includes(id) ? "source" : "sink";
      button.style.setProperty("--x", points[id][0] / 8 + "%");
      button.style.setProperty("--y", points[id][1] / 3.2 + "%");
      button.textContent = id;
      board.append(button);
      ports.set(id, button);
      on(button, "click", () => choose(id));
    }

    for (const button of all("[data-bit]")) on(button, "click", () => {
      if (!active()) return;
      const key = button.dataset.bit;
      inputs[key] = 1 - inputs[key];
      drawTrials();
      feedback("pending", "已选择 A=" + inputs.A + "，B=" + inputs.B, "按「试运行」检查这组输入。");
      notify("draftChanged", exportDraft());
    });
    on($("[data-run]"), "click", () => {
      if (!active()) return;
      const { A, B } = inputs;
      const result = evaluate(A, B, wires);
      trials.set(A * 2 + B, result);
      drawTrials();
      const summary = "A=" + A + "，B=" + B + "：预期 Y=" + result.expected + "，实测 Y=" + (result.actual ?? "无输出") + "。";
      const allMatch = trials.size === vectors.length && [...trials.values()].every(trial => trial.ok);
      feedback(result.ok ? "match" : "mismatch", allMatch ? "四组本地结果一致" : result.ok ? "本组输出一致" : "请检查接线",
        summary + (result.problems.length ? result.problems.join("；") + "。" : allMatch ? " 本地练习不计成绩。" : ""));
      if (allMatch && !completed) {
        completed = true;
        notify("operationCompleted", { draft: exportDraft() });
      }
    });
    const exit = () => notify("exitRequested", { draft: exportDraft() });
    on($("[data-exit]"), "click", () => { if (active()) exit(); });
    on(root, "keydown", event => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || !active() ||
          event.target.closest("input, textarea, select, [contenteditable], [role=textbox]")) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.repeat) return;
      if (selected) {
        selected = null;
        drawWiring();
        message("已取消选择，接线保持不变。");
      } else exit();
    });

    function pause() {
      if (paused || disposed) return;
      paused = true;
      selected = null;
      drawWiring();
      for (const button of all("button")) button.disabled = true;
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      listeners.abort();
      signal.removeEventListener("abort", dispose);
      root.remove();
      if (mounted.get(host) === controller) mounted.delete(host);
    }
    const controller = Object.freeze({ exportDraft, pause, dispose });
    drawWiring();
    drawTrials();
    signal.addEventListener("abort", dispose, { once: true });
    mounted.set(host, controller);
    host.append(root);
    ports.get("A").focus();
    return controller;
  }

  window.HuaxiaNandPreviewRunner = Object.freeze({ mount, config });
})();

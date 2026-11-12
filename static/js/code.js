/* 铸言（代码题）：用章节 SDK 读写存档，自己只负责把结果画出来。
 * 判分完全在服务端：前端只提交源码文本，不执行任何东西。 */
"use strict";
(() => {
  const CHAPTER = "xia-code";
  const $ = id => document.getElementById(id);
  const client = new window.HuaxiaChapterClient(CHAPTER);
  const expectedRows = $("rows-body").cloneNode(true);
  let busy = true;

  function setBusy(value) {
    busy = value;
    $("code-source").readOnly = value;
    $("run").disabled = value;
    $("submit").disabled = value;
  }

  function status(text, tone = "") {
    const box = $("status");
    box.textContent = text;
    box.className = `cd-status${tone ? " " + tone : ""}`;
  }

  function renderRows(rows) {
    const body = $("rows-body");
    body.replaceChildren();
    if (!Array.isArray(rows) || !rows.length) {
      body.append(...expectedRows.cloneNode(true).children);
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.className = row.pass ? "is-pass" : "is-fail";
      for (const value of [row.inputs[0], row.inputs[1], row.expected, row.actual, row.pass ? "✓" : "✗"]) {
        const td = document.createElement("td");
        td.textContent = String(value);
        tr.append(td);
      }
      body.append(tr);
    }
  }

  function apply(progress) {
    const code = (progress && progress.state && progress.state.code) || {};
    if (typeof code.source === "string" && code.source && $("code-source").value !== code.source) {
      $("code-source").value = code.source;
    }
    renderRows(code.rows);
    const result = progress && progress.result;
    if (result) {
      $("score").textContent = `已入库：${result.score} / ${result.maxScore}（可重做，取最高）`;
    } else if (code.passed) {
      $("score").textContent = "有已通过的验算，可以提交成绩。";
    } else {
      $("score").textContent = "";
    }
  }

  async function boot() {
    try {
      const data = await client.load();
      apply(data.progress);
      status("存档已读取。");
    } catch (error) {
      status(`存档读取失败：${error.message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (busy) return;
    setBusy(true);
    const source = $("code-source").value;
    status("正在验算…");
    try {
      const data = await client.dispatch("solve", {source});
      apply(data.progress);
      const rows = data.progress.state.code.rows;
      const passed = rows.length > 0 && rows.every(row => row.pass);
      status(passed ? "四行全对。" : "还有行对不上，请查看真值表。", passed ? "ok" : "");
    } catch (error) {
      status(error.message || "运行失败。", "error");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (busy) return;
    setBusy(true);
    status("正在提交…");
    try {
      const data = await client.dispatch("submit");
      apply(data.progress);
      status("成绩已入库。", "ok");
    } catch (error) {
      status(error.message || "提交失败。", "error");
    } finally {
      setBusy(false);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("run").addEventListener("click", run);
    $("submit").addEventListener("click", submit);
    $("code-source").addEventListener("keydown", event => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {event.preventDefault(); run();}
    });
    boot();
  });
})();

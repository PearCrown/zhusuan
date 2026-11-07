const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const read = file => fs.readFileSync(path.join(__dirname, '../static', file), 'utf8');
const fixtureId = 'nand-preview-fixture-test';
const good = [{ from: 'A', to: 'IN1' }, { from: 'B', to: 'IN2' }, { from: 'Q', to: 'Y' }];
const draft = (wires = good) => ({ version: 1, inputs: { A: 0, B: 0 }, wires: wires.map(wire => ({ ...wire })) });
const json = value => JSON.parse(JSON.stringify(value));

function setup(t) {
  const dom = new JSDOM(read('nand-preview.html'), {
    url: 'http://localhost/nand-preview.html', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  t.after(() => dom.window.close());
  const w = dom.window;
  w.eval(read('js/scene-host.js'));
  w.eval(read('js/nand-preview-runner.js'));
  const runner = w.HuaxiaNandPreviewRunner;
  const doc = w.document;
  const $ = selector => doc.querySelector(selector);
  const host = $('[data-runner-host]');
  host.hidden = false;
  const mount = (saved, callbacks, signal = new w.AbortController().signal) =>
    runner.mount(host, { instanceId: fixtureId, config: runner.config, draft: saved, signal }, callbacks);
  const key = (target, key, repeat = false) => target.dispatchEvent(new w.KeyboardEvent('keydown', {
    key, repeat, bubbles: true, cancelable: true,
  }));
  const port = name => $(`[data-port="${name}"]`);
  const connect = (from, to) => { port(from).click(); port(to).click(); };
  const bit = name => $(`[data-bit="${name}"]`).click();
  const run = () => $('[data-run]').click();
  const runFour = () => { run(); bit('B'); run(); bit('A'); run(); bit('B'); run(); };
  const column = field => [...doc.querySelectorAll(`[data-row] [data-${field}]`)].map(el => el.textContent);
  const active = () => doc.activeElement;
  return { w, $, runner, host, mount, key, port, connect, run, runFour, column, active };
}

test('correct swapped inputs give all four NAND values and emit one local completion only', t => {
  const ui = setup(t), completed = [], submit = [];
  const controller = ui.mount(null, {
    operationCompleted: value => completed.push(json(value)), submitRequested: value => submit.push(value),
  });
  ui.connect('B', 'IN1'); ui.connect('A', 'IN2'); ui.connect('Q', 'Y');
  ui.runFour();
  assert.deepEqual(ui.column('actual'), ['1', '1', '1', '0']);
  assert.deepEqual(ui.column('result'), Array(4).fill('一致'));
  assert.equal(ui.$('[data-tested]').textContent, '4 / 4 组已试');
  assert.equal(ui.$('[data-feedback-title]').textContent, '四组本地结果一致');
  ui.run();
  assert.deepEqual(completed, [{ draft: json(controller.exportDraft()) }]);
  assert.deepEqual(submit, []);
});

test('all four wrong-circuit trials report actual values, including accidental matches', t => {
  const ui = setup(t);
  ui.mount(draft([good[0], good[1], { from: 'A', to: 'Y' }]), {
    operationCompleted: () => assert.fail('bypass must not complete'),
  });
  ui.runFour();
  assert.deepEqual(ui.column('actual'), ['0', '0', '1', '1']);
  assert.deepEqual(ui.column('result'), Array(4).fill('需修正'));
  assert.match(ui.$('[data-feedback-detail]').textContent, /预期 Y=1，实测 Y=1.*Y 直接接了输入/);
  ui.port('Y').click(); ui.connect('Q', 'Y');
  assert.deepEqual(ui.column('actual'), Array(4).fill('—'));
  ui.run();
  assert.equal(ui.column('result')[2], '一致');
});

test('missing wiring shows no output; fanout error is distinct from illegal feedback and multiple drivers', t => {
  const ui = setup(t), controller = ui.mount(null);
  ui.run();
  assert.match(ui.$('[data-feedback-detail]').textContent, /实测 Y=无输出.*IN1 未接线.*IN2 未接线.*Y 未接线/);
  ui.connect('Q', 'IN1');
  assert.match(ui.$('[data-wiring]').textContent, /不能把门输出 Q 接回/);
  ui.port('Y').click();
  ui.connect('A', 'IN1');
  ui.connect('B', 'IN1');
  assert.match(ui.$('[data-wiring]').textContent, /IN1 已接 A/);
  ui.key(ui.port('IN1'), 'Escape');
  ui.connect('A', 'IN2');
  ui.run();
  assert.match(ui.$('[data-feedback-detail]').textContent, /两个门输入接了同一信号/);
  assert.equal(controller.exportDraft().wires.length, 3);
});

test('rejects malformed and illegal drafts before touching the active mount', t => {
  const ui = setup(t), live = ui.mount(draft());
  for (const saved of [
    {}, { ...draft(), version: 2 }, { ...draft(), score: 100 },
    { ...draft(), inputs: { A: '0', B: 0 } }, { ...draft(), inputs: { A: 0, B: false } },
    draft([good[0], good[0]]), draft([good[0], { from: 'B', to: 'IN1' }]),
    draft([{ from: 'X', to: 'Y' }]), draft([{ from: 'A', to: 'Z' }]),
    draft([{ from: 'Q', to: 'IN1' }]), draft([{ from: 'IN1', to: 'Y' }]),
    draft(new Array(1)), draft([...good, good[0]]),
  ]) {
    assert.throws(() => ui.mount(saved), { code: 'INVALID_NAND_DRAFT' });
  }
  assert.deepEqual(json(live.exportDraft()), draft());
  assert.equal(ui.host.querySelectorAll('.nand-runner').length, 1);
});

test('JSON drafts round trip without aliases or transient trial/selection state', t => {
  const ui = setup(t), saved = draft();
  const first = ui.mount(saved);
  saved.inputs.A = 1; saved.wires[0].from = 'B';
  ui.run(); ui.port('Q').click();
  const exported = first.exportDraft();
  assert.deepEqual(json(exported), draft());
  first.dispose();
  const next = ui.mount(json(exported));
  exported.inputs.B = 1; exported.wires.pop();
  assert.deepEqual(json(next.exportDraft()), draft());
  assert.equal(ui.$('[data-tested]').textContent, '0 / 4 组已试');
  assert.equal(ui.port('Q').getAttribute('aria-pressed'), 'false');
});

test('pause, duplicate mount, abort and repeated disposal do not leak controls or callbacks', t => {
  const ui = setup(t), events = [], firstSignal = new ui.w.AbortController();
  const foreign = ui.host.appendChild(ui.w.document.createElement('p'));
  const first = ui.mount(null, { draftChanged: () => events.push('old') }, firstSignal.signal);
  const oldBit = ui.$('[data-bit="A"]'), oldRoot = oldBit.closest('.nand-runner');
  first.pause(); first.pause(); oldBit.click();
  assert.equal(oldBit.disabled, true);
  assert.equal(first.exportDraft().inputs.A, 0);
  const nextSignal = new ui.w.AbortController();
  const next = ui.mount(null, { draftChanged: () => events.push('new') }, nextSignal.signal);
  assert.equal(oldRoot.isConnected, false);
  first.dispose(); firstSignal.abort();
  oldBit.dispatchEvent(new ui.w.MouseEvent('click', { bubbles: true }));
  ui.$('[data-bit="A"]').click();
  assert.deepEqual(events, ['new']);
  nextSignal.abort(); next.dispose(); next.dispose();
  assert.deepEqual([...ui.host.children], [foreign]);
  assert.throws(() => next.exportDraft(), { code: 'NAND_RUNNER_CLOSED' });
  assert.throws(() => ui.mount(null, {}, nextSignal.signal), { code: 'NAND_MOUNT_ABORTED' });
});

test('native buttons form the focus path; Escape cancels before exit and ignores editor input', t => {
  const ui = setup(t), exits = [];
  ui.mount(null, { exitRequested: value => exits.push(value) });
  assert.equal(ui.active(), ui.port('A'));
  assert.deepEqual([...ui.host.querySelectorAll('button')].map(button =>
    button.dataset.port ?? button.dataset.bit ?? (button.hasAttribute('data-run') ? 'run' : 'exit')),
  ['exit', 'A', 'B', 'IN1', 'IN2', 'Q', 'Y', 'A', 'B', 'run']);
  const input = ui.host.querySelector('.nand-runner').appendChild(ui.w.document.createElement('input'));
  assert.equal(ui.key(input, 'Escape'), true);
  assert.equal(ui.key(input, ' '), true);
  ui.port('A').click();
  assert.equal(ui.key(ui.port('A'), 'Escape'), false);
  assert.equal(ui.port('A').getAttribute('aria-pressed'), 'false');
  ui.key(ui.port('A'), 'Escape', true);
  assert.equal(exits.length, 0);
  ui.key(ui.port('A'), 'Escape');
  assert.equal(exits.length, 1);
  assert.deepEqual(json(exits[0].draft), draft([]));
});

test('actual SceneHost page exits, resumes draft, and starts from blank without storage or API', async t => {
  const ui = setup(t);
  ui.w.fetch = () => assert.fail('no API traffic');
  ui.w.eval(read('js/nand-preview.js'));
  ui.$('[data-start]').click();
  ui.connect('A', 'IN1');
  ui.key(ui.port('A'), 'Escape');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.$('[data-intro]').hidden, false);
  assert.equal(ui.active(), ui.$('[data-start]'));
  assert.equal(ui.$('[data-start]').textContent, '继续接线');
  ui.$('[data-start]').click();
  assert.equal(ui.$('[data-count]').textContent, '1 / 3 条连接');
  ui.w.dispatchEvent(new ui.w.Event('pagehide'));
  assert.equal(ui.$('.nand-runner'), null);
  assert.equal(ui.$('[data-intro]').hidden, false);
  ui.$('[data-reset]').click();
  assert.equal(ui.$('[data-count]').textContent, '0 / 3 条连接');
  assert.equal(ui.w.localStorage.length, 0);
  assert.equal(ui.w.sessionStorage.length, 0);
});

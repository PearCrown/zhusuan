const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const source = fs.readFileSync(path.join(__dirname, '../static/js/scene-host.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(t, overrides = {}) {
  const dom = new JSDOM('<div id="runner"></div>', {runScripts: 'outside-only', url: 'http://localhost/game/'});
  const w = dom.window;
  w.eval(source);
  const locks = new w.HuaxiaInputLocks();
  const events = [];
  let callbacks, signal;
  const controller = {
    exportDraft: () => ({nodes: [1]}),
    pause: () => events.push('pause'), dispose: () => events.push('dispose'),
  };
  const runner = {mount: (host, options, cb) => { events.push('mount'); callbacks = cb; signal = options.signal; return controller; }};
  const options = {
    context: {chapterId: 'demo', levelSessionId: 'level-1', sceneId: 'gate', sessionEpoch: 'session-1'},
    scene: {walkRange: [0.1, 0.9], spawn: {x: 0.2, facing: 'right', cameraX: 0}}, locks,
    readProgress: async () => {events.push('read'); return {chapterId: 'demo', revision: 7};},
    restoreScene: async args => {events.push(['restore', args]);},
    clearInput: () => events.push('clear'), callbacks: {submitRequested: value => events.push(['submit', value])},
    ...overrides,
  };
  const scene = new w.HuaxiaSceneHost(options);
  t.after(() => {try {scene.dispose();} finally {w.close();}});
  const input = {instanceId: 'inst-1', runner, host: w.document.getElementById('runner'), snapshot: {x: 0.6, facing: 'left', cameraX: 0.4}};
  return {w, locks, scene, input, options, events, controller, cb: () => callbacks, signal: () => signal,
    begin: changes => scene.beginTask({...input, ...changes})};
}
test('only the acquired lock token releases its owner; task return preserves dialogue lock', async t => {
  const a = setup(t);
  const dialogue = a.locks.acquire('dialogue');
  assert.equal(a.locks.release({owner: 'dialogue'}), false);
  const token = a.begin();
  assert.equal(a.locks.size, 2);
  await a.scene.returnToScene(token);
  assert.equal(a.locks.size, 1);
  assert.equal(a.locks.locked, true);
  assert.equal(a.locks.release(dialogue), true);
  assert.equal(a.locks.release(dialogue), false);
});
test('return reads latest progress before scene/NPC restoration and unlocks only afterwards', async t => {
  const a = setup(t);
  let finish;
  a.scene.restoreScene = args => new Promise(resolve => {finish = () => resolve(args);});
  const token = a.begin();
  const draft = a.scene.exportDraft(token);
  assert.deepEqual(draft, {nodes: [1]});
  const promise = a.scene.returnToScene(token);
  await tick();
  assert.equal(a.locks.locked, true);
  assert.equal(a.signal().aborted, true);
  finish();
  const result = await promise;
  assert.equal(result.revision, 7);
  assert.equal(result.snapshot.x, 0.6);
  assert.equal(result.snapshot.facing, 'left');
  assert.equal(a.locks.locked, false);
  assert.ok(a.events.indexOf('read') > a.events.indexOf('dispose'));
  assert.equal(a.events.at(-1), 'clear');
});
test('duplicate enters and returns mount and restore exactly once; next instance requires finished return', async t => {
  const a = setup(t);
  const token = a.begin();
  assert.equal(a.begin(), token);
  assert.throws(() => a.begin({instanceId: 'inst-2'}), {code: 'HOST_BUSY'});
  const first = a.scene.returnToScene(token);
  assert.equal(a.scene.returnToScene(token), first);
  const result = await first;
  assert.equal(await a.scene.returnToScene(token), result);
  assert.equal(a.events.filter(e => e === 'mount').length, 1);
  assert.equal(a.events.filter(e => Array.isArray(e) && e[0] === 'restore').length, 1);
  a.scene.finishReturn(token);
  assert.throws(() => a.scene.returnToScene(token), {code: 'RETURN_CONTEXT_EXPIRED'});
  a.begin({instanceId: 'inst-2'});
});
test('invalid position falls back to safe spawn and snapshot is isolated from caller changes', async t => {
  const a = setup(t);
  const snapshot = {x: 2, facing: 'left', cameraX: 0.4};
  const token = a.begin({snapshot}); snapshot.x = 0.5;
  const result = await a.scene.returnToScene(token);
  assert.equal(result.snapshot.x, 0.2);
  assert.equal(result.snapshot.facing, 'right');
});
test('callbacks carry instance/generation, never save or grade; stale callbacks after return are ignored', async t => {
  const a = setup(t), token = a.begin();
  const old = a.cb();
  old.submitRequested({answer: 'draft'});
  const report = a.events.find(e => Array.isArray(e) && e[0] === 'submit')[1];
  assert.equal(report.instanceId, 'inst-1'); assert.equal(typeof report.generation, 'number');
  await a.scene.returnToScene(token);
  old.submitRequested({pass: true, score: 100});
  assert.equal(a.events.filter(e => Array.isArray(e) && e[0] === 'submit').length, 1);
});
test('failed read preserves task lock, rejects late callbacks, and supports explicit retry', async t => {
  const a = setup(t), token = a.begin();
  a.scene.readProgress = async () => {throw Error('offline');};
  await assert.rejects(a.scene.returnToScene(token), /offline/);
  assert.equal(a.locks.locked, true);
  a.cb().submitRequested({});
  assert.equal(a.events.some(e => Array.isArray(e) && e[0] === 'submit'), false);
  a.scene.readProgress = a.options.readProgress;
  await a.scene.returnToScene(token);
  assert.equal(a.events.filter(e => e === 'dispose').length, 1);
});
test('restore failure stays locked; no progress or permanent result is changed by host', async t => {
  const a = setup(t), token = a.begin();
  a.scene.restoreScene = async () => {throw Error('asset unavailable');};
  await assert.rejects(a.scene.returnToScene(token), /asset unavailable/);
  assert.equal(a.locks.locked, true);
  a.scene.invalidate(); assert.equal(a.locks.locked, false);
});
test('timeout rejects uncooperative provider; late response never restores scene', async t => {
  const a = setup(t, {timeoutMs: 10}); let resolve, signal;
  a.scene.readProgress = args => {signal = args.signal; return new Promise(r => {resolve = r;});};
  const token = a.begin();
  await assert.rejects(a.scene.returnToScene(token), {code: 'RETURN_TIMEOUT'});
  assert.equal(signal.aborted, true); assert.equal(a.locks.locked, true);
  resolve({chapterId: 'demo', revision: 9}); await tick();
  assert.equal(a.events.some(e => Array.isArray(e) && e[0] === 'restore'), false);
});
test('account/scene invalidation during read cancels return and rejects old token', async t => {
  const a = setup(t); let resolve;
  a.scene.readProgress = () => new Promise(r => {resolve = r;});
  const token = a.begin(), pending = a.scene.returnToScene(token);
  await tick(); a.scene.invalidate();
  await assert.rejects(pending, {code: 'RETURN_CONTEXT_EXPIRED'});
  resolve({chapterId: 'demo', revision: 9}); await tick();
  assert.equal(a.events.some(e => Array.isArray(e) && e[0] === 'restore'), false);
  assert.throws(() => a.scene.returnToScene(token), {code: 'RETURN_CONTEXT_EXPIRED'});
  assert.equal(a.locks.locked, false);
});
test('return provider receives abort on invalidation during restore; no late unlock affects other owners', async t => {
  const a = setup(t); let resolve, signal;
  a.scene.restoreScene = args => {signal = args.signal; return new Promise(r => {resolve = r;});};
  const token = a.begin(), pending = a.scene.returnToScene(token); await tick();
  a.scene.invalidate();
  const dialogue = a.locks.acquire('new-dialogue');
  await assert.rejects(pending, {code: 'RETURN_CONTEXT_EXPIRED'});
  assert.equal(signal.aborted, true); resolve(); await tick();
  assert.equal(a.locks.locked, true); a.locks.release(dialogue);
});
test('page hide invalidates mounted runner; repeated dispose removes listeners and is safe', t => {
  const a = setup(t), token = a.begin();
  a.w.dispatchEvent(new a.w.Event('pagehide'));
  assert.equal(a.signal().aborted, true); assert.equal(a.locks.locked, false);
  assert.throws(() => a.scene.exportDraft(token), {code: 'RETURN_CONTEXT_EXPIRED'});
  a.scene.dispose(); a.scene.dispose();
  assert.equal(a.events.filter(e => e === 'dispose').length, 1);
  assert.throws(() => a.begin(), {code: 'HOST_DISPOSED'});
});
test('mount failure and malformed runner release only their own lock', t => {
  const a = setup(t), external = a.locks.acquire('dialogue');
  assert.throws(() => a.begin({runner: {mount: () => {throw Error('bad mount');}}}), /bad mount/);
  assert.equal(a.locks.size, 1);
  assert.throws(() => a.begin({runner: {mount: () => ({})}}), {code: 'INVALID_RUNNER'});
  assert.equal(a.locks.size, 1); a.locks.release(external);
});
test('invalid config, snapshot, token and server progress are rejected', async t => {
  const a = setup(t);
  assert.throws(() => new a.w.HuaxiaSceneHost({...a.options, timeoutMs: 0}), {code: 'INVALID_HOST_CONFIG'});
  assert.throws(() => a.begin({snapshot: {x: NaN, facing: 'right', cameraX: 0}}), {code: 'INVALID_TASK'});
  const token = a.begin();
  assert.throws(() => a.scene.returnToScene({}), {code: 'RETURN_CONTEXT_EXPIRED'});
  assert.throws(() => a.scene.finishReturn(token), {code: 'RETURN_NOT_RESTORED'});
  for (const progress of [{chapterId: 'other', revision: 7}, {chapterId: 'demo', revision: -1}, {chapterId: 'demo', revision: 1.5}]) {
    a.scene.readProgress = async () => progress;
    await assert.rejects(a.scene.returnToScene(token), {code: 'INVALID_PROGRESS'});
    assert.equal(a.locks.locked, true);
  }
});
test('reentrant invalidation during mount disposes returned controller and ignores stale callbacks', t => {
  const a = setup(t);
  a.scene.callbacks.exitRequested = () => a.scene.invalidate();
  const runner = {mount: (host, opts, cb) => {cb.exitRequested(); return a.controller;}};
  assert.throws(() => a.begin({runner}), {code: 'RETURN_CONTEXT_EXPIRED'});
  assert.equal(a.locks.locked, false);
  assert.equal(a.events.filter(e => e === 'dispose').length, 1);
});
test('throwing runner pause still disposes and allows explicit return retry without unhandled abort', async t => {
  const a = setup(t), token = a.begin();
  a.controller.pause = () => {throw Error('pause failed');};
  await assert.rejects(a.scene.returnToScene(token), /pause failed/);
  assert.equal(a.events.filter(e => e === 'dispose').length, 1);
  assert.equal(a.locks.locked, true);
  await a.scene.returnToScene(token);
  assert.equal(a.locks.locked, false);
});
test('invalid asynchronous mounts are consumed and their late controller is disposed', async t => {
  const a = setup(t);
  assert.throws(() => a.begin({runner: {mount: async () => a.controller}}), {code: 'INVALID_RUNNER'});
  await tick();
  assert.equal(a.events.filter(e => e === 'dispose').length, 1);
  assert.equal(a.locks.locked, false);
  assert.throws(() => a.begin({runner: {mount: async () => {throw Error('load failed');}}}), {code: 'INVALID_RUNNER'});
  await tick();
});
test('visibility hiding clears runtime and SDK/renderer context contains only the v1 whitelist', t => {
  const a = setup(t);
  a.begin();
  Object.defineProperty(a.w.document, 'hidden', {configurable: true, value: true});
  a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));
  assert.equal(a.locks.locked, false); assert.equal(a.signal().aborted, true);
  const scene = new a.w.HuaxiaSceneHost({...a.options, context: {...a.options.context, ignored: 'extra'}});
  try { assert.equal(Object.hasOwn(scene.context, 'ignored'), false); } finally { scene.dispose(); }
});

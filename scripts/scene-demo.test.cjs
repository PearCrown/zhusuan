const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.join(__dirname, '..', 'static');
const source = name => fs.readFileSync(path.join(root, 'js', name + '.js'), 'utf8');
const html = fs.readFileSync(path.join(root, '../templates/game.html'), 'utf8').replace(/\{%.*?%\}/g, '');
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(fn) {for (let i = 0; i < 40; i++) {if (fn()) return; await tick();} assert.ok(fn(), 'UI did not reach expected state');}
const clone = value => JSON.parse(JSON.stringify(value));
function visibility(a, hidden) {Object.defineProperty(a.w.document,'hidden',{configurable:true,value:hidden});a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));}
async function setup(t, ui = true, configure = () => {}) {
  const dom = new JSDOM(html, {url: 'http://localhost/static/scene-demo.html', runScripts: 'outside-only', pretendToBeVisual: true});
  const w = dom.window;
  if (w.document.readyState !== 'complete') await new Promise(resolve => w.addEventListener('load', resolve, {once: true}));
  t.after(() => w.close());
  let callback, time = 0;
  w.requestAnimationFrame = cb => {callback = cb; return 1;}; w.cancelAnimationFrame = () => {callback = null;};
  let progress = {chapterId: 'sample-counting', schemaVersion: 1, revision: 0, questionBank: {bankId: 'sample-arithmetic', version: '1'},
    state: {story: {scene: 'gate', quest: 'not_started', talkedToNpc: false}, practice: {answers: [null, null]}}, result: null};
  const questions = [{questionId: 'one', prompt: '2 + 3 = ?'}, {questionId: 'two', prompt: '3 + 4 = ?'}];
  const calls = []; let override;
  w.confirm = () => true;
  w.fetch = async (url, options = {}) => {
    const payload = options.body && JSON.parse(options.body); calls.push({url, options, payload});
    if (override) {const result = override(url, options); if (result) return result;}
    let data;
    if (url === '/auth/csrf') data = {csrfToken: 'fixture-csrf'};
    else if (url === '/game/api/chapters') data = {chapters: [{chapterId: 'sample-counting', title: '算坊初试'}]};
    else if (url.endsWith('/progress')) data = {progress: clone(progress), saveContext: 'fixture-context', questions};
    else {
      assert.equal(options.method, 'POST'); assert.equal(payload.revision, progress.revision);
      assert.equal(payload.saveContext, 'fixture-context');
      const fields = {move: ['scene'], talk: [], accept: [], answer: ['questionIndex', 'answer'], submit: []};
      assert.deepEqual(Object.keys(payload).sort(), ['action', 'revision', 'saveContext', ...fields[payload.action]].sort());
      if (payload.action === 'move') progress.state.story.scene = payload.scene;
      if (payload.action === 'talk') progress.state.story.talkedToNpc = true;
      if (payload.action === 'accept') progress.state.story.quest = 'accepted';
      if (payload.action === 'answer') progress.state.practice.answers[payload.questionIndex] = payload.answer;
      if (payload.action === 'submit') {progress.state.story.quest = 'submitted'; progress.result = {score: 100, maxScore: 100};}
      progress.revision++; data = {progress: clone(progress), saveContext: 'fixture-context'};
    }
    return {ok: true, json: async () => ({ok: true, data})};
  };
  for (const name of ['chapter-sdk', 'scene-host', 'scene-demo-data', 'scene-model', 'scene-view']) w.eval(source(name));
  configure(w);
  const id = name => w.document.getElementById(name);
  const chapter = () => w.document.querySelector('[data-chapter-id="sample-counting"]');
  const level = () => w.document.querySelector('[data-level-id="sample-gate"]');
  const a = {w, id, chapter, level, calls, progress: () => progress, override: fn => {override = fn;}, frame: () => {time += 100; callback?.(time);},
    x: () => Number.parseFloat(id('viewport').querySelector('.scene-player').style.left),
    key: (type, key) => id('viewport').dispatchEvent(new w.KeyboardEvent(type, {key, bubbles: true, cancelable:true})),
    interact() {this.key('keydown','e'); this.key('keyup','e');},
    async ready() {w.dispatchEvent(new w.Event('pageshow')); await until(() => !id('chapters').hidden);},
    async enter() {await this.ready(); chapter().click(); level().click(); await until(() => !id('scene').hidden && !id('reload').disabled);},
    async walk(label, direction = 'ArrowRight') {
      this.key('keydown', direction);
      for (let i = 0; i < 70 && !id('nearby').textContent.includes(label); i++) this.frame();
      this.key('keyup', direction); assert.match(id('nearby').textContent, new RegExp(label));
    },
    async accept() {await this.walk('守门人'); this.interact(); await until(() => !id('dialogue').hidden && !id('reload').disabled); id('accept').click(); await until(() => id('dialogue').hidden && !id('reload').disabled);},
    async task() {await this.accept(); await this.walk('算坊任务点'); this.interact(); await until(() => !id('runner').hidden && !id('reload').disabled);},
  };
  if (ui) w.eval(source('scene-demo'));
  return a;
}
test('art dimensions and viewport widths do not change movement, interaction range or content IDs', async t => {
  const a = await setup(t, false), data = a.w.HuaxiaSceneDemo;
  const locks = new a.w.HuaxiaInputLocks();
  const changed = {...data, art: {...data.art, playerWidth: 120, playerHeight: 160, footLine: 0.7}};
  const one = new a.w.HuaxiaSceneModel(data, locks), two = new a.w.HuaxiaSceneModel(changed, locks);
  for (let i = 0; i < 8; i++) {one.move(1, 0.1); two.move(1, 0.1);}
  assert.equal(one.x, two.x); assert.equal(one.nearby().id, two.nearby().id);
  const view = new a.w.HuaxiaSceneView(a.id('viewport'), changed); view.draw(two);
  assert.equal(a.id('viewport').querySelector('.scene-player').style.width, '120px');
  assert.equal(a.id('viewport').querySelector('.scene-player').style.left, `${two.x * 100}%`);
});
test('movement clamps elapsed time and world bounds; locked movement and invalid data are rejected', async t => {
  const a = await setup(t, false), locks = new a.w.HuaxiaInputLocks(), model = new a.w.HuaxiaSceneModel(a.w.HuaxiaSceneDemo, locks);
  model.move(1, 999); assert.ok(model.x < 0.15);
  const token = locks.acquire('dialogue'), saved = model.x; model.move(1, 0.1); assert.equal(model.x, saved); locks.release(token);
  for (let i = 0; i < 200; i++) model.move(-1, 0.1); assert.equal(model.x, 0.06);
  assert.throws(() => model.move(2, 1), /INVALID_MOVEMENT/);
  assert.throws(() => new a.w.HuaxiaSceneModel({...a.w.HuaxiaSceneDemo, entities: [{id: 'bad', kind: 'npc', x: NaN, range: 0.1}]}, locks), /INVALID_SCENE/);
});
test('two map levels use a fresh server read on scene entry; distant interactions cannot submit', async t => {
  const a = await setup(t); await a.enter();
  assert.equal(a.calls.filter(c => c.url.endsWith('/progress')).length, 2);
  assert.equal(a.id('interact'), null);
  a.interact(); await tick(); assert.equal(a.calls.some(c => c.payload), false);
  assert.ok(a.id('viewport').querySelector('[data-entity-id="workshop"]'));
});
const chapterListing = chapters => ({ok: true, json: async () => ({ok: true, data: {chapters}})});
function mapKey(a, key) {
  const event = new a.w.KeyboardEvent('keydown', {key, bubbles: true, cancelable: true});
  a.w.document.activeElement.dispatchEvent(event);
  a.w.document.activeElement.dispatchEvent(new a.w.KeyboardEvent('keyup', {key, bubbles: true}));
  return event.defaultPrevented;
}

test('map renders registered chapters and configured levels in stable order and skips unavailable nodes', async t => {
  const a = await setup(t, true, w => {
    const data = w.HuaxiaSceneDemo;
    w.HuaxiaSceneDemo = {...data, mapLevels: [
      ...data.mapLevels,
      {levelId: 'fixture-second-level', sceneId: 'fixture-unwired', levelTitle: '测试关 · 未接入', seal: '测'},
    ]};
  });
  const sample = {chapterId: 'sample-counting', title: '服务端算坊标题'};
  const fixture = {chapterId: 'fixture-second-chapter', title: '测试章 · 未接入'};
  let reversed = false;
  a.override(url => url === '/game/api/chapters' ? chapterListing(reversed ? [fixture, sample] : [sample, fixture]) : null);
  await a.ready();
  const chapterIds = () => [...a.id('chapter-nodes').children].map(node => node.dataset.chapterId);
  assert.deepEqual(chapterIds(), ['fixture-second-chapter', 'sample-counting']);
  assert.match(a.chapter().textContent, /服务端算坊标题/);
  assert.equal(a.w.document.activeElement, a.chapter());
  const unavailableChapter = a.id('chapter-nodes').firstElementChild;
  a.frame();
  assert.equal(unavailableChapter.disabled, true);
  unavailableChapter.click();
  assert.equal(a.id('locations').hidden, true);
  const reads = a.calls.length;
  mapKey(a, 'Enter');
  assert.equal(a.w.document.activeElement, a.level());
  const levels = [...a.id('level-nodes').children];
  assert.deepEqual(levels.map(node => node.dataset.levelId), ['sample-gate', 'fixture-second-level']);
  assert.match(levels[1].textContent, /测试关.*场景暂不可用/);
  assert.equal(levels[1].disabled, true);
  levels[1].click();
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.calls.length, reads);
  mapKey(a, 'ArrowDown');
  assert.equal(a.w.document.activeElement, a.id('back-chapters'));
  mapKey(a, 'ArrowUp');
  assert.equal(a.w.document.activeElement, a.level());
  mapKey(a, 'Escape');
  assert.equal(a.w.document.activeElement, a.chapter());
  a.chapter().click();
  a.level().click();
  await until(() => !a.id('scene').hidden && !a.id('reload').disabled);
  assert.equal(a.w.document.activeElement, a.id('viewport'));
  mapKey(a, 'Escape');
  a.id('back-map').focus();
  mapKey(a, 'Enter');
  assert.equal(a.id('locations').hidden, false);
  assert.equal(a.w.document.activeElement, a.level());
  a.id('back-chapters').click();
  assert.equal(a.w.document.activeElement, a.chapter());
  reversed = true;
  a.id('open-menu').focus();
  assert.equal(mapKey(a, 'Enter'), false); // Native Enter can activate the menu, not a map node.
  a.id('open-menu').click();
  a.id('reload').click();
  await until(() => !a.id('chapters').hidden && !a.id('reload').disabled);
  assert.deepEqual(chapterIds(), ['fixture-second-chapter', 'sample-counting']);
  assert.equal(a.calls.filter(call => call.payload).length, 0);
});

test('a scene in the local manifest cannot open when its chapter is missing from the registry response', async t => {
  const a = await setup(t);
  a.override(url => url === '/game/api/chapters' ? chapterListing([
    {chapterId: 'fixture-second-chapter', title: '测试章 · 未接入'},
  ]) : null);
  await a.ready();
  assert.equal(a.chapter(), null);
  assert.equal(a.level(), null);
  assert.equal(a.id('chapter-nodes').firstElementChild.disabled, true);
  assert.equal(a.w.document.activeElement, a.id('open-menu'));
  assert.match(a.id('status').textContent, /暂无可进入/);
  assert.deepEqual(a.calls.map(call => call.url), ['/game/api/chapters']);
});

test('NPC, task adapter, answer saves, same-position return and exit consume server-confirmed state', async t => {
  const a = await setup(t); await a.enter(); await a.task(); const before = a.x();
  const inputs = a.id('runner-content').querySelectorAll('input');
  for (const [index, answer] of [5, 7].entries()) {
    inputs[index].value = String(answer); inputs[index].dispatchEvent(new a.w.Event('input', {bubbles: true}));
    inputs[index].form.dispatchEvent(new a.w.Event('submit', {bubbles: true, cancelable: true}));
    await until(() => !a.id('reload').disabled);
    assert.equal(a.w.document.activeElement, inputs[index]);
  }
  assert.deepEqual(a.progress().state.practice.answers, [5, 7]);
  a.id('exit-runner').click(); await until(() => a.id('runner').hidden && !a.id('reload').disabled);
  assert.equal(a.x(), before);
  await a.walk('东侧出口'); a.interact(); await tick();
  assert.match(a.id('status').textContent, /先回守门人/); assert.equal(a.progress().result, null);
  await a.walk('守门人', 'ArrowLeft'); a.interact(); await until(() => !a.id('dialogue').hidden && !a.id('reload').disabled);
  a.id('submit').click(); await until(() => Boolean(a.progress().result) && !a.id('reload').disabled);
  await a.walk('东侧出口'); a.interact(); await until(() => !a.id('locations').hidden);
  assert.equal(a.calls.filter(c => c.payload?.action === 'submit').length, 1);
  assert.equal(a.w.localStorage.length, 0); assert.equal(a.w.sessionStorage.length, 0);
});
test('dialogue and task lock movement; releasing input does not resume stale keys', async t => {
  const a = await setup(t); await a.enter(); await a.walk('守门人');
  a.interact(); await until(() => !a.id('dialogue').hidden && !a.id('reload').disabled);
  assert.equal(a.w.document.activeElement, a.id('accept'));
  const x = a.x(); a.key('keydown', 'ArrowRight'); for (let i = 0; i < 5; i++) a.frame(); assert.equal(a.x(), x);
  a.id('close-dialogue').click(); a.key('keyup', 'ArrowLeft'); a.frame(); assert.equal(a.x(), x);
});
test('unsaved runner work requires explicit discard; input fields never move the character', async t => {
  const a = await setup(t); await a.enter(); await a.task();
  const input = a.id('runner-content').querySelector('input'); input.value = '8'; input.dispatchEvent(new a.w.Event('input'));
  input.dispatchEvent(new a.w.KeyboardEvent('keydown', {key: 'd', bubbles: true})); a.frame(); const x = a.x(); a.frame(); assert.equal(a.x(), x);
  a.id('exit-runner').click(); await tick(); assert.equal(a.id('save-choice').hidden, false); a.id('stay-in-task').click(); assert.equal(a.id('runner').hidden, false);
  a.id('exit-runner').click(); a.id('discard-and-return').click(); await until(() => a.id('runner').hidden);
  assert.equal(a.progress().state.practice.answers[0], null);
});
test('failed return keeps scene locked and explicit retry re-reads without replaying writes', async t => {
  const a = await setup(t); await a.enter(); await a.task();
  a.override(url => url.endsWith('/progress') ? Promise.reject(Error('offline')) : null);
  a.id('exit-runner').click(); await until(() => !a.id('retry-return').hidden && !a.id('reload').disabled);
  const x = a.x(); a.key('keydown', 'ArrowRight'); a.frame(); assert.equal(a.x(), x);
  const writes = a.calls.filter(c => c.payload).length;
  const camera = a.id('viewport').querySelector('.scene-world').style.transform;
  a.progress().revision++;
  a.progress().state.story.quest = 'submitted';
  a.progress().result = {score: 62, maxScore: 100};
  a.override(null); a.id('retry-return').click(); await until(() => a.id('runner').hidden && !a.id('reload').disabled);
  assert.equal(a.x(), x);
  assert.equal(a.id('viewport').querySelector('.scene-world').style.transform, camera);
  assert.equal(a.w.document.activeElement, a.id('viewport'));
  assert.match(a.id('quest-state').textContent, /62 \/ 100/);
  assert.equal(a.calls.filter(c => c.payload).length, writes);
});
test('ordinary return rejects a rotated save context before rendering the new result in the old scene', async t => {
  const a = await setup(t); await a.enter(); await a.task();
  const hud = a.id('quest-state'), rendered = [];
  const observer = new a.w.MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) rendered.push(node.textContent);
  });
  observer.observe(hud, {childList: true});
  t.after(() => observer.disconnect());
  const changed = clone(a.progress());
  changed.revision++;
  changed.state.story.quest = 'submitted';
  changed.result = {score: 67, maxScore: 100};
  const writes = a.calls.filter(c => c.payload).length;
  a.override(url => url.endsWith('/progress') ? {ok: true, json: async () => ({ok: true, data: {
    saveContext: 'other-return-context', progress: changed, questions: [{prompt: '新题一'}, {prompt: '新题二'}],
  }})} : null);
  a.id('exit-runner').click();
  await until(() => a.id('runner').hidden && !a.id('reload').disabled);
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.id('viewport').childElementCount, 0);
  assert.equal(a.id('runner-content').childElementCount, 0);
  assert.equal(hud.textContent, '');
  assert.ok(rendered.every(text => !text.includes('67')));
  assert.match(a.id('status').textContent, /会话或题目已变化/);
  assert.equal(a.w.document.activeElement, a.id('open-menu'));
  assert.equal(a.calls.filter(c => c.payload).length, writes);
  a.override(null);
  a.id('open-menu').click(); a.id('reload').click();
  await until(() => !a.id('chapters').hidden && !a.id('reload').disabled);
  assert.equal(a.w.document.activeElement, a.chapter());
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.calls.filter(c => c.payload).length, writes);
});

test('failed return offers a keyboard focus path to the map and recovery if the read still fails', async t => {
  for (const mapReadFails of [false, true]) {
    const a = await setup(t); await a.enter(); await a.task();
    const writes = a.calls.filter(c => c.payload).length;
    const offline = url => url.endsWith('/progress') ? Promise.reject(Error('offline')) : null;
    a.override(offline);
    a.id('exit-runner').click();
    await until(() => !a.id('retry-return').hidden && !a.id('reload').disabled);
    const retry = a.id('retry-return'), map = a.id('return-to-map');
    assert.ok(map && !map.hidden && !map.disabled);
    assert.equal(a.w.document.activeElement, retry);
    const key = new a.w.KeyboardEvent('keydown', {key: 'Tab', shiftKey: true, bubbles: true, cancelable: true});
    retry.dispatchEvent(key);
    assert.equal(key.defaultPrevented, true);
    assert.equal(a.w.document.activeElement, map);
    if (!mapReadFails) a.override(null);
    // JSDOM does not synthesize a native button click from Enter.
    map.click();
    await until(() => a.id('scene').hidden && !a.id('reload').disabled);
    assert.equal(a.id('runner-content').childElementCount, 0);
    if (mapReadFails) {
      assert.match(a.id('status').textContent, /暂时无法读取地图.*菜单/);
      assert.equal(a.w.document.activeElement, a.id('open-menu'));
      a.override(null);
      a.id('open-menu').click(); a.id('reload').click();
    }
    await until(() => !a.id('chapters').hidden && !a.id('reload').disabled);
    assert.equal(a.w.document.activeElement, a.chapter());
    assert.equal(a.id('runner').hidden, true);
    assert.equal(a.calls.filter(c => c.payload).length, writes);
  }
});

test('lost mutation response clears old UI and never auto-replays; stale listing cannot reopen hidden data', async t => {
  const a = await setup(t); await a.enter(); await a.walk('守门人');
  a.override((url, options) => options.method === 'POST' ? Promise.reject(Error('lost')) : null);
  a.interact(); await until(() => a.id('scene').hidden && !a.id('reload').disabled);
  assert.equal(a.calls.filter(c => c.options.method === 'POST').length, 1);
  assert.match(a.id('status').textContent, /尚未确认/);
  let release; a.override(url => url === '/game/api/chapters' ? new Promise(resolve => {release = resolve;}) : null);
  a.id('reload').click(); await tick(); a.w.dispatchEvent(new a.w.Event('pagehide'));
  release({ok: true, json: async () => ({ok: true, data: {chapters: [{chapterId: 'sample-counting', title: 'old'}]}})});
  await tick(); await tick(); assert.equal(a.id('chapters').hidden, true);
});
test('authentication expiry removes previous scene, answers and progress', async t => {
  const a = await setup(t); await a.enter(); await a.task();
  a.override(() => ({ok: false, json: async () => ({ok: false, error: {code: 'authentication_required'}})}));
  a.id('reload').click(); await until(() => a.id('scene').hidden && !a.id('reload').disabled);
  assert.equal(a.id('runner-content').childElementCount, 0);
  assert.equal(a.id('quest-state').textContent, ''); assert.match(a.id('status').textContent, /登录已失效/);
});
test('duplicate answer requests send once; hiding cancels late response and clears all old work', async t => {
  const a = await setup(t); await a.enter(); await a.task();
  let release; a.override((url, options) => options.method === 'POST' ? new Promise(resolve => {release = resolve;}) : null);
  const input = a.id('runner-content').querySelector('input'); input.value = '5';
  const before = a.calls.filter(c => c.options.method === 'POST').length;
  input.form.dispatchEvent(new a.w.Event('submit', {cancelable: true})); await tick();
  input.form.dispatchEvent(new a.w.Event('submit', {cancelable: true}));
  assert.equal(a.calls.filter(c => c.options.method === 'POST').length, before + 1);
  a.w.dispatchEvent(new a.w.Event('pagehide'));
  release({ok: true, json: async () => ({ok: true, data: {saveContext: 'fixture-context', progress: clone(a.progress())}})});
  await tick(); await tick();
  assert.equal(a.id('scene').hidden, true); assert.equal(a.id('runner-content').childElementCount, 0);
  assert.equal(a.id('quest-state').textContent, '');
});
test('invalid answer never reaches API or marks work saved', async t => {
  const a = await setup(t); await a.enter(); await a.task();
  const before = a.calls.filter(c => c.options.method === 'POST').length;
  const input = a.id('runner-content').querySelector('input');
  for (const value of ['', '1.5', '-1', '10001']) {
    input.value = value; input.form.dispatchEvent(new a.w.Event('submit', {cancelable: true}));
    assert.match(a.id('runner-status').textContent, /整数/);
  }
  assert.equal(a.calls.filter(c => c.options.method === 'POST').length, before);
});
test('mouse targets and E share range guards and no movement buttons or click-to-move handler exist', async t => {
  const a = await setup(t); await a.enter();
  assert.equal(a.id('left'), null); assert.equal(a.id('right'), null);
  const npc = a.id('viewport').querySelector('[data-entity-id="gatekeeper"]');
  const before = a.x(); npc.click(); a.interact(); await tick(); assert.equal(a.calls.some(c => c.payload), false);
  a.id('viewport').click(); a.frame(); assert.equal(a.x(), before);
  npc.dispatchEvent(new a.w.KeyboardEvent('keydown',{key:'d',bubbles:true,cancelable:true})); a.frame();
  npc.dispatchEvent(new a.w.KeyboardEvent('keyup',{key:'d',bubbles:true,cancelable:true})); assert.ok(a.x()>before);
  await a.walk('守门人'); a.frame(); assert.equal(npc.getAttribute('aria-disabled'), 'false');
  npc.click(); await until(() => !a.id('dialogue').hidden && !a.id('reload').disabled);
  assert.equal(a.calls.filter(c => c.payload?.action === 'talk').length, 1);
});
test('held movement, immediate key release and blur reset work; pause/dialogue cannot leak discrete input', async t => {
  const a = await setup(t); await a.enter(); const start = a.x();
  a.key('keydown', 'd'); for (let i = 0; i < 3; i++) a.frame(); assert.ok(a.x() > start);
  a.key('keyup', 'd'); const stopped = a.x(); a.frame(); assert.equal(a.x(), stopped);
  a.key('keydown', 'd'); a.w.dispatchEvent(new a.w.Event('blur')); a.frame(); assert.equal(a.x(), stopped);
  a.key('keydown', 'Escape'); a.key('keyup', 'Escape'); assert.equal(a.id('pause').hidden, false);
  a.key('keydown', 'd'); a.frame(); assert.equal(a.x(), stopped);
  a.key('keydown', 'Escape'); assert.equal(a.id('pause').hidden, true);
  a.key('keydown', 'Escape'); assert.equal(a.id('pause').hidden, true); a.key('keyup', 'Escape');
});
test('Tab toggles HUD only in scene; form Tab/Space stay in task and Esc offers save/discard/stay', async t => {
  const a = await setup(t); await a.enter();
  a.key('keydown', 'Tab'); a.key('keyup', 'Tab'); assert.equal(a.id('quest-state').hidden, true);
  a.key('keydown', 'Tab'); a.key('keyup', 'Tab'); assert.equal(a.id('quest-state').hidden, false);
  await a.task();
  const input = a.id('runner-content').querySelector('input'); input.focus();
  const tab = new a.w.KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable:true}); input.dispatchEvent(tab);
  assert.equal(tab.defaultPrevented, false); assert.equal(a.id('quest-state').hidden, false);
  const space = new a.w.KeyboardEvent('keydown', {key:' ', bubbles:true,cancelable:true}); input.dispatchEvent(space); assert.equal(space.defaultPrevented,false);
  input.value = '5'; input.dispatchEvent(new a.w.Event('input'));
  input.dispatchEvent(new a.w.KeyboardEvent('keydown', {key:'Escape',bubbles:true,cancelable:true})); a.key('keyup','Escape');
  assert.equal(a.id('save-choice').hidden, false); a.id('save-and-return').click();
  await until(() => a.id('runner').hidden && !a.id('reload').disabled);
  assert.equal(a.progress().state.practice.answers[0], 5);
});
test('overlapping targets use stable distance/ID ordering and explicit cycling', async t => {
  const a = await setup(t, false), locks = new a.w.HuaxiaInputLocks();
  const data = {...a.w.HuaxiaSceneDemo, entities:[{id:'b',kind:'task',x:0.3,range:0.2},{id:'a',kind:'npc',x:0.3,range:0.2}]};
  const model = new a.w.HuaxiaSceneModel(data,locks); model.restore({x:0.3,facing:'right',cameraX:0});
  assert.equal(model.nearby().id,'a'); model.cycleTarget(); assert.equal(model.nearby().id,'b'); model.cycleTarget(); assert.equal(model.nearby().id,'a');
});
test('background replacement changes only resource CSS and preserves login DOM and existing account logic', async t => {
  const loginHtml=fs.readFileSync(path.join(root,'../templates/home.html'),'utf8').replace(/\{%.*?%\}/g,'');
  const dom=new JSDOM(loginHtml,{url:'http://localhost/',runScripts:'outside-only'}); t.after(()=>dom.window.close());
  const w=dom.window; w.eval(source('game-assets'));
  const form=w.document.getElementById('login-form'), field=w.document.getElementById('login-username'); field.value='fixture-user';
  let submissions=0; form.addEventListener('submit',event=>{event.preventDefault();submissions++;});
  w.HuaxiaGameAssets.applyLoginBackground({src:'/static/replacement-placeholder.png',position:'40% center'});
  assert.equal(w.document.getElementById('login-form'),form); assert.equal(field.value,'fixture-user');
  assert.match(w.document.documentElement.style.getPropertyValue('--login-background'),/replacement-placeholder/);
  form.dispatchEvent(new w.Event('submit',{cancelable:true})); assert.equal(submissions,1);
});
test('re-entering a scene does not stack key listeners or duplicate NPC requests', async t => {
  const a=await setup(t); await a.enter();
  for(let i=0;i<3;i++) {a.key('keydown','Escape');a.key('keyup','Escape');a.id('back-map').click();a.level().click();await until(()=>!a.id('scene').hidden&&!a.id('reload').disabled);}
  await a.walk('守门人');a.interact();await until(()=>!a.id('dialogue').hidden&&!a.id('reload').disabled);
  assert.equal(a.calls.filter(c=>c.payload?.action==='talk').length,1);
});
test('dialogue arrows select options and a held confirmation cannot close then trigger another interaction', async t => {
  const a=await setup(t);await a.enter();await a.walk('守门人');a.interact();await until(()=>!a.id('dialogue').hidden&&!a.id('reload').disabled);
  a.key('keydown','ArrowDown');a.key('keyup','ArrowDown');assert.equal(a.w.document.activeElement,a.id('close-dialogue'));
  const requests=a.calls.length;a.key('keydown','Enter');assert.equal(a.id('dialogue').hidden,true);
  a.key('keydown','Enter');await tick();assert.equal(a.calls.length,requests);a.key('keyup','Enter');
});
test('tab hiding retains unsaved draft privately; authenticated same-context resume restores draft, camera and HUD without writes', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='5';input.dispatchEvent(new a.w.Event('input'));
  const x=a.x(),camera=a.id('viewport').querySelector('.scene-world').style.transform,writes=a.calls.filter(c=>c.payload).length;
  visibility(a,true);a.w.dispatchEvent(new a.w.Event('pagehide'));
  assert.equal(a.id('scene').hidden,true);assert.equal(a.id('runner-content').childElementCount,0);
  const unload=new a.w.Event('beforeunload',{cancelable:true});a.w.dispatchEvent(unload);assert.equal(unload.defaultPrevented,true);
  visibility(a,false);await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'5');assert.equal(a.x(),x);
  assert.equal(a.id('viewport').querySelector('.scene-world').style.transform,camera);
  assert.match(a.id('runner-content').querySelector('.muted').textContent,/未保存输入/);
  assert.equal(a.calls.filter(c=>c.payload).length,writes);assert.equal(a.w.localStorage.length,0);assert.equal(a.w.sessionStorage.length,0);
});
test('different session context never exposes or uploads old draft; matching context can later recover the private entry', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='777';input.dispatchEvent(new a.w.Event('input'));
  const writes=a.calls.filter(c=>c.payload).length;visibility(a,true);
  a.override(url=>url.endsWith('/progress')?{ok:true,json:async()=>({ok:true,data:{saveContext:'other-session',progress:clone(a.progress()),questions:[{questionId:'one',prompt:'2 + 3 = ?'},{questionId:'two',prompt:'3 + 4 = ?'}]}})}:null);
  visibility(a,false);await until(()=>!a.id('chapters').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('scene').hidden,true);assert.equal(a.id('runner-content').childElementCount,0);
  assert.equal(a.calls.filter(c=>c.payload).length,writes);
  visibility(a,true);a.override(null);visibility(a,false);await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'777');
});
test('concurrent cloud answer remains authoritative while recovered local input shows both values', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='5';input.dispatchEvent(new a.w.Event('input'));
  visibility(a,true);a.progress().state.practice.answers[0]=9;a.progress().revision++;
  const writes=a.calls.filter(c=>c.payload).length;visibility(a,false);await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'5');
  assert.match(a.id('runner-content').querySelector('.muted').textContent,/云端当前为：9/);
  assert.equal(a.progress().state.practice.answers[0],9);assert.equal(a.calls.filter(c=>c.payload).length,writes);
});
test('a late saved answer is reconciled after hiding instead of being sent again or called unsaved', async t => {
  const a=await setup(t);await a.enter();await a.task();let release;
  a.override((url,options)=>options.method==='POST'?new Promise(resolve=>{release=resolve;}):null);
  const input=a.id('runner-content').querySelector('input');input.value='5';input.dispatchEvent(new a.w.Event('input'));
  input.form.dispatchEvent(new a.w.Event('submit',{cancelable:true}));await until(()=>Boolean(release));
  visibility(a,true);a.progress().state.practice.answers[0]=5;a.progress().revision++;
  release({ok:true,json:async()=>({ok:true,data:{saveContext:'fixture-context',progress:clone(a.progress())}})});
  await tick();a.override(null);visibility(a,false);await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.calls.filter(c=>c.payload?.action==='answer').length,1);
  assert.match(a.id('runner-content').querySelector('.muted').textContent,/已由服务器保存/);
  a.id('exit-runner').click();await until(()=>a.id('runner').hidden);assert.equal(a.id('save-choice').hidden,true);
});
test('failed revalidation keeps private draft recoverable and no account data visible', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='5';input.dispatchEvent(new a.w.Event('input'));visibility(a,true);
  a.override(()=>({ok:false,json:async()=>({ok:false,error:{code:'authentication_required'}})}));visibility(a,false);
  await until(()=>a.id('status').textContent.includes('登录已失效')&&!a.id('reload').disabled);
  assert.equal(a.id('scene').hidden,true);assert.equal(a.id('runner-content').childElementCount,0);
  a.override(null);a.id('reload').click();await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'5');
});
test('return authentication failure exits the empty runner and offers account navigation instead of trapping retries', async t => {
  const a=await setup(t);await a.enter();await a.task();
  a.override(url=>url.endsWith('/progress')?{ok:false,json:async()=>({ok:false,error:{code:'authentication_required'}})}:null);
  a.id('exit-runner').click();await until(()=>a.id('status').textContent.includes('登录已失效')&&!a.id('reload').disabled);
  assert.equal(a.id('runner').hidden,true);a.key('keydown','Escape');a.key('keyup','Escape');
  assert.equal(a.id('pause').hidden,false);assert.equal(a.id('pause').querySelector('a').getAttribute('href'),'/');
});
test('changed server scene is not automatically moved; explicit task re-entry can recover preserved local input', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='5';input.dispatchEvent(new a.w.Event('input'));visibility(a,true);
  a.progress().state.story.scene='gate';a.progress().revision++;const writes=a.calls.filter(c=>c.payload).length;
  visibility(a,false);await until(()=>!a.id('scene').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner').hidden,true);assert.equal(a.calls.filter(c=>c.payload).length,writes);
  a.interact();await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'5');
  assert.equal(a.calls.filter(c=>c.payload).length,writes+1);
});
test('context rotation between resume reads never applies a private draft and leaves it recoverable', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='777';input.dispatchEvent(new a.w.Event('input'));visibility(a,true);
  let reads=0;a.override(url=>url.endsWith('/progress')&&++reads===2?{ok:true,json:async()=>({ok:true,data:{saveContext:'rotated',progress:clone(a.progress()),questions:[{questionId:'one',prompt:'2 + 3 = ?'},{questionId:'two',prompt:'3 + 4 = ?'}]}})}:null);
  visibility(a,false);await until(()=>!a.id('chapters').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').childElementCount,0);assert.match(a.id('status').textContent,/会话或题目已变化/);
  a.override(null);a.id('reload').click();await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'777');
});
test('uncertain answer save keeps local input for explicit re-read without replaying the mutation', async t => {
  const a=await setup(t);await a.enter();await a.task();
  const input=a.id('runner-content').querySelector('input');input.value='5';input.dispatchEvent(new a.w.Event('input'));
  a.override((url,options)=>options.method==='POST'?Promise.reject(Error('lost response')):null);
  input.form.dispatchEvent(new a.w.Event('submit',{cancelable:true}));
  await until(()=>a.id('status').textContent.includes('尚未确认')&&!a.id('reload').disabled);
  assert.equal(a.id('scene').hidden,true);a.override(null);a.id('reload').click();
  await until(()=>!a.id('runner').hidden&&!a.id('reload').disabled);
  assert.equal(a.id('runner-content').querySelector('input').value,'5');
  assert.equal(a.calls.filter(c=>c.payload?.action==='answer').length,1);assert.equal(a.progress().state.practice.answers[0],null);
});

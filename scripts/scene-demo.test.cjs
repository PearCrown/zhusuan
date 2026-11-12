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
async function setup(t, ui = true, configure = () => {}, stageMode = false) {
  const dom = new JSDOM(html, {url: 'http://localhost/static/scene-demo.html', runScripts: 'outside-only', pretendToBeVisual: true});
  const w = dom.window;
  if (w.document.readyState !== 'complete') await new Promise(resolve => w.addEventListener('load', resolve, {once: true}));
  t.after(() => w.close());
  let callback, time = 0;
  w.requestAnimationFrame = cb => {callback = cb; return 1;}; w.cancelAnimationFrame = () => {callback = null;};
  const calls = [];
  let override;
  w.fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (override) { const result = override(url, options); if (result) return result; }
    assert.notEqual(options.method, 'POST', '营前剧情不应写入任务或成绩');
    let data;
    if (url === '/game/api/chapters') data = {chapters: [{chapterId: 'sample-counting', title: '算坊初试'}]};
    else if (url.endsWith('/progress')) data = {progress: {chapterId: 'sample-counting', revision: 0, result: null}, saveContext: 'fixture-context'};
    else assert.fail('unexpected ' + url);
    return {ok: true, json: async () => ({ok: true, data})};
  };
  w.HUAXIA_STAGE_MODE = stageMode;
  for (const name of ['chapter-sdk', 'scene-host', 'scene-demo-data', 'region-map-data', 'scene-model', 'scene-view', 'curriculum', 'stage-select']) w.eval(source(name));
  configure(w);
  const id = name => w.document.getElementById(name);
  const chapter = () => w.document.querySelector('[data-chapter-id="sample-counting"]');
  const level = () => w.document.querySelector('[data-level-id="tc-nand"]');
  const a = {w, id, chapter, level, calls, override: fn => {override = fn;}, frame: () => {time += 100; callback?.(time);},
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
test('营前入口重新验证会话，距离不足时不开对话', async t => {
  const a = await setup(t); await a.enter();
  assert.equal(a.calls.filter(c => c.url.endsWith('/progress')).length, 1);
  a.interact();
  assert.equal(a.id('dialogue').hidden, true);
  assert.equal(a.id('viewport').querySelectorAll('.scene-entity').length, 2);
});
const chapterListing = chapters => ({ok: true, json: async () => ({ok: true, data: {chapters}})});
function mapKey(a, key) {
  const event = new a.w.KeyboardEvent('keydown', {key, bubbles: true, cancelable: true});
  a.w.document.activeElement.dispatchEvent(event);
  a.w.document.activeElement.dispatchEvent(new a.w.KeyboardEvent('keyup', {key, bubbles: true}));
  return event.defaultPrevented;
}

test('world map exposes regions first and reveals only the selected region and its events', async t => {
  const a = await setup(t);
  const sample = {chapterId: 'sample-counting', title: '服务端算坊标题'};
  const unplaced = {chapterId: 'fixture-second-chapter', title: '未定位章'};
  a.override(url => url === '/game/api/chapters' ? chapterListing([unplaced, sample]) : null);
  await a.ready();
  const regionIds = [...a.id('chapter-nodes').children].map(node => node.dataset.regionId);
  assert.deepEqual(regionIds, ['guanzhong', 'jinnan', 'central-plains', 'eastlands']);
  assert.equal(a.id('level-nodes').children.length, 0);
  assert.equal(a.id('region-event-points').children.length, 0);
  assert.equal(a.w.document.activeElement, a.chapter());
  const reads = a.calls.length;
  const guanzhong = a.id('chapter-nodes').firstElementChild;
  guanzhong.click();
  assert.equal(a.id('location-name').textContent, '关中');
  assert.deepEqual([...a.id('level-nodes').children].map(node => node.dataset.placeId), ['longdong', 'qizhou', 'fenghao', 'huyi']);
  assert.deepEqual([...a.id('region-event-points').children].map(node => node.dataset.event), ['4', '10', '14', '15', '16', '17']);
  assert.equal(a.id('region-crop').parentElement.style.getPropertyValue('--crop-width'), String(1540 / 430));
  a.id('level-nodes').querySelector('[data-place-id="qizhou"]').click();
  assert.equal(a.id('map-note-title').textContent, '岐周');
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.calls.length, reads);
  mapKey(a, 'Escape');
  assert.equal(a.w.document.activeElement, guanzhong);
  a.chapter().focus();
  mapKey(a, 'Enter');
  assert.equal(a.id('location-name').textContent, '中原');
  assert.equal(a.w.document.activeElement, a.level());
  assert.equal(a.id('level-nodes').querySelector('[data-place-id="qizhou"]'), null);
  assert.equal(a.level().dataset.placeId, 'bo');
  assert.equal(a.level().querySelector('.atlas-landmark').dataset.kind, 'city');
  assert.equal(a.id('level-nodes').querySelectorAll('button').length, 7);
  assert.equal(a.calls.length, reads);
});

test('从亳的关卡选择进入营前并回到同一入口', async t => {
  const a = await setup(t, true, () => {}, true);
  await a.ready();
  a.chapter().click();
  assert.equal(a.id('locations').hidden, false);

  // 关卡选择屏自己去读关卡与存档，这里替换掉页面级 fetch。
  const nav = [];
  a.w.HuaxiaStageNavigate = url => nav.push(url);
  a.override(url => {
    if (url === '/game/api/circuit/puzzles') return {ok:true, json:async()=>({ok:true, data:{puzzles:[{id:'tc-nand',title:'第一关：识·与非',description:'用与非门接出真值表'}]}})};
    if (url.includes('/xia-circuit/progress')) return {ok:true, json:async()=>({ok:true, data:{saveContext:'ctx', progress:{chapterId:'xia-circuit', state:{circuit:{levels:{},puzzleIds:['tc-nand'],attempts:[]}}, result:null}}})};
  });

  a.level().click();
  await until(() => !a.id('stages').hidden);
  assert.equal(a.id('scene').hidden, true, '不该再进横版场景');
  await until(() => a.id('stage-app').querySelector('.ark-stage'));
  assert.match(a.id('stage-app').textContent, /识·与非/);
  a.id('stage-app').querySelector('[data-stage-id="camp"]').click();
  await until(() => !a.id('scene').hidden && !a.id('open-menu').disabled);
  a.id('camp-back').click();
  await until(() => a.id('scene').hidden && !a.id('stages').hidden);

  // Esc 回到地点图
  a.key('keydown', 'Escape'); a.key('keyup', 'Escape');
  await until(() => a.id('stages').hidden);
  assert.equal(a.id('locations').hidden, false);
});

test('世界地图左侧列出各章，点已开放的章进入地区图', async t => {
  const a = await setup(t);
  await a.ready();
  const guide = a.id('chapter-guide');
  assert.ok(guide, '地图左侧应有课程指引');
  const items = guide.querySelectorAll('.map-guide-item');
  assert.equal(items.length, 4, '四个地区各一章');
  assert.match(guide.textContent, /第一章/);
  assert.match(guide.textContent, /从逻辑门到存算器件/);
  assert.match(guide.textContent, /中原 · 可进入/);
  assert.equal(guide.querySelectorAll('.map-guide-item.is-locked').length, 3, '其余三章未开放');
  // 章节要按一、二、三、四排，而不是按地区数组顺序。
  const nos = [...items].map(item => item.querySelector('.map-guide-no').textContent);
  assert.deepEqual(nos, ['第一章', '第二章', '第三章', '第四章']);

  guide.querySelector('.map-guide-item.is-open').click();
  assert.equal(a.id('location-name').textContent, '中原');
  assert.match(a.id('location-kicker').textContent, /第一章/);
  assert.match(a.id('location-kicker').textContent, /从逻辑门到存算器件/);

  // 地区图左侧也要有小节指引，标出亳 是第一节。
  const sectionGuide = a.id('section-guide');
  assert.ok(sectionGuide, '地区图左侧应有小节指引');
  assert.match(sectionGuide.textContent, /第一节/);
  assert.match(sectionGuide.textContent, /亳/);
  assert.match(sectionGuide.textContent, /进入本节行动/);
});

test('带 #stage-select 打开页面时直接落在亳 的关卡选择', async t => {
  const a = await setup(t, true, () => {}, true);
  const original = a.w.fetch;
  a.w.fetch = async (url, options) => {
    if (url === '/game/api/circuit/puzzles') return {ok:true, json:async()=>({ok:true, data:{puzzles:[{id:'tc-nand',title:'第一关：识·与非',description:'x'}]}})};
    if (url.includes('/xia-circuit/progress')) return {ok:true, json:async()=>({ok:true, data:{saveContext:'c', progress:{chapterId:'xia-circuit', state:{circuit:{levels:{},puzzleIds:['tc-nand'],attempts:[]}}, result:null}}})};
    return original(url, options);
  };
  a.w.location.hash = '#stage-select';
  // 深链接会直接跳过总图，所以不能等"chapters 可见"，直接看关卡选择屏。
  a.w.dispatchEvent(new a.w.Event('pageshow'));
  await until(() => !a.id('stages').hidden);
  assert.equal(a.id('locations').hidden, true, '深链接应越过地点图');
  await until(() => a.id('stage-app').querySelector('.ark-stage'));
});

test('reserved B slots follow named map locations without opening a scene or calling the API', async t => {
  const a = await setup(t);
  await a.ready();
  a.chapter().click();
  const levels = ['hewan-village', 'linshui-workshop', 'dongyuan-earthworks'];
  const slots = levels.map(id => a.id('level-nodes').querySelector('[data-level-id="' + id + '"]'));
  const reads = a.calls.length;
  mapKey(a, 'ArrowRight');
  assert.equal(a.w.document.activeElement.dataset.placeId, 'chengzhou');
  slots[0].focus();
  mapKey(a, 'Enter');
  assert.equal(a.id('map-note-title').textContent, '斟鄩');
  assert.match(a.id('level-state').textContent, /开发者 B/);
  for (const [slot, title] of [[slots[1], '阳城'], [slots[2], '蒙泽']]) {
    slot.click();
    assert.equal(a.id('map-note-title').textContent, title);
    assert.deepEqual(slots.filter(node => node.getAttribute('aria-pressed') === 'true'), [slot]);
  }
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.calls.length, reads);
  mapKey(a, 'Escape');
  assert.equal(a.w.document.activeElement, a.chapter());
  a.chapter().click();
  assert.equal(a.w.document.activeElement.dataset.placeId, 'mengze');
  a.level().click();
  await until(() => !a.id('scene').hidden && !a.id('reload').disabled);
  assert.equal(a.id('map-note-title').textContent, '亳城营前');
  assert.equal(a.calls.length, reads + 1);
});

test('regional event index has native keyboard activation and closes before returning to the world map', async t => {
  const a = await setup(t);
  await a.ready();
  a.chapter().click();
  const details = a.id('region-event-index');
  const summary = details.querySelector('summary');
  assert.deepEqual([...details.querySelectorAll('li:not([hidden])')].map(li => li.value), [3, 6, 8, 13, 18]);
  summary.focus();
  assert.equal(mapKey(a, 'Enter'), false);
  assert.equal(a.id('scene').hidden, true);
  details.open = true;
  assert.equal(mapKey(a, 'Escape'), true);
  assert.equal(details.open, false);
  assert.equal(a.id('locations').hidden, false);
  assert.equal(a.w.document.activeElement, summary);
  mapKey(a, 'Escape');
  assert.equal(a.w.document.activeElement, a.chapter());
});

test('regional geography remains browsable but a missing registry chapter cannot open its scene', async t => {
  const a = await setup(t);
  a.override(url => url === '/game/api/chapters' ? chapterListing([
    {chapterId: 'fixture-second-chapter', title: '未定位章'},
  ]) : null);
  await a.ready();
  assert.equal(a.chapter(), null);
  a.id('chapter-nodes').querySelector('[data-region-id="central-plains"]').click();
  assert.equal(a.level(), null);
  const bo = a.id('level-nodes').querySelector('[data-place-id="bo"]');
  bo.click();
  assert.equal(a.id('map-note-title').textContent, '亳');
  assert.equal(a.id('scene').hidden, true);
  assert.deepEqual(a.calls.map(call => call.url), ['/game/api/chapters']);
});
test('两位人物在营前讲完台词，整个过程不写任务进度', async t => {
  const a = await setup(t); await a.enter();
  const reads = a.calls.length;
  for (const label of ['守门人', '妇好']) {
    await a.walk(label); a.interact();
    assert.equal(a.id('dialogue').hidden, false);
    assert.equal(a.id('dialogue-title').textContent, label);
    const first = a.id('dialogue-text').textContent;
    a.id('advance-dialogue').click();
    assert.notEqual(a.id('dialogue-text').textContent, first);
    while (!a.id('dialogue').hidden) a.id('advance-dialogue').click();
    assert.equal(a.w.document.activeElement, a.id('viewport'));
  }
  assert.equal(a.calls.length, reads);
  assert.equal(a.w.localStorage.length, 0);
  assert.equal(a.w.sessionStorage.length, 0);
  for (const removed of ['accept', 'runner', 'taskbar', 'story-link']) assert.equal(a.id(removed), null);
});

test('退出营前无需完成委托', async t => {
  const a = await setup(t); await a.enter();
  a.id('camp-back').click();
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.id('locations').hidden, false);
});

test('登录失效时不会恢复营前画面', async t => {
  const a = await setup(t); await a.enter();
  visibility(a, true);
  a.override(() => ({ok: false, json: async () => ({ok: false, error: {code: 'authentication_required'}})}));
  visibility(a, false);
  await until(() => /登录已失效/.test(a.id('status').textContent));
  assert.equal(a.id('scene').hidden, true);
  assert.equal(a.id('viewport').childElementCount, 0);
});

test('鼠标和 E 都遵守人物对话范围，对话时锁住行走', async t => {
  const a = await setup(t); await a.enter();
  const npc = a.id('viewport').querySelector('[data-entity-id="gate.keeper"]');
  npc.click();
  a.interact();
  assert.equal(a.id('dialogue').hidden, true);
  await a.walk('守门人');
  npc.click();
  assert.equal(a.id('dialogue').hidden, false);
  const before = a.x();
  a.key('keydown', 'd'); a.frame();
  assert.equal(a.x(), before);
  a.key('keydown', 'Escape'); a.key('keyup', 'Escape');
  assert.equal(a.id('dialogue').hidden, true);
  a.frame(); assert.equal(a.x(), before);
});

test('按住方向键移动，松键和失焦时停止', async t => {
  const a = await setup(t); await a.enter(); const start = a.x();
  a.key('keydown', 'd'); for (let i = 0; i < 3; i++) a.frame(); assert.ok(a.x() > start);
  a.key('keyup', 'd'); const stopped = a.x(); a.frame(); assert.equal(a.x(), stopped);
  a.key('keydown', 'd');
  a.w.dispatchEvent(new a.w.Event('blur')); a.frame(); assert.equal(a.x(), stopped);
});

test('回到标签页恢复营前位置和方向', async t => {
  const a = await setup(t); await a.enter();
  await a.walk('守门人');
  const before = a.x();
  visibility(a, true);
  visibility(a, false);
  await until(() => !a.id('scene').hidden && !a.id('camp-back').disabled);
  assert.equal(a.x(), before);
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
test('重复进出营前只保留一组人物和对话动作', async t => {
  const a = await setup(t); await a.enter();
  for (let i = 0; i < 3; i++) {
    a.id('camp-back').click();
    a.level().click();
    await until(() => !a.id('scene').hidden && !a.id('camp-back').disabled);
  }
  await a.walk('守门人'); a.interact();
  assert.equal(a.id('viewport').querySelectorAll('.scene-npc').length, 2);
  a.id('advance-dialogue').click();
  assert.equal(a.id('dialogue').hidden, false);
  a.id('advance-dialogue').click();
  assert.equal(a.id('dialogue').hidden, true);
});

test('营前使用全景背景、学徒与两位独立人物立绘', async t => {
  const a = await setup(t); await a.enter();
  const world = a.id('viewport').querySelector('.scene-world');
  assert.match(world.querySelector('.scene-backdrop').style.backgroundImage, /camp\/bo-camp\.png/);
  assert.match(world.querySelector('[data-entity-id="gate.keeper"] .entity-shape').style.backgroundImage, /camp\/gatekeeper\.png/);
  assert.match(world.querySelector('[data-entity-id="fu-hao"] .entity-shape').style.backgroundImage, /camp\/fu-hao\.png/);
  const player = world.querySelector('.scene-player');
  assert.equal(player.getAttribute('aria-label'), '学徒');
  assert.match(player.style.backgroundImage, /camp\/apprentice\.png/);
});

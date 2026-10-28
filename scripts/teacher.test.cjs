const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/teacher.html'), 'utf8').replace(/\{%.*?%\}/g, '');
const script = fs.readFileSync(path.join(root, 'static/js/teacher.js'), 'utf8');
const classroom = { classId: 'class-a', code: 'A01', name: '一班' };
const classes = { items: [classroom], total: 1, page: 1, pageSize: 50, hasNext: false };
const roster = { classroom, items: [{ username: 'learner', displayName: '<img src=x onerror=alert(1)>' }], total: 1, page: 1, pageSize: 50, hasNext: false };
const ok = (data) => ({ ok: true, headers: new Map([['Content-Type', 'application/json']]), json: async () => ({ ok: true, data }) });
const fail = (code) => ({ ok: false, headers: new Map([['Content-Type', 'application/json']]), json: async () => ({ ok: false, error: { code } }) });
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function until(fn) { for (let i = 0; i < 100; i++) { if (fn()) return; await tick(); } assert.fail('Teacher UI did not settle'); }
async function setup(t, initial = () => ok(classes)) {
  const dom = new JSDOM(html, { url: 'http://localhost/teacher/', runScripts: 'outside-only', pretendToBeVisual: true });
  t.after(() => dom.window.close());
  const w = dom.window;
  if (w.document.readyState !== 'complete') await new Promise((resolve) => w.addEventListener('load', resolve, { once: true }));
  let responder = initial;
  const calls = [];
  w.fetch = async (url, options) => { calls.push({ url, options }); return responder(url, options); };
  w.eval(script);
  w.dispatchEvent(new w.Event('pageshow'));
  await until(() => !w.document.getElementById('reload-classes').disabled);
  return { w, calls, id: (id) => w.document.getElementById(id), respond: (fn) => { responder = fn; }, idle: () => until(() => !w.document.getElementById('reload-classes').disabled) };
}

test('anonymous data request exposes no class or roster and explains login', async (t) => {
  const a = await setup(t, () => fail('authentication_required'));
  assert.equal(a.id('class-list').children.length, 0);
  assert.equal(a.id('roster').hidden, true);
  assert.match(a.id('teacher-status').textContent, /重新登录/);
  assert.equal(a.calls[0].options.credentials, 'same-origin');
});

test('class selection shows scoped roster using safe text only', async (t) => {
  const a = await setup(t);
  a.respond(() => ok(roster));
  a.id('class-list').querySelector('button').click();
  await a.idle();
  assert.equal(a.calls.at(-1).url, '/teacher/api/classes/class-a/students?page=1');
  assert.equal(a.id('roster').hidden, false);
  assert.match(a.id('students-body').textContent, /<img/);
  assert.equal(a.id('students-body').querySelector('img'), null);
  assert.equal(a.w.localStorage.length, 0);
  assert.equal(a.w.sessionStorage.length, 0);
});

test('no class grants produces explicit empty state', async (t) => {
  const a = await setup(t, () => ok({ ...classes, items: [], total: 0 }));
  assert.match(a.id('teacher-status').textContent, /没有有效的班级授权/);
  assert.equal(a.id('class-list').children.length, 0);
});

test('revoked role on refresh clears previous classes and roster', async (t) => {
  const a = await setup(t);
  a.respond(() => ok(roster));
  a.id('class-list').querySelector('button').click();
  await a.idle();
  a.respond(() => fail('teacher_access_required'));
  a.id('reload-classes').click();
  await a.idle();
  assert.equal(a.id('class-list').children.length, 0);
  assert.equal(a.id('students-body').children.length, 0);
  assert.equal(a.id('roster').hidden, true);
  assert.match(a.id('teacher-status').textContent, /教师权限/);
});

test('export denial does not download JSON as CSV or keep stale data', async (t) => {
  const a = await setup(t);
  a.respond(() => ok(roster));
  a.id('class-list').querySelector('button').click();
  await a.idle();
  let downloads = 0;
  a.w.URL.createObjectURL = () => { downloads++; return 'blob:fake'; };
  a.respond(() => fail('teacher_access_required'));
  a.id('export-roster').click();
  await a.idle();
  assert.equal(downloads, 0);
  assert.equal(a.id('roster').hidden, true);
  assert.equal(a.calls.filter((call) => call.url.endsWith('.csv')).length, 1);
});

test('late roster response cannot restore hidden data; return checks new grants', async (t) => {
  const a = await setup(t);
  let release;
  a.respond(() => new Promise((resolve) => { release = resolve; }));
  a.id('class-list').querySelector('button').click();
  await until(() => Boolean(release));
  Object.defineProperty(a.w.document, 'hidden', { configurable: true, value: true });
  a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));
  release(ok(roster));
  await a.idle();
  assert.equal(a.id('class-list').children.length, 0);
  assert.equal(a.id('roster').hidden, true);
  a.respond(() => fail('teacher_access_required'));
  Object.defineProperty(a.w.document, 'hidden', { configurable: true, value: false });
  a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));
  await a.idle();
  assert.match(a.id('teacher-status').textContent, /教师权限/);
  assert.equal(a.id('students-body').children.length, 0);
});

test('duplicate class clicks issue only one pending data request', async (t) => {
  const a = await setup(t);
  let release;
  a.respond(() => new Promise((resolve) => { release = resolve; }));
  const button = a.id('class-list').querySelector('button');
  button.click();
  button.click();
  await until(() => Boolean(release));
  assert.equal(a.calls.filter((call) => call.url.includes('/students')).length, 1);
  release(ok(roster));
  await a.idle();
});

test('scores render safely and revoked score export removes old scores without downloading errors', async (t) => {
  const a = await setup(t);
  a.respond(() => ok(roster));
  a.id('class-list').querySelector('button').click();
  await a.idle();
  a.respond(() => ok({ items: [{ username: 'learner', displayName: '<img src=x>', chapterId: 'sample-counting', questionBank: { version: '1' }, score: 100, maxScore: 100 }], total: 1, page: 1, hasNext: false }));
  a.id('load-scores').click();
  await a.idle();
  assert.equal(a.calls.at(-1).url, '/game/api/teacher/classes/class-a/scores?page=1');
  assert.match(a.id('scores-body').textContent, /100 \/ 100/);
  assert.match(a.id('scores-body').textContent, /<img/);
  assert.equal(a.id('scores-body').querySelector('img'), null);
  let downloads = 0;
  a.w.URL.createObjectURL = () => { downloads++; return 'blob:fake'; };
  a.respond(() => fail('class_not_found'));
  a.id('export-scores').click();
  await a.idle();
  assert.equal(a.calls.at(-1).url, '/game/api/teacher/classes/class-a/scores.csv');
  assert.equal(downloads, 0);
  assert.equal(a.id('scores-body').children.length, 0);
  assert.equal(a.id('teacher-scores').hidden, true);
  assert.equal(a.id('class-list').children.length, 0);
});

test('late score response cannot restore scores after the page hides', async (t) => {
  const a = await setup(t);
  a.respond(() => ok(roster));
  a.id('class-list').querySelector('button').click();
  await a.idle();
  let release;
  a.respond(() => new Promise(resolve => { release = resolve; }));
  a.id('load-scores').click();
  await until(() => Boolean(release));
  Object.defineProperty(a.w.document, 'hidden', { configurable: true, value: true });
  a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));
  release(ok({ items: [{ username: 'old-user', displayName: 'old-data', chapterId: 'sample-counting', questionBank: { version: '1' }, score: 100, maxScore: 100 }], total: 1, page: 1, hasNext: false }));
  await a.idle();
  assert.equal(a.id('scores-body').children.length, 0);
  assert.equal(a.id('teacher-scores').hidden, true);
  assert.equal(a.id('class-list').children.length, 0);
});

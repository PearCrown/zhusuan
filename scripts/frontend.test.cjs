/* DOM state/failure checks. Does not connect to any database or real browser. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/home.html'), 'utf8').replace(/\{%.*?%\}/g, '');
const script = fs.readFileSync(path.join(root, 'static/js/accounts.js'), 'utf8');
const user = { username: 'tester01', displayName: '验收同学', roles: ['student'], classId: null, teachingClassIds: [] };
const ok = (data) => ({ ok: true, headers: new Map(), json: async () => ({ ok: true, data }) });
const fail = (code, message = '请求失败', fields = {}, headers = new Map()) => ({ ok: false, headers, json: async () => ({ ok: false, error: { code, message, fields } }) });
const anonymous = () => fail('authentication_required');
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function until(predicate) {
  for (let n = 0; n < 100; n++) { if (predicate()) return; await tick(); }
  assert.fail('UI did not settle');
}
async function setup(t) {
  const dom = new JSDOM(html, { url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true });
  t.after(() => dom.window.close());
  const w = dom.window;
  if (w.document.readyState !== 'complete') await new Promise((resolve) => w.addEventListener('load', resolve, { once: true }));
  const calls = [];
  let responder = (url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh-token' }) : anonymous();
  w.fetch = async (url, options) => {
    calls.push({ url, method: options.method || 'GET', data: options.body && JSON.parse(options.body), options });
    return responder(url, options);
  };
  w.eval(script);
  w.dispatchEvent(new w.Event('pageshow'));
  await until(() => !w.document.getElementById('guest').hidden);
  return {
    w, calls,
    id: (id) => w.document.getElementById(id),
    respond: (fn) => { responder = fn; },
    async submit(name, values) {
      for (const [key, value] of Object.entries(values)) w.document.getElementById(`${name}-${key}`).value = value;
      w.document.getElementById(`${name}-form`).dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
      await tick();
    },
    async idle() { await until(() => !w.document.getElementById('show-login').disabled); },
  };
}
const loginValues = { username: 'tester01', password: ' Maple!River-7429 ' };
const registerValues = { ...loginValues, displayName: '验收同学', confirm: loginValues.password };

test('initial identity comes from server; anonymous sees login', async (t) => {
  const a = await setup(t);
  assert.equal(a.calls[0].url, '/auth/me');
  assert.equal(a.id('identity').hidden, true);
  assert.equal(a.w.localStorage.length, 0);
  assert.equal(a.w.sessionStorage.length, 0);
});

test('confirmation mismatch stays local and clears passwords', async (t) => {
  const a = await setup(t);
  a.id('show-register').click();
  await a.submit('register', { ...registerValues, confirm: 'wrong' });
  assert.match(a.id('register-confirm-error').textContent, /不一致/);
  assert.equal(a.calls.filter((c) => c.method === 'POST').length, 0);
  assert.equal(a.id('register-password').value, '');
  assert.equal(a.id('register-confirm').value, '');
});

test('registration sends whitelist only, preserves password spaces and does not auto login', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'rotated' }) : ok({ username: 'tester01' }));
  a.id('show-register').click();
  await a.submit('register', registerValues);
  await a.idle();
  const call = a.calls.find((c) => c.method === 'POST');
  assert.deepEqual(call.data, { username: 'tester01', displayName: '验收同学', password: loginValues.password });
  assert.equal(call.options.headers['X-CSRFToken'], 'rotated');
  assert.equal(call.options.credentials, 'same-origin');
  assert.equal(a.calls.some((c) => c.url === '/auth/login'), false);
  assert.equal(a.id('login-form').hidden, false);
  assert.equal(a.id('login-username').value, 'tester01');
  assert.match(a.id('status').textContent, /注册成功/);
});

test('wrong password and field errors are visible without retrying login', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : fail('invalid_credentials', '账号或密码错误'));
  await a.submit('login', loginValues);
  await a.idle();
  assert.match(a.id('status').textContent, /账号或密码错误/);
  assert.equal(a.calls.filter((c) => c.method === 'POST').length, 1);
  assert.equal(a.id('login-password').value, '');
});

test('server registration errors map to associated input', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : fail('validation_error', '请检查密码', { password: ['密码过于常见'] }));
  a.id('show-register').click();
  await a.submit('register', registerValues);
  await a.idle();
  assert.equal(a.id('register-password').getAttribute('aria-invalid'), 'true');
  assert.equal(a.id('register-password-error').textContent, '密码过于常见');
  assert.equal(a.w.document.activeElement, a.id('register-password'));
});

test('login rechecks retained cookie, and renders user text safely', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : url === '/auth/login' ? ok({ user }) : ok({ ...user, displayName: '<img src=x onerror=alert(1)>', roles: ['student', 'teacher'], teachingClassIds: ['class-2'] }));
  await a.submit('login', loginValues);
  await a.idle();
  assert.equal(a.id('identity').hidden, false);
  assert.equal(a.id('guest').hidden, true);
  assert.equal(a.id('welcome').querySelector('img'), null);
  assert.match(a.id('welcome').textContent, /<img/);
  assert.equal(a.id('identity-roles').textContent, '学生、教师');
  assert.equal(a.id('identity-teaching').textContent, 'class-2');
  assert.equal(a.id('teacher-link').hidden, false);
  assert.equal(a.w.localStorage.length, 0);
  assert.equal(a.w.sessionStorage.length, 0);
});

test('a successful login response alone cannot establish UI identity', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : url === '/auth/login' ? ok({ user }) : anonymous());
  await a.submit('login', loginValues);
  await a.idle();
  assert.equal(a.id('identity').hidden, true);
  assert.equal(a.id('guest').hidden, false);
  assert.match(a.id('status').textContent, /当前未登录/);
});

test('duplicate submit while request is pending sends exactly once', async (t) => {
  const a = await setup(t);
  let release;
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : new Promise((resolve) => { release = resolve; }));
  await a.submit('login', loginValues);
  await a.submit('login', loginValues);
  assert.equal(a.calls.filter((c) => c.method === 'POST').length, 1);
  assert.equal(a.id('show-register').disabled, true);
  release(fail('invalid_credentials', '账号或密码错误'));
  await a.idle();
});

test('CSRF failure does not replay mutation; next explicit attempt refreshes token', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : fail('csrf_failed'));
  await a.submit('login', loginValues);
  await a.idle();
  assert.match(a.id('status').textContent, /安全校验/);
  assert.equal(a.calls.filter((c) => c.method === 'POST').length, 1);
  await a.submit('login', loginValues);
  await a.idle();
  assert.equal(a.calls.filter((c) => c.url === '/auth/csrf').length, 2);
});

test('lost login response reconciles server identity instead of guessing or replaying', async (t) => {
  const a = await setup(t);
  a.respond((url) => {
    if (url === '/auth/csrf') return ok({ csrfToken: 'fresh' });
    if (url === '/auth/login') throw new Error('connection reset');
    return ok(user);
  });
  await a.submit('login', loginValues);
  await a.idle();
  assert.equal(a.id('identity').hidden, false);
  assert.equal(a.calls.filter((c) => c.url === '/auth/login').length, 1);
});

test('logout failure and unavailable identity clear stale account and offer retry', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : ok(user));
  await a.submit('login', loginValues);
  await a.idle();
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : fail('service_unavailable'));
  a.id('logout').click();
  await a.idle();
  assert.equal(a.id('identity').hidden, true);
  assert.equal(a.id('welcome').textContent, '');
  assert.equal(a.id('guest').hidden, true);
  assert.equal(a.id('retry').hidden, false);
  assert.match(a.id('status').textContent, /无法确认/);
});

test('identity expiry removes all previous user text', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : ok(user));
  await a.submit('login', loginValues);
  await a.idle();
  a.respond(anonymous);
  a.id('refresh').click();
  await a.idle();
  assert.equal(a.id('identity').hidden, true);
  assert.equal(a.id('welcome').textContent, '');
  assert.equal(a.id('guest').hidden, false);
  assert.equal(a.id('teacher-link').hidden, true);
});

test('rate limit displays wait duration without automatic retries', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : fail('rate_limited', '操作频繁', {}, new Map([['Retry-After', '32']])));
  await a.submit('login', loginValues);
  await a.idle();
  assert.match(a.id('status').textContent, /32秒/);
  assert.equal(a.calls.filter((c) => c.method === 'POST').length, 1);
});

test('old in-flight response cannot restore identity after hiding; return fetches fresh roles', async (t) => {
  const a = await setup(t);
  a.respond((url) => url === '/auth/csrf' ? ok({ csrfToken: 'fresh' }) : ok(user));
  await a.submit('login', loginValues);
  await a.idle();
  let release;
  a.respond(() => new Promise((resolve) => { release = resolve; }));
  a.id('refresh').click();
  await until(() => Boolean(release));
  Object.defineProperty(a.w.document, 'hidden', { configurable: true, value: true });
  a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));
  assert.equal(a.id('welcome').textContent, '');
  release(ok(user));
  await a.idle();
  assert.equal(a.id('identity').hidden, true);
  a.respond(() => ok({ ...user, displayName: '新账号', roles: ['teacher'], teachingClassIds: [] }));
  Object.defineProperty(a.w.document, 'hidden', { configurable: true, value: false });
  a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));
  await a.idle();
  assert.equal(a.id('welcome').textContent, '你好，新账号');
  assert.equal(a.id('identity-roles').textContent, '教师');
});

test('back-forward restoration clears password and rechecks server identity', async (t) => {
  const a = await setup(t);
  a.id('login-password').value = 'temporary password';
  a.w.dispatchEvent(new a.w.Event('pagehide'));
  assert.equal(a.id('login-password').value, '');
  const previous = a.calls.length;
  a.w.dispatchEvent(new a.w.Event('pageshow'));
  await a.idle();
  assert.equal(a.calls.length, previous + 1);
  assert.equal(a.id('guest').hidden, false);
});

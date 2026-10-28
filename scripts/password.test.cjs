const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'static/js/password.js'),'utf8');
const raw=fs.readFileSync(path.join(root,'templates/password.html'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const ok=data=>({ok:true,headers:new Map(),json:async()=>({ok:true,data})});
const fail=code=>({ok:false,headers:new Map(),json:async()=>({ok:false,error:{code,message:'固定安全提示'}})});
async function setup(t,mode='change'){
  const html=raw.replace(/\{%.*?%\}/g,'').replaceAll('{{ mode }}',mode);
  const dom=new JSDOM(html,{url:`http://localhost/password/${mode}/`,runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window;
  if(w.document.readyState!=='complete')await new Promise(resolve=>w.addEventListener('load',resolve,{once:true}));
  w.document.getElementById(mode==='change'?'reset-credential':'current-password').remove();
  let responder=url=>ok(url==='/auth/csrf'?{csrfToken:'fresh'}:{passwordChanged:true});
  const calls=[];
  w.fetch=async(url,options)=>{calls.push({url,options,payload:options.body&&JSON.parse(options.body)});return responder(url,options);};
  w.eval(source);
  const id=name=>w.document.getElementById(name);
  return {w,id,calls,respond:fn=>{responder=fn;},async submit(confirm=' Copper!Forest-9372 '){
    id(mode==='change'?'current-password':'reset-credential').value=mode==='change'?'Old!River-3278':'one-time-credential';
    id('new-password').value=' Copper!Forest-9372 ';
    id('confirm-password').value=confirm;
    id('password-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();
  },async idle(){for(let i=0;i<100;i++){if(!id('password-submit').disabled)return;await tick();}assert.fail('Password page did not settle');}};
}
test('confirmation mismatch sends nothing and clears all secret inputs',async t=>{
  const a=await setup(t);await a.submit('wrong');
  assert.equal(a.calls.length,0);assert.match(a.id('password-status').textContent,/不一致/);
  assert.equal(a.id('new-password').value,'');assert.equal(a.id('current-password').value,'');
});
test('change submits whitelist, retains spaces and requires fresh login',async t=>{
  const a=await setup(t);await a.submit();await a.idle();
  assert.deepEqual(a.calls[1].payload,{currentPassword:'Old!River-3278',newPassword:' Copper!Forest-9372 '});
  assert.equal(a.calls[1].options.headers['X-CSRFToken'],'fresh');
  assert.equal(a.id('password-form').hidden,true);assert.equal(a.id('password-login').hidden,false);
  assert.match(a.id('password-status').textContent,/旧登录已失效/);
});
test('reset credential is sent only in POST body and never persisted',async t=>{
  const a=await setup(t,'reset');await a.submit();await a.idle();
  assert.equal(a.calls[1].url,'/auth/password/reset');assert.equal(a.calls[1].payload.credential,'one-time-credential');
  assert.equal(a.calls.some(c=>c.url.includes('one-time-credential')),false);
  assert.equal(a.id('reset-credential').value,'');assert.equal(a.w.localStorage.length,0);assert.equal(a.w.sessionStorage.length,0);
});
test('old password failure does not retry or falsely report success',async t=>{
  const a=await setup(t);a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'}):fail('current_password_invalid'));
  await a.submit();await a.idle();assert.equal(a.calls.length,2);assert.equal(a.id('password-form').hidden,false);
  assert.match(a.id('password-status').textContent,/重新填写/);assert.equal(a.id('current-password').value,'');
});
test('network loss reports uncertainty and never replays mutation',async t=>{
  const a=await setup(t);a.respond(url=>{if(url==='/auth/csrf')return ok({csrfToken:'fresh'});throw new Error('lost response');});
  await a.submit();await a.idle();assert.equal(a.calls.length,2);assert.match(a.id('password-status').textContent,/结果未确认/);
});
test('expired authentication returns user to login',async t=>{
  const a=await setup(t);a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'}):fail('authentication_required'));
  await a.submit();await a.idle();assert.equal(a.id('password-form').hidden,true);assert.equal(a.id('password-login').hidden,false);
});
test('pending submit disables duplicate requests',async t=>{
  const a=await setup(t);let release;a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'}):new Promise(resolve=>{release=resolve;}));
  await a.submit();a.id('password-form').dispatchEvent(new a.w.Event('submit',{cancelable:true}));
  assert.equal(a.calls.length,2);release(fail('csrf_failed'));await a.idle();assert.match(a.id('password-status').textContent,/安全校验/);
});
test('hiding before CSRF completes cancels later mutation and clears secrets',async t=>{
  const a=await setup(t);let release;a.respond(()=>new Promise(resolve=>{release=resolve;}));
  await a.submit();a.w.dispatchEvent(new a.w.Event('pagehide'));release(ok({csrfToken:'fresh'}));await a.idle();
  assert.equal(a.calls.length,1);assert.equal(a.id('new-password').value,'');
});
test('invalid reset credential stays generic and clears credential input',async t=>{
  const a=await setup(t,'reset');a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'}):fail('reset_invalid'));
  await a.submit();await a.idle();assert.match(a.id('password-status').textContent,/固定安全提示/);assert.equal(a.id('reset-credential').value,'');
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const sdk=fs.readFileSync(path.join(root,'static/js/chapter-sdk.js'),'utf8');
const ui=fs.readFileSync(path.join(root,'static/js/game.js'),'utf8');
const html=fs.readFileSync(path.join(root,'templates/game.html'),'utf8').replace(/\{%.*?%\}/g,'');
const ok=data=>({ok:true,json:async()=>({ok:true,data})});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const state=()=>({chapterId:'sample-counting',schemaVersion:1,revision:0,questionBank:{bankId:'sample-arithmetic',version:'1'},state:{story:{scene:'gate',quest:'not_started',talkedToNpc:false},practice:{bankId:'sample-arithmetic',bankVersion:'1',answers:[null,null,null]}},result:null});
async function setup(t,withUI=false){
  const dom=new JSDOM(html,{url:'http://localhost/game/',runScripts:'outside-only',pretendToBeVisual:true});t.after(()=>dom.window.close());
  const w=dom.window;
  if(w.document.readyState!=='complete')await new Promise(resolve=>w.addEventListener('load',resolve,{once:true}));
  let respond=url=>ok(url==='/auth/csrf'?{csrfToken:'fresh'}:{saveContext:'context',progress:state(),questions:[{questionId:'a',prompt:'2 + 3 = ?'}]});
  const calls=[];
  w.fetch=async(url,options)=>{calls.push({url,options,payload:options.body&&JSON.parse(options.body)});return respond(url,options);};
  w.eval(sdk);
  const a={w,calls,id:name=>w.document.getElementById(name),respond:fn=>{respond=fn;}};
  if(withUI)w.eval(ui);
  return a;
}
test('SDK reports server progress and scores via callbacks without persistent storage',async t=>{
  const a=await setup(t);let progress,score;
  const client=new a.w.HuaxiaChapterClient('sample-counting',{onProgress:p=>{progress=p;},onScore:s=>{score=s;}});
  await client.load();assert.equal(progress.revision,0);
  a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'}):ok({saveContext:'context',progress:{...state(),revision:1,result:{score:60,maxScore:100}}}));
  await client.dispatch('submit');assert.equal(score.score,60);
  assert.equal(a.calls.at(-1).payload.saveContext,'context');assert.equal(a.calls.at(-1).payload.revision,0);
  assert.equal(a.calls.at(-1).options.headers['X-CSRFToken'],'fresh');
  assert.equal(a.w.localStorage.length,0);assert.equal(a.w.sessionStorage.length,0);
});
test('SDK duplicate concurrent action sends only once',async t=>{
  const a=await setup(t);const client=new a.w.HuaxiaChapterClient('sample-counting');await client.load();
  let release;a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'}):new Promise(resolve=>{release=resolve;}));
  const first=client.dispatch('talk');await tick();
  await assert.rejects(client.dispatch('talk'));
  assert.equal(a.calls.filter(c=>c.options.method==='POST').length,1);
  release(ok({saveContext:'context',progress:{...state(),revision:1}}));await first;
});
test('SDK lost response is not automatically replayed',async t=>{
  const a=await setup(t);const client=new a.w.HuaxiaChapterClient('sample-counting');await client.load();
  a.respond(url=>{if(url==='/auth/csrf')return ok({csrfToken:'fresh'});throw Error('lost');});
  await assert.rejects(client.dispatch('submit'));
  assert.equal(a.calls.filter(c=>c.options.method==='POST').length,1);
});
test('SDK invalidate during load prevents stale callbacks',async t=>{
  const a=await setup(t);let release,callbacks=0;a.respond(()=>new Promise(resolve=>{release=resolve;}));
  const client=new a.w.HuaxiaChapterClient('sample-counting',{onProgress:()=>callbacks++});
  const promise=client.load();client.invalidate();release(ok({saveContext:'old',progress:state()}));
  await assert.rejects(promise);assert.equal(callbacks,0);assert.equal(client.progress,null);
});
test('game shell clears account data after login failure',async t=>{
  const a=await setup(t,true);
  a.respond(()=>({ok:false,json:async()=>({ok:false,error:{code:'authentication_required'}})}));
  a.w.dispatchEvent(new a.w.Event('pageshow'));
  for(let i=0;i<30&&!a.id('game-status').textContent.includes('登录已失效');i++)await tick();
  assert.equal(a.id('play').hidden,true);assert.equal(a.id('chapter-map').hidden,true);
  assert.match(a.id('game-status').textContent,/登录已失效/);
});
test('game return does not allow a stale chapter listing to expose a hidden page',async t=>{
  const a=await setup(t,true);let release;
  a.respond(()=>new Promise(resolve=>{release=resolve;}));
  a.w.dispatchEvent(new a.w.Event('pageshow'));await tick();
  a.w.dispatchEvent(new a.w.Event('pagehide'));
  release(ok({chapters:[{chapterId:'sample-counting',title:'样例'}]}));await tick();await tick();
  assert.equal(a.calls.length,1);assert.equal(a.id('play').hidden,true);assert.equal(a.id('chapter-map').hidden,true);
});

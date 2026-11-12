/* 任务栏组件的契约（static/js/quest.js）。
 *
 * 这是 B 对 A 的接口，所以测的不是「字对不对」，而是几条容易做坏的约定：
 * 1. 组件不认识页面：同一个挂载点 + 章节 id 就能用，多挂一次不叠两层；
 * 2. 未接任务 / 没有文案数据时整条栏不出现，绝不画半个空栏；
 * 3. 存档推过来就渲染、不重复请求；refresh() 才真的重新读一次；
 * 4. 本章存档看不出某一步时标 unknown，而不是猜一个勾。
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');

const root=path.resolve(__dirname,'..');
const sdk=fs.readFileSync(path.join(root,'static/js/chapter-sdk.js'),'utf8');
const ui=fs.readFileSync(path.join(root,'static/js/quest.js'),'utf8');

const META={title:'算坊初试 · 清点三道数',route:'main',objective:'与守门人谈妥差事，往算坊清点三道算式，回城门呈上。',
  steps:[{kind:'talk',text:'与守门人谈妥差事'},{kind:'answers',text:'在算坊清点三道算式'},{kind:'submit',text:'回城门呈上验符'}]};

const ok=data=>({ok:true,json:async()=>({ok:true,data})});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const until=async(fn,limit=40)=>{for(let i=0;i<limit&&!fn();i++)await tick();};

function progressOf({story=null,practice=null,result=null,chapterId='sample-counting'}={}){
  const state={};
  if(story)state.story=story;
  if(practice)state.practice=practice;
  return {chapterId,revision:1,questionBank:{bankId:'bank',version:'1'},state,result};
}
const accepted=extra=>progressOf({story:{quest:'accepted',talkedToNpc:true},practice:{answers:[5,12,null]},...extra});

function shell({meta=META,variant='full'}={}){
  return `<!doctype html><html><body>
  <div id="quest-slot" data-variant="${variant}" hidden></div>
  ${meta?`<script id="quest-meta" type="application/json">${JSON.stringify(meta)}</script>`:''}
  </body></html>`;
}

async function boot(t,{variant='full',meta=META,progress=accepted()}={}){
  const dom=new JSDOM(shell({meta,variant}),{url:'http://localhost/game/level/tc-nand',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window;
  if(w.document.readyState!=='complete')await new Promise(resolve=>w.addEventListener('load',resolve,{once:true}));
  let respond=()=>ok({saveContext:'ctx',progress});
  const calls=[];
  w.fetch=async url=>{calls.push(String(url));return respond();};
  w.eval(sdk);
  w.eval(ui);
  const a={
    w,calls,
    id:name=>w.document.getElementById(name),
    part:name=>w.document.querySelector(`#quest-slot [data-quest-part="${name}"]`),
    mount:(chapterId='sample-counting')=>w.HuaxiaQuestBar.mountQuestBar(w.document.getElementById('quest-slot'),chapterId),
    respond:fn=>{respond=fn;},
  };
  return a;
}

test('未接任务时任务栏不出现',async t=>{
  const a=await boot(t,{progress:progressOf({story:{quest:'not_started',talkedToNpc:false},practice:{answers:[null,null,null]}})});
  a.mount();
  await until(()=>a.calls.some(url=>String(url).includes('/progress')));
  assert.equal(a.id('quest-slot').hidden,true,'未接任务时整条栏都该藏着');
});

test('没有文案数据时宁可不画，也不留一个空栏',async t=>{
  const a=await boot(t,{meta:null});
  a.mount();
  await tick();await tick();
  assert.equal(a.id('quest-slot').hidden,true);
});

test('接任务后显示标题、路线、状态与真实答题进度',async t=>{
  const a=await boot(t);
  a.mount();
  await until(()=>a.part('title').textContent.length>0);
  assert.equal(a.id('quest-slot').hidden,false);
  assert.equal(a.part('title').textContent,'算坊初试 · 清点三道数');
  assert.equal(a.part('route').textContent,'主线');
  assert.equal(a.part('state').textContent,'进行中');
  assert.equal(a.part('objective').textContent,META.objective);
  const steps=[...a.part('steps').children];
  assert.deepEqual(steps.map(li=>li.dataset.done),['true','false','false']);
  assert.match(steps[1].textContent,/（2\/3）/,'三道题填了两道，就该报 2/3');
});

test('紧凑版只留标题和状态，不展开步骤',async t=>{
  const a=await boot(t,{variant:'compact'});
  a.mount();
  await until(()=>a.part('title').textContent.length>0);
  assert.equal(a.id('quest-slot').hidden,false);
  assert.ok(a.part('title').textContent);
  assert.equal(a.part('body').hidden,true,'紧凑版不展开正文');
  assert.equal(a.part('toggle').hidden,true,'紧凑版没有收起按钮');
});

test('本章存档看不出某一步时标 unknown，而不是假装完成',async t=>{
  // 电路章节的存档只有 circuit.levels，没有 story / practice。
  const a=await boot(t,{progress:progressOf({chapterId:'xia-circuit'})});
  a.mount('xia-circuit');
  await until(()=>a.part('title').textContent.length>0);
  const steps=[...a.part('steps').children];
  assert.deepEqual(steps.map(li=>li.dataset.done),['unknown','unknown','false']);
  assert.match(steps[0].title,/不记录/,'要说清为什么没勾，而不是默默留空');
  assert.equal(a.part('state').textContent,'进行中');
});

test('页面推来的存档直接渲染，不再自己打一次 /progress',async t=>{
  const a=await boot(t);
  const bar=a.mount();
  await until(()=>a.part('title').textContent.length>0);
  const readsBefore=a.calls.filter(url=>url.includes('/progress')).length;
  bar.render(progressOf({chapterId:'sample-counting',story:{quest:'submitted',talkedToNpc:true},
    practice:{answers:[5,12,13]},result:{score:100,maxScore:100}}));
  assert.equal(a.calls.filter(url=>url.includes('/progress')).length,readsBefore,'推送路径不该再请求');
  assert.equal(a.part('state').textContent,'已通过 · 100 / 100');
  assert.equal(a.part('state').dataset.tone,'pass');
});

test('差几分就照实说未通过，核验中不预告结果',async t=>{
  const a=await boot(t);
  const bar=a.mount();
  await until(()=>a.part('title').textContent.length>0);

  bar.setPending(true);
  assert.equal(a.part('state').textContent,'核验中…');
  assert.equal(a.part('state').dataset.tone,undefined);

  bar.render(progressOf({chapterId:'sample-counting',story:{quest:'submitted'},practice:{answers:[5,12,0]},
    result:{score:60,maxScore:100}}));
  bar.setPending(false);
  assert.equal(a.part('state').textContent,'未通过 · 60 / 100');
  assert.equal(a.part('state').dataset.tone,'fail');
});

test('refresh() 才重新读存档，且同一挂载点重复挂载不叠两层',async t=>{
  const a=await boot(t);
  const first=a.mount();
  const second=a.mount();
  assert.equal(first,second,'同一挂载点应复用同一个句柄');
  await until(()=>a.part('title').textContent.length>0);
  assert.equal(a.id('quest-slot').children.length,1,'不该叠出第二层卡片');

  const readsBefore=a.calls.filter(url=>url.includes('/progress')).length;
  a.respond(()=>ok({saveContext:'ctx',progress:progressOf({chapterId:'sample-counting',
    story:{quest:'submitted'},practice:{answers:[5,12,13]},result:{score:60,maxScore:100}})}));
  await a.w.HuaxiaQuestBar.refresh();
  assert.equal(a.calls.filter(url=>url.includes('/progress')).length,readsBefore+1);
  assert.equal(a.part('state').textContent,'未通过 · 60 / 100');
});

test('读不到存档（未登录/断网）时静默隐藏，不把异常抛给页面',async t=>{
  const a=await boot(t);
  a.respond(()=>({ok:false,json:async()=>({ok:false,error:{code:'authentication_required'}})}));
  a.mount();
  await tick();await tick();await tick();
  assert.equal(a.id('quest-slot').hidden,true);
});

test('非计分章节不会显示「已通过 null / null」',async t=>{
  // grade=None 的章节（纯剧情 / 将来拆出去的通道）结算后有提交时间但没有分数。
  const a=await boot(t,{progress:progressOf({chapterId:'story-only',
    result:{score:null,maxScore:null,submittedAt:'2026-10-30T12:00:00+08:00'}})});
  a.mount('story-only');
  await until(()=>a.part('title').textContent.length>0);
  assert.equal(a.id('quest-slot').hidden,false);
  assert.equal(a.part('state').textContent,'已提交 · 不计分');
  assert.equal(a.part('state').dataset.tone,undefined,'不计分就不该带通过/不通过的颜色');
});

test('多 NPC 章节：任务状态按挂载点的 data-npc 取，不被别的 NPC 带动',async t=>{
  const npcId='wu-ding';
  const court=(quest,talked)=>({chapterId:'xia-court',schemaVersion:1,revision:1,
    questionBank:{bankId:'',version:'1'},
    state:{npcs:{
      [npcId]:{talkedToNpc:talked,quest,dialogue:null},
      'fu-hao':{talkedToNpc:true,quest:'accepted',dialogue:null},
    },flags:{},cleared:[],rewards:{}},
    result:null});

  // 未接任务：整条栏不出现（哪怕同一个章节里另一个 NPC 已经接了任务）
  const fresh=await boot(t,{progress:court('not_started',false)});
  fresh.id('quest-slot').dataset.npc=npcId;
  fresh.mount('xia-court');
  await tick();await tick();
  assert.equal(fresh.id('quest-slot').hidden,true,'这个 NPC 还没接任务，栏就不该出现');

  // 已接任务：出现，且 talk 步按"这个 NPC"的 talkedToNpc 打勾
  const taken=await boot(t,{progress:court('accepted',true)});
  taken.id('quest-slot').dataset.npc=npcId;
  taken.mount('xia-court');
  await until(()=>taken.part('title').textContent.length>0);
  assert.equal(taken.id('quest-slot').hidden,false);
  assert.equal(taken.part('state').textContent,'进行中');
  assert.equal([...taken.part('steps').children][0].dataset.done,'true');
});

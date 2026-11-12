/* 全屏剧情层的 DOM 行为。
 *
 * 重点不是「字有没有显示」，而是几条容易做坏的规则：
 * 1. 翻页必须是纯本地动作，不发请求；
 * 2. 跳过只能停在选项之前，不能替玩家做会改存档的选择；
 * 3. 打字未完成时第一次点击是「显示完整」，不是「跳到下一句」。
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');

const root=path.resolve(__dirname,'..');
const sdk=fs.readFileSync(path.join(root,'static/js/chapter-sdk.js'),'utf8');
const ui=fs.readFileSync(path.join(root,'static/js/story.js'),'utf8');
// 任务栏已抽成独立组件（static/js/quest.js），剧情页挂的是精简版。
const questUi=fs.readFileSync(path.join(root,'static/js/quest.js'),'utf8');
const QUEST_META={title:'算坊初试 · 清点三道数',route:'main',objective:'往算坊清点三道算式，回城门呈上。',
  steps:[{kind:'talk',text:'与守门人谈妥差事'},{kind:'answers',text:'在算坊清点三道算式'},{kind:'submit',text:'回城门呈上验符'}]};

const NPC={name:'守门人',title:'城门卫',seal:'卫',color:'#8c5a2b',portrait:''};
const STAGE={episode:{title:'铸算·夏',operation:'城门前的差事',phase:'行动前',summary:'摘要。'},
  background:'img/story/bg-shan-shui.jpg',then:{label:'前往算坊',url:'/game/level/tc-nand'},npc:NPC,npcId:'gate.keeper'};

const raw=fs.readFileSync(path.join(root,'templates/story.html'),'utf8');
const html=raw.replace(/\{%[^%]*%\}/g,'')
  .replace('{{ stage|json_script:"story-data" }}',`<script id="story-data" type="application/json">${JSON.stringify(STAGE)}</script>`)
  .replace('{{ quest|json_script:"quest-meta" }}',`<script id="quest-meta" type="application/json">${JSON.stringify(QUEST_META)}</script>`)
  .replace(/\{\{\s*chapter_id\s*\}\}/g,'sample-counting')
  .replace(/\{\{\s*npc_id\s*\}\}/g,'gate.keeper')
  .replace(/\{\{\s*next_url\s*\}\}/g,'/game/level/tc-nand')
  .replace(/\{\{\s*back_url\s*\}\}/g,'/game/map')
  .replace(/\{\{\s*stage\.then\.label\s*\}\}/g,'前往算坊')
  .replace(/\{\{\s*stage\.episode\.title\s*\}\}/g,'铸算·夏')
  .replace(/\{\{\s*stage\.episode\.operation\s*\}\}/g,'城门前的差事')
  .replace(/\{\{\s*stage\.episode\.phase\s*\}\}/g,'行动前')
  .replace(/\{\{\s*stage\.episode\.summary\s*\}\}/g,'摘要。');

const ok=data=>({ok:true,json:async()=>({ok:true,data})});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
// 打字机是 26ms 的定时器，只让出 microtask 是等不到的，必须真的等真实时间。
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async(fn,limit=240)=>{for(let i=0;i<limit&&!fn();i++)await wait(5);};

const offerPages=()=>[
  {nodeId:'intro',lines:['站住。','你这身打扮，倒不像奸细。']},
  {nodeId:'offer',lines:['我这儿有一桩差事。'],choices:[
    {id:'take',text:'接下这桩差事',command:{action:'accept'}},
    {id:'decline',text:'容我再想想'},
  ]},
];
const onTaskPages=()=>[{nodeId:'on-task',lines:['差事已在你名下。']}];

function progressOf(dialogue,extra={}){
  return {chapterId:'sample-counting',schemaVersion:1,revision:1,
    questionBank:{bankId:'sample-arithmetic',version:'1'},
    state:{story:{scene:'gate',talkedToNpc:true,quest:'not_started',dialogue,...extra},
      practice:{bankId:'sample-arithmetic',bankVersion:'1',answers:[null,null,null]}},
    result:null};
}

async function boot(t,{progress,pages=offerPages()}={}){
  const dom=new JSDOM(html,{url:'http://localhost/game/story/',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window;
  if(w.document.readyState!=='complete')await new Promise(resolve=>w.addEventListener('load',resolve,{once:true}));
  let current=progress||progressOf({npcId:'gate.keeper',speaker:NPC,pages});
  let respond=url=>url==='/auth/csrf'?ok({csrfToken:'fresh'})
    :ok({saveContext:'context',progress:current,questions:[]});
  const calls=[];
  w.fetch=async(url,options)=>{calls.push({url,options,payload:options.body&&JSON.parse(options.body)});return respond(url,options);};
  w.eval(sdk);
  const a={w,calls,
    id:name=>w.document.getElementById(name),
    qp:name=>w.document.querySelector(`#quest-slot [data-quest-part="${name}"]`),
    respond:fn=>{respond=fn;}};
  w.eval(questUi);
  w.eval(ui);
  await until(()=>a.id('story-text').textContent.length>0);
  return a;
}

/** 反复点击舞台推进；打字未完成时第一次点击只是显示完整。 */
async function drive(a,predicate,limit=80){
  for(let i=0;i<limit&&!predicate();i++){a.id('story-stage').click();await tick();}
  assert.ok(predicate(),'没有推进到预期状态');
}

test('story shows one line at a time and never requests while paging',async t=>{
  const a=await boot(t);
  assert.equal(a.id('story-speaker-name').textContent,'守门人');
  await until(()=>a.id('story-text').textContent==='站住。');
  const postsBefore=a.calls.filter(c=>c.options.method==='POST').length;

  await drive(a,()=>a.id('story-text').textContent==='你这身打扮，倒不像奸细。');
  await drive(a,()=>a.id('story-text').textContent==='我这儿有一桩差事。');
  assert.equal(a.calls.filter(c=>c.options.method==='POST').length,postsBefore,'翻页不该产生请求');
});

test('choices appear only after the last line, and take dispatches one accept',async t=>{
  const a=await boot(t);
  await drive(a,()=>a.id('story-choices').children.length>0);
  assert.deepEqual([...a.id('story-choices').children].map(b=>b.textContent),
    ['接下这桩差事','容我再想想']);

  a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'})
    :ok({saveContext:'context',progress:progressOf({npcId:'gate.keeper',speaker:NPC,pages:onTaskPages()},{quest:'accepted'}),questions:[]}));
  [...a.id('story-choices').children].find(b=>b.textContent==='接下这桩差事').click();
  await until(()=>a.id('story-text').textContent==='差事已在你名下。');

  const posts=a.calls.filter(c=>c.options.method==='POST');
  assert.equal(posts.length,1,'只应有一次 accept 提交');
  assert.equal(posts[0].payload.action,'accept');
});

test('declining a choice leaves the story without any request',async t=>{
  const a=await boot(t);
  await drive(a,()=>a.id('story-choices').children.length>0);
  const postsBefore=a.calls.filter(c=>c.options.method==='POST').length;
  [...a.id('story-choices').children].find(b=>b.textContent==='容我再想想').click();
  await tick();
  assert.equal(a.calls.filter(c=>c.options.method==='POST').length,postsBefore,'拒绝不该产生请求');
  // jsdom 不实现真实跳转，这里验证离开状态已被标记（真实浏览器会跳回 back 地址）。
  assert.ok(a.id('story-stage').classList.contains('leaving'),'应进入离开状态回到宿主页面');
});

test('skip confirms first and stops before the choice instead of deciding for the player',async t=>{
  const a=await boot(t);
  await until(()=>a.id('story-text').textContent==='站住。');
  a.id('story-skip').click();
  assert.equal(a.id('story-skip-modal').hidden,false,'跳过应先弹确认');
  assert.match(a.id('story-skip-modal').textContent,/是否跳过剧情/);
  assert.match(a.id('story-skip-modal').textContent,/铸算·夏/);

  a.id('story-skip-yes').click();
  await tick();
  assert.equal(a.id('story-skip-modal').hidden,true);
  assert.equal(a.id('story-choices').children.length,2,'跳过必须停在选项处，不能替玩家接任务');
  assert.equal(a.calls.filter(c=>c.options.method==='POST').length,0,'跳过不该产生请求');
});

test('skip on a choice-free script goes straight to the end card',async t=>{
  const pages=[{nodeId:'thanks',lines:['算得不错。','进城吧。']}];
  const a=await boot(t,{pages,progress:progressOf({npcId:'gate.keeper',speaker:NPC,pages},{quest:'accepted'})});
  await until(()=>a.id('story-text').textContent==='算得不错。');
  a.id('story-skip').click();
  a.id('story-skip-yes').click();
  await until(()=>a.id('story-end').hidden===false);
  assert.equal(a.id('story-end').hidden,false);
  assert.equal(a.id('story-next').getAttribute('href'),'/game/level/tc-nand');
});

test('the end card appears after the last line and points at the level',async t=>{
  const pages=[{nodeId:'thanks',lines:['算得不错。']}];
  const a=await boot(t,{pages,progress:progressOf({npcId:'gate.keeper',speaker:NPC,pages},{quest:'accepted'})});
  await drive(a,()=>a.id('story-end').hidden===false);
  assert.match(a.id('story-next').textContent,/前往算坊/);
});

test('the dialogue log keeps every line already shown',async t=>{
  const a=await boot(t);
  await drive(a,()=>a.id('story-text').textContent==='你这身打扮，倒不像奸细。');
  a.id('story-log-btn').click();
  assert.equal(a.id('story-log').hidden,false);
  const items=[...a.id('story-log-list').children].map(li=>li.textContent);
  assert.ok(items.some(text=>text.includes('站住。')),'记录里应含第一句');
  assert.ok(items.some(text=>text.includes('倒不像奸细')),'记录里应含当前句');
  a.id('story-log-close').click();
  assert.equal(a.id('story-log').hidden,true);
});

test('a portrait-less npc falls back to the seal glyph instead of a blank box',async t=>{
  const a=await boot(t);
  const portrait=a.id('story-portrait');
  assert.equal(portrait.textContent.trim(),'卫');
  assert.equal(portrait.querySelector('img'),null);
  assert.ok(portrait.classList.contains('seal-panel'));
});

test('clicks on the tool bar do not advance the script',async t=>{
  const a=await boot(t);
  await until(()=>a.id('story-text').textContent==='站住。');
  a.id('story-hide').click();
  assert.ok(a.id('story-stage').classList.contains('ui-hidden'));
  assert.equal(a.id('story-text').textContent,'站住。','点工具按钮不该翻页');
  a.id('story-hide').click();
  assert.equal(a.id('story-stage').classList.contains('ui-hidden'),false);
});

test('an already submitted chapter shows the archived notice instead of talking again',async t=>{
  const progress={...progressOf(null,{quest:'submitted'}),result:{score:100,maxScore:100,submittedAt:'2026-11-06T10:00:00Z'}};
  progress.state.story.dialogue=null;
  const a=await boot(t,{progress});
  await until(()=>a.id('story-end').hidden===false);
  assert.match(a.id('story-end-note').textContent,/已结算/);
  assert.equal(a.calls.filter(c=>c.options.method==='POST').length,0,'已结算章节不该再 talk');
});

// ---------- 任务栏（精简版，挂左上角） ----------
test('剧情页开始时不显示任务栏：任务还没接',async t=>{
  const a=await boot(t);
  await until(()=>a.id('story-text').textContent.length>0);
  assert.equal(a.id('quest-slot').hidden,true,'未接任务时角落不该出现任务栏');
});

test('接下差事后角落出现精简任务栏，且不占用台词的位置',async t=>{
  const a=await boot(t);
  const accepted=progressOf({npcId:'gate.keeper',speaker:NPC,pages:onTaskPages()},{quest:'accepted'});
  a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'})
    :ok({saveContext:'context',progress:accepted,questions:[]}));

  await drive(a,()=>a.id('story-choices').children.length>0);
  [...a.id('story-choices').children].find(b=>b.textContent==='接下这桩差事').click();
  await until(()=>a.id('quest-slot').hidden===false);

  assert.equal(a.id('quest-slot').hidden,false,'接任务后角落应出现任务栏');
  assert.equal(a.qp('title').textContent,'算坊初试 · 清点三道数');
  assert.equal(a.qp('state').textContent,'进行中');
  assert.equal(a.qp('body').hidden,true,'精简版不展开步骤，避免遮住台词');
  assert.equal(a.qp('toggle').hidden,true,'精简版没有收起按钮');
  // 舞台仍在演出（接完任务后从头打下一段）：任务栏只是角落的一张卡，不接管舞台。
  assert.ok(a.id('story-dialogue').classList.contains('visible'),'台词区应仍然可见');
  assert.equal(a.id('story-speaker-name').textContent,'守门人');
});

test('选项里的 command 除 action 外原样转给服务端',async t=>{
  // 多 NPC 章节靠这个字段告诉服务端"这一页是谁在说话"。
  const pages=[
    {nodeId:'intro',lines:['站住。']},
    {nodeId:'ask',lines:['接是不接？'],choices:[
      {id:'take',text:'接下这桩差事',command:{action:'accept',npcId:'gate.keeper',flag:'gateWord'}},
    ]},
  ];
  const a=await boot(t,{pages});
  await drive(a,()=>a.id('story-choices').children.length>0);
  [...a.id('story-choices').children].find(b=>b.textContent==='接下这桩差事').click();
  await tick();await tick();

  const post=a.calls.find(c=>c.options.method==='POST'&&c.payload.action==='accept');
  assert.ok(post,'应该发出一次 accept');
  assert.equal(post.payload.npcId,'gate.keeper');
  assert.equal(post.payload.flag,'gateWord');
  // 基本字段仍在，且没有把 action 重复塞进 payload
  assert.equal(post.payload.action,'accept');
});

test('多 NPC 章节：对话快照放在 state.npcs[<npcId>] 里也能正常演',async t=>{
  // 夏社那类章节把每个 NPC 的状态分开存：state.npcs[npcId].dialogue。
  // 前端不能假设对话一定在 state.story.dialogue。
  const npcId='gate.keeper';
  const court=dil=>({chapterId:'xia-court',schemaVersion:1,revision:1,
    questionBank:{bankId:'',version:'1'},
    state:{npcs:{[npcId]:{talkedToNpc:true,quest:'not_started',dialogue:dil}},flags:{},cleared:[],rewards:{}},
    result:null});

  const a=await boot(t,{progress:court({npcId,speaker:NPC,pages:offerPages()})});
  await drive(a,()=>a.id('story-choices').children.length>0);
  a.respond(url=>url==='/auth/csrf'?ok({csrfToken:'fresh'})
    :ok({saveContext:'context',progress:court({npcId,speaker:NPC,pages:onTaskPages()}),questions:[]}));

  [...a.id('story-choices').children].find(b=>b.textContent==='接下这桩差事').click();
  await until(()=>a.id('story-text').textContent==='差事已在你名下。');

  assert.equal(a.id('story-status').textContent,'','不该把前端异常写进状态栏');
  assert.equal(a.id('story-end').hidden,true,'接完任务应该继续演，而不是直接跳到结束卡');
});

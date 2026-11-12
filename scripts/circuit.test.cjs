const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');

const root=path.resolve(__dirname,'..');
const sdk=fs.readFileSync(path.join(root,'static/js/chapter-sdk.js'),'utf8');
const ui=fs.readFileSync(path.join(root,'static/js/circuit.js'),'utf8');
// 任务栏已抽成独立组件（static/js/quest.js），电路页也要挂它。
const questUi=fs.readFileSync(path.join(root,'static/js/quest.js'),'utf8');
const QUEST_META={title:'铸铜工坊 · 验符',route:'main',objective:'验算电路并提交工数。',
  steps:[{kind:'answers',text:'通过电路验算'},{kind:'submit',text:'提交工数'}]};
const htmlRaw=fs.readFileSync(path.join(root,'templates/circuit.html'),'utf8').replace(/\{%.*?%\}/g,'');
// {{ initial_puzzle }} 由服务端渲染；测试里默认置空，需要时由 setup 注入。
const html=htmlRaw.replace("{{ initial_puzzle|default:'' }}",'')
  .replace('{{ quest|json_script:"quest-meta" }}',`<script id="quest-meta" type="application/json">${JSON.stringify(QUEST_META)}</script>`);

const ok=data=>({ok:true,status:200,json:async()=>({ok:true,data})});
const tick=()=>new Promise(resolve=>setImmediate(resolve));

const LEVELS=['tc-nand','tc-and'];

function puzzle(id,title){
  // 故意不带 id：后端详情响应曾经就是没有 id 的，前端不该依赖它。
  return {
    title,
    description:`${title}的说明`,
    components:['NAND'],
    inputs:['A','B'],
    outputs:['Y'],
    truthTable:[
      {inputs:[0,0],outputs:[1]},
      {inputs:[0,1],outputs:[1]},
      {inputs:[1,0],outputs:[1]},
      {inputs:[1,1],outputs:[0]},
    ],
    points:20,
  };
}

const DETAILS=Object.fromEntries(LEVELS.map(id=>[id,puzzle(id,`关卡 ${id}`)]));

// 剧情结构必须与 gameplay/data/circuit_story.json 一致；
// 改那边的字段时，这里的夹具要跟着改，否则测的不是真实形状。
const STORY={
  chapterTitle:'铸算·夏 · 铸铜工坊',
  chapterSubtitle:'受命铸符，以算定天下',
  npcs:{
    'wu-ding':{name:'武丁',title:'商王',seal:'丁',color:'#8c5a2b',portrait:''},
    'fu-hao':{name:'妇好',title:'商朝女将',seal:'好',color:'#7a3b45',portrait:'/static/img/portraits/fu-hao.png'},
  },
  opening:{speaker:'wu-ding',quest:'初入工坊',lines:['开场第一句','开场第二句']},
  levels:{
    'tc-nand':{speaker:'wu-ding',quest:'铸「与非符」',objective:'仅用一枚与非符。',
      intro:['入门第一句','入门第二句'],cleared:['通关台词'],hint:['卡住时的提示']},
    'tc-and':{speaker:'fu-hao',quest:'铸「与符」',objective:'两枚与非相叠。',
      intro:['妇好第一句'],cleared:['妇好婆奖'],hint:['妇好提示']},
  },
  closing:{speaker:'wu-ding',lines:['收尾一句']},
};

// 关卡结构：主线/支线/前置/区域。字段与 gameplay/data/level_meta.json 一致。
const CATALOG={levels:{
  'tc-nand':{route:'main',order:1,region:'铸铜工坊',requires:[]},
  'tc-and':{route:'side',order:1,region:'妇好营帐',requires:[]},
}};

function progress(levels={},result=null,extra={}){
  return {
    chapterId:'xia-circuit',
    schemaVersion:1,
    revision:3,
    questionBank:{bankId:'circuit-levels',version:'1'},
    state:{circuit:{levels,solvedOrder:Object.keys(levels),puzzleIds:LEVELS,
      attempts:[],pendingSettle:false,...extra}},
    result,
  };
}

// 一个 NAND 电路：两个输入各接一根线，输出接一根线。
const SAVED_LEVEL={
  passed:true,
  points:20,
  attempts:2,
  gates:[{id:'g1',type:'NAND',x:300,y:220}],
  wires:[
    {from:{gateId:'__in_A',port:'out'},to:{gateId:'g1',port:'in1'}},
    {from:{gateId:'__in_B',port:'out'},to:{gateId:'g1',port:'in2'}},
    {from:{gateId:'g1',port:'out'},to:{gateId:'__out_Y',port:'in1'}},
  ],
};

function solveAction(call,previous){
  const id=call.payload.puzzleId;
  const levels=JSON.parse(JSON.stringify(previous.state.circuit.levels));
  const level=levels[id]||{passed:false,points:0,attempts:0};
  level.attempts+=1;
  level.passed=true;
  level.points=20;
  level.lastResult={passed:true,points:20,cases:[{inputs:[0,0],expected:[1],actual:[1],pass:true}]};
  levels[id]=level;
  return ok({saveContext:'ctx-2',progress:progress(levels,null)});
}

function totalPoints(levels){
  return Object.values(levels).reduce((sum,level)=>sum+(level.passed?level.points:0),0);
}

/** settle：一次结算尝试。判分留档，只有满分才 pendingSettle。 */
function settleAction(previous){
  const levels=previous.state.circuit.levels;
  const score=totalPoints(levels);
  const passed=score>=100;
  const attempts=(previous.state.circuit.attempts||[]).concat(
    [{n:(previous.state.circuit.attempts||[]).length+1,score,maxScore:100,passed}]);
  return ok({saveContext:'ctx-settle',progress:progress(levels,null,{attempts,pendingSettle:passed})});
}

/** submit：真正的结算，前置是上一次尝试已通过。 */
function submitAction(previous){
  if(!previous.state.circuit.pendingSettle){
    return {ok:false,status:409,json:async()=>({ok:false,error:{code:'invalid_transition',message:'本章还没有通过结算尝试'}})};
  }
  const levels=previous.state.circuit.levels;
  return ok({saveContext:'ctx-3',progress:progress(levels,
    {score:totalPoints(levels),maxScore:100,submittedAt:'2026-10-30T12:00:00+08:00'},
    {attempts:previous.state.circuit.attempts||[],pendingSettle:false})});
}

async function setup(t,{levels={},result=null,actionHandler=null,storyOverride=null,initialPuzzle='',returnUrl='/game/#stage-select'}={}){
  const page=html.replace('data-initial-puzzle=""',`data-initial-puzzle="${initialPuzzle}"`)
    .replaceAll('{{ return_url }}',returnUrl);
  const dom=new JSDOM(page,{url:'http://localhost/game/circuit',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window;
  const alerts=[];
  w.alert=message=>alerts.push(message);
  w.confirm=()=>true;

  // 统计 window 级监听器：拖拽监听器必须只注册一次，不能随渲染堆积。
  const windowListeners={};
  const nativeAdd=w.addEventListener.bind(w);
  w.addEventListener=(type,...rest)=>{
    windowListeners[type]=(windowListeners[type]||0)+1;
    return nativeAdd(type,...rest);
  };

  if(w.document.readyState!=='complete'){
    await new Promise(resolve=>w.addEventListener('load',resolve,{once:true}));
  }

  let current=progress(levels,result);
  const calls=[];
  w.fetch=async(url,options)=>{
    const call={
      url:String(url),
      options:options||{},
      payload:options&&options.body?JSON.parse(options.body):null,
    };
    calls.push(call);
    if(call.url==='/game/api/circuit/story')return storyOverride?storyOverride():ok({story:STORY,catalog:CATALOG});
    if(call.url==='/game/api/circuit/puzzles')return ok({puzzles:LEVELS.map(id=>({id,title:DETAILS[id].title,description:DETAILS[id].description}))});
    if(call.url.startsWith('/game/api/circuit/puzzles/')){
      const id=call.url.split('/').pop();
      return ok({puzzle:DETAILS[id]});
    }
    if(call.url==='/game/api/chapters/xia-circuit/progress')return ok({saveContext:'ctx-1',progress:current,questions:[]});
    if(call.url==='/auth/csrf')return ok({csrfToken:'fresh'});
    if(call.url==='/game/api/chapters/xia-circuit/action'){
      const settled=actionHandler
        ? actionHandler(call,current)
        : (call.payload.action==='submit'?submitAction(current)
          :call.payload.action==='settle'?settleAction(current)
          :solveAction(call,current));
      const body=await settled.json();
      if(body.ok)current=body.data.progress;
      return settled;
    }
    throw new Error(`未预期的请求 ${call.url}`);
  };

  w.eval(sdk);
  w.eval(questUi);
  w.eval(ui);
  // circuit.js 在 DOMContentLoaded 上启动；jsdom 已完成加载时需要手动触发。
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  for(let i=0;i<40;i++)await tick();

  return {
    w,
    calls,
    alerts,
    windowListeners,
    id:name=>w.document.getElementById(name),
    query:selector=>w.document.querySelector(selector),
    qp:name=>w.document.querySelector(`#quest-slot [data-quest-part="${name}"]`),
    queryAll:selector=>Array.from(w.document.querySelectorAll(selector)),
  };
}

test('关卡列表与真值表能真正渲染出来（后端 {ok,data} 信封必须被拆开）',async t=>{
  const a=await setup(t);
  assert.deepEqual(a.alerts,[]);
  const options=a.queryAll('#puzzle-select option');
  assert.equal(options.length,2);
  // 有剧情数据时，任务下拉显示的是委托名而不是关卡原名
  assert.equal(options[0].textContent,'铸「与非符」');
  // 列表只给摘要，真值表必须来自详情接口——这一行保证编辑器走的是详情而不是列表。
  assert.equal(a.queryAll('#truth-table tbody tr').length,4);
  // 卦象列 + 两个输入 + 一个输出 = 4 列
  assert.equal(a.queryAll('#truth-table tbody tr')[0].children.length,4);
  assert.equal(a.queryAll('#truth-table tbody tr')[0].querySelectorAll('.yao-bar').length,3);
  assert.match(a.id('puzzle-title').textContent,/铸「与非符」/);
});

test('已通关的存档能还原电路，连线真的画在画布上',async t=>{
  const a=await setup(t,{levels:{'tc-nand':SAVED_LEVEL}});
  const wires=a.queryAll('#wires-layer path.wire');
  // 三根线：A→NAND.in1、B→NAND.in2、NAND.out→Y。字段名对不上时这里是 0。
  assert.equal(wires.length,3);
  for(const wire of wires)assert.ok(wire.getAttribute('d'),'连线必须有路径数据');
  // 三个固定端点 + 还原出来的 NAND 门
  assert.equal(a.queryAll('#gates-layer g.gate').length,4);
});

test('从真值表切换试演用例，结束试演后清除输出',async t=>{
  const a=await setup(t,{levels:{'tc-nand':SAVED_LEVEL}});
  const cases=a.queryAll('[data-sim-case]');
  a.id('btn-sim').click();
  assert.equal(a.id('actual-outs').textContent,'Y=1');

  cases[3].click();
  assert.equal(a.id('sim-case').textContent,'4 / 4');
  assert.equal(cases[3].getAttribute('aria-current'),'true');
  assert.equal(cases[0].getAttribute('aria-current'),'false');
  assert.equal(a.id('actual-outs').textContent,'Y=0');

  a.id('sim-next').click();
  assert.equal(a.id('actual-outs').textContent,'Y=1');
  a.id('btn-stop').click();
  assert.match(a.id('actual-outs').textContent,/等待模拟/);
  assert.deepEqual(a.alerts,[]);
});

test('点击组件库能往画布上加门',async t=>{
  const a=await setup(t);
  const before=a.queryAll('#gates-layer g.gate').length;
  a.query('#palette-gates .palette-gate').click();
  assert.equal(a.queryAll('#gates-layer g.gate').length,before+1);
});

test('提交本关走章节接口，不再请求那条不入库的旁路',async t=>{
  const a=await setup(t);
  a.query('#palette-gates .palette-gate').click();
  a.id('btn-submit').click();
  for(let i=0;i<20;i++)await tick();

  assert.equal(a.calls.some(call=>call.url.includes('/grade')),false,'不应再调用 /grade');
  const posts=a.calls.filter(call=>call.options.method==='POST');
  assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/game/api/chapters/xia-circuit/action');
  assert.equal(posts[0].payload.action,'solve');
  assert.equal(posts[0].payload.puzzleId,'tc-nand');
  assert.ok(Array.isArray(posts[0].payload.gates));
  assert.ok(Array.isArray(posts[0].payload.wires));
  assert.equal(posts[0].options.headers['X-CSRFToken'],'fresh');
});

test('服务端的判分结果直接填进结果面板',async t=>{
  const a=await setup(t);
  a.query('#palette-gates .palette-gate').click();
  a.id('btn-submit').click();
  for(let i=0;i<30;i++)await tick();
  assert.equal(a.id('result-panel').hidden,false);
  assert.match(a.id('result-text').textContent,/验收通过/);
  assert.match(a.id('result-text').textContent,/20/);
  assert.match(a.id('result-details').innerHTML,/truth-table/);
});

test('进度条反映已通关关数，没全通也能点结算（会记为未通过）',async t=>{
  const a=await setup(t,{levels:{'tc-nand':SAVED_LEVEL}});
  assert.match(a.id('chapter-status').textContent,/已通关 1 \/ 2 关/);
  // 失败可重试：结算按钮不再藏起来，改成在提示里警告"未全通会记为未通过"。
  assert.equal(a.id('btn-settle').hidden,false);
  // 已通关的关卡在下拉里带对勾
  assert.match(a.queryAll('#puzzle-select option')[0].textContent,/^✓/);
});

test('满分结算：settle 判分 → submit 入库 → 显示总分并收起按钮',async t=>{
  const full={...SAVED_LEVEL,points:50};          // 两关各 50，凑满 100
  const both={'tc-nand':full,'tc-and':full};
  const a=await setup(t,{levels:both});

  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();

  const posts=a.calls.filter(call=>call.options.method==='POST');
  assert.deepEqual(posts.map(call=>call.payload.action),['settle','submit'],
    '先是一次结算尝试，通过后才是真正的结算');
  assert.match(a.id('chapter-status').textContent,/已结算：100 \/ 100 分/);
  assert.match(a.id('chapter-status').textContent,/可重做，取最高分/);
  assert.equal(a.id('btn-settle').hidden,false,'结算后仍可重做，按钮不收起');
});

test('结算通过后给出「返回亳」入口，点了就回场景页',async t=>{
  const full={...SAVED_LEVEL,points:50};
  const a=await setup(t,{levels:{'tc-nand':full,'tc-and':full}});
  const nav=[];
  a.w.HuaxiaReturnToScene=url=>nav.push(url);
  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();

  assert.equal(a.id('back-camp').getAttribute('href'),'/game/#stage-select','头部随时能回亳 的关卡选择');
  assert.equal(a.id('result-return').hidden,false,'结算后应出现返回入口');
  assert.equal(a.id('return-to-camp').getAttribute('href'),'/game/#stage-select','默认回到亳 的关卡选择');
  assert.deepEqual(nav,[],'工坊索引页不该自动替玩家跳走');
  a.id('return-to-camp').click();
  assert.deepEqual(nav,['/game/#stage-select'],'点按钮应回到关卡选择');
});

test('从营前进关，结算通过后自动返回营前',async t=>{
  const full={...SAVED_LEVEL,points:100};
  const a=await setup(t,{levels:{'tc-nand':full},initialPuzzle:'tc-nand',returnUrl:'/game/#camp'});
  const nav=[];
  a.w.HuaxiaReturnToScene=url=>nav.push(url);
  a.w.document.body.dataset.returnDelay='1000';   // 测试里不等默认的 6 秒
  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();
  assert.equal(a.id('result-return').hidden,false);
  for(let i=0;i<20 && !nav.length;i++) await new Promise(r=>setTimeout(r,100));
  assert.deepEqual(nav,['/game/#camp']);
});

test('已结算之后还能再做一轮，成绩取最高',async t=>{
  const full={...SAVED_LEVEL,points:50};
  const a=await setup(t,{levels:{'tc-nand':full,'tc-and':full}});
  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();
  assert.match(a.id('chapter-status').textContent,/已结算：100 \/ 100 分/);

  // 再来一轮：同样的两关再做一次结算，成绩不会变低，也不会报"不能再挑战"。
  assert.equal(a.id('btn-settle').hidden,false);
  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();
  const actions=a.calls.filter(call=>call.options.method==='POST').map(call=>call.payload.action);
  assert.deepEqual(actions,['settle','submit','settle','submit'],'重做会再走一次结算与提交');
  assert.equal(a.alerts.length,0,a.alerts.join('|'));
  assert.match(a.id('result-text').textContent,/最高成绩 100 \/ 100/);
});

test('端口圆圈跟着门走，不会飘到画面别处',async t=>{
  const a=await setup(t,{levels:{'tc-nand':SAVED_LEVEL}});
  const portGroups=a.queryAll('#gates-layer g.port');
  assert.ok(portGroups.length>=5,'三个端点各一个端口 + NAND 三个端口');
  for(const group of portGroups){
    const gateId=group.getAttribute('data-gate');
    const gate=a.query(`#gates-layer g.gate[data-gate-id="${gateId}"]`);
    assert.ok(gate,`缺少门 ${gateId}`);
    // 端口 <g> 必须与所属门用同一个平移量，否则圆圈与门脱节。
    assert.equal(group.getAttribute('transform'),gate.getAttribute('transform'),`门 ${gateId} 的端口错位`);
  }
});

test('拖动门按画布缩放换算位置，且不会往 window 上堆积监听器',async t=>{
  const a=await setup(t);
  a.query('#palette-gates .palette-gate').click();
  a.query('#palette-gates .palette-gate').click();
  a.query('#palette-gates .palette-gate').click();

  // 拖拽监听器只在初始化时注册一次；渲染再多次也不该增加。
  assert.equal(a.windowListeners.mousemove,1);
  assert.equal(a.windowListeners.mouseup,1);

  const svg=a.id('circuit-canvas');
  svg.getBoundingClientRect=()=>({left:0,top:0,right:800,bottom:560,width:800,height:560});

  const gate=a.query('#gates-layer g.gate[data-gate-id="g1"]');
  const before=gate.getAttribute('transform').match(/-?\d+(?:\.\d+)?/g).map(Number);
  gate.dispatchEvent(new a.w.MouseEvent('mousedown',{bubbles:true,clientX:0,clientY:0}));
  gate.dispatchEvent(new a.w.MouseEvent('mousemove',{bubbles:true,clientX:40,clientY:30}));
  a.w.dispatchEvent(new a.w.MouseEvent('mouseup',{bubbles:true}));

  const moved=a.query('#gates-layer g.gate[data-gate-id="g1"]');
  const after=moved.getAttribute('transform').match(/-?\d+(?:\.\d+)?/g).map(Number);
  assert.equal(after[0],before[0]+40);
  assert.equal(after[1],before[1]+30);
  assert.equal(a.windowListeners.mousemove,1,'拖动后不应新增监听器');
});

test('头部有回到主页的常驻入口',async t=>{
  const a=await setup(t);
  const home=a.id('back-home');
  assert.ok(home,'缺少返回主页入口');
  assert.equal(home.getAttribute('href'),'/');
  // 文案来自 ui_strings.json（模板占位），不写死在 HTML 里。
  // 渲染后的真实文字由 Django 测试保证。
  assert.match(home.textContent,/\{\{\s*ui\.homeLink\s*\}\}/);
});

test('剧情数据驱动章节名、人物与委托栏',async t=>{
  const a=await setup(t);
  assert.equal(a.id('chapter-title').textContent,'铸算·夏 · 铸铜工坊');
  assert.equal(a.id('chapter-subtitle').textContent,'受命铸符，以算定天下');
  assert.equal(a.id('npc-name').textContent,'武丁');
  assert.equal(a.id('npc-title').textContent,'商王');
  // 没有配立绘时回退成印章单字
  assert.equal(a.id('npc-portrait').textContent.trim(),'丁');
  // 一关未通时说的是开场白
  assert.equal(a.id('npc-line').textContent,'开场第一句');
  assert.equal(a.id('quest-objective').textContent,'仅用一枚与非符。');
  assert.equal(a.id('chapter-progress').textContent,'0 / 2');
});

test('继续按钮逐句推进，最后一句后收起',async t=>{
  const a=await setup(t);
  assert.equal(a.id('npc-next').hidden,false);
  assert.equal(a.id('npc-line').textContent,'开场第一句');
  a.id('npc-next').click();
  assert.equal(a.id('npc-line').textContent,'开场第二句');
  assert.equal(a.id('npc-next').hidden,true);
});

test('换到已通关的关卡时换成该关委托人，并支持立绘',async t=>{
  const a=await setup(t,{levels:{'tc-and':SAVED_LEVEL}});
  const select=a.id('puzzle-select');
  select.value='tc-and';
  select.dispatchEvent(new a.w.Event('change'));
  for(let i=0;i<25;i++)await tick();

  assert.equal(a.id('npc-name').textContent,'妇好');
  assert.equal(a.id('npc-title').textContent,'商朝女将');
  assert.equal(a.id('npc-line').textContent,'妇好婆奖');
  const image=a.id('npc-portrait').querySelector('img');
  assert.ok(image,'配了立绘就该渲染 img');
  assert.equal(image.getAttribute('src'),'/static/img/portraits/fu-hao.png');
});

test('剧情接口挂掉时工坊仍然可用',async t=>{
  const a=await setup(t,{storyOverride:()=>({ok:false,status:500,json:async()=>({ok:false,error:{code:'story_invalid',message:'剧情数据有误'}})})});
  // 关卡照常加载
  assert.equal(a.queryAll('#truth-table tbody tr').length,4);
  assert.match(a.id('npc-line').textContent,/剧情未载入/);
});

test('主线/支线标记来自关卡结构数据',async t=>{
  const a=await setup(t);
  assert.equal(a.id('quest-route').hidden,false);
  assert.equal(a.id('quest-route').textContent,'主线');

  const select=a.id('puzzle-select');
  select.value='tc-and';       // 这一关在夹具里是支线
  select.dispatchEvent(new a.w.Event('change'));
  for(let i=0;i<25;i++)await tick();
  assert.equal(a.id('quest-route').textContent,'支线');
});

test('文案层决定卦列表头，改文案就能改名',async t=>{
  const a=await setup(t);
  // 模板里 data-yao-header 的值来自 ui_strings.json
  const header=a.query('#truth-table thead th');
  assert.match(header.textContent,/\{\{\s*ui\.truthYaoHeader\s*\}\}/,
    '表头应取自文案层占位，而不是写死在 JS');
});

// ---------- 关卡页（/game/level/<id>）----------
test('关卡页会直接打开指定那一关，而不是永远从第一关开始',async t=>{
  const a=await setup(t,{initialPuzzle:'tc-and'});
  assert.deepEqual(a.alerts,[]);
  assert.equal(a.id('puzzle-select').value,'tc-and','下拉应停在被指定的关卡');
  assert.ok(a.calls.some(c=>c.url==='/game/api/circuit/puzzles/tc-and'),
    '应按 tc-and 拉取关卡详情');
  assert.ok(!a.calls.some(c=>c.url==='/game/api/circuit/puzzles/tc-nand'),
    '不该先去拉第一关详情');
  // 从场景只接了一个入口，页面就不该再把其余四关摆出来。
  assert.equal(a.queryAll('#puzzle-select option').length,1,'只保留被指定的那一关');
  assert.equal(a.id('puzzle-select').hidden,true,'只剩一关时下拉收起');
});

test('从章节页进入（未指定关卡）时，五关仍然都在',async t=>{
  const a=await setup(t);
  assert.equal(a.queryAll('#puzzle-select option').length,LEVELS.length,'/game/circuit 不是关卡页，列表不变');
  assert.equal(a.id('puzzle-select').hidden,false);
});

test('关卡页给了不存在的关卡时退回第一关而不是白屏',async t=>{
  const a=await setup(t,{initialPuzzle:'tc-does-not-exist'});
  assert.deepEqual(a.alerts,[]);
  assert.equal(a.id('puzzle-select').value,'tc-nand','不认识就退回第一关');
});

test('不指定关卡时行为不变，仍是第一关',async t=>{
  const a=await setup(t);
  assert.equal(a.id('puzzle-select').value,'tc-nand');
});

// ---------- 任务生命周期：失败可重试（第④步） ----------
test('结算没通过：成绩不入库，可以再试一次且旧记录保留',async t=>{
  const both={'tc-nand':SAVED_LEVEL,'tc-and':SAVED_LEVEL};   // 合计 40 分
  const a=await setup(t,{levels:both});

  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();

  const posts=a.calls.filter(call=>call.options.method==='POST');
  assert.deepEqual(posts.map(call=>call.payload.action),['settle'],'没通过就不该发 submit');
  assert.match(a.id('chapter-status').textContent,/尚未结算/);
  assert.match(a.id('chapter-status').textContent,/已尝试 1 次/);
  assert.match(a.id('chapter-status').textContent,/上次 40 \/ 100，可再试/);
  assert.match(a.id('result-text').textContent,/本次结算未通过/);
  assert.equal(a.id('btn-settle').hidden,false,'还能再试，按钮不该消失');
});

test('重试：第一次没过，第二次通过，两次尝试记录都在',async t=>{
  const both={'tc-nand':SAVED_LEVEL,'tc-and':SAVED_LEVEL};
  let settles=0;
  const a=await setup(t,{levels:both,actionHandler:(call,current)=>{
    if(call.payload.action==='settle'){
      settles+=1;
      const passed=settles>1;
      const attempts=(current.state.circuit.attempts||[]).concat(
        [{n:settles,score:passed?100:40,maxScore:100,passed}]);
      return ok({saveContext:`ctx-settle-${settles}`,
        progress:progress(current.state.circuit.levels,null,{attempts,pendingSettle:passed})});
    }
    if(call.payload.action==='submit'){
      return ok({saveContext:'ctx-done',progress:progress(current.state.circuit.levels,
        {score:100,maxScore:100,submittedAt:'2026-10-30T12:00:00+08:00'},
        {attempts:current.state.circuit.attempts||[],pendingSettle:true})});
    }
    return solveAction(call,current);
  }});

  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();
  assert.match(a.id('chapter-status').textContent,/已尝试 1 次/);
  assert.equal(a.id('btn-settle').hidden,false,'还能再试');

  a.id('btn-settle').click();
  for(let i=0;i<40;i++)await tick();
  assert.match(a.id('chapter-status').textContent,/已结算：100 \/ 100 分/);
  assert.equal(a.id('btn-settle').hidden,false,'已结算仍可重做');

  const actions=a.calls.filter(call=>call.options.method==='POST').map(call=>call.payload.action);
  assert.deepEqual(actions,['settle','settle','submit'],'第一次失败、第二次才真正结算');
});

// ---------- 任务栏（第③步：挂到玩家真正提交的那一屏） ----------
test('关卡页任务栏从电路存档读取验算和提交步骤',async t=>{
  const a=await setup(t);
  assert.equal(a.id('quest-slot').hidden,false,'关卡页应该有任务栏');
  assert.equal(a.qp('title').textContent,'铸铜工坊 · 验符');
  assert.equal(a.qp('state').textContent,'进行中');
  // 电路章节的存档只有 circuit.levels，没有 story / practice：
  assert.deepEqual([...a.qp('steps').children].map(li=>li.dataset.done),['false','false']);
});

test('结算时先显示核验中，落定后如实报未通过并提示可再试',async t=>{
  const both={'tc-nand':SAVED_LEVEL,'tc-and':SAVED_LEVEL};
  const a=await setup(t,{levels:both});
  a.id('btn-settle').click();
  // 点击后同步进入「核验中」：此时结果还不知道，不能先乐观地显示通过。
  assert.equal(a.qp('state').textContent,'核验中…');

  for(let i=0;i<30;i++)await tick();
  // 40/100 没到通过线：任务栏照实说未通过，并说明还能再试（而不是假装结束）。
  assert.equal(a.qp('state').textContent,'未通过 · 40 / 100（可再试）');
  assert.equal(a.qp('state').dataset.tone,'fail');
  const steps=[...a.qp('steps').children];
  assert.equal(steps[steps.length-1].dataset.done,'false','没结算，最后一步不该打勾');
});

test('刷新关卡页后任务栏仍是同一个结论',async t=>{
  const both={'tc-nand':SAVED_LEVEL,'tc-and':SAVED_LEVEL};
  const a=await setup(t,{levels:both,result:{score:100,maxScore:100,submittedAt:'2026-10-30T12:00:00+08:00'}});
  assert.equal(a.id('quest-slot').hidden,false);
  assert.equal(a.qp('state').textContent,'已通过 · 100 / 100');
  assert.equal(a.qp('state').dataset.tone,'pass');
});

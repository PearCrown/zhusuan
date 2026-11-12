/* 亳 · 关卡选择屏（明日方舟风格）与「行动记录」的行动契约。
 *
 * 这里测的是新界面的三件关键事，而不是像素：
 * 1. 关卡卡片按服务端的关卡与存档渲染，通关状态和分数对得上；
 * 2. 未通关点进去是剧情页，通关后点进去是行动记录，不是直接跳关卡；
 * 3. 行动记录里的时间、提交次数、进度条和逐关得分来自同一份存档。
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');

const root=path.resolve(__dirname,'..');
const script=fs.readFileSync(path.join(root,'static/js/stage-select.js'),'utf8');
const curriculum=fs.readFileSync(path.join(root,'static/js/curriculum.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const until=async(fn,limit=60)=>{for(let i=0;i<limit&&!fn();i++)await tick();assert.ok(fn(),'界面没有进入预期状态');};

const PUZZLES=[{id:'tc-nand',title:'第一关：识·与非',description:'用一个与非门接出真值表'}];

function progressOf({passed=false,points=0,attempts=[],result=null}={}){
  return {
    chapterId:'xia-circuit',
    state:{circuit:{
      levels:{'tc-nand':passed?{passed:true,points,attempts:attempts.length}:{passed:false,points:0,attempts:attempts.length}},
      puzzleIds:['tc-nand'],
      attempts,
      pendingSettle:false,
    }},
    result,
  };
}

function boot({progress, puzzles=PUZZLES}={}){
  const dom=new JSDOM('<!doctype html><html><body><div id="stage-app"></div></body></html>',
    {url:'http://localhost/game/', runScripts:'outside-only', pretendToBeVisual:true});
  const w=dom.window;
  const nav=[];
  w.HuaxiaStageNavigate=url=>nav.push(url);
  w.fetch=async url=>{
    const data=url.includes('/circuit/puzzles')?{puzzles}
      : url.includes('/progress')?{progress, saveContext:'ctx'}
      : null;
    return {ok:true, json:async()=>({ok:true, data})};
  };
  w.eval(curriculum);
  w.eval(script);
  return {w, nav, app:w.document.getElementById('stage-app')};
}

test('左侧指引说明这是第几章、第几节、学什么',async t=>{
  const {w,app}=boot({progress:progressOf()});
  t.after(()=>w.close());
  w.HuaxiaStageSelect.open(app,{onBack(){}});
  await until(()=>app.querySelector('.ark-guide'));
  const guide=app.querySelector('.ark-guide');
  assert.match(guide.textContent,/第一章/);
  assert.match(guide.textContent,/从逻辑门到存算器件/);
  assert.match(guide.textContent,/第一节/);
  assert.match(guide.textContent,/与非门/);
  assert.match(guide.textContent,/本节目标/);
  assert.equal(guide.querySelectorAll('.ark-guide-tag').length,3);
});

test('关卡选择页头部有进入战绩页的入口',async t=>{
  const {w,app}=boot({progress:progressOf()});
  t.after(()=>w.close());
  w.HuaxiaStageSelect.open(app,{onBack(){}});
  await until(()=>app.querySelector('.ark-head-actions a'));
  const link=app.querySelector('.ark-head-actions a');
  assert.equal(link.getAttribute('href'),'/game/profile');
  assert.match(link.textContent,/战绩/);
});

test('关卡卡片按存档显示通关状态与分数',async t=>{
  const {w,app}=boot({progress:progressOf({passed:true,points:100,attempts:[{n:1,at:'2026-11-10T10:00:00+08:00'}]})});
  t.after(()=>w.close());
  w.HuaxiaStageSelect.open(app,{onBack(){}});
  await until(()=>app.querySelector('.ark-stage'));

  const card=app.querySelector('.ark-stage');
  assert.equal(card.dataset.stageId,'tc-nand');
  assert.match(card.textContent,/识·与非/);
  assert.match(card.textContent,/已通关 100\/100/);
  assert.match(card.textContent,/查看记录/);
  assert.match(app.textContent,/已通关 1 \/ 1 关/);
});

/**
 * 通关后的行动记录：时间、次数、进度条、逐关得分都来自同一份存档。
 */
test('通关后点关卡打开行动记录，而不是直接跳关卡',async t=>{
  const progress=progressOf({
    passed:true, points:100,
    attempts:[
      {n:1,score:0,maxScore:100,passed:false,at:'2026-11-10T10:00:00+08:00'},
      {n:2,score:100,maxScore:100,passed:true,at:'2026-11-10T10:05:00+08:00'},
    ],
    result:{score:100,maxScore:100,submittedAt:'2026-11-10T10:06:00+08:00'},
  });
  const {w,app,nav}=boot({progress});
  t.after(()=>w.close());
  w.HuaxiaStageSelect.open(app,{onBack(){}});
  await until(()=>app.querySelector('.ark-stage'));

  app.querySelector('.ark-stage').click();
  await until(()=>app.querySelector('.ark-record'));
  const record=app.querySelector('.ark-record');
  assert.match(record.textContent,/行动记录/);
  assert.match(record.textContent,/提交次数/);
  assert.match(record.textContent,/2/);
  assert.match(record.textContent,/100 \/ 100/);
  assert.equal(record.querySelectorAll('.ark-table tbody tr').length,1);
  assert.match(record.querySelector('.ark-bar-label').textContent,/100%/);
  assert.deepEqual(nav,[],'点已通关的关卡不该直接跳走');
});

test('未通关点已发布的电路关卡，进入该关工作台',async t=>{
  const {w,app,nav}=boot({progress:progressOf()});
  t.after(()=>w.close());
  w.HuaxiaStageSelect.open(app,{onBack(){}});
  await until(()=>app.querySelector('.ark-stage'));
  assert.match(app.querySelector('.ark-stage').textContent,/未通关/);
  app.querySelector('.ark-stage').click();
  assert.deepEqual(nav,['/game/level/tc-nand']);
});

test('行动记录里的「重做本关」打开对应工作台，关闭后回到关卡列表',async t=>{
  const progress=progressOf({passed:true,points:100,attempts:[{n:1,score:100,maxScore:100,passed:true,at:'2026-11-10T10:00:00+08:00'}],
    result:{score:100,maxScore:100,submittedAt:'2026-11-10T10:01:00+08:00'}});
  const {w,app,nav}=boot({progress});
  t.after(()=>w.close());
  w.HuaxiaStageSelect.open(app,{onBack(){}});
  await until(()=>app.querySelector('.ark-stage'));
  app.querySelector('.ark-stage').click();
  await until(()=>app.querySelector('.ark-record'));

  const again=[...app.querySelectorAll('.ark-record-actions button')].find(b=>/重做/.test(b.textContent));
  again.click();
  assert.deepEqual(nav,['/game/level/tc-nand']);

  app.querySelector('.ark-record').querySelector('.ark-record-head button').click();
  assert.equal(app.querySelector('.ark-record'),null,'关闭后浮层应移除');
  const card=app.querySelector('.ark-stage');
  card.click();
  w.document.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  assert.equal(app.querySelector('.ark-record'),null,'Esc 只关闭行动记录');
  assert.equal(w.document.activeElement,card,'关闭后回到打开记录的关卡');
});

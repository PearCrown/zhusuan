const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/js/maintenance.js'),'utf8');
test('maintenance history restoration clears old HTML and requests reload',()=>{
  let reloads=0;
  const console=new VirtualConsole();
  console.on('jsdomError',(error)=>{ if(error.message.includes('navigation')) reloads++; else throw error; });
  const dom=new JSDOM('<main>private roster<form><input value="unsaved"></form></main>',{url:'http://localhost/maintenance/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
  try {
    dom.window.eval(code);
    dom.window.dispatchEvent(new dom.window.Event('pagehide'));
    assert.equal(dom.window.document.querySelector('main').children.length,0);
    assert.equal(dom.window.document.querySelector('main').textContent,'');
    dom.window.dispatchEvent(new dom.window.PageTransitionEvent('pageshow',{persisted:true}));
    assert.equal(reloads,1);
  } finally {dom.window.close();}
});
test('maintenance hidden tab drops stale form and data',()=>{
  const dom=new JSDOM('<main>private roster</main>',{url:'http://localhost/maintenance/',runScripts:'outside-only',pretendToBeVisual:true});
  try {
    dom.window.eval(code);
    Object.defineProperty(dom.window.document,'hidden',{configurable:true,value:true});
    dom.window.document.dispatchEvent(new dom.window.Event('visibilitychange'));
    assert.equal(dom.window.document.querySelector('main').textContent,'');
  } finally {dom.window.close();}
});

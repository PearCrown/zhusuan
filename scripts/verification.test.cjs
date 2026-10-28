const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'); const {JSDOM} = require('jsdom');
const html=fs.readFileSync('templates/verification.html','utf8').replace(/\{%.*?%\}/g,'');
const script=fs.readFileSync('static/js/verification.js','utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function setup(t) {
 const dom=new JSDOM(html,{url:'http://localhost/verification/',runScripts:'outside-only',pretendToBeVisual:true});t.after(()=>dom.window.close());
 const w=dom.window; if(w.document.readyState!=='complete')await new Promise(r=>w.addEventListener('load',r,{once:true}));
 let handler=async()=>({csrfToken:'csrf'});const calls=[];
 w.fetch=async(url,options)=>{calls.push({url,options});const data=await handler(url,options);return {ok:true,json:async()=>({ok:true,data})};};w.eval(script);
 return {w,calls,id:x=>w.document.getElementById(x),respond:x=>handler=x,idle:async()=>{for(let i=0;i<100;i++){await tick();if(!w.document.querySelector('button').disabled)return;}assert.fail('pending');}};
}
function submit(a,id){a.id(id).dispatchEvent(new a.w.Event('submit',{bubbles:true,cancelable:true}));}
test('issue uses POST/CSRF and editing target invalidates old challenge',async t=>{
 const a=await setup(t);a.respond(async url=>url==='/auth/csrf'?{csrfToken:'csrf'}:{challengeId:'id',expiresIn:300});a.id('code-destination').value='owner@example.com';submit(a,'code-request');await a.idle();
 assert.equal(a.calls[1].options.method,'POST');assert.equal(a.calls[1].options.headers['X-CSRFToken'],'csrf');assert.equal(a.id('code-verify').hidden,false);
 a.id('code-destination').dispatchEvent(new a.w.Event('input'));assert.equal(a.id('code-verify').hidden,true);submit(a,'code-verify');await a.idle();assert.equal(a.calls.length,2);assert.equal(a.w.localStorage.length,0);
});
test('hiding pending request prevents mutation and clears secrets',async t=>{
 const a=await setup(t);let resolve;a.respond(()=>new Promise(r=>resolve=r));a.id('code-password').value='private';submit(a,'code-request');
 Object.defineProperty(a.w.document,'hidden',{value:true,configurable:true});a.w.document.dispatchEvent(new a.w.Event('visibilitychange'));resolve({csrfToken:'csrf'});await a.idle();assert.equal(a.calls.length,1);assert.equal(a.id('code-password').value,'');assert.equal(a.id('code-verify').hidden,true);
});
test('lost response never replays and warns of uncertain result',async t=>{
 const a=await setup(t);a.respond(async url=>{if(url==='/auth/csrf')return {csrfToken:'csrf'};throw Error('offline');});submit(a,'code-request');submit(a,'code-request');await a.idle();assert.equal(a.calls.length,2);assert.match(a.id('code-status').textContent,/未确认/);assert.equal(a.id('code-verify').hidden,true);
});

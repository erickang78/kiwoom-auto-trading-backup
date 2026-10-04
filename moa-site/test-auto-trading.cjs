const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Element{constructor(){this.style={};this.listeners={};this.children=[];this.hidden=false;this.value='500000';this.max='100000000'}setAttribute(){}addEventListener(k,f){this.listeners[k]=f}append(...e){this.children.push(...e)}after(){}replaceChildren(){this.children=[]}querySelector(s){return elements[s]||(elements[s]=new Element())}}
const elements={},panel=new Element(),choice={market:'KR',strategy:'trend'},requests=[],timers=[];
panel.querySelector=s=>s.startsWith('[data-strategy-market]')?{dataset:{strategyMarket:choice.market}}:s.startsWith('[data-strategy]')?{dataset:{strategy:choice.strategy}}:(elements[s]||(elements[s]=new Element()));
const context={document:{querySelector:s=>s==='#panel-strategy'?panel:null,createElement:()=>new Element(),head:new Element()},window:{addEventListener(){}},MutationObserver:class{observe(){}},TOKEN:'test',fetch:(url,opts)=>new Promise((resolve,reject)=>requests.push({url,body:JSON.parse(opts.body),resolve,reject})),setTimeout(f,ms){timers.push({f,ms});return timers.length},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync(__dirname+'/auto-trading-ui.js','utf8'),context);
const flush=()=>new Promise(setImmediate),start=elements['#auto-start'],submit=elements['#auto-confirm-start'],cancel=elements['#auto-cancel'],confirm=elements['#auto-confirm'],budget=elements['#auto-budget'];
function respond(overrides={}){const req=requests.at(-1);req.resolve({ok:true,json:async()=>({market:req.body.market,strategy:req.body.strategy,enabled:false,selected_active:false,global_enabled:true,budget:req.body.market==='KR'?'500000':'1000',last_check:null,positions:[],orders:[],issues:[],...overrides})})}
(async()=>{
 assert.equal(requests[0].body.action,'status');assert(start.disabled);respond();await flush();assert(!start.disabled);
 const before=requests.length;start.listeners.click();assert.equal(requests.length,before);assert(!confirm.hidden);cancel.listeners.click();assert(confirm.hidden);assert.equal(requests.length,before);
 budget.value='0';start.listeners.click();assert.equal(requests.length,before);budget.value='200000';budget.listeners.input();start.listeners.click();assert(!confirm.hidden);submit.listeners.click();submit.listeners.click();assert.equal(requests.length,before+1);assert.deepEqual(requests.at(-1).body,{market:'KR',strategy:'trend',action:'start',budget:'200000',confirmed:true});respond({enabled:true,selected_active:true});await flush();assert(start.disabled);assert.match(elements['#auto-running-strategy'].textContent,/현재 실행 전략: 국내주식 · 추세추종/);assert.match(elements['#auto-running-rule'].textContent,/종가 > 5일선 > 20일선 > 60일선/);
 choice.strategy='momentum';timers.at(-1).f();respond({strategy:'trend',enabled:true,global_enabled:false});await flush();assert.match(elements['#auto-running-strategy'].textContent,/실행 대기 전략: 국내주식 · 추세추종/);choice.strategy='trend';
 elements['#auto-stop'].listeners.click();assert.equal(requests.at(-1).body.action,'stop');respond();await flush();
 start.listeners.click();choice.market='US';panel.listeners.click({target:{closest:()=>true}});assert(confirm.hidden);assert.equal(budget.value,'1000');assert.equal(requests.at(-1).body.action,'status');const beforeChange=requests.length;submit.listeners.click();assert.equal(requests.length,beforeChange);
 choice.strategy='breakout';panel.listeners.click({target:{closest:()=>true}});respond();await flush();assert.equal(elements['#auto-status'].textContent,'상태를 확인하고 있습니다…');assert.equal(timers.at(-1).ms,0);timers.at(-1).f();respond();await flush();assert(!start.disabled);
 // Stopped restart performs a read-only check before showing the order confirmation.
 timers.at(-1).f();respond({started_at:'2026-10-02T00:00:00Z',stop_reason:{reason:'주문번호를 확인하지 못했습니다.',orders:[]}});await flush();
 const restartCount=requests.length;start.listeners.click();assert.equal(requests.length,restartCount+1);assert.equal(requests.at(-1).body.action,'check_restart');
 respond({started_at:'2026-10-02T00:00:00Z',stop_reason:{reason:'미확인 주문',orders:[]},restart_check:{result:'blocked',message:'접수 확인 필요',orders:[{id:24,can_confirm_absent:true,name:'제주반도체',code:'080220',side:'sell',quantity:'1',price:'93150',created:'2026-10-02T00:49:50Z',message:'미접수 확인 필요'}]}});await flush();
 assert(!confirm.hidden);assert(submit.disabled);const absent=elements['#auto-confirm-absent'];const count=requests.length;submit.listeners.click();assert.equal(requests.length,count);
 absent.checked=true;absent.listeners.change();assert(!submit.disabled);submit.listeners.click();assert.deepEqual(requests.at(-1).body.confirmed_absent_orders,[24]);assert.equal(requests.at(-1).body.action,'start');
 respond({enabled:false,started_at:'2026-10-02T00:00:00Z',restart_check:{result:'blocked',message:'보유 수량 불일치'},stop_reason:{reason:'보유 수량 불일치',orders:[]}});await flush();assert(!start.disabled);assert.match(elements['#auto-status'].textContent,/실제 자동매매 중지/);
 // A history tab must not change the strategy being restarted.
 choice.market='KR';choice.strategy='trend';panel.listeners.click({target:{closest:()=>true}});
 respond({strategy:'breakout',started_at:'2026-10-02T00:00:00Z'});await flush();
 start.listeners.click();respond({strategy:'breakout',started_at:'2026-10-02T00:00:00Z',restart_check:{result:'ready',orders:[]}});await flush();
 assert.match(elements['#auto-confirm-copy'].textContent,/돌파매매/);
 submit.listeners.click();assert.equal(requests.at(-1).body.strategy,'breakout');assert.equal(requests.at(-1).body.action,'start');assert.equal(requests.at(-1).body.viewStrategy,undefined);
 respond({strategy:'breakout',enabled:true});await flush();assert(start.disabled);
 requests.at(-1);console.log('PASS: confirmation/cancel, exact market/strategy/budget, duplicate submit, server-confirmed state, stop, selection invalidation, stale response, immediate retry');
})().catch(e=>{console.error(e);process.exitCode=1});

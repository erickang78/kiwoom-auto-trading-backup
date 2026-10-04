const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(){this.hidden=false;this.dataset={};this.attrs={};this.listeners={};this.children=[];this.classList={toggle(){},add(){}};this.innerHTML='';}
 append(e){this.children.push(e)} insertBefore(e){this.append(e)}
 setAttribute(k,v){this.attrs[k]=v} addEventListener(k,f){this.listeners[k]=f}
 click(){this.listeners.click?.({target:this})}
 querySelector(s){return fields[s]??(fields[s]=new Element())}
 querySelectorAll(s){if(s==='[data-signal-type]')return types;if(s==='[data-signal-days]')return periods;if(s==='[data-signal-event]')return eventTabs;if(s==='[data-signal-market]')return markets;if(s==='[data-signal-strategy]')return strategies;return []}
}
const fields={},nav=new Element(),main=new Element(),head=new Element();
const markets=['KR','US'].map(m=>Object.assign(new Element(),{dataset:{signalMarket:m}}));
const strategies=['trend','breakout','pullback','reversion','momentum'].map(s=>Object.assign(new Element(),{dataset:{signalStrategy:s}}));
const eventTabs=['BUY','SELL'].map(kind=>Object.assign(new Element(),{dataset:{signalEvent:kind}}));
const types=['virtual','real'].map(type=>Object.assign(new Element(),{dataset:{signalType:type}}));
const periods=['all',3,5,10,30,50,100].map(n=>Object.assign(new Element(),{dataset:{signalDays:String(n)}}));
const documentListeners={};const requests=[];let hash='';
const timers=new Map();let timerId=0;
let now=Date.parse('2026-09-30T05:40:41Z');
class Clock extends Date {static now(){return now}}
const context={Date:Clock,document:{addEventListener:(name,fn)=>documentListeners[name]=fn,head,createElement:()=>new Element(),querySelector:s=>s==='.primary-nav'?nav:s==='main'?main:(fields[s]??=new Element()),querySelectorAll:()=>main.children},accountTabs:new Element(),history:{replaceState(a,b,c){hash=c}},location:{hash:''},window:{addEventListener(){}},fetchQuote:(url,body)=>new Promise((resolve,reject)=>requests.push({url,body,resolve,reject})),setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},clearTimeout(id){timers.delete(id)},console};
vm.runInNewContext(fs.readFileSync(__dirname+'/signal-validation-ui.js','utf8'),context);
const response=(body)=>({enabled:true,status:'monitoring',positions:[],events:[],issues:[],scan:{},market:body.market,strategy:body.strategy,performance:{return_pct:null,total_pnl:0,cumulative_buy_amount:0,realized_pnl:0,unrealized_pnl:0,win_rate_pct:null,closed_trades:0}});
const flush=()=>new Promise(setImmediate);
(async()=>{
 nav.children[0].click();assert.equal(requests.at(-1).body.market,'KR');
 assert.equal(requests.at(-1).body.days,null);
 for(const b of periods){b.click();assert.equal(requests.at(-1).body.days,b.dataset.signalDays==='all'?null:Number(b.dataset.signalDays));assert.equal(b.attrs['aria-pressed'],'true')}
 const stale=requests.at(-1);
 markets[1].click();strategies[4].click();
 const latest=requests.at(-1);latest.resolve(response(latest.body));await flush();
 assert.equal(hash,'#signal-validation-us-momentum');
 assert.match(fields['#signal-title'].textContent,/모멘텀/);
 stale.resolve({...response(stale.body),enabled:false});await flush();
 assert.equal(fields['#signal-toggle'].textContent,'검증 일시정지');
 assert.match(fields['#signal-summary'].innerHTML,/검증수익률/);assert.match(fields['#signal-summary'].innerHTML,/—/);
 fields['#signal-toggle'].click();assert.equal(requests.at(-1).body.action,'pause');assert.equal(requests.at(-1).body.strategy,'momentum');
 requests.at(-1).resolve({...response(requests.at(-1).body),enabled:false});await flush();
 for(const m of markets)for(const s of strategies){m.click();s.click();const r=requests.at(-1);r.resolve(response(r.body));await flush();assert.equal(r.body.market,m.dataset.signalMarket);assert.equal(r.body.strategy,s.dataset.signalStrategy)}
 const events=[{kind:'BUY',name:'매수종목'},{kind:'SKIP',name:'제외종목'},{kind:'SELL',name:'익절종목',reason:'익절 +5%',pnl:5},{kind:'SELL',name:'손절종목',reason:'손절 -3%',pnl:-3},{kind:'SELL',name:'기타종목',reason:'수동 청산',pnl:1}].map(e=>({code:'TEST',quantity:1,reference_price:100,at:'2026-09-29T12:00:00Z',...e}));
 fields['#signal-refresh'].click();requests.at(-1).resolve({...response(requests.at(-1).body),events});await flush();
 assert.match(fields['#signal-events'].innerHTML,/매수종목/);assert.match(fields['#signal-events'].innerHTML,/제외종목/);assert.doesNotMatch(fields['#signal-events'].innerHTML,/익절종목/);
 eventTabs[1].click();assert.match(fields['#signal-events'].innerHTML,/signal-exit-profit">익절/);assert.match(fields['#signal-events'].innerHTML,/signal-exit-loss">손절/);assert.match(fields['#signal-events'].innerHTML,/기타 매도/);assert.doesNotMatch(fields['#signal-events'].innerHTML,/매수종목/);
 assert.equal(eventTabs[1].attrs['aria-selected'],'true');assert.equal(eventTabs[1].textContent,'매도 · 3건');
 fields['#signal-refresh'].click();requests.at(-1).resolve({...response(requests.at(-1).body),events});await flush();assert.match(fields['#signal-events'].innerHTML,/손절종목/);
 markets[0].click();eventTabs[0].click();assert.equal(fields['#signal-events'].textContent,'조회 중…');requests.at(-1).resolve(response(requests.at(-1).body));await flush();assert.match(fields['#signal-events'].innerHTML,/기록된 매수 신호가 없습니다/);
 eventTabs[1].click();assert.match(fields['#signal-events'].innerHTML,/기록된 매도 신호가 없습니다/);
 fields['#signal-refresh'].click();requests.at(-1).resolve({...response(requests.at(-1).body),started_at:'2026-09-27T00:26:41Z'});await flush();
 assert.equal(fields['#signal-elapsed'].textContent,'3일 5시간 14분 0초');
 const requestCount=requests.length;
 for(const [advance,expected] of [[1000,'3일 5시간 14분 1초'],[58000,'3일 5시간 14분 59초'],[1000,'3일 5시간 15분 0초']]){now+=advance;const [id,t]=[...timers].find(([,t])=>t.ms===1000);timers.delete(id);t.fn();assert.equal(fields['#signal-elapsed'].textContent,expected);assert.equal(requests.length,requestCount)}
 fields['#signal-refresh'].click();requests.at(-1).resolve({...response(requests.at(-1).body),enabled:false,started_at:'2026-09-27T00:26:41Z'});await flush();
 assert.equal(fields['#signal-elapsed'].textContent,'3일 5시간 15분 0초');
 for(const started_at of [null,'invalid','2026-10-01T00:00:00Z']){fields['#signal-refresh'].click();requests.at(-1).resolve({...response(requests.at(-1).body),started_at});await flush();assert.equal(fields['#signal-elapsed'].textContent,started_at?.startsWith('2026')?'0일 0시간 0분 0초':'시작 시각 확인 중')}
 markets[1].click();assert.equal(fields['#signal-elapsed'].textContent,'조회 중…');assert.equal(fields['#signal-started'].textContent,'');assert.equal([...timers.values()].filter(t=>t.ms===1000).length,0);
 // Actual fills are counted independently of virtual signal linkage.
 types[1].click();assert.match(fields['#signal-events'].textContent,/조회/);
 const order=(id,side,filled,strategy='momentum',market='US')=>({id,market,strategy,status:filled?'filled':'accepted',filled,average:'104',created:'2026-09-29T12:00:00Z',updated:'2026-09-29T12:00:01Z',number:'123',order:{side,name:'<Apple>',code:'AAPL',exchange:'ND',quantity:2,reason:side==='sell'?'손절 -3%':''}});
 documentListeners['moa:real-orders']({detail:{market:'US',selected_strategy:'momentum',orders:[order(1,'buy',2),order(2,'sell',1),order(3,'buy',0),order(4,'buy',2,'trend'),order(5,'buy',2,'momentum','KR')]}});
 assert.equal(eventTabs[0].textContent,'매수 · 1건');assert.equal(eventTabs[1].textContent,'매도 · 1건');
 eventTabs[1].click();assert.match(fields['#signal-events'].innerHTML,/signal-exit-loss">손절/);assert.match(fields['#signal-events'].innerHTML,/부분 체결/);assert.match(fields['#signal-events'].innerHTML,/&lt;Apple&gt;/);assert.doesNotMatch(fields['#signal-events'].innerHTML,/<Apple>/);
 const profitOrder=order(6,'sell',2);profitOrder.order.reason='익절 +5%';documentListeners['moa:real-orders']({detail:{market:'US',selected_strategy:'momentum',orders:[profitOrder]}});assert.match(fields['#signal-events'].innerHTML,/signal-exit-profit">익절/);
 const unknownOrder=order(7,'sell',2);delete unknownOrder.order.reason;documentListeners['moa:real-orders']({detail:{market:'US',selected_strategy:'momentum',orders:[unknownOrder]}});assert.match(fields['#signal-events'].innerHTML,/사유 미기록/);

 eventTabs[0].click();documentListeners['moa:real-orders']({detail:{market:'US',selected_strategy:'momentum',orders:[]}});assert.equal(eventTabs[0].textContent,'매수 · 0건');assert.match(fields['#signal-events'].innerHTML,/실제 매수 체결이 없습니다/);
 types[0].click();
 fields['#signal-refresh'].click();requests.at(-1).resolve({...response(requests.at(-1).body),performance_history:{market:'US',series:[{strategy:'trend',points:[{day:'2026-09-28',at:'2026-09-28T06:00:00Z',return_pct:10},{day:'2026-09-29',at:'2026-09-29T06:00:00Z',return_pct:null},{day:'2026-09-30',at:'2026-09-30T06:00:00Z',return_pct:-5}]}]}});await flush();
 const realChart=new Element();context.window.moaRenderRealReturnHistory({market:'US',series:[{strategy:'trend',points:[{day:'2026-09-30',at:'2026-09-30T06:00:00Z',return_pct:4}]}]},realChart,'trend');assert.match(realChart.innerHTML,/일별 누적 실제매매 수익률/);assert.match(realChart.innerHTML,/4.00%/);
 const chart=fields['#signal-history-chart'].innerHTML;assert.match(chart,/<svg/);assert.match(chart,/10.00%/);assert.match(chart,/-5.00%/);assert.equal((chart.match(/<circle/g)||[]).length,2);assert.doesNotMatch(chart,/<line x1="58" y1=/);
 assert.equal(fields['#signal-refresh'].hidden,true);
 const poll=[...timers.values()].find(t=>t.ms===15000);assert.ok(poll);poll.fn();
 requests.at(-1).reject(Error('offline'));await flush();
 assert.equal(fields['#signal-refresh'].hidden,false);assert.equal(fields['#signal-refresh'].disabled,false);
 fields['#signal-refresh'].click();assert.equal(fields['#signal-refresh'].disabled,true);assert.equal(requests.at(-1).body.action,'status');
 requests.at(-1).resolve(response(requests.at(-1).body));await flush();assert.equal(fields['#signal-refresh'].hidden,true);
 console.log('PASS: automatic polling, error retry visibility, retry pending and recovery');
 types[0].click();console.log('PASS: real ledger fills independent of virtual linkage, market/strategy/side isolation, unfilled exclusion, partial fills, empty records and XSS escaping');
 console.log('PASS: elapsed days/hours/minutes/seconds, second ticking without API requests, minute rollover, paused wall time, invalid/future start, market isolation; buy/sell filtering, exit badges, counts, refresh persistence, loading isolation; ten menu combinations, empty returns, scoped pause, stale-response isolation');
})().catch(e=>{console.error(e);process.exitCode=1});

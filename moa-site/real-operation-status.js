(()=>{
'use strict';
const card=document.querySelector('#panel-real .card.plan');
if(!card)return;
const values=card.querySelectorAll('.plan-values strong'),labels=card.querySelectorAll('.plan-values span'),tag=card.querySelector('.tag'),note=card.querySelector('.plan-note');
labels[1].textContent='실제매매';labels[2].textContent='실제매매 보유종목';
const layout=document.createElement('style');layout.textContent='#panel-real .plan-values{grid-template-columns:minmax(0,1.15fr) minmax(0,.7fr) minmax(0,1.25fr);gap:10px}#panel-real .plan-values>div{min-width:0}#panel-real .plan-values>div+div{padding-left:10px}#panel-real .plan-values span{white-space:nowrap}#panel-real .plan-values strong{white-space:nowrap}#panel-real .plan-values small{display:inline;margin:0 0 0 3px}#panel-real .plan-values>div:last-child small{margin-left:0}@media(max-width:450px){#panel-real .plan-values{gap:6px;grid-template-columns:minmax(0,1.15fr) minmax(0,.65fr) minmax(0,1.3fr)}#panel-real .plan-values>div+div{padding-left:7px}#panel-real .plan-values span{font-size:12px}#panel-real .plan-values strong{font-size:20px}}';document.head.append(layout);
// The account snapshot owns cash only; automatic positions come from the trading ledger.
const originalUpdateHoldings=updateHoldings;
updateHoldings=function(items){originalUpdateHoldings(items);render()};
let results=null,busy=false,timer,again=false;
function render(){
 if(!results){values[1].textContent='—';values[2].textContent='—';tag.textContent='상태 확인 중';note.textContent='실제매매 운영 상태를 조회하고 있습니다.';return;}
 const states=results.map(r=>r.status==='fulfilled'?r.value:null);
 const active=states.some(s=>s&&s.enabled&&s.global_enabled);
 const complete=states.every(Boolean);
 values[1].textContent=active?'ON':complete?'OFF':'—';
 values[1].style.color=active?'#16704c':'';
 tag.textContent=active?'실제매매 동작 중':complete?'실제매매 중지':'상태 확인 불가';
 values[2].innerHTML=complete?states.reduce((n,s)=>n+s.positions.filter(p=>Number(p.quantity)>0).length,0)+'<small>개</small>':'—';
 note.textContent='국내·미국 실제 자동매매 합산 · '+states.map((s,i)=>(i?'미국':'국내')+' '+(s?(s.enabled&&s.global_enabled?'ON':'OFF'):'확인 불가')).join(' / ')+(complete?' · 중지 중에도 보유 종목은 유지됩니다.':' · 일부 상태를 조회하지 못했습니다.');
}
async function refresh(){
 if(busy){again=true;return;}busy=true;clearTimeout(timer);
 try{results=await Promise.allSettled(['KR','US'].map(async market=>{
  const r=await fetch('/v1/trading/auto',{method:'POST',headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'application/json'},body:JSON.stringify({action:'status',market,strategy:'trend'}),signal:AbortSignal.timeout(10000)});
  const d=await r.json();if(!r.ok||typeof d.enabled!=='boolean'||typeof d.global_enabled!=='boolean'||!Array.isArray(d.positions))throw Error('status unavailable');return d;
 }));render();}finally{busy=false;if(again){again=false;refresh();}else timer=setTimeout(refresh,15000);}
}
window.addEventListener('trading-control-changed',refresh);
window.addEventListener('hashchange',refresh);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
render();refresh();
})();

(()=>{
'use strict';
const key='moa-last-stock';let last=null,lookupVersion=0;
function valid(s){return s&&['KR','US'].includes(s.market)&&(s.market==='KR'?/^\d{6}$/:/^[A-Z][A-Z0-9.\-]{0,11}$/).test(s.code)&&(s.market==='KR'||['ND','NY','NA'].includes(s.exchange));}
try{const stored=JSON.parse(localStorage.getItem(key));if(valid(stored))last=stored;}catch(e){}
function remember(s){if(!valid(s))return;last={market:s.market,code:s.code,exchange:s.market==='KR'?'KRX':s.exchange,name:String(s.name||s.code)};try{localStorage.setItem(key,JSON.stringify(last));}catch(e){}}
window.moaRememberStock=remember;
const quoteLookup=loadQuoteAndChart;
loadQuoteAndChart=async function(market,code,exchange=''){
 const current=++lookupVersion;await quoteLookup(market,code,exchange);
 if(current!==lookupVersion)return;
 const q=activeQuote?.quote?.quote||{};
 remember({market,code:String(code).replace(/^A(?=\d{6}$)/,'').toUpperCase(),exchange:market==='KR'?'KRX':q.stex_tp||exchange,name:q.stk_nm||q.stk_enm||code});
};
const flowLookup=loadFlow;
loadFlow=async function(code){const before=flowData,current=++lookupVersion;await flowLookup(code);if(current!==lookupVersion||flowData===before)return;const q=flowData?.stock||{};remember({market:'KR',code:String(q.stk_cd||activeFlowCode).replace(/^A/,''),exchange:'KRX',name:q.stk_nm||activeFlowCode});};
function restore(view){
 if(!last){if(view==='quote')loadQuote();return;}
 const stock={...last};
 if(view==='quote'){
  if(quoteMarket!==stock.market)setQuoteMarket(stock.market);
  quoteCode.value=stock.name+' · '+stock.code;
  quoteResult.textContent='마지막 조회 종목의 현재가와 차트를 확인하고 있습니다…';
  loadQuoteAndChart(stock.market,stock.code,stock.exchange).catch(showQuoteError);
 }else if(view==='flow'){
  if(stock.market==='US'){flowCode.value=stock.name+' · '+stock.code;flowResult.replaceChildren();const p=document.createElement('p');p.className='card flow-placeholder';p.textContent='마지막 조회 종목은 해외주식 '+stock.name+' ('+stock.code+')입니다. 투자자 수급 조회는 국내주식만 지원합니다.';flowResult.append(p);return;}
  flowCode.value=stock.name+' · '+stock.code;loadFlow(stock.code);
 }else if(view==='trade')document.dispatchEvent(new CustomEvent('moa:restore-order',{detail:stock}));
}
const nav=document.querySelector('.primary-nav');let entering=false;
nav.addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b)return;const panel=document.querySelector('#panel-'+b.dataset.view);entering=Boolean(panel?.hidden);},true);
nav.addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b||!e.isTrusted)return;if(b.dataset.view==='quote'&&!entering){loadQuote();return;}if(entering)restore(b.dataset.view);});
for(const view of ['flow','quote','trade']){const panel=document.querySelector('#panel-'+view);if(panel&&!panel.hidden){restore(view);break;}}
})();

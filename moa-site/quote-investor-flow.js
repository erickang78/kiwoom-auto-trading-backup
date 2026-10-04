(()=>{
'use strict';
const nav=document.querySelector('.primary-nav'),flowTab=nav.querySelector('[data-view="flow"]');
flowTab.hidden=true;
const style=document.createElement('style');style.textContent='.primary-nav [data-view="flow"]{display:none!important}#quote-investor-flow{margin-top:18px}';document.head.append(style);
// Keep older links working while routing all visible navigation to the quote screen.
nav.addEventListener('click',e=>{if(!e.target.closest('[data-view="flow"]'))return;e.stopImmediatePropagation();nav.querySelector('[data-view="quote"]').click();},true);
const requests=new WeakMap();let generation=0;
const originalRender=renderQuote;
renderQuote=function(data,chart){
 originalRender(data,chart);const current=++generation;
 const market=data.market||quoteMarket,q=data.quote||{},code=String(q.stk_cd||activeQuote?.code||'').replace(/^A(?=\d{6}$)/,'');
 if(market!=='KR'||!/^\d{6}$/.test(code))return;
 const host=document.createElement('div');host.id='quote-investor-flow';host.setAttribute('aria-label','종목별 투자자 수급');
 const news=quoteResult.querySelector('.stock-news');if(news)news.before(host);else quoteResult.append(host);
 host.append(flowResult);flowResult.innerHTML='<section class="card flow-placeholder">개인·외국인·기관 수급을 조회하고 있습니다…</section>';
 function load(retry=false){
  if(retry)requests.delete(data);
  if(!requests.has(data))requests.set(data,(async()=>{for(let attempt=0;attempt<3;attempt++){try{return await fetchQuote('/v1/market/investor-flow',{code});}catch(error){if(error.message!=='429'||attempt===2)throw error;await new Promise(resolve=>setTimeout(resolve,5200));if(current!==generation||!host.isConnected)return null;}}})());
  requests.get(data).then(result=>{
   if(current!==generation||!host.isConnected||!result)return;
   flowData=result;activeFlowCode=code;renderFlow();
  }).catch(error=>{
   if(current!==generation||!host.isConnected)return;
   flowResult.replaceChildren();const card=document.createElement('section');card.className='card flow-placeholder';
   const text=document.createElement('p');text.textContent='수급을 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.';
   const retryButton=document.createElement('button');retryButton.type='button';retryButton.className='stock-news-retry';retryButton.textContent='수급 다시 조회';retryButton.addEventListener('click',()=>load(true));card.append(text,retryButton);flowResult.append(card);
  });
 }
 load();
};
if(!flowPanel.hidden){flowPanel.hidden=true;nav.querySelector('[data-view="quote"]').click();}
})();

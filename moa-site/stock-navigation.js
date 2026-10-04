(()=>{
const nav=document.querySelector('.primary-nav');
function openQuote(market,code,exchange=''){
 nav.querySelector('[data-view="quote"]').click();setQuoteMarket(market);quoteCode.value=code;
 if(market==='US'&&!['ND','NY','NA'].includes(exchange)){loadQuote();return;}
 quoteResult.innerHTML='<section class="card flow-placeholder">현재가와 차트를 조회하고 있습니다…</section>';
 loadQuoteAndChart(market,code,exchange).catch(showQuoteError);
}
// Capture replaces the earlier domestic holdings → investor-flow handler.
document.addEventListener('click',e=>{
 const b=e.target.closest('.holding-link[data-flow-code]');if(!b)return;
 e.preventDefault();e.stopImmediatePropagation();openQuote('KR',b.dataset.flowCode);
},true);
const oldHolding=holdingButton;
holdingButton=function(h){return oldHolding(h).replace(' 수급 보기',' 현재가 보기')};
document.querySelectorAll('.holding-link[data-flow-code]').forEach(b=>b.setAttribute('aria-label',(b.dataset.flowName||b.dataset.flowCode)+' 현재가 보기'));
const oldUs=renderUsAccount;
renderUsAccount=function(us){
 oldUs(us);const positions=Array.isArray(us?.positions)?us.positions:[];
 usHoldingCard.querySelectorAll('.holding-item').forEach((row,i)=>{
  const p=positions[i];if(!p?.stk_cd)return;
  const b=document.createElement('button');b.type='button';b.className=row.className+' holding-link';b.innerHTML=row.innerHTML;
  b.setAttribute('aria-label',(p.frgn_stk_nm||p.stk_cd)+' 현재가 보기');
  b.addEventListener('click',()=>openQuote('US',String(p.stk_cd).trim().toUpperCase(),p.stex_tp||''));row.replaceWith(b);
 });
};
const oldRender=renderQuote;
renderQuote=function(data,chart){
 oldRender(data,chart);
 const q=data.quote||{},market=data.market||quoteMarket,code=String(q.stk_cd||'').trim().replace(market==='KR'?/^A/:/^$/,'').toUpperCase();
 const exchange=market==='KR'?'KRX':q.stex_tp||activeQuote?.exchange;
 // Use the broker's raw quote, never the formatted or converted display price.
 const price=Math.abs(Number(String(q.cur_prc??'').replace(/,/g,'')));
 if(!Number.isFinite(price)||price<=0||!code||(market==='US'&&!['ND','NY','NA'].includes(exchange)))return;
 const draft={market,code,exchange,price:String(price),name:q.stk_nm||q.stk_enm||code};
 quoteResult.querySelectorAll('.quote-name > strong,.quote-price > strong').forEach(target=>{
  const b=document.createElement('button');b.type='button';b.className='quote-order-link';b.textContent=target.textContent;
  b.setAttribute('aria-label',draft.name+' '+(target.parentElement.classList.contains('quote-price')?'현재가로 ':'')+'매수 주문 입력');
  b.title='이 종목 매수 주문 입력';b.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('moa:prefill-order',{detail:draft})));
  target.replaceChildren(b);
 });
 const hint=document.createElement('p');hint.className='trade-help';hint.textContent='종목명이나 현재가를 누르면 매수 주문 화면에 자동 입력됩니다.';
 quoteResult.querySelector('.quote-main').after(hint);
};
const style=document.createElement('style');style.textContent='.quote-order-link{border:0;background:transparent;padding:0;color:inherit;font:inherit;letter-spacing:inherit;text-align:inherit;cursor:pointer;text-decoration:underline;text-decoration-color:#b8c9d2;text-underline-offset:5px}.quote-order-link:hover{color:#16856d}.quote-order-link:focus-visible{outline:3px solid #2f6fec;outline-offset:5px;border-radius:4px}';document.head.append(style);
})();

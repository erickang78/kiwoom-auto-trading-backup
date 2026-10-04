(()=>{
'use strict';
const head=document.querySelector('.us-holding-card .card-head');
if(!head)return;
const button=document.createElement('button');button.type='button';button.id='holdings-currency-toggle';button.innerHTML='<span data-currency="USD">$</span><span data-currency="KRW">원</span>';
head.append(button);
function sync(){const displayCurrency=localStorage.getItem('moa-currency')==='USD'?'USD':'KRW';button.querySelectorAll('span').forEach(s=>s.classList.toggle('active',s.dataset.currency===displayCurrency));button.setAttribute('aria-label','해외주식 보유 종목 '+(displayCurrency==='USD'?'달러':'원화')+' 표시 중. '+(displayCurrency==='USD'?'원화':'달러')+'로 전환');}
button.addEventListener('click',()=>{document.querySelector('#panel-quote .currency-toggle-button').click();sync()});
document.addEventListener('change',e=>{if(e.target.closest('.currency-control'))queueMicrotask(sync)});
new MutationObserver(sync).observe(document.querySelector('#panel-quote .currency-toggle-button'),{attributes:true,attributeFilter:['aria-label']});
const style=document.createElement('style');style.textContent='.us-holding-card .card-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.us-holding-card .card-head .section-title{margin-right:auto}#holdings-currency-toggle{display:inline-flex;align-items:center;flex:0 0 72px;width:72px;height:30px;gap:0;padding:3px;border:0;border-radius:10px;background:#eceef1;cursor:pointer}#holdings-currency-toggle span{display:flex;align-items:center;justify-content:center;flex:1;height:24px;border-radius:7px;color:#858990;font-size:14px;font-weight:750;line-height:1}#holdings-currency-toggle span.active{background:#fff;color:#252932;box-shadow:0 2px 5px #15233820}#holdings-currency-toggle:focus-visible{outline:2px solid #4b77d1;outline-offset:3px}';document.head.append(style);sync();
})();

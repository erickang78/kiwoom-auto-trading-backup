(()=>{
const number=v=>{if(v===null||v===undefined||String(v).trim()==='')return null;const n=Number(String(v).replace(/,/g,'').replace(/%$/,''));return Number.isFinite(n)?n:null};
function returnRate(profit,price,quantity){const p=number(profit),c=number(price),q=number(quantity);return p!==null&&c!==null&&q!==null&&c>0&&q>0?p/(c*q)*100:null}
function badge(value,us=false){
 const n=value===null?null:Number(value.toFixed(2));
 const text=n===null?'—':(n>0?'+':'')+n.toFixed(2)+'%';
 return '<div class="holding-return '+(n>0?'positive':n<0?'negative':'')+'" title="'+(us?'증권사 제공 달러 기준 수익률':'평가손익 ÷ (매입단가 × 보유수량) × 100')+'">수익률'+(us?' (달러)':'')+' '+text+'</div>';
}
const originalHolding=holdingButton;
holdingButton=function(h){const html=originalHolding(h);return html.replace(/<\/div><\/button>$/,badge(returnRate(h.evltv_prft,h.pur_pric,h.rmnd_qty))+'</div></button>')};
const originalUs=renderUsAccount;
renderUsAccount=function(us){originalUs(us);const positions=Array.isArray(us?.positions)?us.positions:[];usHoldingCard.querySelectorAll('.holding-item').forEach((row,i)=>{const p=positions[i];if(!p)return;row.querySelector('.holding-value')?.insertAdjacentHTML('beforeend',badge(number(p.pl_rt),true))})};
const style=document.createElement('style');style.textContent='.holding-return{font-size:13px;font-weight:750;margin-top:6px;white-space:nowrap}#panel-real .holding-return.positive,#panel-gold .holding-return.positive,#panel-coin .coin-return.positive{color:#d94343}#panel-real .holding-return.negative,#panel-gold .holding-return.negative,#panel-coin .coin-return.negative{color:#3276c3}';document.head.append(style);
})();

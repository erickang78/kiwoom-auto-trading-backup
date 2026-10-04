(()=>{
const panel=document.querySelector('#panel-trade'),control=panel?.querySelector('#order-currency');if(!control)return;
const intro=panel.querySelector('.intro'),choices=[...control.querySelectorAll('[data-order-currency]')];
intro.classList.add('order-currency-intro');intro.append(control);control.classList.remove('order-tabs');
const tag=intro.querySelector('.tag');if(tag)intro.querySelector('div').append(tag);
choices.forEach(b=>{b.textContent=b.dataset.orderCurrency==='USD'?'$':'원';b.tabIndex=-1;b.setAttribute('aria-hidden','true')});
const toggle=document.createElement('button');toggle.type='button';toggle.className='order-currency-toggle';
function sync(){const usd=choices.find(b=>b.dataset.orderCurrency==='USD').getAttribute('aria-pressed')==='true';toggle.setAttribute('aria-label',(usd?'달러':'원화')+' 입력 중. '+(usd?'원화':'달러')+'로 전환');toggle.disabled=choices.some(b=>b.disabled)}
toggle.addEventListener('click',()=>choices.find(b=>b.getAttribute('aria-pressed')!=='true').click());control.append(toggle);
const observer=new MutationObserver(sync);choices.forEach(b=>observer.observe(b,{attributes:true,attributeFilter:['aria-pressed','disabled']}));sync();
const style=document.createElement('style');style.textContent=`
#panel-trade .order-currency-intro{position:relative}
#panel-trade .order-currency-intro>div:first-child{padding-right:104px}
#panel-trade .order-currency-intro .tag{display:inline-block;margin-top:8px}
#order-currency{position:absolute;top:0;right:0;display:flex;box-sizing:border-box;width:88px;height:34px;padding:3px;border-radius:12px;background:#eceef1;gap:0;margin:0}
#order-currency[hidden]{display:none}
#order-currency [data-order-currency]{flex:1;height:28px;margin:0;padding:0;border:0;border-radius:9px;background:transparent;color:#858990;font:inherit;font-size:17px;font-weight:750;line-height:1;pointer-events:none}
#order-currency [aria-pressed=true]{background:#fff;color:#252932;box-shadow:0 2px 5px #15233820}
#order-currency .order-currency-toggle{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:12px;background:transparent;cursor:pointer;padding:0}
#order-currency .order-currency-toggle:focus-visible{outline:2px solid #4b77d1;outline-offset:3px}
#order-currency .order-currency-toggle:disabled{cursor:wait}
`;document.head.append(style);
})();

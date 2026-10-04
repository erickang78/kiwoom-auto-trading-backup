(()=>{
const panel=document.querySelector('#panel-trade');if(!panel)return;
let market='US',side='buy',version=0,preview=null,previewBusy=false,sending=false,expiryTimer;
let orderCurrency='USD',orderFx=0,currencyBusy=false,usdValue='',shownValue='';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const marketName=()=>market==='US'?'해외주식':'국내주식',sideName=()=>side==='buy'?'매수':'매도';
panel.innerHTML=`<div class="intro"><div><h1 id="order-title"></h1><p class="muted">키움 실전계좌 · 지정가 수동 주문</p></div><span class="tag safe">2단계 확인</span></div>
<div class="order-tabs" role="group" aria-label="주문 시장"><button type="button" data-order-market="KR">국내주식</button><button type="button" data-order-market="US">해외주식</button></div>
<div class="order-tabs order-sides" role="group" aria-label="매수 또는 매도"><button type="button" data-order-side="buy">매수</button><button type="button" data-order-side="sell">매도</button></div>
<div class="order-tabs" id="order-currency" role="group" aria-label="해외주식 주문 입력 통화"><button type="button" data-order-currency="USD">달러 $</button><button type="button" data-order-currency="KRW">원화 ₩</button></div>
<section class="card trade-card"><div class="trade-warning"><strong>실제 주문 화면</strong><span>주문 내용을 확인한 후 최종 전송 버튼을 눌러야 주문이 전송됩니다.</span></div>
<form id="order-form"><div class="trade-fields"><label><span id="order-code-label"></span><input id="order-code" required maxlength="60" autocomplete="off"></label><label>거래소<select id="order-exchange"><option value="ND">NASDAQ</option><option value="NY">NYSE</option><option value="NA">AMEX</option></select><span id="order-krx" hidden>KRX</span></label><label>수량 (주)<input id="order-quantity" type="text" required pattern="[1-9][0-9]{0,8}" inputmode="numeric" value="1"></label><label><span id="order-price-label"></span><input id="order-price" type="text" required inputmode="decimal" autocomplete="off"></label></div><p class="trade-help" id="order-fx" aria-live="polite"></p><p class="trade-help" id="order-help"></p><button class="refresh-button trade-preview-button" id="order-preview" type="submit">주문 내용 확인</button></form><div id="order-result" aria-live="polite"></div></section>`;
const el=id=>panel.querySelector('#order-'+id),form=el('form'),result=el('result');
const style=document.createElement('style');style.textContent='.order-tabs{display:flex;gap:8px;margin:0 0 15px}.order-tabs button{border:1px solid #d5dfe8;border-radius:11px;background:#fff;color:#5c6c7d;padding:11px 24px;font:inherit;font-weight:700;cursor:pointer}.order-tabs button[aria-pressed=true]{background:#163d4b;color:#fff;border-color:#163d4b}.order-sides button[data-order-side=buy][aria-pressed=true]{background:#b83e42;border-color:#b83e42}.order-sides button[data-order-side=sell][aria-pressed=true]{background:#3167a8;border-color:#3167a8}#order-krx{display:block;margin-top:7px;padding:11px 12px;border:1px solid #cdd8e3;border-radius:11px}#order-currency[hidden],#order-fx[hidden],#order-krx[hidden],#order-exchange[hidden]{display:none}#order-form .trade-help{margin:14px 0}#order-result .trade-summary{grid-template-columns:repeat(3,minmax(0,1fr))}#order-result h2{font-size:19px;margin-top:0}#order-result .trade-check{line-height:1.6;align-items:flex-start}#order-result .sell-submit{background:#3167a8}#order-result .trade-summary b{overflow-wrap:anywhere}.order-tabs button:focus-visible{outline:3px solid #2f6fec;outline-offset:2px}@media(max-width:680px){.order-tabs button{flex:1;padding:11px 12px}#order-result .trade-summary{grid-template-columns:1fr 1fr}}';document.head.append(style);
function priceUSD(){
 const value=el('price').value.trim();
 if(market!=='US'||orderCurrency==='USD')return value;
 if(value===shownValue&&usdValue)return usdValue;
 if(!(orderFx>0)||!value||!Number.isFinite(Number(value)))return '';
 return String(Number((Number(value)/orderFx).toFixed(4)));
}
function showUSD(value){
 usdValue=String(value||'');shownValue=orderCurrency==='KRW'&&usdValue?String(Math.round(Number(usdValue)*orderFx)):usdValue;
 el('price').value=shownValue;
}
function syncCurrency(){
 el('currency').hidden=market!=='US';el('fx').hidden=market!=='US';
 panel.querySelectorAll('[data-order-currency]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.orderCurrency===orderCurrency));b.disabled=sending||currencyBusy});
 if(market!=='US')return;
 const rate=orderFx>0?'적용 환율 1달러 = '+orderFx.toLocaleString('ko-KR',{maximumFractionDigits:4})+'원. ':'';
 const price=priceUSD(),equiv=Number(price)>0?'실제 주문 지정가 '+money(price,'USD')+(orderFx>0?' · 약 '+Math.round(Number(price)*orderFx).toLocaleString('ko-KR')+'원':'')+'. ':'';
 el('fx').textContent=currencyBusy?'환율을 확인하고 있습니다…':rate+equiv+(orderCurrency==='KRW'?'원화 입력은 달러로 환산하며 소수점 4자리로 반올림합니다. ':'')+'실제 주문은 달러로 전송됩니다. 원화 금액은 참고용이며 실제 환전 금액과 다를 수 있습니다.';
}
panel.querySelectorAll('[data-order-currency]').forEach(b=>b.addEventListener('click',async()=>{
 if(sending||currencyBusy||market!=='US'||b.dataset.orderCurrency===orderCurrency)return;
 const next=b.dataset.orderCurrency,id=version,original=priceUSD();
 if(next==='KRW'){
  currencyBusy=true;syncCurrency();
  try{
   let rate=typeof displayFxRate!=='undefined'?Number(displayFxRate):0;
   if(!(Number.isFinite(rate)&&rate>0)){
    const code=el('code').value.trim().toUpperCase();
    const data=await fetchQuote('/v1/market/quote/us',{code:code||'AAPL',exchange:code?el('exchange').value:'ND'});rate=Number(data.fx_rate);
   }
   if(!(Number.isFinite(rate)&&rate>0))throw Error('fx');
   orderFx=rate;
  }catch(e){currencyBusy=false;syncCurrency();el('fx').textContent='환율을 조회하지 못했습니다. 달러로 입력하거나 원화 버튼을 다시 눌러 주세요.';return;}
  currencyBusy=false;
 }
 if(id!==version||market!=='US'){syncCurrency();return;}
 invalidate();orderCurrency=next;showUSD(original);render();
}));
function invalidate(){version++;preview=null;clearInterval(expiryTimer);result.replaceChildren();}
function title(){el('title').textContent=marketName()+' 지정가 '+sideName();if(!panel.hidden)document.querySelector('#header-status').textContent=marketName()+' · 실전 '+sideName();}
function render(){title();panel.querySelectorAll('[data-order-market]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.orderMarket===market)));panel.querySelectorAll('[data-order-side]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.orderSide===side)));el('code-label').textContent=market==='US'?'종목 티커':'종목명 또는 6자리 코드';el('code').placeholder=market==='US'?'예: AAPL':'예: 삼성전자 또는 005930';el('price-label').textContent='지정가 ('+(market==='US'&&orderCurrency==='USD'?'USD':'원')+')';el('price').placeholder=market==='US'&&orderCurrency==='USD'?'예: 200.00':'예: 70000';el('price').pattern=market==='US'&&orderCurrency==='USD'?'(?:0|[1-9][0-9]{0,6})(?:\\.[0-9]{1,4})?':'[1-9][0-9]{0,10}';el('exchange').hidden=market==='KR';el('krx').hidden=market==='US';el('help').textContent=(market==='KR'?'국내주식은 KRX 지정가 주문입니다. ':'해외주식은 달러 지정가 주문입니다. ')+(side==='sell'?'계좌의 매도 가능 수량을 확인해 입력하세요.':'수량과 지정가를 입력해 주문 내용을 확인하세요.');syncCurrency();}
panel.querySelectorAll('[data-order-market]').forEach(b=>b.addEventListener('click',()=>{if(sending||market===b.dataset.orderMarket)return;market=b.dataset.orderMarket;el('code').value='';el('price').value='';el('quantity').value='1';invalidate();render()}));
panel.querySelectorAll('[data-order-side]').forEach(b=>b.addEventListener('click',()=>{if(sending||side===b.dataset.orderSide)return;side=b.dataset.orderSide;invalidate();render()}));
form.addEventListener('input',e=>{if(!sending){invalidate();if(e.target===el('price')){usdValue='';shownValue=''}syncCurrency()}});el('exchange').addEventListener('change',()=>{if(!sending)invalidate()});
document.querySelector('.primary-nav').addEventListener('click',e=>{if(e.target.closest('[data-view="trade"]'))title()});
function money(value,currency){return currency==='USD'?'$'+Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4}):Number(value).toLocaleString('ko-KR')+'원'}
form.addEventListener('submit',async e=>{
 e.preventDefault();if(previewBusy||sending||!form.reportValidity())return;
 invalidate();const id=version,started=Date.now();previewBusy=true;el('preview').disabled=true;
 const order={mode:'real',market,side,code:el('code').value.trim().toUpperCase(),exchange:market==='US'?el('exchange').value:'KRX',quantity:el('quantity').value.trim(),price:priceUSD()};const previewFx=orderFx;let name='';
 try{
  if(order.market==='KR'){await stockListReady;const stock=resolveStock(order.code);if(!stock||!/^\d{6}$/.test(stock.code))throw Error('stock');order.code=stock.code;name=stock.name||'';}
  if(id!==version)return;
  const data=await fetchQuote('/v1/trade/preview',order);if(id!==version)return;
  const o=data.order;if(!o||['mode','market','side','code','exchange','quantity','price'].some(k=>o[k]!==order[k]))throw Error('mismatch');
  window.moaRememberStock?.({market:order.market,code:order.code,exchange:order.exchange,name});
  preview={id:data.preview_id,expires:started+Math.min(120,Number(data.expires_in))*1000,version:id};
  const mn=o.market==='US'?'해외주식':'국내주식',sn=o.side==='buy'?'매수':'매도';
  const items=[['종목',(name?name+' · ':'')+o.code],['계좌 / 시장','실전 / '+mn],['매매 구분','수동매매 · 지정가 '+sn],['거래소',({ND:'NASDAQ',NY:'NYSE',NA:'AMEX',KRX:'KRX'})[o.exchange]],['수량',o.quantity+'주'],['지정가',money(o.price,data.currency)],['주문 예정액',money(data.total,data.currency)]];
  if(o.market==='US'&&previewFx>0)items.push(['원화 환산 지정가 (참고)',money(Math.round(Number(o.price)*previewFx),'KRW')],['원화 환산 예정액 (참고)',money(Math.round(Number(data.total)*previewFx),'KRW')],['적용 환율','1달러 = '+previewFx.toLocaleString('ko-KR',{maximumFractionDigits:4})+'원']);
  result.innerHTML='<div class="trade-confirm"><h2>'+mn+' '+sn+' 주문 확인</h2><div class="trade-summary">'+items.map(([k,v])=>'<div><span>'+esc(k)+'</span><b>'+esc(v)+'</b></div>').join('')+'</div><p class="trade-help">주문 예정액은 수수료·세금 제외 금액입니다.</p><p class="trade-help" id="order-expiry"></p><label class="trade-check"><input type="checkbox" id="order-check"> 위 지정가 '+sn+' 주문이 실제 계좌로 전송됨을 확인했습니다.</label><button type="button" class="refresh-button trade-submit '+(o.side==='sell'?'sell-submit':'')+'" id="order-submit" disabled>실제 '+sn+' 주문 전송</button></div>';
  const check=el('check'),submit=el('submit');
  const update=()=>{if(!preview||preview.version!==version)return;const left=Math.max(0,Math.ceil((preview.expires-Date.now())/1000));el('expiry').textContent=left?'확인 유효시간 '+left+'초':'확인 시간이 만료되었습니다. 주문 내용을 다시 확인하세요.';submit.disabled=sending||!check.checked||left===0;if(!left){check.disabled=true;clearInterval(expiryTimer)}};
  check.addEventListener('change',update);submit.addEventListener('click',send);update();expiryTimer=setInterval(update,1000);
 }catch(error){if(id===version)result.innerHTML='<p class="trade-status error">주문 내용을 확인하지 못했습니다. 종목·거래소·수량·지정가와 로그인 상태를 확인하세요.</p>';}
 finally{previewBusy=false;el('preview').disabled=sending;}
});
async function send(){
 if(sending||!preview||preview.version!==version||Date.now()>=preview.expires||!el('check')?.checked)return;
 sending=true;clearInterval(expiryTimer);const previewId=preview.id;preview=null;
 panel.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);el('submit').textContent='주문 전송 중…';
 try{const data=await fetchQuote('/v1/trade/submit',{preview_id:previewId,confirmed:true});result.innerHTML=data.status==='accepted'?'<p class="trade-status">[수동매매] 주문 접수 · 주문번호 '+esc(data.order_number)+'</p><p class="trade-help">접수는 체결 완료가 아닙니다. 체결/미체결 화면에서 확인하세요.</p>':'<p class="trade-status error">주문 결과를 확인할 수 없습니다. 키움 주문내역을 먼저 확인하고 중복 주문하지 마세요.</p>';}
 catch(error){result.innerHTML='<p class="trade-status error">응답을 확인하지 못했습니다. 주문이 접수되었을 수 있으므로 키움 주문내역을 먼저 확인하고 중복 주문하지 마세요.</p>';}
 finally{sending=false;panel.querySelectorAll('button,input,select').forEach(e=>e.disabled=false);}
}
document.addEventListener('moa:restore-order',async e=>{
 const d=e.detail;if(sending||!d||!['KR','US'].includes(d.market))return;
 if(!(d.market==='KR'?/^\d{6}$/:/^[A-Z][A-Z0-9.\-]{0,11}$/).test(d.code)||d.market==='US'&&!['ND','NY','NA'].includes(d.exchange))return;
 invalidate();market=d.market;render();el('code').value=market==='KR'&&d.name?d.name+' · '+d.code:d.code;el('exchange').value=market==='US'?d.exchange:'ND';el('price').value='';usdValue='';shownValue='';
 const current=version;el('help').textContent='마지막 조회 종목의 현재가를 확인하고 있습니다…';
 try{
  const data=await fetchQuote(market==='KR'?'/v1/market/quote/domestic':'/v1/market/quote/us',{code:d.code,exchange:d.exchange});
  if(current!==version||panel.hidden)return;
  const q=data.quote||{},price=Math.abs(Number(String(q.cur_prc||'').replaceAll(',','')));
  if(!Number.isFinite(price)||price<=0)throw Error('quote');
  if(market==='US'){orderFx=Number(data.fx_rate)||0;showUSD(String(price));}else el('price').value=String(price);
  syncCurrency();el('help').textContent=(d.name||d.code)+' · 현재가를 지정가로 입력했습니다. 수량과 가격을 확인하세요.';
 }catch(error){if(current===version)el('help').textContent='마지막 종목을 선택했습니다. 현재가 조회에 실패해 지정가는 직접 입력해 주세요.';}
});
document.addEventListener('moa:prefill-order',e=>{
 const d=e.detail;if(sending||!d||!['KR','US'].includes(d.market))return;
 if(!(d.market==='KR'?/^\d{6}$/:/^[A-Z][A-Z0-9.\-]{0,11}$/).test(d.code)||!Number.isFinite(Number(d.price))||Number(d.price)<=0)return;
 if(d.market==='US'&&!['ND','NY','NA'].includes(d.exchange))return;
 invalidate();market=d.market;side='buy';render();
 el('code').value=d.market==='KR'&&d.name?d.name+' · '+d.code:d.code;
 el('exchange').value=d.market==='US'?d.exchange:'ND';if(d.market==='US'){showUSD(d.price)}else{el('price').value=d.price}el('quantity').value='1';syncCurrency();
 document.querySelector('.primary-button[data-view="trade"]').click();
 el('help').textContent=(d.name?d.name+' · ':'')+d.code+' · 조회한 현재가를 지정가로 입력했습니다. 수량과 가격을 확인하세요.';
});
render();
})();

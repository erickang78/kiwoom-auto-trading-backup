(()=>{
'use strict';
function mount(panel,signal=false){
if(!panel)return;
const prefix=signal?'signal-auto-':'auto-';
const find=selector=>card.querySelector(selector.replace('#auto-', '#'+prefix));
const names={trend:'추세추종',breakout:'돌파매매',pullback:'눌림목',reversion:'평균회귀',momentum:'모멘텀'};
const strategyDefinitions={
 trend:['추세추종','종가 > 5일선 > 20일선 > 60일선, 20일선 상승. 20일 수익률 순.'],
 breakout:['돌파매매','직전 20일 고가 돌파, 거래량이 직전 20일 평균의 1.5배 이상. 거래량 배수 순.'],
 pullback:['눌림목매매','20일선 > 60일선, 20일선 상승. 20일선 ±3%, 직전 20일 고점 대비 -3~-12%. 20일선에 가까운 순.'],
 reversion:['평균회귀','20일 볼린저밴드 하단(평균−2표준편차) 이하, 단순 RSI(14) 35 이하. RSI 낮은 순.'],
 momentum:['모멘텀매매','20일 수익률 10% 이상, 5일 수익률 양수, 종가 > 20일선. 20일 수익률 순.']
};
const card=document.createElement('section');card.className='card';card.id=signal?'signal-real-auto-trading':'real-auto-trading';
card.innerHTML='<h2>실제 자동매매</h2><p>선택한 시장·전략으로 실전 계좌에 지정가 주문을 전송합니다.</p><p id="auto-running-strategy" role="status" aria-live="polite">실행 전략을 확인하고 있습니다…</p><p id="auto-running-rule" class="muted"></p><p class="muted">원화 기준 1만원 미만 5주 · 1만~3만원 2주 · 3만원 초과 1주 · 최대 5종목 · 익절 +5% / 손절 -3% · 정규장 60초 주기<br>해외주식은 조회 환율로 원화 환산해 수량을 결정합니다. 자동매매로 체결된 보유분만 매도합니다. 지정가는 미체결될 수 있으며 손절 가격은 보장되지 않습니다.</p><label class="auto-budget-label">자동매매 보유·미체결 매수 예산 <span class="auto-budget-field"><input id="auto-budget" type="number" min="1" step="1" value="500000" inputmode="numeric"> <span id="auto-currency">원</span></span></label><p class="muted">보유 매입금액과 미체결 매수를 기준으로 한도 적용 · 비용 여유 1% · 매도 후 예산 재사용</p><div class="auto-actions"><button type="button" id="auto-start">선택한 전략으로 실제 자동매매 시작</button><button type="button" id="auto-stop">이 시장 자동매매 중지</button></div><div id="auto-confirm" hidden><p id="auto-confirm-copy"></p><label id="auto-recovery-confirm" hidden><input type="checkbox" id="auto-confirm-absent"> 키움 주문·미체결 내역에서 아래 주문이 접수되지 않았음을 확인했습니다.</label><div id="auto-recovery-orders"></div><button type="button" id="auto-confirm-start">확인 후 실전 주문 자동 전송 시작</button> <button type="button" id="auto-cancel">취소</button></div><p id="auto-status" role="status" aria-live="polite">상태를 확인하고 있습니다…</p><div id="auto-orders"></div>';
card.innerHTML=card.innerHTML.replaceAll('id="auto-', 'id="'+prefix);
if(signal){card.querySelector('h2').textContent='실제 보유 종목 · 실제 자동매매';panel.querySelector('#signal-positions').parentElement.after(card);}else panel.querySelector('.strategy-info').after(card);
const overview=signal?document.createElement('section'):null;
if(overview){overview.id='signal-real-overview';overview.className='card signal-card';panel.querySelector('.signal-type-tabs').after(overview);}
const realHistoryCard=signal?document.createElement('section'):null;
let realHistoryPlot;
if(realHistoryCard){realHistoryCard.id='signal-real-history-card';realHistoryCard.className='card signal-card';const heading=document.createElement('h2');heading.textContent='전략별 일별 누적 실제매매 수익률';const note=document.createElement('p');note.className='muted';note.textContent='한국시간 날짜별 마지막 기록 기준 · 수수료·세금·환전 비용 제외 · 실제 자동매매 체결과 마지막 확인 시세로 평가합니다. 기록 수집 시작 전 날짜는 복원하지 않으며, 무체결·확인 불가·기록 없는 날짜는 연결하지 않습니다.';realHistoryPlot=document.createElement('div');realHistoryPlot.className='signal-return-chart';realHistoryPlot.id='signal-real-history-chart';realHistoryCard.append(heading,note,realHistoryPlot);panel.querySelector('#signal-history-card').after(realHistoryCard);}
function renderRealHistory(){if(!realHistoryPlot)return;if(!data){realHistoryPlot.textContent='실제 일별 수익률 기록을 조회하고 있습니다…';return;}if(window.moaRenderRealReturnHistory)window.moaRenderRealReturnHistory(data.performance_history,realHistoryPlot,data.selected_strategy||selected().strategy);}
function renderOverview(){
 if(!overview)return;
 renderRealHistory();
 overview.replaceChildren();
 const add=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;overview.append(e);};
 if(!data){add('h2','실제 자동매매 조건 · 누적 수익률');add('p','실제매매 데이터를 확인하고 있습니다…');return;}
 const r=data.rules||{quantity:1,max_positions:5,take_profit_pct:5,stop_loss_pct:-3,poll_seconds:60};
 const viewed=data.selected_strategy||selected().strategy;
 const name=strategyDefinitions[viewed]?.[0]||viewed;
 add('div',(data.market==='KR'?'국내주식':'해외주식')+' · '+name+' · 실제매매');
 add('h2','신호 포착 시 '+'원화 기준 1만원 미만 5주 · 1만~3만원 2주 · 초과 1주'+' · 최대 '+r.max_positions+'종목');
 add('p','실제 평균 매수가 대비 +'+r.take_profit_pct+'% 익절 / '+r.stop_loss_pct+'% 손절 · 정규장 '+r.poll_seconds+'초 주기');
 add('p',strategyDefinitions[viewed]?.[1]||'전략 조건 확인 중');
 add('p',data.strategy===viewed?((data.enabled?(data.global_enabled?'선택한 전략 실행 중':'전체 중지로 실행 대기'):'선택한 전략 중지')+' · 예산 '+Number(data.budget).toLocaleString('ko-KR')+(data.market==='KR'?'원':' USD')+(data.started_at?' · 최초 시작 '+new Date(data.started_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'')):'선택한 전략은 현재 실행 중이 아닙니다. 현재 실행 상태는 아래 실제 자동매매 카드에서 확인합니다.');
 const perf=data.performance, valid=perf?.available===true;
 const amount=v=>valid&&typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:4})+(data.market==='KR'?'원':' USD'):'—';
 const percent=v=>valid&&typeof v==='number'&&Number.isFinite(v)?v.toFixed(2)+'%':'—';
 add('h2','누적 실제매매 수익률');
 const grid=document.createElement('div');grid.className='signal-summary';overview.append(grid);
 for(const [label,value] of [['누적 실제매매 수익률',percent(perf?.return_pct)],['실현 + 평가손익',amount(perf?.total_pnl)],['누적 매수금액',amount(perf?.cumulative_buy_amount)],['실현손익',amount(perf?.realized_pnl)],['평가손익',amount(perf?.unrealized_pnl)],['승률 / 청산 횟수',valid?percent(perf.win_rate_pct)+' / '+perf.closed_trades+'건':'—']]){const cell=document.createElement('div');cell.className='signal-metric';cell.textContent=label;const valueNode=document.createElement('strong');valueNode.textContent=value;cell.append(valueNode);grid.append(cell);}
 add('p',valid?(perf.cumulative_buy_amount>0?'실제 자동매매 체결 기준 · 수수료·세금·환전 비용 제외. 누적 수익률 = 실현·평가손익 ÷ 누적 실제 매수금액 × 100.':'실제 자동매매 체결 내역이 없어 수익률을 표시하지 않습니다.'):perf?.reason||'실제 성과 데이터를 확인할 수 없습니다.');
 add('p','선택한 시장·전략의 과거 전체 자동매매 기록 기준입니다. 중지·재시작 전 기록을 포함하며, 수동 주문은 제외합니다.');
}
const duration=signal?document.createElement('div'):null;
let elapsedValue,elapsedLabel,elapsedStarted;
if(duration){duration.id='signal-real-duration';duration.className='signal-duration';duration.hidden=true;elapsedLabel=document.createElement('span');elapsedValue=document.createElement('strong');elapsedValue.id='signal-real-elapsed';elapsedStarted=document.createElement('small');const note=document.createElement('small');note.textContent='최근 재시작 이후 장외 대기 시간을 포함합니다. 누적 성과는 계속 유지됩니다.';duration.append(elapsedLabel,elapsedValue,elapsedStarted,note);find('#auto-running-rule').after(duration);}
const holdings=document.createElement('div');holdings.className='auto-holdings';card.append(holdings);
if(!signal)panel.querySelector('.strategy-foot').textContent='조건에 맞는 종목이 10개 미만이면 해당 종목만 표시합니다. 실제 자동매매는 신호검증 화면에서 확인할 수 있습니다.';
const style=document.createElement('style');style.textContent='#real-auto-trading{margin-bottom:20px}#real-auto-trading h2{margin-top:0;font-size:18px}#real-auto-trading p{line-height:1.7}#real-auto-trading .muted{font-size:12px}#real-auto-trading .auto-budget-label{display:flex;align-items:center;flex-wrap:wrap;gap:8px}#real-auto-trading .auto-budget-field{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}#auto-budget{box-sizing:border-box;text-align:right;min-width:0;width:140px;padding:9px;border:1px solid #ccd9d2;border-radius:8px;font:inherit}#real-auto-trading button{padding:10px 14px;border-radius:9px;border:1px solid #b8cec4;background:#eef8f2;color:#175a42;font:inherit;font-weight:700;cursor:pointer}#real-auto-trading button:disabled{opacity:.5;cursor:default}.auto-actions{display:flex;flex-wrap:wrap;gap:8px}#real-auto-trading #auto-stop{color:#a43c35;background:#fff5f3;border-color:#e0c4c1}#auto-confirm{padding:14px;margin-top:12px;background:#fff6e6;border-radius:10px}#auto-confirm[hidden]{display:none}#auto-orders{font-size:12px;line-height:1.8;overflow-wrap:anywhere}#auto-status{font-size:13px}';if(signal)style.textContent=style.textContent.replaceAll('#real-auto-trading','#signal-real-auto-trading').replaceAll('#auto-', '#'+prefix);document.head.append(style);
const budget=find('#auto-budget'),status=find('#auto-status'),orders=find('#auto-orders'),start=find('#auto-start'),stop=find('#auto-stop'),confirm=find('#auto-confirm'),submit=find('#auto-confirm-start');
let key='',busy=false,data=null,generation=0,timer,pending=null,elapsedTimer,budgetTouched=false;
const recoveryConfirm=find('#auto-recovery-confirm'),absentConfirm=find('#auto-confirm-absent'),recoveryOrders=find('#auto-recovery-orders');
const failureBox=document.createElement('div');failureBox.id=prefix+'failure';failureBox.style.cssText='padding:12px;background:#fff6e6;border-radius:8px;white-space:pre-line;margin:12px 0';status.after(failureBox);
function renderFailure(){failureBox.hidden=!!data?.enabled||!data?.stop_reason;if(failureBox.hidden)return;if(data.restart_check?.result==='ready'){failureBox.textContent='중지 원인 점검 완료 · 재시작 가능\n계좌·주문 점검을 통과했습니다. 최종 시작 확인을 기다리고 있습니다.';return;}const reason=data.stop_reason;failureBox.textContent='실제매매 중지 사유\n'+reason.reason+(reason.stage?'\n확인 단계: '+reason.stage:'')+(reason.at?'\n최근 확인: '+new Date(reason.at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'');for(const o of reason.orders||[]){failureBox.textContent+='\n'+o.name+' ('+o.code+') · '+(o.side==='buy'?'매수':'매도')+' '+o.quantity+'주 · 지정가 '+Number(o.price).toLocaleString('ko-KR')+(data.market==='KR'?'원':' USD')+' · '+(o.failure?.message||'주문번호·접수 결과 미확인');}if(data.restart_check?.result==='blocked')failureBox.textContent+='\n재시작 점검: '+data.restart_check.message;}
renderOverview();
function renderElapsed(){
 clearTimeout(elapsedTimer);
 if(!duration)return;
 const began=data?.session_started_at?Date.parse(data.session_started_at):NaN;
 duration.hidden=!data?.enabled||panel.hidden;
 if(duration.hidden)return;
 elapsedLabel.textContent='재시작 후 경과 · '+(data.market==='KR'?'국내주식':'해외주식')+' · '+(strategyDefinitions[data.strategy]?.[0]||data.strategy);
 const seconds=Math.max(0,Math.floor((Date.now()-began)/1000));
 elapsedValue.textContent=Number.isFinite(began)?Math.floor(seconds/86400)+'일 '+Math.floor(seconds%86400/3600)+'시간 '+Math.floor(seconds%3600/60)+'분 '+seconds%60+'초':'재시작 시각 기록 없음';
 const operating=!data.global_enabled?'전체 매매 중지로 대기':data.status==='outside_session'?'장외 대기':data.status==='waiting'?'시작 준비 중':data.status==='error'?'조회 오류 · 재시도 대기':'매매 감시 중';
 elapsedStarted.textContent=operating+(Number.isFinite(began)?' · 최근 재시작 '+new Date(began).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'')+(data.started_at?' · 최초 시작 '+new Date(data.started_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'');
 elapsedTimer=setTimeout(renderElapsed,1000);
}
function selected(){if(signal)return {market:panel.querySelector('[data-signal-market][aria-pressed="true"]')?.dataset.signalMarket||'KR',strategy:panel.querySelector('[data-signal-strategy][aria-pressed="true"]')?.dataset.signalStrategy||'trend'};return {market:panel.querySelector('[data-strategy-market][aria-pressed="true"]')?.dataset.strategyMarket||'KR',strategy:panel.querySelector('[data-strategy][aria-pressed="true"]')?.dataset.strategy||'trend'}}
const labels={accepted:'접수·체결 확인 대기',filled:'체결',partial:'부분체결',failed:'주문 거절',unknown:'결과 불명 · 확인 필요',cancelled:'취소·종료',reconcile_error:'확인 필요'};
const errors={trading_paused:'전체 매매가 중지되어 있습니다. 하단 매매 시작 버튼으로 허용한 뒤 다시 시도하세요.',auto_strategy_has_positions:'기존 전략이 실행 중이거나 자동매매 보유·미체결 주문이 남아 있어 전략을 변경할 수 없습니다.',auto_unresolved_order:'결과가 불명확한 주문이 있습니다. 키움 주문내역을 확인한 뒤 운영 점검이 필요합니다.',invalid_auto_budget:'예산을 정수로 입력하세요. 국내 최대 1억 원, 미국 최대 10만 달러입니다.'};
budget.addEventListener('input',()=>{budgetTouched=true});
function buttons(){if(data&&!data.enabled&&!budgetTouched&&budget.type==='number')budget.value=String(data.budget);start.textContent=data?.started_at&&!data.enabled?'점검 후 실제매매 재시작 · '+(names[data.strategy]||data.strategy):'선택한 전략으로 실제 자동매매 시작';start.disabled=busy||!data||!data.global_enabled||data.enabled;stop.disabled=busy||!data||!data.enabled;submit.disabled=busy||(!recoveryConfirm.hidden&&!absentConfirm.checked);budget.disabled=busy||(signal&&(!data||data.enabled));if(signal){if(data?.enabled){budget.type='text';budget.value=Number(data.budget).toLocaleString('ko-KR');}else if(data&&budget.type==='text'){const raw=budget.value.replaceAll(',','');budget.type='number';budget.value=raw;}}}
function renderHoldings(){holdings.replaceChildren();const title=document.createElement('h3');title.textContent='실제 보유 종목 · '+data.positions.length+' / 5종목';holdings.append(title);const currency=data.market==='US'?' USD':'원';const price=v=>Number.isFinite(Number(v))&&v!=null?Number(v).toLocaleString('ko-KR',{maximumFractionDigits:4})+currency:'—';if(!data.positions.length){const empty=document.createElement('p');empty.className='muted';empty.textContent='실제 자동매매로 체결된 보유 종목이 없습니다. 예산을 입력하고 시작을 확인하면 새 전략 신호에 따라 실제 매수를 시도합니다.';holdings.append(empty);}for(const p of data.positions){const row=document.createElement('div');row.className='signal-row';const name=document.createElement('strong');name.textContent=p.name+' ('+p.code+') · '+p.quantity+'주 · 자동매매';const detail=document.createElement('p');detail.className='muted';detail.textContent='평균 매수가 '+price(p.entry_price)+' → 마지막 확인 '+price(p.last_price)+' · 수익률 '+(Number.isFinite(p.return_pct)?p.return_pct.toFixed(2)+'%':'—')+' · 익절 '+price(p.entry_price*1.05)+' / 손절 '+price(p.entry_price*.97)+(p.last_at?' · 가격 확인 '+new Date(p.last_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'');row.append(name,detail);holdings.append(row);}}
function render(){renderFailure();renderElapsed();renderOverview();buttons();if(!data)return;renderHoldings();const active=strategyDefinitions[data.strategy]?.[0]||names[data.strategy]||data.strategy;find('#auto-running-strategy').textContent=(data.enabled?(data.global_enabled?'현재 실행 전략: ':'실행 대기 전략: '):'자동매매 중지 · 설정 전략: ')+(data.market==='KR'?'국내주식':'해외주식')+' · '+active;find('#auto-running-rule').textContent='매수 후보 조건: '+(strategyDefinitions[data.strategy]?.[1]||'전략 조건을 확인할 수 없습니다.')+' 완료된 일봉으로 후보를 선정하고, 정규장에 연속 조회 거래량 증가가 확인되면 예산·보유·미체결 조건에 따라 지정가 매수를 시도합니다.';status.textContent=(data.enabled?(data.global_enabled?'실제 자동매매 실행 중':'전체 매매 중지로 실행 대기'):'실제 자동매매 중지')+' · '+active+' · 예산 '+Number(data.budget).toLocaleString()+(data.market==='KR'?'원':' USD')+' · 자동 보유 '+data.positions.length+'종목'+(data.last_check?' · 최근 확인 '+new Date(data.last_check).toLocaleString('ko-KR'):'')+(data.issues.length&&data.restart_check?.result!=='ready'?'\n'+data.issues.join(' / '):'');status.style.whiteSpace='pre-line';orders.replaceChildren();if(data.orders.length){const title=document.createElement('strong');title.textContent='최근 실제 자동주문';orders.append(title);for(const item of data.orders.slice(0,8)){const line=document.createElement('div');line.textContent='[자동매매] '+(item.order.side==='buy'?'매수':'매도')+' · '+item.order.name+' ('+item.order.code+') · '+labels[item.status]+' · '+(item.average?'체결가 '+item.average:'지정가 '+item.order.price)+' · '+(item.number?'주문 '+item.number:'주문번호 미확인');orders.append(line)}}}
async function request(action='status',payload={}){if(busy)return;busy=true;clearTimeout(timer);buttons();const choice=selected(),current=++generation;try{const r=await fetch('/v1/trading/auto',{method:'POST',headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'application/json'},body:JSON.stringify({...choice,action,...payload})});const value=await r.json();if(!r.ok)throw Error(errors[value.error]||'자동매매 요청을 처리하지 못했습니다.');if(current!==generation)return;data=value;if(signal)document.dispatchEvent(new CustomEvent('moa:real-orders',{detail:value}));render();return value;}catch(e){if(current===generation){if(!data){renderElapsed();renderOverview();holdings.replaceChildren();find('#auto-running-strategy').textContent='실행 전략을 확인하지 못했습니다.';find('#auto-running-rule').textContent='';}status.textContent=e.message;}return null;}finally{busy=false;buttons();timer=setTimeout(sync,current===generation?15000:0)}}
function sync(){if(panel.hidden)return;const choice=selected(),next=choice.market+':'+choice.strategy;if(next!==key){key=next;generation++;data=null;budgetTouched=false;failureBox.hidden=true;renderElapsed();renderOverview();confirm.hidden=true;pending=null;budget.value=choice.market==='KR'?'500000':'1000';budget.max=choice.market==='KR'?'100000000':'100000';find('#auto-currency').textContent=choice.market==='KR'?'원':'USD';status.textContent='상태를 확인하고 있습니다…';find('#auto-running-strategy').textContent='실행 전략을 확인하고 있습니다…';find('#auto-running-rule').textContent='';orders.replaceChildren();holdings.replaceChildren();buttons();}request();}
function showStartConfirmation(choice,absent=[]){
 pending={...choice,viewStrategy:selected().strategy,budget:budget.value,confirmed_absent_orders:absent.map(o=>o.id)};confirm.hidden=false;recoveryConfirm.hidden=!absent.length;absentConfirm.checked=false;recoveryOrders.replaceChildren();
 for(const o of absent){const line=document.createElement('p');line.textContent=o.name+' ('+o.code+') · '+(o.side==='buy'?'매수':'매도')+' '+o.quantity+'주 · 지정가 '+Number(o.price).toLocaleString('ko-KR')+' · '+new Date(o.created).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' · '+o.message+(o.price_issue?' · '+o.price_issue:'');recoveryOrders.append(line);}
 find('#auto-confirm-copy').textContent=(choice.market==='KR'?'국내주식':'해외주식')+' · '+names[choice.strategy]+' · 예산 '+Number(budget.value).toLocaleString()+(choice.market==='KR'?'원':' USD')+'으로 실전 주문을 자동 전송합니다. 재시작 직전에 인증·계좌·주문 상태를 다시 확인합니다. 미접수로 확인한 이전 주문은 기록을 보존하고 새 시세로 전략을 다시 평가합니다. 이미 접수된 주문은 중지해도 취소되지 않고 보유분은 자동 청산되지 않습니다.';buttons();
}
start.addEventListener('click',async()=>{
 const choice=selected();if(!/^[1-9]\d*$/.test(budget.value)||Number(budget.value)>Number(budget.max)){status.textContent=errors.invalid_auto_budget;return;}
 if(data?.started_at||data?.stop_reason?.orders?.length){
  status.textContent='재시작 전 인증·계좌·주문 내역을 점검하고 있습니다…';const checked=await request('check_restart');
  if(!checked||choice.market!==selected().market||choice.strategy!==selected().strategy)return;
  const result=checked.restart_check,absent=(result?.orders||[]).filter(o=>o.can_confirm_absent);
  if(result?.result!=='ready'&&(absent.length!==(result?.orders||[]).length||!absent.length)){status.textContent='재시작할 수 없습니다. '+(result?.message||'계좌·주문 점검을 다시 진행해 주세요.');return;}
  showStartConfirmation({...choice,strategy:checked.started_at?checked.strategy:choice.strategy},absent);return;
 }
 showStartConfirmation(choice);
});
absentConfirm.addEventListener('change',buttons);
submit.addEventListener('click',()=>{if(!pending||pending.market!==selected().market||pending.viewStrategy!==selected().strategy||(!recoveryConfirm.hidden&&!absentConfirm.checked))return;const {viewStrategy,...orderChoice}=pending;const payload={...orderChoice,confirmed:true};if(!payload.confirmed_absent_orders.length)delete payload.confirmed_absent_orders;pending=null;confirm.hidden=true;request('start',payload)});
find('#auto-cancel').addEventListener('click',()=>{confirm.hidden=true;pending=null});stop.addEventListener('click',()=>request('stop'));
panel.addEventListener('click',e=>{if(e.target.closest(signal?'[data-signal-market],[data-signal-strategy]':'[data-strategy-market],[data-strategy]')){clearTimeout(timer);sync()}});new MutationObserver(()=>{if(panel.hidden){clearTimeout(timer);renderElapsed();confirm.hidden=true;pending=null;}else sync()}).observe(panel,{attributes:true,attributeFilter:['hidden']});window.addEventListener('trading-control-changed',sync);if(!panel.hidden)sync();
}
mount(document.querySelector('#panel-strategy'));
mount(document.querySelector('#panel-signal-validation'),true);
})();

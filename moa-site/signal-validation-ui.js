(()=>{
const definitions={
 trend:['추세추종','종가 > 5일선 > 20일선 > 60일선, 20일선 상승. 20일 수익률 순.'],
 breakout:['돌파매매','직전 20일 고가 돌파, 거래량이 직전 20일 평균의 1.5배 이상. 거래량 배수 순.'],
 pullback:['눌림목매매','20일선 > 60일선, 20일선 상승. 20일선 ±3%, 직전 20일 고점 대비 -3~-12%. 20일선에 가까운 순.'],
 reversion:['평균회귀','20일 볼린저밴드 하단(평균−2표준편차) 이하, 단순 RSI(14) 35 이하. RSI 낮은 순.'],
 momentum:['모멘텀매매','20일 수익률 10% 이상, 5일 수익률 양수, 종가 > 20일선. 20일 수익률 순.']
};
let market="KR",selected="trend",days=null;
const nav=document.querySelector('.primary-nav'), button=document.createElement('button');
button.type='button';button.className='primary-button';button.dataset.view='signal-validation';button.textContent='신호 검증';nav.append(button);
const panel=document.createElement('section');panel.className='panel';panel.id='panel-signal-validation';panel.hidden=true;panel.dataset.signalDetails='false';
panel.innerHTML=`<div class="intro"><div><h1>신호검증 · 매매 비교</h1><p class="muted">시장·전략별 신호와 가상·실제 매매 결과 비교</p></div><div><span class="muted">15초마다 자동 갱신</span><button type="button" class="refresh-button" id="signal-refresh" hidden style="margin-left:12px">다시 시도</button></div></div>
<div class="strategy-tabs" role="group" aria-label="검증 시장"><button type="button" data-signal-market="KR">국내주식</button><button type="button" data-signal-market="US">해외주식</button></div><div class="strategy-tabs" role="group" aria-label="검증 전략">${Object.entries(definitions).map(([key,d])=>`<button type="button" data-signal-strategy="${key}">${d[0]}</button>`).join('')}</div><section class="card signal-card"><h2>최근 신호 · 매매 비교</h2><div class="signal-type-tabs" role="group" aria-label="매매 유형 조회"><button type="button" data-signal-type="virtual" aria-pressed="true">가상매매</button><button type="button" data-signal-type="real" aria-pressed="false">실제매매</button></div><p class="muted" id="signal-comparison-scope">최근 100개 신호 기준 · 유형 선택에 따라 보유 카드와 아래 기록이 전환됩니다. 수익률은 각 유형의 매수·매도 기록 기준입니다.</p><p id="signal-comparison-note" class="signal-comparison-note" role="status"></p><label class="signal-detail-toggle"><input type="checkbox" id="signal-details"> 자세히</label><div class="signal-event-tabs" role="tablist" aria-label="최근 신호 구분"><button type="button" id="signal-events-buy" role="tab" aria-controls="signal-events" aria-selected="true" data-signal-event="BUY">매수</button><button type="button" id="signal-events-sell" role="tab" aria-controls="signal-events" aria-selected="false" tabindex="-1" data-signal-event="SELL">매도</button></div><div id="signal-events" role="tabpanel" aria-labelledby="signal-events-buy">조회 중…</div></section><section class="card signal-card" id="signal-virtual-conditions"><div class="signal-badge"><span id="signal-title"></span> · 가상매매</div><h2>신호 포착 시 원화 기준 1만원 미만 5주 · 1만~3만원 2주 · 3만원 초과 1주 · 최대 5종목</h2><p>가상 매수가 대비 <strong>+5% 익절 / −3% 손절</strong></p><p class="muted" id="signal-rule"></p><p class="muted">전략마다 원화 기준 1만원 미만은 5주, 1만~3만원은 2주, 3만원 초과는 1주씩 최대 5종목을 독립적으로 가상 매수하며 같은 기준일 신호에는 재진입하지 않습니다. 해외주식은 조회 환율로 원화 환산합니다. 모든 전략은 화면 선택과 관계없이 서버에서 검증합니다. 일시정지는 선택한 전략에만 적용됩니다.</p><div class="signal-actions"><button type="button" id="signal-toggle" disabled>상태 확인 중</button><span id="signal-state" role="status" aria-live="polite">서버 상태를 확인하고 있습니다.</span></div><div class="signal-duration"><span>검증 시작 후 경과</span><strong id="signal-elapsed">조회 중…</strong><small id="signal-started"></small><small>휴장·일시정지를 포함한 전체 경과 시간입니다.</small></div><p id="signal-check" class="muted"></p></section>
<div class="strategy-tabs signal-period-tabs" role="group" aria-label="검증수익률 기간">${[null,3,5,10,30,50,100].map(n=>`<button type="button" data-signal-days="${n??'all'}" aria-pressed="${n===null}">${n===null?'누적':n+'일'}</button>`).join('')}</div><p id="signal-period" class="muted" role="status"></p><div class="signal-summary" id="signal-summary"></div><section class="card signal-card" id="signal-history-card"><h2>전략별 일별 누적 가상매매 수익률</h2><p class="muted">한국시간 날짜별 마지막 기록 기준 · 현재 날짜는 갱신 중 · 수수료·세금 제외. 각 전략의 검증 시작부터 누적 수익률이며 기간 선택과 별개입니다. 기록 없는 날짜는 연결하지 않습니다. 점에 마우스를 올리면 수익률과 기록 시각을 볼 수 있습니다.</p><div id="signal-history-chart" class="signal-return-chart">조회 중…</div></section><section class="card signal-card" id="signal-virtual-holdings"><h2>가상 보유 종목</h2><div id="signal-positions">조회 중…</div></section><section class="card signal-card"><h2>검증 범위</h2><p class="muted">전략매매와 동일한 거래대금 상위 종목·완료 일봉 조건과 15분 분석 캐시를 사용합니다. 국내 KRX, 해외는 미국 NASDAQ·NYSE·AMEX를 지원합니다. 정규장에 연속 조회 거래량 증가를 확인하여 가상매매합니다.</p><p class="muted">누적은 선택한 시장·전략의 최초 검증 시작부터 전체 매매 기록으로 계산합니다. 누적 검증수익률 = 누적 실현·평가손익 ÷ 누적 매수금액 × 100. 일별 기간은 한국시간으로 오늘을 포함한 달력일 기준입니다. 검증수익률 = 기간 손익 ÷ (기간 시작 보유 평가금액 + 기간 내 매수금액) × 100. 이전 보유분은 기간 시작 전 마지막 기록 가격을 기준으로 계산합니다. 원금 재투입도 누적하므로 계좌 수익률이나 연환산 수익률과 다릅니다. 국내는 원화, 미국은 달러 기준이며 수수료·세금·환전 비용은 제외합니다. 거래 전에는 수익률을 표시하지 않습니다.</p><p class="muted">가격은 조회 시세를 사용한 가상 기준가이며 실제 체결가가 아닙니다. 시세 지연 여부는 보장되지 않으며 조회 사이에 지나간 익절·손절 가격은 기록하지 못할 수 있습니다. 가상 보유에 주식분할 등이 발생하면 수동 점검이 필요합니다. 일시정지 중에는 매수·매도 신호 기록이 모두 멈춥니다.</p><div id="signal-issues" class="muted"></div></section>`;
document.querySelector('main').insertBefore(panel,document.querySelector('footer.bottom'));
panel.querySelector('.signal-type-tabs').after(panel.querySelector('.signal-period-tabs'),panel.querySelector('#signal-period'),panel.querySelector('#signal-summary'));
const style=document.createElement('style');style.textContent=`#panel-signal-validation:not([data-signal-trade-type="real"]) #signal-real-auto-trading,#panel-signal-validation:not([data-signal-trade-type="real"]) #signal-real-overview,#panel-signal-validation[data-signal-trade-type="real"] #signal-virtual-holdings,#panel-signal-validation[data-signal-trade-type="real"] #signal-virtual-conditions,#panel-signal-validation[data-signal-trade-type="real"] .signal-period-tabs,#panel-signal-validation[data-signal-trade-type="real"] #signal-period,#panel-signal-validation[data-signal-trade-type="real"] #signal-summary{display:none!important}#panel-signal-validation[data-signal-details="false"] .signal-result:not(.signal-result-real){display:none}#panel-signal-validation[data-signal-details="false"][data-signal-trade-type="virtual"] .signal-results{display:none}#panel-signal-validation[data-signal-details="false"][data-signal-trade-type="real"] .signal-result-real{display:none}.signal-detail-toggle{display:flex;align-items:center;gap:6px;margin:12px 0;font-size:13px;cursor:pointer}.signal-detail-toggle input{accent-color:#13704d;width:16px;height:16px}#panel-signal-validation[data-signal-trade-type="real"] #signal-history-card{display:none}.signal-chart-legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;margin:16px 0}#panel-signal-validation:not([data-signal-trade-type="real"]) #signal-real-history-card{display:none}.signal-return-chart svg{width:100%;height:auto;display:block}.signal-chart-table{overflow-x:auto}.signal-return-chart table{width:100%;border-collapse:collapse;font-size:12px}.signal-return-chart th,.signal-return-chart td{padding:8px;text-align:right;border-bottom:1px solid #e2e8ed;white-space:nowrap}.signal-return-chart summary{cursor:pointer;font-size:13px;margin-top:10px}.signal-type-tabs{display:flex;gap:6px;margin:16px 0}.signal-type-tabs button{flex:1;padding:9px 8px;border:1px solid #cbd8e2;border-radius:9px;background:#fff;color:#52657a;font:inherit;font-size:13px;font-weight:700;cursor:pointer}.signal-type-tabs button[aria-pressed="true"]{background:#e5f5ed;border-color:#13704d;color:#13704d}.signal-type-tabs button:focus-visible{outline:3px solid #478bcb;outline-offset:2px}.signal-comparison-note{padding:12px;border-radius:9px;background:#f4f7fa;font-size:12px;color:#52657a}.signal-results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}.signal-results-single{grid-template-columns:1fr}.signal-result{min-width:0;padding:12px;border:1px solid #dbe9e2;background:#f7fbf8;border-radius:10px}.signal-result-real{background:#f7f9fc;border-color:#dce5ed}.signal-result>strong{display:block;margin:6px 0;font-size:14px}.signal-type-badge{font-size:11px;font-weight:700;color:#13704d}.signal-result-real .signal-type-badge{color:#365b8b}@media(max-width:560px){.signal-results{grid-template-columns:1fr}}#panel-signal-validation .signal-period-tabs{display:flex;flex-wrap:nowrap;gap:3px}#panel-signal-validation .signal-period-tabs button{flex:1 1 0;min-width:0;padding:7px 2px;font-size:11px;white-space:nowrap;border-radius:7px}.signal-duration{margin-top:18px;padding:16px;background:#f0f6f3;border:1px solid #dbe9e2;border-radius:12px;color:#315749}.signal-duration>span{font-size:12px}.signal-duration strong{display:block;margin:6px 0;font-size:24px;font-variant-numeric:tabular-nums}.signal-duration small{display:block;font-size:12px;line-height:1.8;color:#63768b}.signal-card{margin-bottom:16px}.signal-card h2{font-size:18px;margin:12px 0}.signal-card p{line-height:1.7}.signal-card .muted{font-size:12px}.signal-badge{display:inline-block;background:#e5f5ed;color:#13704d;font-size:12px;font-weight:700;border-radius:8px;padding:6px 10px}.signal-actions{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-top:16px}.signal-actions button{padding:10px 14px;border:1px solid #cbd8e2;border-radius:10px;background:#fff;font:inherit;cursor:pointer}.signal-actions button:disabled{opacity:.5}.signal-actions span{font-size:13px}.signal-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}.signal-metric{padding:15px 10px;border:1px solid #dce5ed;background:#fff;border-radius:12px;font-size:12px;color:#63768b}.signal-metric strong{display:block;font-size:19px;color:#142236;margin-top:8px}.signal-row{padding:13px 0;border-top:1px solid #e5ebf0;line-height:1.7;overflow-wrap:anywhere}.signal-row small{display:block;color:#63768b;font-size:12px}.signal-empty{padding:20px 0;color:#63768b;font-size:13px}.signal-event-tabs{display:flex;gap:8px;margin:14px 0}.signal-event-tabs button{flex:1;padding:10px 14px;border:1px solid #cbd8e2;border-radius:10px;background:#fff;color:#52657a;font:inherit;font-weight:700;cursor:pointer}.signal-event-tabs button[aria-selected="true"]{background:#142236;border-color:#142236;color:#fff}.signal-event-tabs button:focus-visible{outline:3px solid #478bcb;outline-offset:3px}.signal-event-heading{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.signal-exit-badge{display:inline-block;padding:3px 10px;border-radius:7px;font-size:13px;font-weight:800;border:1px solid}.signal-exit-profit{color:#b42332;background:#fff0f1;border-color:#f4bac0}.signal-exit-loss{color:#1855aa;background:#edf4ff;border-color:#b6cff5}.signal-exit-other{color:#52657a;background:#f1f4f7;border-color:#cbd8e2}.signal-error{color:#a73535!important}#signal-issues{line-height:1.8}@media(max-width:500px){.signal-metric strong{font-size:16px}.signal-summary{gap:6px}}`;document.head.append(style);
const el=id=>panel.querySelector('#signal-'+id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const usd=v=>Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4}), when=v=>v?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'아직 없음';
let elapsedTimer;
let timer, generation=0, enabled=false, mutation=false;
let eventSide='BUY', eventRecords=null, tradeType='virtual', executionRecords=[];
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const money=v=>v==null?'—':market==='US'?'$'+usd(v):Number(v).toLocaleString('ko-KR',{maximumFractionDigits:2})+'원';
const periodLabel=()=>days===null?'누적':days+'일';
const parseDays=value=>value==='all'?null:Number(value);
const pct=v=>v==null?'—':Number(v).toFixed(2)+'%';
function elapsedSince(value){
 const start=value?new Date(value).getTime():NaN;
 if(!Number.isFinite(start))return '시작 시각 확인 중';
 const seconds=Math.floor(Math.max(0,Date.now()-start)/1000);
 return Math.floor(seconds/86400)+'일 '+Math.floor(seconds%86400/3600)+'시간 '+Math.floor(seconds%3600/60)+'분 '+seconds%60+'초';
}
function tickElapsed(startedAt){
 clearTimeout(elapsedTimer);
 if(panel.hidden)return;
 el('elapsed').textContent=elapsedSince(startedAt);
 elapsedTimer=setTimeout(()=>tickElapsed(startedAt),1000);
}
function renderHistory(history,target=null,real=false,selection=selected){
 const chart=target||el('history-chart'), names={trend:'추세추종',breakout:'돌파매매',pullback:'눌림목매매',reversion:'평균회귀',momentum:'모멘텀매매'},colors=['#13704d','#2864b7','#bf6520','#9557b5','#ba3d61'];
 if(!history||history.market!==market){chart.textContent='일별 수익률 기록을 조회하고 있습니다…';return;}
 const series=history.series||[], recordedDates=[...new Set(series.flatMap(s=>s.points.map(p=>p.day)))].sort(), dates=[];
 if(recordedDates.length){for(let date=new Date(recordedDates[0]+'T00:00:00Z'),end=new Date(recordedDates.at(-1)+'T00:00:00Z');date<=end;date.setUTCDate(date.getUTCDate()+1))dates.push(date.toISOString().slice(0,10));}
 const values=series.flatMap(s=>s.points.map(p=>p.return_pct)).filter(finite);
 if(!dates.length||!values.length){chart.innerHTML='<p class="signal-empty">아직 그래프에 표시할 일별 수익률이 없습니다.</p>';return;}
 const width=760,height=280,left=58,right=20,top=20,bottom=42,plotW=width-left-right,plotH=height-top-bottom;
 let lo=Math.min(0,...values),hi=Math.max(0,...values);if(hi===lo){lo-=1;hi+=1;}else{const pad=(hi-lo)*.12;lo-=pad;hi+=pad;}
 const x=i=>left+(dates.length===1?plotW/2:i/(dates.length-1)*plotW),y=v=>top+(hi-v)/(hi-lo)*plotH;
 let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${market==='KR'?'국내주식':'해외주식'} 5개 전략 일별 누적 ${real?'실제':'가상'}매매 수익률"><title>일별 누적 ${real?'실제':'가상'}매매 수익률 · 수수료·세금 제외</title>`;
 for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,py=y(v);svg+=`<line x1="${left}" x2="${width-right}" y1="${py}" y2="${py}" stroke="#e2e8ed"/><text x="${left-8}" y="${py+4}" text-anchor="end" fill="#63768b" font-size="11">${v.toFixed(1)}%</text>`;}
 svg+=`<line x1="${left}" x2="${width-right}" y1="${y(0)}" y2="${y(0)}" stroke="#9eabb5" stroke-dasharray="4 3"/>`;
 const step=Math.max(1,Math.ceil(dates.length/6));dates.forEach((d,i)=>{if(i%step===0||i===dates.length-1)svg+=`<text x="${x(i)}" y="${height-15}" text-anchor="middle" fill="#63768b" font-size="11">${esc(d.slice(5))}</text>`});
 series.forEach((s,index)=>{const color=colors[index%colors.length],points=new Map(s.points.map(p=>[p.day,p]));let prev=null;dates.forEach((day,i)=>{const p=points.get(day);if(!p||!finite(p.return_pct)){prev=null;return;}const px=x(i),py=y(p.return_pct);if(prev)svg+=`<line x1="${prev[0]}" y1="${prev[1]}" x2="${px}" y2="${py}" stroke="${color}" stroke-width="${s.strategy===selection?3:1.8}"/>`;svg+=`<circle cx="${px}" cy="${py}" r="${s.strategy===selection?4:3}" fill="${color}"><title>${esc(names[s.strategy])} · ${esc(day)} · ${p.return_pct.toFixed(2)}% · 기록 ${esc(when(p.at))}</title></circle>`;prev=[px,py];});});
 svg+='</svg>';
 const legend=series.map((s,i)=>`<span style="color:${colors[i%colors.length]}">● ${esc(names[s.strategy])}</span>`).join('');
 const table=dates.map(day=>`<tr><th scope="row">${esc(day)}</th>${series.map(s=>{const p=s.points.find(p=>p.day===day);return `<td>${p&&finite(p.return_pct)?p.return_pct.toFixed(2)+'%':'—'}</td>`}).join('')}</tr>`).join('');
 chart.innerHTML=`<div class="signal-chart-legend">${legend}</div>${svg}<details><summary>날짜별 수익률 보기</summary><div class="signal-chart-table"><table><thead><tr><th>날짜</th>${series.map(s=>`<th>${esc(names[s.strategy])}</th>`).join('')}</tr></thead><tbody>${table}</tbody></table></div></details>`;
}

window.moaRenderRealReturnHistory=(history,target,selection)=>renderHistory(history,target,true,selection);
function render(d){
 renderHistory(d.performance_history);
 tickElapsed(d.started_at);
 el('started').textContent='검증 시작 '+when(d.started_at)+' (한국시간)';
 enabled=d.enabled;el('toggle').textContent=enabled?'검증 일시정지':'검증 재개';el('toggle').disabled=d.global_enabled===false;
 const stale=d.last_check&&Date.now()-new Date(d.last_check).getTime()>180000;
 el('state').textContent=d.global_enabled===false?'전체 매매 중지됨':!enabled?'일시정지됨':stale?'서버 확인 지연 · 기록 상태 점검 필요':({starting:'검증 시작 대기',outside_session:'정규장 시간 대기',monitoring:'신호 검증 중',error:'조회 실패 · 다음 주기에 재시도'})[d.status]||'상태 확인 중';
 el('state').classList.toggle('signal-error',!!stale&&enabled||d.status==='error');
 el('check').textContent='마지막 확인 '+when(d.last_check)+' (한국시간) · 일봉 기준일 '+(d.scan?.date||'분석 대기')+' · 후보 '+(d.scan?.candidates==null?'분석 중':d.scan.candidates+'개');
 const perf=d.performance;
 el('period').textContent=perf.start_at?`${periodLabel()} · ${when(perf.start_at)} ~ ${when(perf.end_at)} (한국시간) · ${perf.note||'마지막 기록 시세 기준'}`:`${periodLabel()} 검증수익률`;
 const metrics=[[periodLabel()+' 검증수익률',pct(perf.return_pct)],['실현 + 평가손익',money(perf.total_pnl)],[days===null?'누적 매수금액':'기간 기준금액',money(perf.cumulative_buy_amount)],['실현손익',money(perf.realized_pnl)],['평가손익',money(perf.unrealized_pnl)],['승률 / 청산 횟수',pct(perf.win_rate_pct)+' / '+(perf.closed_trades??'—')+'건']];
 el('summary').innerHTML=metrics.map(([label,value])=>`<div class="signal-metric">${label}<strong>${value}</strong></div>`).join('');
 el('positions').innerHTML=`<p class="muted">${d.positions.length} / 5종목 보유</p>`+(d.positions.length?d.positions.map(p=>`<div class="signal-row"><strong>${esc(p.name)} (${esc(p.code)}) · ${p.quantity}주</strong><small>매수가 ${money(p.entry_price)} → 마지막 확인 ${money(p.last_price)} · ${pct(p.return_pct)}</small><small>익절 ${money(p.entry_price*1.05)} / 손절 ${money(p.entry_price*.97)}</small><small>가격 확인 ${when(p.last_at)} (한국시간)</small></div>`).join(''):'<p class="signal-empty">아직 가상 보유 종목이 없습니다. 장중 조건과 시세 갱신을 확인하면 자동으로 기록합니다.</p>');
 eventRecords=d.events;executionRecords=Array.isArray(d.executions)?d.executions:[];renderEvents();
 el('issues').innerHTML=(d.issues||[]).map(i=>'<div>'+esc(i)+'</div>').join('');
}
// Execution records are explicit, real-account aggregates for one original signal.
// Never associate a manual order by approximate order/fill time or ticker alone.
function signalKey(v,execution=false){
 const at=execution?v.signal_at:v.at, side=execution?v.side:(v.kind==='SKIP'?'BUY':v.kind);
 const m=execution?v.market:market, strategy=execution?v.strategy:selected;
 const stamp=Date.parse(at);
 if(!Number.isFinite(stamp)||!v.code||!v.exchange||!m||!strategy||!['BUY','SELL'].includes(side))return null;
 return JSON.stringify([m,strategy,v.exchange,v.code,side,stamp]);
}
function actualFor(e){
 const key=signalKey(e);
 if(!key)return null;
 const signals=eventRecords.filter(v=>signalKey(v)===key);
 const matches=executionRecords.filter(v=>v.mode==='real'&&signalKey(v,true)===key);
 return signals.length===1&&matches.length===1?matches[0]:null;
}
function virtualReturn(e){
 return e.kind==='SELL'&&finite(e.entry_price)&&e.entry_price>0&&finite(e.reference_price)?(e.reference_price/e.entry_price-1)*100:null;
}
function actualCard(e,x){
 const states={filled:'체결 완료',partial:'부분 체결',unfilled:'미체결',failed:'주문 실패',insufficient_balance:'잔고 부족',duplicate_holding:'중복 보유',disabled:'실제매매 비활성',cancelled:'주문 취소',not_submitted:'주문 미전송'};
 const state=x?(states[x.status]||'상태 확인 필요'):'실제 주문 미연결';
 const filled=x&&['filled','partial'].includes(x.status)&&finite(x.filled_quantity)&&x.filled_quantity>0&&finite(x.average_fill_price)&&x.average_fill_price>0;
 const price=filled?x.average_fill_price:null;
 const diff=filled&&finite(e.reference_price)&&e.reference_price>0?price-e.reference_price:null;
 const delay=filled?(Date.parse(x.first_fill_at)-Date.parse(e.at))/1000:NaN;
 const net=x&&e.kind==='SELL'&&x.status==='filled'&&x.costs_complete===true&&finite(x.net_return_pct)?x.net_return_pct:null;
 const vr=virtualReturn(e), gap=net!==null&&vr!==null?net-vr:null;
 return `<section class="signal-result signal-result-real"><span class="signal-type-badge">실제매매</span><strong>${state}</strong><small>${esc(x?.reason||(x?'사유 기록 없음':'신호에 연결된 실제 주문·체결 기록이 없습니다. 잔고 부족·미체결 여부는 확인할 수 없습니다.'))}</small><small>체결 ${filled?esc(x.filled_quantity)+'주':'—'} · 평균 체결가 ${money(price)}</small><small>기준가 대비 ${money(diff)}${diff!==null?' ('+pct(diff/e.reference_price*100)+')':''} · 첫 체결 지연 ${Number.isFinite(delay)&&delay>=0?delay.toFixed(1)+'초':'—'}</small><small>수수료 ${money(finite(x?.fee)?x.fee:null)} · 세금 ${money(finite(x?.tax)?x.tax:null)} · 기타 비용 ${money(finite(x?.other_cost)?x.other_cost:null)}</small><small>비용 반영 수익률 <b>${pct(net)}</b> · 가상 대비 ${gap===null?'—':gap.toFixed(2)+'%p'}</small>${net===null?'<small>매도 체결과 매수·매도 비용이 모두 확인된 경우 계산합니다.</small>':''}</section>`;
}
const actualSnapshots=new Map();
document.addEventListener('moa:real-orders',e=>{const d=e.detail;if(!d?.market||!d.selected_strategy)return;actualSnapshots.set(d.market+':'+d.selected_strategy,d);if(tradeType==='real')renderEvents();});
function renderActualOrders(){
 const d=actualSnapshots.get(market+':'+selected);
 const records=d?(d.orders||[]).filter(x=>x.market===market&&x.strategy===selected&&Number(x.filled)>0&&['buy','sell'].includes(x.order?.side)):null;
 panel.querySelectorAll('[data-signal-event]').forEach(b=>{const side=b.dataset.signalEvent==='SELL'?'sell':'buy';b.textContent=(side==='sell'?'매도':'매수')+(records?' · '+records.filter(x=>x.order.side===side).length+'건':' · 조회 중');});
 el('comparison-note').textContent='선택한 시장·전략의 실제 자동매매 체결기록입니다. 최근 시장 주문 30개 중 체결 수량이 있는 주문만 집계합니다. 부분체결은 주문당 1건이며 미체결·주문 실패·수동 주문은 제외됩니다.';
 if(!records){el('events').textContent='실제 체결내역을 조회하고 있습니다…';return;}
 const side=eventSide==='SELL'?'sell':'buy',visible=records.filter(x=>x.order.side===side);
 el('events').innerHTML=visible.length?visible.map(x=>{const o=x.order,quantity=Number(x.filled),price=Number(x.average),filled=quantity>=Number(o.quantity),currency=market==='KR'?'원':' USD';const reason=String(o.reason||''),exit=side==='sell'?(reason.startsWith('익절')?['profit','익절']:reason.startsWith('손절')?['loss','손절']:['other',reason?'기타 매도':'사유 미기록']):null;const badge=exit?`<span class="signal-exit-badge signal-exit-${exit[0]}">${exit[1]}</span>`:'';return `<article class="signal-row"><div class="signal-event-heading">${badge}<strong>${esc(o.name||o.code)} (${esc(o.code)}) · 실제 ${side==='sell'?'매도':'매수'}</strong></div><small>주문 ${when(x.created)} (한국시간) · 마지막 확인 ${when(x.updated)} (한국시간)</small><section class="signal-result signal-result-real"><span class="signal-type-badge">실제매매</span><strong>${filled?'체결 완료':'부분 체결'}</strong><small>체결 ${quantity.toLocaleString('ko-KR')}주 · 평균 체결가 ${Number.isFinite(price)&&price>0?price.toLocaleString('ko-KR',{maximumFractionDigits:4})+currency:'—'}</small><small>주문번호 ${esc(x.number||'미확인')} · ${esc(o.exchange||'')}</small><small>${esc(o.reason||'실제 자동매매 주문')}</small></section></article>`;}).join(''):`<p class="signal-empty">선택한 시장·전략에 기록된 실제 ${side==='sell'?'매도':'매수'} 체결이 없습니다.</p>`;
}
function renderEvents(){
 panel.dataset.signalTradeType=tradeType;
 el('comparison-scope').textContent=tradeType==='real'?'최근 실제 자동주문 기준 · 선택한 시장·전략의 체결내역입니다.':'최근 100개 신호 기준 · 가상매매 기록입니다.';
 const tabs=panel.querySelectorAll('[data-signal-event]');
 tabs.forEach(b=>{const active=b.dataset.signalEvent===eventSide;b.setAttribute('aria-selected',String(active));b.setAttribute('tabindex',active?'0':'-1');const count=eventRecords?.filter(e=>(b.dataset.signalEvent==='SELL'?e.kind==='SELL':e.kind==='BUY'||e.kind==='SKIP')&&(tradeType!=='real'||actualFor(e))).length;b.textContent=(b.dataset.signalEvent==='SELL'?'매도':'매수')+(count==null?'':' · '+count+'건')});
 panel.querySelectorAll('[data-signal-type]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.signalType===tradeType)));
 el('events').setAttribute('aria-labelledby',eventSide==='SELL'?'signal-events-sell':'signal-events-buy');
 el('comparison-note').textContent=tradeType==='virtual'?'가상 결과는 수수료·세금 제외 기준입니다.': '같은 시장·전략의 신호 발생 시각·종목·매수/매도 방향으로 비교합니다. 실제매매에서는 신호에 연결된 주문 내역만 표시합니다. 가격 차이 = 실제 체결가 − 신호 기준가. 실제 자동주문·체결 내역은 아래 실제 보유 종목 카드에서 확인합니다. 이 비교 화면의 가상 신호와 실제 주문 연결은 아직 지원하지 않습니다.';
 if(tradeType==='real'){renderActualOrders();return;}
 if(eventRecords===null){el('events').textContent='조회 중…';return}
 const records=eventRecords.filter(e=>(eventSide==='SELL'?e.kind==='SELL':e.kind==='BUY'||e.kind==='SKIP')&&(tradeType!=='real'||actualFor(e)));
 el('events').innerHTML=records.length?records.map(e=>{
  const exit=e.kind==='SELL'?(String(e.reason||'').includes('익절')?['profit','익절']:String(e.reason||'').includes('손절')?['loss','손절']:['other','기타 매도']):null;
  const badge=exit?`<span class="signal-exit-badge signal-exit-${exit[0]}">${exit[1]}</span>`:'';
  const virtual=`<section class="signal-result"><span class="signal-type-badge">가상매매</span><strong>${({BUY:'가상 매수',SELL:'가상 매도',SKIP:'매수 제외'})[e.kind]}</strong><small>${esc(e.quantity??'—')}주 · 기준가 ${money(e.reference_price)}</small><small>${esc(e.reason)}</small><small>손익 ${money(e.pnl)} · 수익률 <b>${pct(virtualReturn(e))}</b></small><small>수수료·세금 제외${e.kind==='BUY'?' · 매수 시점에는 실현 수익률 없음':''}</small></section>`;
  return `<article class="signal-row"><div class="signal-event-heading">${badge}<strong>${esc(e.name)} (${esc(e.code)}) · ${e.kind==='SELL'?'매도':'매수'} 신호</strong></div><small>신호 발생 ${when(e.at)} (한국시간)</small><div class="signal-results ${tradeType==='all'?'':'signal-results-single'}">${tradeType!=='real'?virtual:''}${tradeType!=='virtual'?actualCard(e,actualFor(e)):''}</div></article>`;
 }).join(''):tradeType==='real'?'<p class="signal-empty">이 신호에 연결된 실제 주문 내역이 없습니다.</p>':`<p class="signal-empty">기록된 ${eventSide==='SELL'?'매도':'매수'} 신호가 없습니다.</p>`;
}
el('details').addEventListener('change',()=>{panel.dataset.signalDetails=String(el('details').checked)});
panel.querySelectorAll('[data-signal-type]').forEach(b=>b.addEventListener('click',()=>{tradeType=b.dataset.signalType;renderEvents()}));
panel.querySelectorAll('[data-signal-event]').forEach((b,index,tabs)=>{
 b.addEventListener('click',()=>{eventSide=b.dataset.signalEvent;renderEvents()});
 b.addEventListener('keydown',e=>{let target;if(e.key==='ArrowRight'||e.key==='ArrowLeft')target=tabs[1-index];else if(e.key==='Home')target=tabs[0];else if(e.key==='End')target=tabs[1];if(target){e.preventDefault();target.click();target.focus()}});
});
async function load(action='status'){
 if(action!=='status'&&mutation)return;
 if(action!=='status')mutation=true;
 const id=++generation,requestMarket=market,requestStrategy=selected;clearTimeout(timer);el('toggle').disabled=true;el('refresh').disabled=true;
 try{const d=await fetchQuote('/v1/market/signal-validation',{action,market:requestMarket,strategy:requestStrategy,days});if(id===generation&&!panel.hidden){render(d);el('refresh').hidden=true}}
 catch(e){if(id===generation&&!panel.hidden){el('refresh').hidden=false;el('summary').innerHTML='';el('history-chart').textContent='일별 수익률 조회 실패 · 자동 재시도 예정입니다.';el('period').textContent='기간 수익률 조회 실패 · 다시 선택해 주세요.';el('state').textContent='조회 실패 · 자동 재시도 예정입니다. 다시 시도 버튼으로 즉시 조회할 수 있습니다.';el('state').classList.add('signal-error')}}
 finally{if(action!=='status')mutation=false;if(id===generation&&!panel.hidden){el('refresh').disabled=false;timer=setTimeout(()=>load(),15000)}}
}
function choose(){
 el('refresh').hidden=true;
 generation++;clearTimeout(timer);clearTimeout(elapsedTimer);
 panel.querySelectorAll('[data-signal-market]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.signalMarket===market)));
 panel.querySelectorAll('[data-signal-strategy]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.signalStrategy===selected)));
 el('title').textContent=(market==='KR'?'국내주식':'해외주식')+' · '+definitions[selected][0];el('rule').textContent=definitions[selected][1];
 el('period').textContent=periodLabel()+' 수익률 계산 중…';el('summary').innerHTML='';el('positions').textContent='조회 중…';el('history-chart').textContent='조회 중…';eventRecords=null;executionRecords=[];renderEvents();el('issues').textContent='';el('check').textContent='';el('elapsed').textContent='조회 중…';el('started').textContent='';el('state').textContent='선택한 전략의 검증 결과를 조회하고 있습니다.';
 document.querySelector('#header-status').textContent=el('title').textContent+' · 신호검증';
 history.replaceState(null,'','#signal-validation-'+market.toLowerCase()+'-'+selected);load();
}
panel.querySelectorAll('[data-signal-days]').forEach(b=>b.addEventListener('click',()=>{days=parseDays(b.dataset.signalDays);panel.querySelectorAll('[data-signal-days]').forEach(x=>x.setAttribute('aria-pressed',String(parseDays(x.dataset.signalDays)===days)));el('summary').innerHTML='';el('period').textContent=periodLabel()+' 수익률 계산 중…';load()}));
panel.querySelectorAll('[data-signal-market]').forEach(b=>b.addEventListener('click',()=>{market=b.dataset.signalMarket;choose()}));
panel.querySelectorAll('[data-signal-strategy]').forEach(b=>b.addEventListener('click',()=>{selected=b.dataset.signalStrategy;choose()}));
nav.addEventListener('click',e=>{const b=e.target.closest('.primary-button');if(b&&b!==button){panel.hidden=true;generation++;clearTimeout(timer);clearTimeout(elapsedTimer)}});
button.addEventListener('click',()=>{document.querySelectorAll('main > .panel, main > .flow-panel').forEach(p=>p.hidden=true);accountTabs.hidden=true;panel.hidden=false;nav.querySelectorAll('.primary-button').forEach(b=>b.classList.toggle('active',b===button));document.querySelector('#header-status').textContent='해외주식 · 신호 검증';document.querySelector('#footer-state').textContent='● 신호 검증 · 실제 자동매매 상태는 실제 보유 카드에서 확인';choose()});
window.addEventListener('trading-control-changed',()=>{if(!panel.hidden)load()});
el('refresh').addEventListener('click',()=>load());el('toggle').addEventListener('click',()=>load(enabled?'pause':'resume'));
const initial=window.moaInitialHash||location.hash;const match=initial.match(/^#signal-validation-(kr|us)-(trend|breakout|pullback|reversion|momentum)$/);if(match){market=match[1].toUpperCase();selected=match[2]}else if(initial==='#signal-validation'){market='US'}if(match||initial==='#signal-validation')button.click();
})();

(()=>{
const nav=document.querySelector('.primary-nav');
const strategyButton=nav.querySelector('[data-view="strategy"]');
const signalButton=nav.querySelector('[data-view="signal-validation"]');
const strategyPanel=document.querySelector('#panel-strategy');
const signalPanel=document.querySelector('#panel-signal-validation');
if(!strategyButton||!signalButton||!strategyPanel||!signalPanel)return;
strategyButton.textContent='자동매매';
signalButton.hidden=true;
const tabs=document.createElement('div');
tabs.id='auto-trading-tabs';tabs.hidden=true;tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','자동매매 화면');
tabs.innerHTML='<button type="button" id="auto-strategy-tab" role="tab" aria-controls="panel-strategy">전략매매</button><button type="button" id="auto-signal-tab" role="tab" aria-controls="panel-signal-validation">신호검증</button>';
nav.after(tabs);
const strategyTab=tabs.children[0],signalTab=tabs.children[1];
for(const [panel,tab] of [[strategyPanel,strategyTab],[signalPanel,signalTab]]){panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id)}
const style=document.createElement('style');
style.textContent='.primary-nav [data-view="signal-validation"][hidden],#auto-trading-tabs[hidden]{display:none!important}#auto-trading-tabs{display:flex;gap:6px;padding:5px;background:#e9edf1;border-radius:13px;margin:0 0 22px;width:fit-content}#auto-trading-tabs button{border:0;background:transparent;color:#687787;border-radius:10px;padding:11px 24px;font:inherit;font-weight:700;cursor:pointer}#auto-trading-tabs button[aria-selected="true"]{background:#fff;color:#174f43;box-shadow:0 1px 5px #142f4314}#auto-trading-tabs button:focus-visible{outline:3px solid #2f6fec;outline-offset:2px}@media(max-width:500px){#auto-trading-tabs{width:100%}#auto-trading-tabs button{flex:1;padding:11px 12px}}';
// Market selection is the parent level; strategies are its subordinate menu.
for(const panel of [strategyPanel,signalPanel]){
 panel.querySelector('[data-strategy-market], [data-signal-market]')?.parentElement.classList.add('auto-market-menu');
 panel.querySelector('[data-strategy], [data-signal-strategy]')?.parentElement.classList.add('auto-strategy-menu');
}
style.textContent+=`
:is(#panel-strategy,#panel-signal-validation) .auto-market-menu{display:flex;align-items:center;gap:24px;border-bottom:1px solid #dce3e8;margin:0 0 14px;padding:0;background:transparent;border-radius:0}
:is(#panel-strategy,#panel-signal-validation) .auto-market-menu > :is([data-strategy-market],[data-signal-market]){position:relative;min-height:48px;padding:12px 4px;border:0;border-bottom:3px solid transparent;border-radius:0;background:transparent;color:#657383;font-size:16px;font-weight:700;box-shadow:none}
:is(#panel-strategy,#panel-signal-validation) .auto-market-menu > :is([data-strategy-market],[data-signal-market])[aria-pressed="true"]{color:#174f43;border-bottom-color:#287563;background:transparent}
:is(#panel-strategy,#panel-signal-validation) .auto-strategy-menu{display:flex;flex-wrap:wrap;gap:6px;padding:8px;margin:0 0 20px;background:#eaf0ee;border:1px solid #e0e8e4;border-radius:14px;width:fit-content;max-width:100%;box-sizing:border-box}
:is(#panel-strategy,#panel-signal-validation) .auto-strategy-menu > button{min-height:38px;padding:8px 14px;border:1px solid transparent;border-radius:999px;background:transparent;color:#596c65;font-size:13px;font-weight:600;box-shadow:none}
:is(#panel-strategy,#panel-signal-validation) .auto-strategy-menu > button[aria-pressed="true"]{background:#fff;border-color:#b6cec4;color:#174f43;box-shadow:0 1px 3px #173d3010;font-weight:700}
@media(hover:hover){:is(#panel-strategy,#panel-signal-validation) .auto-market-menu > :is([data-strategy-market],[data-signal-market]):hover{color:#174f43}:is(#panel-strategy,#panel-signal-validation) .auto-strategy-menu > button:hover{background:#f8fbf9;color:#174f43}}
:is(#panel-strategy,#panel-signal-validation) :is(.auto-market-menu,.auto-strategy-menu) > button:focus-visible{outline:3px solid #478bcb;outline-offset:3px}
@media(max-width:500px){:is(#panel-strategy,#panel-signal-validation) .auto-market-menu{gap:20px}:is(#panel-strategy,#panel-signal-validation) .auto-strategy-menu{width:100%;gap:6px}:is(#panel-strategy,#panel-signal-validation) .auto-strategy-menu > button{padding:9px 12px;min-height:40px}}
`;
document.head.append(style);
function sync(view){
 const active=view==='strategy'||view==='signal-validation';tabs.hidden=!active;
 strategyButton.classList.toggle('active',active);signalButton.classList.remove('active');
 for(const [tab,key] of [[strategyTab,'strategy'],[signalTab,'signal-validation']]){const selected=key===view;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1}
}
strategyTab.addEventListener('click',()=>{strategyButton.click();strategyTab.focus()});
signalTab.addEventListener('click',()=>{signalButton.click();signalTab.focus()});
nav.addEventListener('click',e=>{const b=e.target.closest('.primary-button');if(b)sync(b.dataset.view)});
tabs.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?strategyTab:e.key==='End'?signalTab:document.activeElement===strategyTab?signalTab:strategyTab;next.click()});
sync(!signalPanel.hidden?'signal-validation':!strategyPanel.hidden?'strategy':'');
})();

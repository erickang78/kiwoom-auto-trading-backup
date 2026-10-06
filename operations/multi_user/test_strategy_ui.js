/* Minimal DOM integration: verify selected strategy actions and running budget edits. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.style={};this.hidden=false;this.value='';this.type='number';this.nodes={};this.dataset={};}
 set innerHTML(value){this.html=value;for(const match of value.matchAll(/id="([^"]+)"/g))this.nodes['#'+match[1]]=new Element();for(const [key,node] of Object.entries(this.nodes)){const input=value.match(new RegExp('id="'+key.slice(1)+'"[^>]*'));if(input){node.value=input[0].match(/value="([^"]*)"/)?.[1]||'';node.hidden=input[0].includes('hidden');}}}
 get innerHTML(){return this.html;}
 querySelector(selector){return this.nodes[selector]||(this.nodes[selector]=new Element());}
 append(...items){this.children.push(...items);}after(...items){this.afterItems=items;}
 replaceChildren(...items){this.children=items;}addEventListener(event,fn){this.events[event]=fn;}
 setSelectionRange(start,end,direction){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
 async fire(event){return this.events[event]?.({target:this});}
}
(async()=>{
 const page=fs.readFileSync('server-baseline/dashboard/dist/index.html','utf8');
 const source=page.split('<script id="auto-trading-execution-module">')[1].split('</script>')[0];
 const panel=new Element(),head=new Element(),elements=[],calls=[];let choice='trend',focusedBudget=null;
 panel.querySelector=selector=>selector.startsWith('[data-strategy-market]')?{dataset:{strategyMarket:'KR'}}:selector.startsWith('[data-strategy]')?{dataset:{strategy:choice}}:(panel.nodes[selector]||(panel.nodes[selector]=new Element()));
 const states={trend:{enabled:true,budget:'2400000'},breakout:{enabled:false,budget:'0'}};
 const response=body=>({market:'KR',strategy:body.strategy,selected_strategy:body.strategy,global_enabled:true,...states[body.strategy],started_at:null,positions:[],orders:[],issues:[],market_budget:{total_cap:'2400000',allocated:'2400000',strategies:[{strategy:'trend',enabled:true,allocation:'2400000',committed:'500000',positions:9,slots:9},{strategy:'breakout',enabled:false,allocation:'0',committed:'0',positions:0,slots:0}]}});
 const document={head,createElement:tag=>{const e=new Element(tag);elements.push(e);return e;},querySelector:selector=>selector==='#panel-strategy'?panel:null};
 const context={document,window:{addEventListener(){}},MutationObserver:class{observe(){}},TOKEN:'synthetic',setTimeout(){return 1;},clearTimeout(){},fetch:async(url,options)=>{const body=JSON.parse(options.body);if(focusedBudget)assert.equal(focusedBudget.disabled,false,'polling must not disable and blur the focused input');calls.push(body);if(body.action==='allocate')states[body.strategy].budget=body.budget;if(body.action==='stop')states[body.strategy].enabled=false;if(body.action==='start')states[body.strategy].enabled=true;return {ok:true,json:async()=>response(body)};}};
 vm.runInNewContext(source,context);const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};await flush();
 const card=elements.find(e=>e.id==='real-auto-trading'),node=id=>card.querySelector('#auto-'+id);
 assert.equal(node('budget').disabled,false,'running allocation must be editable');assert.equal(node('budget').value,'2,400,000');
 assert.equal(node('start').disabled,true);assert.equal(node('stop').disabled,false);
 assert.match(node('market-overview').children.map(e=>e.textContent).join(' '),/시장 전체 한도 2,400,000원.*돌파매매/);
 assert.match(card.innerHTML,/id="auto-budget" type="text" value="0" inputmode="numeric"/);
 await node('budget').fire('focus');focusedBudget=node('budget');node('budget').value='2,399,999';await panel.events.click({target:{closest:()=>true}});await flush();assert.equal(node('budget').value,'2,399,999','focused value survives polling before input event');
 node('budget').value='2400500';node('budget').setSelectionRange(4,4,'none');await node('budget').fire('input');
 assert.equal(node('budget').value,'2,400,500');assert.equal(node('budget').selectionStart,5,'middle insertion keeps logical digit position');
 node('budget').value='2,40,500';node('budget').setSelectionRange(4,4,'none');await node('budget').fire('input');
 assert.equal(node('budget').value,'240,500');assert.equal(node('budget').selectionStart,3,'middle deletion keeps logical digit position');
 node('budget').value='1234567';node('budget').setSelectionRange(2,5,'backward');await node('budget').fire('input');
 assert.equal(node('budget').value,'1,234,567');assert.equal(node('budget').selectionStart,3);assert.equal(node('budget').selectionEnd,7);assert.equal(node('budget').selectionDirection,'backward');
 await panel.events.click({target:{closest:()=>true}});await flush();assert.equal(node('budget').value,'1,234,567','poll preserves focused draft');
 await node('budget').fire('blur');focusedBudget=null;
 node('budget').value='1800000';await node('budget').fire('input');await node('allocate').fire('click');await flush();
 assert.deepEqual(calls.at(-1),{market:'KR',strategy:'trend',action:'allocate',budget:'1800000'});
 await node('stop').fire('click');await flush();assert.equal(calls.at(-1).strategy,'trend');assert.equal(calls.at(-1).action,'stop');
 choice='breakout';await panel.events.click({target:{closest:()=>true}});await flush();assert.equal(node('budget').value,'0');assert.equal(node('start').disabled,true);
 await node('budget').fire('focus');focusedBudget=node('budget');assert.equal(node('budget').value,'','zero clears immediately');
 await panel.events.click({target:{closest:()=>true}});await flush();assert.equal(node('budget').value,'','poll cannot restore focused empty zero');
 await node('budget').fire('blur');focusedBudget=null;assert.equal(node('budget').value,'0','empty blur restores zero');
 node('budget').value='600000';await node('budget').fire('input');await node('start').fire('click');
 assert.equal(calls.at(-1).action,'status','start must wait for explicit confirmation');
 await node('confirm-start').fire('click');await flush();
 assert.equal(calls.at(-1).strategy,'breakout');assert.equal(calls.at(-1).action,'start');assert.equal(calls.at(-1).confirmed,true);assert.equal(calls.at(-1).budget,'600000','start payload excludes commas');
 assert.equal(states.trend.enabled,false);assert.equal(states.breakout.enabled,true);
 // Exercise the existing chart renderer with five independently calculated series.
 const chart=new Element(),chartContext={market:'KR',selected:'breakout',finite:v=>typeof v==='number'&&Number.isFinite(v),esc:v=>String(v),when:v=>String(v),el:()=>chart};
 const renderSource=page.slice(page.indexOf('function renderHistory('),page.indexOf('\nwindow.moaRenderRealReturnHistory='));
 vm.runInNewContext(renderSource,chartContext);
 const strategyNames=['trend','breakout','pullback','reversion','momentum'];
 chartContext.renderHistory({market:'KR',series:strategyNames.map((strategy,index)=>({strategy,points:[{day:'2026-09-30',at:'synthetic',return_pct:index===0?10:index===1?-10:null}]}))},chart,true,'breakout');
 assert.equal((chart.innerHTML.match(/<span style="color:/g)||[]).length,5);
 assert.match(chart.innerHTML,/5개 전략 일별 누적 실제매매 수익률/);
 assert.match(chart.innerHTML,/추세추종 · 2026-09-30 · 10\.00%/);assert.match(chart.innerHTML,/돌파매매 · 2026-09-30 · -10\.00%/);
 console.log('Strategy UI integration PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});

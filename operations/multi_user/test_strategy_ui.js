/* Minimal DOM integration: verify selected strategy actions and running budget edits. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.style={};this.hidden=false;this.value='';this.type='number';this.nodes={};this.dataset={};}
 set innerHTML(value){this.html=value;for(const match of value.matchAll(/id="([^"]+)"/g))this.nodes['#'+match[1]]=new Element();for(const [key,node] of Object.entries(this.nodes)){const input=value.match(new RegExp('id="'+key.slice(1)+'"[^>]*'));if(input){node.value=input[0].match(/value="([^"]*)"/)?.[1]||'';node.hidden=input[0].includes('hidden');}}}
 get innerHTML(){return this.html;}
 querySelector(selector){return this.nodes[selector]||(this.nodes[selector]=new Element());}
 append(...items){this.children.push(...items);}after(...items){this.afterItems=items;}
 replaceChildren(...items){this.children=items;}addEventListener(event,fn){this.events[event]=fn;}
 async fire(event){return this.events[event]?.({target:this});}
}
(async()=>{
 const page=fs.readFileSync('server-baseline/dashboard/dist/index.html','utf8');
 const source=page.split('<script id="auto-trading-execution-module">')[1].split('</script>')[0];
 const panel=new Element(),head=new Element(),elements=[],calls=[];let choice='trend';
 panel.querySelector=selector=>selector.startsWith('[data-strategy-market]')?{dataset:{strategyMarket:'KR'}}:selector.startsWith('[data-strategy]')?{dataset:{strategy:choice}}:(panel.nodes[selector]||(panel.nodes[selector]=new Element()));
 const states={trend:{enabled:true,budget:'2400000'},breakout:{enabled:false,budget:'0'}};
 const response=body=>({market:'KR',strategy:body.strategy,selected_strategy:body.strategy,global_enabled:true,...states[body.strategy],started_at:null,positions:[],orders:[],issues:[],market_budget:{total_cap:'2400000',allocated:'2400000',strategies:[{strategy:'trend',enabled:true,allocation:'2400000',committed:'500000',positions:9,slots:9},{strategy:'breakout',enabled:false,allocation:'0',committed:'0',positions:0,slots:0}]}});
 const document={head,createElement:tag=>{const e=new Element(tag);elements.push(e);return e;},querySelector:selector=>selector==='#panel-strategy'?panel:null};
 const context={document,window:{addEventListener(){}},MutationObserver:class{observe(){}},TOKEN:'synthetic',setTimeout(){return 1;},clearTimeout(){},fetch:async(url,options)=>{const body=JSON.parse(options.body);calls.push(body);if(body.action==='allocate')states[body.strategy].budget=body.budget;if(body.action==='stop')states[body.strategy].enabled=false;if(body.action==='start')states[body.strategy].enabled=true;return {ok:true,json:async()=>response(body)};}};
 vm.runInNewContext(source,context);const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};await flush();
 const card=elements.find(e=>e.id==='real-auto-trading'),node=id=>card.querySelector('#auto-'+id);
 assert.equal(node('budget').disabled,false,'running allocation must be editable');assert.equal(node('budget').value,'2400000');
 assert.equal(node('start').disabled,true);assert.equal(node('stop').disabled,false);
 assert.match(node('market-overview').children.map(e=>e.textContent).join(' '),/시장 전체 한도 2,400,000원.*돌파매매/);
 node('budget').value='1800000';await node('budget').fire('input');await node('allocate').fire('click');await flush();
 assert.deepEqual(calls.at(-1),{market:'KR',strategy:'trend',action:'allocate',budget:'1800000'});
 await node('stop').fire('click');await flush();assert.equal(calls.at(-1).strategy,'trend');assert.equal(calls.at(-1).action,'stop');
 choice='breakout';await panel.events.click({target:{closest:()=>true}});await flush();assert.equal(node('budget').value,'0');assert.equal(node('start').disabled,true);
 node('budget').value='600000';await node('budget').fire('input');await node('start').fire('click');
 assert.equal(calls.at(-1).action,'status','start must wait for explicit confirmation');
 await node('confirm-start').fire('click');await flush();
 assert.equal(calls.at(-1).strategy,'breakout');assert.equal(calls.at(-1).action,'start');assert.equal(calls.at(-1).confirmed,true);
 assert.equal(states.trend.enabled,false);assert.equal(states.breakout.enabled,true);
 console.log('Strategy UI integration PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});

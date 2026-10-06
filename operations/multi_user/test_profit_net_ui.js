const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('server-baseline/dashboard/dist/index.html','utf8');
const js=html.split('<script id="profit-report-module">')[1].split('</script>')[0];
const render=js.slice(js.indexOf('function render(){'),js.indexOf('async function load(){'));
class E{constructor(){this.textContent='';this.children=[];this.style={};this.selectedOptions=[{textContent:'전체 전략'}]}append(...x){this.children.push(...x)}replaceChildren(){this.children=[];this.textContent=''}}
const els={};const el=id=>els[id]||(els[id]=new E());
const context={el,document:{querySelector:()=>el('header'),createElement:()=>new E()},source:'real',market:'KR',period:'daily',labels:{daily:'일별',monthly:'월별',yearly:'연도별'},color:v=>v>0?'positive':v<0?'negative':'',money:v=>String(v)+'원',percent:v=>v==null?'—':v.toFixed(2)+'%'};
vm.createContext(context);vm.runInContext(render,context);
for(const period of ['daily','monthly','yearly'])for(const pnl of [100,-100,0]){
const row={period:'2026-10',pnl,return_pct:pnl/10,cost:1000,proceeds:1100,net_proceeds:1090,sell_orders:1,confirmed_cost:10,pending_cost_orders:2,provisional:true};context.period=period;context.data={available:true,provisional:true,summary:row,[period]:[row]};context.render();assert(el('heading').textContent.includes('잠정'));assert(el('rows').children[0].children[4].textContent==='1090원');assert(el('rows').children[0].children[7].textContent==='미확정 2건');assert(el('chart').children[0].children[2].textContent===pnl+'원 · 잠정');assert(el('note').textContent.includes('매입원금(비용 제외)'));
context.source='virtual';context.render();assert(el('rows').children[0].children[4].textContent==='1100원');assert(el('rows').children[0].children[7].textContent==='비용 제외');assert(!el('heading').textContent.includes('잠정'));context.source='real';}
context.data={available:true,summary:{pnl:0,return_pct:null,sell_orders:0,confirmed_cost:0,pending_cost_orders:0},daily:[]};context.period='daily';context.render();assert(el('totals').children[1].children[0].textContent==='—');assert(el('rows').children[0].children[0].colSpan===8);
context.data={available:false};context.render();assert(el('totals').children.length===0);console.log('profit UI: 20 synthetic render checks PASS');

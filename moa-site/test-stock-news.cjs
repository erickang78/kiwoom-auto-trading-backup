const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class El {
 constructor(tag){this.tag=tag;this.children=[];this.isConnected=true;this.textContent='';}
 setAttribute(){} append(...els){this.children.push(...els)} replaceChildren(...els){this.children=els}
 set innerHTML(s){this.html=s;this.body=new El('div')} querySelector(){return this.body}
}
const cards=[],pending=[];let calls=0;
const ctx={document:{createElement:t=>new El(t),head:new El('head')},quoteResult:{append:c=>cards.push(c)},
 renderQuote:()=>{for(const c of cards)c.isConnected=false},quoteMarket:'KR',activeQuote:null,URL,Intl,Date,
 fetchQuote:()=>{calls++;return new Promise(resolve=>pending.push(resolve))}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/stock-news-ui.js','utf8'),ctx);
const a={market:'KR',quote:{stk_cd:'005930',stk_nm:'삼성전자'}},b={market:'US',quote:{stk_cd:'AAPL',stk_enm:'APPLE INC'}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 ctx.renderQuote(a,{});const old=cards.at(-1);ctx.renderQuote(b,{});const current=cards.at(-1);
 pending[0]({status:'ok',items:[]});await tick();assert.equal(old.body.children.length,0,'stale response ignored');
 pending[1]({status:'ok',items:[{title:'<img onerror=alert(1)>',source:'Press',url:'https://news.google.com/rss/articles/a',published_at:new Date().toISOString()},{title:'bad',url:'javascript:alert(1)'}]});await tick();
 const list=current.body.children[0];assert.equal(list.children.length,1);assert.equal(list.children[0].children[0].children[0].textContent,'<img onerror=alert(1)>');
 assert.equal(list.children[0].children[0].rel,'noopener noreferrer');
 ctx.renderQuote(b,{});await tick();assert.equal(calls,2,'chart/currency rerender reuses news');
 ctx.renderQuote({market:'KR',quote:{stk_cd:'000660',stk_nm:'SK하이닉스'}},{});pending[2]({status:'unavailable',items:[]});await tick();
 const error=cards.at(-1).body;assert.match(error.children[0].textContent,/불러오지 못/);error.children[1].onclick();assert.equal(calls,4);
 pending[3]({status:'ok',items:[]});await tick();assert.match(error.children[0].textContent,/없습니다/);
 console.log('News UI: stale responses, safe text/links, rerenders, failure/retry and empty state passed');
})();

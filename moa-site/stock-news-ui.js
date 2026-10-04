(() => {
'use strict';
const style=document.createElement('style');
style.textContent='.stock-news{margin-top:18px}.stock-news .card-head{gap:12px;flex-wrap:wrap}.stock-news-list{list-style:none;margin:0;padding:0}.stock-news-list li+li{border-top:1px solid #edf0f4}.stock-news-link{display:block;padding:15px 0;text-decoration:none;color:#26394f;line-height:1.55;overflow-wrap:anywhere}.stock-news-link:hover .stock-news-title{text-decoration:underline;color:#16866f}.stock-news-link:focus-visible{outline:2px solid #16866f;outline-offset:3px}.stock-news-title{font-size:15px;font-weight:700}.stock-news-meta{display:block;margin-top:5px;color:#788698;font-size:12px}.stock-news-note{font-size:12px;color:#788698;margin:8px 0 0}.stock-news-status{color:#788698;font-size:14px;line-height:1.6}.stock-news-retry{margin-top:8px;border:1px solid #d7e1e9;background:#f7f9fb;color:#26394f;border-radius:8px;padding:8px 12px;cursor:pointer}';
document.head.append(style);
const requests=new WeakMap();
const originalRender=renderQuote;
renderQuote=function(data,chart){
  originalRender(data,chart);
  const q=data.quote||{},market=data.market||quoteMarket,code=q.stk_cd||activeQuote?.code;
  const name=(market==='US'?q.stk_enm||q.stk_nm:q.stk_nm)||code;
  const card=document.createElement('section');card.className='card stock-news';card.setAttribute('aria-label','종목 관련 뉴스');
  card.innerHTML='<div class="card-head"><h2 class="section-title">관련 뉴스</h2><span class="tag">최근 7일 · 최대 5개</span></div><div class="stock-news-body" aria-live="polite"><p class="stock-news-status">뉴스를 불러오고 있습니다…</p></div><p class="stock-news-note">Google 뉴스 검색 · 제목을 누르면 기사로 이동합니다.</p>';
  quoteResult.append(card);
  const body=card.querySelector('.stock-news-body');
  function load(retry=false){
    if(retry)requests.delete(data);
    body.textContent='뉴스를 불러오고 있습니다…';
    if(!requests.has(data))requests.set(data,fetchQuote('/v1/market/news',{market,code,name}).catch(()=>({status:'unavailable',items:[]})));
    requests.get(data).then(result=>{
      if(!card.isConnected)return;
      body.replaceChildren();
      if(result.status!=='ok'){
        const p=document.createElement('p');p.className='stock-news-status';p.textContent='뉴스를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
        const retryButton=document.createElement('button');retryButton.type='button';retryButton.className='stock-news-retry';retryButton.textContent='뉴스 다시 조회';retryButton.onclick=()=>load(true);body.append(p,retryButton);return;
      }
      const items=(Array.isArray(result.items)?result.items:[]).filter(item=>{try{const u=new URL(item.url);return u.protocol==='https:'&&u.hostname==='news.google.com'&&u.pathname.startsWith('/rss/articles/')&&!u.username&&!u.password;}catch{return false;}}).slice(0,5);
      if(!items.length){const p=document.createElement('p');p.className='stock-news-status';p.textContent='최근 7일간 검색된 관련 뉴스가 없습니다.';body.append(p);return;}
      const list=document.createElement('ul');list.className='stock-news-list';
      for(const item of items){
        const li=document.createElement('li'),a=document.createElement('a'),title=document.createElement('span'),meta=document.createElement('span');
        a.className='stock-news-link';a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';
        title.className='stock-news-title';title.textContent=item.title;
        meta.className='stock-news-meta';const date=new Date(item.published_at);meta.textContent=(item.source||'출처 미표시')+(Number.isFinite(date.getTime())?' · '+new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(date):'');
        a.append(title,meta);li.append(a);list.append(li);
      }
      body.append(list);
    });
  }
  load();
};
})();

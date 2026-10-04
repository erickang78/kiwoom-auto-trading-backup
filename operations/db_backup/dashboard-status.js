(()=>{
  const card=document.createElement('section');
  card.id='db-backup-status';
  card.style.cssText='margin:20px auto;padding:16px 20px;max-width:1160px;border:1px solid #dbe3e9;border-radius:16px;background:#fff;color:#344256;font-size:13px;line-height:1.7;box-sizing:border-box';
  const title=document.createElement('strong');title.textContent='거래 데이터 백업';
  const state=document.createElement('span');state.style.marginLeft='12px';state.textContent='확인 중';
  const detail=document.createElement('div');detail.style.cssText='margin-top:4px;color:#66758a';
  card.append(title,state,detail);
  const code=document.createElement('div');code.style.cssText='margin-top:10px;padding-top:10px;border-top:1px solid #e4e9ee';card.append(code);
  const footer=document.querySelector('footer'); if(footer)footer.before(card);else document.body.append(card);
  const labels={ok:'정상',failed:'백업 실패',stale:'일별 백업 지연',never:'첫 백업 대기',unavailable:'상태 확인 불가'};
  async function refresh(){
    if(document.hidden)return;
    try{
      const response=await fetch('/v1/backup/status',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
      if(!response.ok)throw Error('status');
      const data=await response.json();state.textContent=labels[data.status]||labels.unavailable;
      state.style.color=data.status==='ok'?'#147a67':'#b45309';
      const last=data.last_success?new Date(data.last_success).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false}):'없음';
      detail.textContent='마지막 성공: '+last+' · 매일 01:05 자동 백업'+(data.status==='failed'?' · 최근 백업 작업을 완료하지 못했습니다.':data.status==='stale'?' · 26시간 이상 백업이 없습니다. 서버 상태를 점검해 주세요.':'');
      const c=data.code||{};const codeLast=c.last_success?new Date(c.last_success).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false}):'없음';
      code.textContent='코드 백업 · '+(labels[c.status]||labels.unavailable)+' · 마지막 성공: '+codeLast+' · 매일 01:10 GitHub 백업';
    }catch(error){code.textContent='코드 백업 · 상태 확인 불가';state.textContent=labels.unavailable;state.style.color='#b45309';detail.textContent='백업 상태를 불러오지 못했습니다. 연결을 확인해 주세요.';}
  }
  refresh();setInterval(refresh,60000);document.addEventListener('visibilitychange',refresh);
})();

(()=>{
'use strict';
function mount(){
 const logout=document.querySelector('form[action="/logout"]');
 if(!logout||document.querySelector('#trading-control'))return;
 const button=document.createElement('button');button.id='trading-control';button.type='button';
 button.style.cssText='margin-right:12px;padding:10px 18px;border:1px solid #c23f38;border-radius:9px;background:#fff4f3;color:#b3342d;font:inherit;font-weight:700;cursor:pointer';
 const message=document.createElement('div');message.id='trading-control-message';message.setAttribute('role','status');message.setAttribute('aria-live','polite');message.style.cssText='font-size:12px;margin-top:10px;color:#687078;line-height:1.6';
 const controls=document.createElement('span');controls.style.cssText='display:inline-flex;flex-direction:column;align-items:flex-start;vertical-align:top;margin-right:12px';
 const note=document.createElement('small');note.id='trading-control-scope';note.style.cssText='display:block;margin-top:7px;font-size:11px;color:#687078;line-height:1.6;text-align:left;max-width:260px';note.textContent='매매 중지 시 가상매매와 실제매매가 모두 중지되며, 국내·미국 시장에 함께 적용됩니다.';
 button.setAttribute('aria-describedby','trading-control-scope');controls.append(button,note);logout.prepend(controls);logout.append(message);
 let enabled=null,busy=false,timer;
 function render(){button.disabled=busy;button.textContent=busy?'처리 중…':enabled===null?'매매 상태 확인':enabled?'매매 중지':'매매 시작';button.style.opacity=busy?'.6':'1';button.style.color=enabled===false?'#16704c':'#b3342d';button.style.borderColor=enabled===false?'#16704c':'#c23f38';button.style.background=enabled===false?'#eef9f2':'#fff4f3';}
 async function request(action='status'){
  if(busy)return;busy=true;clearTimeout(timer);render();
  try{
   const response=await fetch('/v1/trading/control',{method:'POST',headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'application/json'},body:JSON.stringify({action})});
   const data=await response.json();if(!response.ok||typeof data.enabled!=='boolean')throw Error('unavailable');
   const changed=enabled!==data.enabled;enabled=data.enabled;
   message.textContent=enabled?'가상·실제 매매 허용 중':'가상·실제 매매 중지됨 · 과거 매매 기록과 보유 내역은 유지됩니다. 이미 접수된 주문은 취소되지 않습니다.';
   if(changed||action!=='status')window.dispatchEvent(new Event('trading-control-changed'));
  }catch(error){enabled=null;message.textContent='매매 상태를 확인하지 못했습니다. 버튼을 눌러 다시 확인해 주세요.';}
  finally{busy=false;render();timer=setTimeout(()=>request(),15000);}
 }
 button.addEventListener('click',()=>request(enabled===null?'status':enabled?'pause':'resume'));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)request()});
 request();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();

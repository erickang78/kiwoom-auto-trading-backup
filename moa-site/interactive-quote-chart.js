(()=>{
'use strict';
const style=document.createElement('style');style.textContent='.chart-navigation{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:10px 0}.chart-navigation button{border:1px solid #d7e1e9;border-radius:8px;background:#fff;padding:6px 11px;color:#26394f;cursor:pointer;font:inherit;font-size:13px}.chart-navigation button:disabled{opacity:.4;cursor:default}.chart-navigation span{font-size:12px;color:#788698}.chart-viewport{touch-action:pan-y;cursor:grab;user-select:none}.chart-viewport.dragging{cursor:grabbing}.chart-viewport svg{display:block;width:100%}.chart-gesture-note{font-size:12px;color:#788698;margin:6px 0}';document.head.append(style);
function range(total,start,count){count=Math.max(Math.min(8,total),Math.min(total,Math.round(count)));return {start:Math.max(0,Math.min(total-count,Math.round(start))),count};}
const originalRender=renderQuote;
renderQuote=function(data,chart){
 originalRender(data,chart);
 const box=quoteResult.querySelector('.price-chart');if(!box)return;
 const bars=(chart?.bars||[]).filter(b=>chartNumber(b.high)>0).slice(-60),total=bars.length;
 if(!total)return;
 const market=data.market||quoteMarket;
 let view={start:0,count:total};
 const controls=document.createElement('div');controls.className='chart-navigation';
 controls.innerHTML='<button type="button" data-action="in" aria-label="차트 확대">＋</button><button type="button" data-action="out" aria-label="차트 축소">−</button><button type="button" data-action="left" aria-label="차트 이전 구간">←</button><button type="button" data-action="right" aria-label="차트 다음 구간">→</button><button type="button" data-action="reset">전체 보기</button><span aria-live="polite"></span>';
 const viewport=document.createElement('div');viewport.className='chart-viewport';viewport.tabIndex=0;viewport.setAttribute('role','group');viewport.setAttribute('aria-label','주가 차트. 위아래 화살표로 확대 축소, 좌우 화살표로 이동');
 box.querySelector('svg')?.remove();box.append(controls,viewport);
 const note=document.createElement('p');note.className='chart-gesture-note';note.textContent='휠로 확대·축소 · 좌우 드래그로 이동 · 모바일은 두 손가락 확대·축소 (최근 60개 범위)';box.append(note);
 function draw(){
  const html=renderChart({...chart,market,bars:bars.slice(view.start,view.start+view.count)}),temporary=document.createElement('div');temporary.innerHTML=html;
  viewport.replaceChildren(temporary.querySelector('svg'));
  controls.querySelector('span').textContent=(view.start+1)+'–'+(view.start+view.count)+' / '+total+'개';
  controls.querySelector('[data-action="in"]').disabled=view.count<=Math.min(8,total);
  controls.querySelector('[data-action="out"]').disabled=view.count===total;
  controls.querySelector('[data-action="left"]').disabled=view.start===0;
  controls.querySelector('[data-action="right"]').disabled=view.start+view.count===total;
 }
 function zoom(factor,anchor=.5){const count=range(total,view.start,view.count*factor).count;view=range(total,view.start+(view.count-count)*anchor,count);draw();}
 function pan(amount){view=range(total,view.start+amount,view.count);draw();}
 controls.addEventListener('click',e=>{const action=e.target.closest('button')?.dataset.action;if(action==='in')zoom(.8);else if(action==='out')zoom(1.25);else if(action==='left')pan(-Math.max(1,Math.round(view.count*.25)));else if(action==='right')pan(Math.max(1,Math.round(view.count*.25)));else if(action==='reset'){view={start:0,count:total};draw();}});
 viewport.addEventListener('wheel',e=>{if(!e.deltaY)return;e.preventDefault();const rect=viewport.getBoundingClientRect();zoom(e.deltaY<0?.8:1.25,Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width)));},{passive:false});
 viewport.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(e.key))return;e.preventDefault();if(e.key==='ArrowUp')zoom(.8);else if(e.key==='ArrowDown')zoom(1.25);else if(e.key==='Home'){view={start:0,count:total};draw();}else pan(e.key==='ArrowLeft'?-Math.max(1,Math.round(view.count*.1)):Math.max(1,Math.round(view.count*.1)));});
 let drag=null;
 viewport.addEventListener('pointerdown',e=>{if(e.pointerType==='touch'||e.button!==0)return;viewport.setPointerCapture(e.pointerId);drag={x:e.clientX,start:view.start,count:view.count};viewport.classList.add('dragging');});
 viewport.addEventListener('pointermove',e=>{if(!drag)return;view=range(total,drag.start-(e.clientX-drag.x)/viewport.getBoundingClientRect().width*drag.count,drag.count);draw();});
 function endDrag(){drag=null;viewport.classList.remove('dragging');}viewport.addEventListener('pointerup',endDrag);viewport.addEventListener('pointercancel',endDrag);viewport.addEventListener('lostpointercapture',endDrag);
 let touch=null;
 function touchState(touches){const a=touches[0],b=touches[1];return {x:b?(a.clientX+b.clientX)/2:a.clientX,y:a.clientY,distance:b?Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY):0,start:view.start,count:view.count};}
 viewport.addEventListener('touchstart',e=>{touch=touchState(e.touches);},{passive:true});
 viewport.addEventListener('touchmove',e=>{
  if(!touch)return;const now=touchState(e.touches),width=viewport.getBoundingClientRect().width;
  if(e.touches.length>=2&&touch.distance>0){e.preventDefault();const count=range(total,touch.start,touch.count*touch.distance/Math.max(1,now.distance)).count;const anchor=Math.max(0,Math.min(1,(touch.x-viewport.getBoundingClientRect().left)/width));view=range(total,touch.start+(touch.count-count)*anchor-(now.x-touch.x)/width*count,count);draw();}
  else if(e.touches.length===1&&Math.abs(now.x-touch.x)>Math.abs(now.y-touch.y)&&Math.abs(now.x-touch.x)>8){e.preventDefault();view=range(total,touch.start-(now.x-touch.x)/width*touch.count,touch.count);draw();}
 },{passive:false});
 viewport.addEventListener('touchend',e=>{touch=e.touches.length?touchState(e.touches):null;},{passive:true});viewport.addEventListener('touchcancel',()=>{touch=null;},{passive:true});
 draw();
};
})();

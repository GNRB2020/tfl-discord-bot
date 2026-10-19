/* Phase 12 presentation patch; load after phase11.js. */
(()=>{'use strict';
 const $=id=>document.getElementById(id);
 const css=document.createElement('style'); css.textContent=`
 #menuView #trainingHub{grid-column:1/-1;background:#8c1825;border-color:#e75b68}
 #trainingHubPanel{display:none;grid-column:1/-1;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
 #trainingHubPanel.open{display:grid}
 #tugShared{background:#0b1c2c;border:2px solid #34a8d3;border-radius:13px;text-align:center;padding:8px;}
 #tugShared .value{font-size:clamp(43px,8vh,82px);font-weight:900}
 #tugView .tugplayers .tugscore{font-size:clamp(24px,4.2vh,42px)!important}
 @media(max-width:650px){#trainingHubPanel{grid-template-columns:1fr}}
 `;document.head.append(css);
 function labels(){for(const el of document.querySelectorAll('button')){if(el.textContent.trim().toUpperCase()==='BUCHEN')el.textContent='EINGABE';if(el.textContent.trim().toUpperCase()==='SCORE BUCHEN')el.textContent='EINGABE'} }
 new MutationObserver(labels).observe(document.body,{subtree:true,childList:true});labels();
 // Group the training games behind a single menu entry, without changing their handlers.
 const menu=$('menuView')?.querySelector('.menu');
 if(menu){
  const hub=document.createElement('button');hub.id='trainingHub';hub.className='menucard';hub.innerHTML='TRAINING<small>Spiele und Trainingsturniere auswählen</small>';
  const panel=document.createElement('div');panel.id='trainingHubPanel';
  menu.prepend(panel);menu.prepend(hub);
  hub.onclick=()=>panel.classList.toggle('open');
  function move(){for(const id of ['x01','sau','trainingTournament']){const n=$(id);if(n&&n.parentElement!==panel)panel.append(n)}
   const tug=Array.from(menu.querySelectorAll('.menucard')).find(x=>x.textContent.includes('Tauziehen'));if(tug)panel.append(tug);
   const bobs=Array.from(menu.querySelectorAll('.menucard')).find(x=>x.textContent.includes('Bobs27'));if(bobs)panel.append(bobs);
  }
  move();setTimeout(move,0); // other phase scripts may append their menu entry in DOMContentLoaded
 }
 // Tug of war: the shared counter is the source of truth; both target distances derive from it.
 function syncTug(){const view=$('tugView');if(!view||!S||S.kind!=='tug')return;
  let shared=$('tugShared');if(!shared){shared=document.createElement('div');shared.id='tugShared';view.querySelector('.tugplayers')?.before(shared)}
  const common=Number.isFinite(Number(S.position))?Number(S.position):Number(S.remaining?.[0]);
  if(!Number.isFinite(common))return;
  shared.innerHTML='<div>GEMEINSAMER SCORE</div><div class="value"></div><div>Spieler 1 bis 0: <b id="tugTo0"></b> · Spieler 2 bis 362: <b id="tugTo362"></b></div>';
  shared.querySelector('.value').textContent=common;
  $('tugTo0').textContent=common;
  $('tugTo362').textContent=362-common;
  const p=view.querySelector('.tugplayers');if(p){p.style.display='grid';p.querySelectorAll('.tugscore').forEach(x=>x.style.display='none')}
 }
 new MutationObserver(()=>{if($('tugView')?.classList.contains('hide'))return;syncTug()}).observe($('tugView')||document.body,{attributes:true,subtree:false,attributeFilter:['class']});
 // phase11 script redraws the screen after every throw; wrap that redraw if present.
 if(typeof showTug==='function'){const prev=showTug;showTug=function(){prev();syncTug()}}
})();

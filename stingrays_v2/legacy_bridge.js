/* Original Stingrays scorer UI, V2 Neon transport; no legacy-session dependency. */
(()=>{'use strict';
 const qs=new URLSearchParams(location.search),mid=qs.get('match'),freeMode=qs.get('free')==='1';
 if(!mid){location.replace('/dart/v2/');return}
 let version=0,completed=false,meta={};
 const back=()=>location.assign(freeMode?'/dart/v2/':'/dart/v2/?competition='+encodeURIComponent(qs.get('competition')||''));
 const base=(freeMode?'/dart/v2/api/free-x01/':'/dart/v2/api/matches/')+encodeURIComponent(mid);
 async function req(path='',data){const r=await fetch(base+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json','Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const txt=await r.text();let obj={};try{obj=JSON.parse(txt)}catch{}if(!r.ok)throw Error(obj.error||txt||'HTTP '+r.status);return obj}
 function normalize(raw){
   const state=typeof raw.state==='string'?JSON.parse(raw.state||'{}'):(raw.state||{}),rules=state.rules||(typeof meta.rules==='string'?JSON.parse(meta.rules):meta.rules)||{},rest=state.remaining||[rules.start_score||501,rules.start_score||501],visits=state.visits||[];
   version=raw.state_version??raw.version??version;
   const current=state.current||0;
   const stats=[0,1].map(i=>{const items=visits.filter(v=>v.player===i&&!v.bust),d=items.reduce((v,x)=>v+(x.darts||3),0);return {average:d?items.reduce((v,x)=>v+(x.score||0),0)*3/d:0}});
   return {...state,kind:'x01',names:state.names||[meta.player1,meta.player2],rules,remaining:rest,current,
      legs:state.legs||[raw.legs1||0,raw.legs2||0],sets:state.sets||[raw.sets1||0,raw.sets2||0],
      done:!!state.done||raw.status==='finished',can_checkout:state.done?[]:possible(rest[current]),
      current_stats:stats,last:visits.slice(-8),history:visits,can_undo:raw.status==='running'&&visits.length>0,summary:raw.summary||null};
 }
 api=async function(path,data){
   if(path==='state'){const m=await req();meta=m;return normalize(m)}
   if(path==='throw'){
     const r=await req('/throw',{points:data.points,darts:data.darts||3,checkout:!!data.checkout,bullfinish:!!data.bullfinish,checkout_attempts:data.checkout_attempts||0,version});
     return normalize({...r,status:r.state?.done?'finished':'running'});
   }
   if(path==='undo'){const r=await req('/undo',{version});return normalize({...r,status:'running'})}
   throw Error('Bitte den Wettbewerb über die V2-Übersicht verwalten.');
 };
 // The original scorer remains untouched; add a match header and per-player history.
 const playersRow=document.querySelector('#scorerView .players');
 const middle=document.createElement('aside');middle.id='v2Central';middle.className='v2-central';
 middle.innerHTML='<span class="v2-sub">SPIELSTAND</span><strong id="v2LegScore">0 : 0</strong><span id="v2SetScore">SETS 0 : 0</span><small id="v2MatchFormat"></small>';
 playersRow.insertBefore(middle,document.getElementById('p1'));
 for(let i=0;i<2;i++){const wrap=document.createElement('div');wrap.className='v2-recent';wrap.innerHTML='<div class="v2-recent-head">LETZTE 3 AUFNAHMEN</div><div id="v2Recent'+i+'" class="v2-recent-list">–</div>';
   document.getElementById('p'+i).querySelector('div').append(wrap)}
 const tabs=document.createElement('div');tabs.className='v2-match-tabs';tabs.innerHTML='<button type="button" id="v2ScoreTab">SCORER</button><button type="button" id="v2StatsTab">STATISTIKEN</button><button type="button" id="v2BestTab">BESTLEISTUNGEN</button>';
 const scorer=document.querySelector('#scorerView .scorer');scorer.prepend(tabs);
 document.getElementById('v2StatsTab').onclick=()=>showLiveStats('stats');
 document.getElementById('v2BestTab').onclick=()=>showLiveStats('best');
 document.getElementById('v2ScoreTab').onclick=()=>{closeModal()};
 function showLiveStats(mode){
  const vis=S?.history||[],names=S?.names||['Spieler 1','Spieler 2'];
  const items=[0,1].map(i=>vis.filter(v=>v.player===i));
  const fields=mode==='best'?[
    ['180',p=>p.filter(v=>v.score===180).length],['171+',p=>p.filter(v=>v.score>=171).length],
    ['Highfinish',p=>Math.max(0,...p.filter(v=>v.checkout).map(v=>v.score))],['Bullfinishes',p=>p.filter(v=>v.bullfinish).length]
  ]:[['Aufnahmen',p=>p.length],['Average',p=>{const d=p.reduce((s,v)=>s+(v.darts||3),0);return d?(3*p.filter(v=>!v.bust).reduce((s,v)=>s+v.score,0)/d).toFixed(2):'0,00'}],
    ['100+',p=>p.filter(v=>v.score>=100).length],['140+',p=>p.filter(v=>v.score>=140).length],
    ['Checkouts',p=>p.filter(v=>v.checkout).length],['Legs',(_,i)=>S.legs[i]]];
  let html='<h2>'+(mode==='best'?'Bestleistungen':'Matchstatistiken')+'</h2><table class="v2-stats-table"><thead><tr><th>'+names[0]+'</th><th>Wert</th><th>'+names[1]+'</th></tr></thead><tbody>';
  for(const [title,calc] of fields){html+='<tr><td>'+calc(items[0],0)+'</td><th>'+title+'</th><td>'+calc(items[1],1)+'</td></tr>'}
  html+='</tbody></table><div class="actions"><button id="v2CloseStats">ZUM SCORER</button></div>';
  modal(html);document.getElementById('v2CloseStats').onclick=closeModal;
 }
 function showBoard(){
  if(!S?.names)return;
  document.getElementById('v2LegScore').textContent=(S.legs?.[0]||0)+' : '+(S.legs?.[1]||0);
  document.getElementById('v2SetScore').textContent='SETS '+(S.sets?.[0]||0)+' : '+(S.sets?.[1]||0);
  document.getElementById('v2MatchFormat').textContent=S.rules?.mode==='sets'?'Best of '+S.rules.best_of_sets+' Sets':'Best of '+S.rules?.max_legs+' Legs';
  for(let i=0;i<2;i++){const target=document.getElementById('v2Recent'+i);target.replaceChildren();
    const last=(S.history||[]).filter(v=>v.player===i).slice(-3).reverse();
    if(!last.length){target.textContent='Noch keine Aufnahme';continue}
    for(const v of last){const pill=document.createElement('span');pill.className='v2-visit';pill.textContent=v.score+(v.checkout?' ✓':'');target.appendChild(pill)}
  }
 }
 // Checkout: one choice, one booking. No redundant second dart-count dialog.
 const nativeCheckout=checkoutDialog;
 checkoutDialog=function(isSau,selected){
   const remainder=isSau?S.remaining:S.remaining[S.current];
   const choices=(isSau?possible(remainder):(S.can_checkout||[])).filter(d=>d>=1&&d<=3);
   if(!choices.length){err('Kein gültiger Checkout für diese Restpunktzahl');return}
   if(!choices.includes(selected))selected=choices[0];
   const mask=document.createElement('div');mask.className='v2-checkout-choice';
   const label=document.createElement('h2');label.textContent='Checkout · '+remainder+' Rest';mask.append(label);
   const note=document.createElement('p');note.textContent='Wie viele Darts wurden benötigt? Ein Klick bucht den Checkout direkt.';mask.append(note);
   const row=document.createElement('div');row.className='v2-checkout-actions';mask.append(row);
   let bull=null;
   if(remainder>=50){const b=document.createElement('label');b.className='v2-bull-choice';bull=document.createElement('input');bull.type='checkbox';b.append(bull,document.createTextNode(' Bullfinish'));mask.append(b)}
   const help=document.createElement('small');help.textContent='Tipp: 1, 2 oder 3 auf dem Zahlenfeld lange halten, um direkt auszuchecken.';mask.append(help);
   const cancel=document.createElement('button');cancel.textContent='Abbrechen';cancel.onclick=closeModal;
   for(const darts of choices){const button=document.createElement('button');button.textContent=darts+' Dart'+(darts>1?'s':'');button.className='green';button.onclick=()=>{const isBull=!!bull?.checked;closeModal();send(remainder,{checkout:true,darts,bullfinish:isBull,checkout_attempts:1})};row.append(button)}
   row.append(cancel);$('modalContent').replaceChildren(mask);$('modal').classList.remove('hide');
 };
 // Existing generic 1/2/3 HOLD row is redundant. Long-holding number-pad keys
 // now checks out directly, without a second question about dart count.
 const oldHold=$('hold');if(oldHold)oldHold.style.display='none';
 const pad=$('pad');let suppressNextClick=false;
 pad?.addEventListener('click',ev=>{if(!suppressNextClick)return;ev.preventDefault();ev.stopImmediatePropagation();suppressNextClick=false},true);
 for(const button of pad?.querySelectorAll('button')||[]){
   const dart=Number(button.textContent.trim());if(![1,2,3].includes(dart))continue;
   let holdTimer=null,triggered=false;
   button.addEventListener('pointerdown',()=>{triggered=false;holdTimer=setTimeout(()=>{
     if(!S||S.done||!(S.can_checkout||[]).includes(dart))return;
     triggered=true;suppressNextClick=true;
     const remainder=S.remaining[S.current];entry='';send(remainder,{checkout:true,darts:dart,bullfinish:false,checkout_attempts:1});
   },650)});
   for(const event of ['pointerup','pointerleave','pointercancel'])button.addEventListener(event,()=>{clearTimeout(holdTimer);holdTimer=null});
 }
 // Match-scoped statistics only, without solo modes from unrelated disciplines.
 function summaryFromHistory(){
   const names=S?.names||['Spieler 1','Spieler 2'],vis=S?.history||[];
   const own=[0,1].map(i=>vis.filter(v=>v.player===i));
   const avg=a=>{const d=a.reduce((n,v)=>n+(v.darts||3),0);return d?(3*a.reduce((n,v)=>n+(v.bust?0:v.score),0)/d).toFixed(2):'–'};
   const firstNine=(a,limit=9)=>{const groups={};for(const v of a)(groups[v.leg_index]??=[]).push(v);
      let score=0,darts=0;for(const leg of Object.values(groups)){let used=0;for(const v of leg){if(used+(v.darts||3)>limit)break;used+=v.darts||3;darts+=v.darts||3;score+=v.bust?0:v.score}}return darts?(score*3/darts).toFixed(2):'–'};
   const count=(a,p)=>a.filter(p).length;
   const rows=[
     ['Ø Average',...own.map(avg)],['Ø First 9',...own.map(a=>firstNine(a,9))],
     ['Ø First 12',...own.map(a=>firstNine(a,12))],['Ø First 15',...own.map(a=>firstNine(a,15))],['Ø First 18',...own.map(a=>firstNine(a,18))],
     ['60+',...own.map(a=>count(a,v=>v.score>=60&&!v.bust))],
     ['80+',...own.map(a=>count(a,v=>v.score>=80&&!v.bust))],
     ['100+',...own.map(a=>count(a,v=>v.score>=100&&!v.bust))],
     ['140+',...own.map(a=>count(a,v=>v.score>=140&&!v.bust))],
     ['180',...own.map(a=>count(a,v=>v.score===180&&!v.bust))],
     ['Gewonnene Legs',...(S.legs||[0,0])],
     ['Gewonnene Sets',...(S.sets||[0,0])],
   ];
   const best=[['Highscore',...own.map(a=>Math.max(0,...a.filter(v=>!v.bust).map(v=>v.score)))],
     ['Highfinish',...own.map(a=>Math.max(0,...a.filter(v=>v.checkout).map(v=>v.score)))],
     ['Bullfinishes',...own.map(a=>count(a,v=>v.bullfinish))],
     ['Shortgame',...own.map(a=>{const groups={};for(const v of a)(groups[v.leg_index]??=[]).push(v);const totals=Object.values(groups).filter(x=>x.some(v=>v.checkout)).map(x=>x.reduce((n,v)=>n+(v.darts||3),0));return totals.length?Math.min(...totals):'–'})]];
   return {names,rows,best,vis};
 }
 function showCompleteReport(){
   const data=summaryFromHistory();
   const wrap=document.createElement('div');wrap.className='v2-final-report';
   const title=document.createElement('h2');title.textContent='Match beendet · '+data.names[0]+' – '+data.names[1];wrap.append(title);
   const tabs=document.createElement('div');tabs.className='v2-report-tabs';wrap.append(tabs);
   const report=document.createElement('div');report.className='v2-report-body';wrap.append(report);
   const makeGrid=(heads,records)=>{const sc=document.createElement('div');sc.className='v2-report-scroll';const table=document.createElement('table');table.className='v2-report-grid';
     const tr=document.createElement('tr');for(const h of heads){const th=document.createElement('th');th.textContent=h;tr.append(th)}table.append(tr);
     for(const record of records){const row=document.createElement('tr');for(const cell of record){const td=document.createElement('td');td.textContent=String(cell??'–');row.append(td)}table.append(row)}sc.append(table);return sc};
   const render=(name)=>{report.replaceChildren();
     if(name==='Statistiken')report.append(makeGrid(['Kennzahl',...data.names],data.rows));
     if(name==='Bestleistungen')report.append(makeGrid(['Bestleistung',...data.names],data.best));
     if(name==='Darts / Leg'){
       const legs=[...new Set(data.vis.map(v=>v.leg_index))].sort((a,b)=>a-b);
       const rows=legs.map(leg=>[leg+1,...[0,1].map(i=>{const own=data.vis.filter(v=>v.player===i&&v.leg_index===leg);const darts=own.reduce((n,v)=>n+(v.darts||3),0);return darts?(own.some(v=>v.checkout)?String(darts):'('+darts+')'):'–'})]);
       report.append(makeGrid(['Leg',...data.names],rows));
     }
     if(name==='Averages / Leg'){
       const legs=[...new Set(data.vis.map(v=>v.leg_index))].sort((a,b)=>a-b);
       const rows=legs.map(leg=>[leg+1,...[0,1].map(i=>{const a=data.vis.filter(v=>v.player===i&&v.leg_index===leg),d=a.reduce((n,v)=>n+(v.darts||3),0);return d?(3*a.reduce((n,v)=>n+(v.bust?0:v.score),0)/d).toFixed(1):'–'})]);
       report.append(makeGrid(['Leg',...data.names],rows));
     }
     if(name==='Checkouts / Leg'){
       report.append(makeGrid(['Leg',...data.names],[...new Set(data.vis.map(v=>v.leg_index))].sort((a,b)=>a-b).map(leg=>[leg+1,...[0,1].map(i=>data.vis.find(v=>v.player===i&&v.leg_index===leg&&v.checkout)?.score??'–')])))
     }
   };
   for(const item of ['Statistiken','Bestleistungen','Darts / Leg','Averages / Leg','Checkouts / Leg']){
     const b=document.createElement('button');b.textContent=item;b.onclick=()=>render(item);tabs.append(b)
   }
   render('Statistiken');const close=document.createElement('button');close.className='green';close.textContent='ZUM WETTBEWERB';close.onclick=back;wrap.append(close);
   $('modalContent').replaceChildren(wrap);$('modal').classList.remove('hide');
 }

 result=function(){if(!S?.done||completed)return;completed=true;showCompleteReport()};
 const originalShow=showMatch;showMatch=function(){originalShow();document.getElementById('context').textContent='STINGRAYS · WETTBEWERB';};
 const oldScreen=screen;screen=function(id){if(id==='loginView'||id==='menuView'||id==='configView'){back();return}oldScreen(id)};
 for(const id of ['homebtn','logout'])document.getElementById(id).onclick=back;
 const undo=document.createElement('button');undo.textContent='↶ LETZTE AUFNAHME ZURÜCK';undo.type='button';undo.style.cssText='background:#37495f;border:1px solid #c7a86a;color:white;font-weight:800';
 undo.onclick=async()=>{if(!S?.can_undo||!confirm('Letzte Aufnahme zurücknehmen?'))return;try{S=await api('undo',{});entry='';closeModal();showMatch()}catch(e){err(e.message)}};
 document.querySelector('#scorerView .columns .box')?.append(undo);
 const showWithUndo=showMatch;showMatch=function(){showWithUndo();undo.disabled=!S?.can_undo;showBoard()};

 req().then(async m=>{
   meta=m;if(!m.can_score&&m.status!=='finished')throw Error('Für dieses Spiel fehlen die Spielrechte');
   if(m.status==='open'||m.status==='running'){
     let starter=0;
     const previous=typeof m.state==='string'?JSON.parse(m.state||'{}'):(m.state||{});
     if(m.status==='open'&&!previous.visits?.length){
       starter=await new Promise(resolve=>{
         modal('<h2>Ausbullen – wer beginnt?</h2><p>Startspieler wählen</p><div class="actions" id="v2Starter"></div>');
         for(let i=0;i<2;i++){const button=document.createElement('button');button.textContent=i===0?m.player1:m.player2;
           button.onclick=()=>{closeModal();resolve(i)};document.getElementById('v2Starter').append(button)}
       });
     }
     const r=await req('/start',{starter});m={...m,state:r.state,state_version:r.version,status:'running'};
   }
   S=normalize(m);entry='';showMatch();
 }).catch(e=>{oldScreen('loginView');err(e.message+' – Bitte zur Wettbewerbsübersicht zurückkehren.');});
})();

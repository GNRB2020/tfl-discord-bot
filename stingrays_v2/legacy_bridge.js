/* Original Stingrays scorer UI, V2 Neon transport; no legacy-session dependency. */
(()=>{'use strict';
 const qs=new URLSearchParams(location.search),mid=qs.get('match'),freeMode=qs.get('free')==='1';
 if(!mid){location.replace('/dart/v2/');return}
 let version=0,completed=false,meta={};
 const back=()=>{if(window.opener&&!window.opener.closed){window.close();return}location.assign(freeMode?'/dart/v2/':'/dart/v2/?competition='+encodeURIComponent(qs.get('competition')||''))};
 const base=(freeMode?'/dart/v2/api/free-x01/':'/dart/v2/api/matches/')+encodeURIComponent(mid);
 async function req(path='',data){const r=await fetch(base+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json','Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const txt=await r.text();let obj={};try{obj=JSON.parse(txt)}catch{}if(!r.ok)throw Error(obj.error||txt||'HTTP '+r.status);return obj}
 function normalize(raw){
   const state=typeof raw.state==='string'?JSON.parse(raw.state||'{}'):(raw.state||{}),rules=state.rules||(typeof meta.rules==='string'?JSON.parse(meta.rules):meta.rules)||{},rest=state.remaining||[rules.start_score||501,rules.start_score||501],visits=state.visits||[];
   version=raw.state_version??raw.version??version;
   const current=state.current||0;
   const stats=[0,1].map(i=>{const items=visits.filter(v=>v.player===i),d=items.reduce((v,x)=>v+(x.darts||3),0);return {average:d?items.reduce((v,x)=>v+(v.bust?0:(v.score||0)),0)*3/d:0}});
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
 const avatarStyle=document.createElement('style');avatarStyle.textContent='.v2-player-photo{width:clamp(36px,5vw,62px);height:clamp(36px,5vw,62px);object-fit:cover;border-radius:10px;border:2px solid #c9a751;flex-shrink:0;margin-right:6px}#scorerView .players .player{display:flex;align-items:center;gap:8px}';document.head.append(avatarStyle);
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
 const statsEngine=window.StingrayMatchStats;
 function getStats(){return statsEngine.summarize(S?.history||[],S?.names||['Spieler 1','Spieler 2'],S?.legs||[0,0],S?.sets||[0,0],S?.rules||{});}
 function statsGrid(data,rows){
   const wrap=document.createElement('div');wrap.className='v2-report-scroll';
   const table=document.createElement('table');table.className='v2-report-grid v2-versus';
   const head=document.createElement('thead'),header=document.createElement('tr');
   const score=S?.rules?.mode==='sets'?(S.sets||[0,0]):(S?.legs||[0,0]);
   for(const value of [data.names[0]+' ['+(score[0]||0)+']','STATISTIK', '['+(score[1]||0)+'] '+data.names[1]]){
     const th=document.createElement('th');th.textContent=value;header.append(th);
   }head.append(header);table.append(head);
   const body=document.createElement('tbody');
   for(const row of rows){const tr=document.createElement('tr');
     for(const cell of [row[1],row[0],row[2]]){const td=document.createElement('td');td.textContent=String(cell??'–');tr.append(td)}body.append(tr);
   }table.append(body);wrap.append(table);return wrap;
 }
 function statsReport(finished=false,initial='Statistiken'){
   const data=getStats(),wrap=document.createElement('div');wrap.className='v2-final-report';
   const closeX=document.createElement('button');closeX.type='button';closeX.className='modal-close';closeX.textContent='×';closeX.setAttribute('aria-label','Fenster schließen');closeX.onclick=closeModal;wrap.append(closeX);
   const heading=document.createElement('h2');heading.textContent=finished?'Match beendet · '+data.names.join(' – '):'Matchstatistik · '+data.names.join(' – ');wrap.append(heading);
   const tabs=document.createElement('div');tabs.className='v2-report-tabs';wrap.append(tabs);
   const body=document.createElement('div');body.className='v2-report-body';wrap.append(body);
   const formats=[['Spielinfo','Spielinfo'],['Bestleistungen','Bestleistungen'],['Statistiken','Statistiken'],['Scoreboard','Scoreboard']];
   const buttons=new Map();
   function render(name){
     body.replaceChildren();for(const [k,v] of buttons)v.classList.toggle('active',name===k);
     if(name==='Statistiken')body.append(statsGrid(data,data.statisticalRows));
     else if(name==='Bestleistungen')body.append(statsGrid(data,data.bestRows));
     else if(name==='Spielinfo'){
       const info=[['Spielstand',...(S?.legs||[0,0])],...(S?.rules?.mode==='sets'?[['Sets',...(S?.sets||[0,0])]]:[]),
         ['Modus',...(S?.rules?.mode==='sets'?['Sets','Sets']:['Legs','Legs'])],
         ['Startpunkte',S?.rules?.start_score||501,S?.rules?.start_score||501],
         ['Status',finished?'Beendet':'Laufend',finished?'Beendet':'Laufend']];
       body.append(statsGrid(data,info));
     }else if(name==='Scoreboard'){
       const rows=data.scoreboard.flatMap(leg=>[
         ['Leg '+leg.leg+' · Darts',...leg.darts.map((n,i)=>leg.checkouts[i]==='–'?'('+n+')':n)],
         ['Leg '+leg.leg+' · Average',...leg.averages],
         ['Leg '+leg.leg+' · Checkout',...leg.checkouts]
       ]);body.append(statsGrid(data,rows.length?rows:[['Keine Aufnahmen','–','–']]));
     }
   }
   for(const [key,label] of formats){const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=()=>render(key);tabs.append(button);buttons.set(key,button)}
   const footer=document.createElement('div');footer.className='v2-report-footer';
   const close=document.createElement('button');close.type='button';close.textContent=finished?'ZUM WETTBEWERB':'ZUM SCORER';close.className='green';close.onclick=finished?back:closeModal;footer.append(close);
   if(finished){const ret=document.createElement('button');ret.type='button';ret.textContent='SCHLIESSEN';ret.onclick=closeModal;footer.append(ret)}
   wrap.append(footer);document.getElementById('modalContent').replaceChildren(wrap);
   document.getElementById('modal').classList.remove('hide');render(initial);
 }
 function showLiveStats(mode){statsReport(false,mode==='best'?'Bestleistungen':'Statistiken')}
 function showBoard(){
  if(!S?.names)return;
  document.getElementById('v2LegScore').textContent=(S.legs?.[0]||0)+' : '+(S.legs?.[1]||0);
  document.getElementById('v2SetScore').textContent='SETS '+(S.sets?.[0]||0)+' : '+(S.sets?.[1]||0);document.getElementById('v2SetScore').hidden=S.rules?.mode!=='sets';
  document.getElementById('v2MatchFormat').textContent=S.rules?.mode==='sets'?'Best of '+S.rules.best_of_sets+' Sets':'Best of '+S.rules?.max_legs+' Legs';
  // Update visible averages from the entire persisted match history on every redraw.
  for(let i=0;i<2;i++){
    const visits=(S.history||[]).filter(v=>Number(v.player)===i);
    const darts=visits.reduce((sum,v)=>sum+Number(v.darts??3),0);
    const points=visits.reduce((sum,v)=>sum+(v.bust?0:Number(v.score||0)),0);
    const field=document.getElementById('av'+i);
    if(field)field.textContent=(darts?3*points/darts:0).toLocaleString('de-DE',{minimumFractionDigits:2,maximumFractionDigits:2});
  }
  for(let i=0;i<2;i++){const target=document.getElementById('v2Recent'+i);target.replaceChildren();
    const last=(S.history||[]).filter(v=>v.player===i).slice(-3).reverse();
    if(!last.length){target.textContent='Noch keine Aufnahme';continue}
    for(const v of last){const pill=document.createElement('span');pill.className='v2-visit';pill.textContent=(v.bust?'0 · Bust':v.score)+(v.checkout?' ✓':'');target.appendChild(pill)}
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
 function showCompleteReport(){statsReport(true,'Spielinfo')}

 result=function(){if(!S?.done||completed)return;completed=true;showCompleteReport()};
 const originalShow=showMatch;showMatch=function(){originalShow();document.getElementById('context').textContent='STINGRAYS · WETTBEWERB';};
 const oldScreen=screen;screen=function(id){if(id==='loginView'||id==='menuView'||id==='configView'){back();return}oldScreen(id)};
 for(const id of ['homebtn','logout'])document.getElementById(id).onclick=back;
 const undo=document.createElement('button');undo.textContent='↶ LETZTE AUFNAHME ZURÜCK';undo.type='button';undo.style.cssText='background:#37495f;border:1px solid #c7a86a;color:white;font-weight:800';
 undo.onclick=async()=>{if(!S?.can_undo||!confirm('Letzte Aufnahme zurücknehmen?'))return;try{S=await api('undo',{});entry='';closeModal();showMatch()}catch(e){err(e.message)}};
 document.querySelector('#scorerView .columns .box')?.append(undo);
 // All started games, including free X01, must have an explicit exit action.
 const abandon=document.createElement('button');abandon.type='button';abandon.textContent='SPIEL ABBRECHEN';
 abandon.style.cssText='background:#5b302e;color:#ffe0b7;border:1px solid #b47770;font-weight:800';
 abandon.onclick=async()=>{
   if(S?.done){err('Ein abgeschlossenes Spiel kann nicht abgebrochen werden.');return}
   if(!window.confirm(freeMode?'Freies Training endgültig abbrechen? Es zählt nicht in die Statistiken.':'Spiel abbrechen? Alle Aufnahmen werden verworfen, der Status geht zurück auf OFFEN.'))return;
   abandon.disabled=true;
   try{
     await req('/abort',freeMode?{confirm:'ABBRECHEN'}:{mode:'reset',confirm:'ABBRECHEN',reason:'Am Board abgebrochen'});
     back();
   }catch(e){abandon.disabled=false;err('Abbruch fehlgeschlagen: '+e.message)}
 };
 document.querySelector('#scorerView .columns .box')?.append(abandon);

 // Alternative X01 input: the keypad contains the REMAINING points, not the scored points.
 // Convert to a real visit so Neon history, averages, leg statistics and Undo remain consistent.
 function pointsFromRestscore(currentRest,targetRest){
   if(!Number.isInteger(currentRest)||!Number.isInteger(targetRest))throw Error('Bitte einen gültigen Restscore eingeben.');
   if(targetRest===0)throw Error('Für das Beenden des Legs bitte CHECK verwenden.');
   if(targetRest===1)throw Error('Ein Restscore von 1 ist bei Double-Out nicht zulässig.');
   if(targetRest<0)throw Error('Der Restscore darf nicht negativ sein.');
   if(targetRest>currentRest)throw Error('Der neue Restscore ist höher als der aktuelle. Bitte die letzte Aufnahme zurücknehmen.');
   const scored=currentRest-targetRest;
   if(scored>180)throw Error('Mehr als 180 Punkte in einer Aufnahme sind nicht möglich. Bitte die letzte Aufnahme prüfen.');
   return scored;
 }
 const restScoreButton=document.createElement('button');
 restScoreButton.id='v2RestScore';restScoreButton.type='button';
 restScoreButton.textContent='RESTSCORE';
 restScoreButton.title='Eingegebene Zahl als neuen Restscore übernehmen (3 Darts)';
 document.querySelector('#scorerView .columns .box .footer')?.insertBefore(restScoreButton,$('checkout'));
 restScoreButton.addEventListener('click',()=>{
   if(!S||S.kind!=='x01'||S.done||busy)return;
   if(!/^\d{1,5}$/.test(entry)){err('Bitte den gewünschten Restscore über das Zahlenfeld eingeben.');return;}
   const before=Number(S.remaining[S.current]);
   const after=Number(entry);
   let points;
   try{points=pointsFromRestscore(before,after)}catch(e){err(e.message);return}
   // Match ordinary score booking: with <=170 left the user may record missed doubles.
   if(before<=170){
     modal('<h2>Restscore '+after+'</h2><p>Gebuchte Aufnahme: '+points+' Punkte. Wie viele Versuche auf Doppel?</p><div class="actions" id="v2RestAttempts"></div><div class="actions"><button type="button" id="v2RestCancel">ABBRECHEN</button></div>');
     for(let n=0;n<=3;n++){
       const button=document.createElement('button');button.type='button';button.textContent=String(n);
       button.onclick=()=>{closeModal();send(points,{checkout_attempts:n})};
       $('v2RestAttempts').appendChild(button);
     }
     $('v2RestCancel').onclick=closeModal;
   }else send(points);
 });
 // Highlight the original keypad's 1/2/3 only if that dart count is a legal checkout.
 // A short tap remains the existing number input; a long press is handled above.
 const checkoutKeys=new Map();
 for(const button of document.querySelectorAll('#pad button')){
   const value=button.textContent.trim();
   if(['1','2','3'].includes(value))checkoutKeys.set(Number(value),button);
 }
 const checkoutKeyStyle=document.createElement('style');
 checkoutKeyStyle.textContent=`
 #pad button.v2-check-ready {background:#147847!important;color:#fff!important;
   border:2px solid #e6d18a!important;box-shadow:0 0 0 2px rgba(230,209,138,.22);
   font-weight:900;position:relative;touch-action:none}
 #pad button.v2-check-ready::after{content:'CHECK';display:block;font-size:10px;line-height:1.1;
   font-weight:700;letter-spacing:.06em;color:#fff2bd}
 #pad button.v2-check-ready:active{background:#0b5634!important}
 `;
 document.head.appendChild(checkoutKeyStyle);
 function updateCheckoutKeys(){
   const legal=(S?.kind==='x01' && !S?.done && Array.isArray(S?.can_checkout)) ? S.can_checkout : [];
   for(const [darts,button] of checkoutKeys){
     const active=legal.includes(darts);
     button.classList.toggle('v2-check-ready',active);
     button.setAttribute('aria-label',active?`${darts} – kurz tippen: Ziffer, lange halten: Checkout mit ${darts} Dart${darts===1?'':'s'}`:`${darts}`);
     button.title=active?`${darts} Dart${darts===1?'':'s'} Checkout möglich: lange halten`:`Ziffer ${darts}`;
   }
 }

 const showWithUndo=showMatch;showMatch=function(){showWithUndo();
   for(let i=0;i<2;i++){const label=document.getElementById('l'+i);if(label&&S?.rules?.mode!=='sets')label.textContent=(S.legs?.[i]||0)+' Legs'}
   undo.disabled=!S?.can_undo;abandon.disabled=!S||S.done;restScoreButton.disabled=!S||S.done;showBoard();updateCheckoutKeys()};

 req().then(async m=>{
   meta=m;if(m.status==='cancelled'){back();return}if(!m.can_score&&m.status!=='finished')throw Error('Für dieses Spiel fehlen die Spielrechte');
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
   // Only request avatars for players who actually uploaded one.
   for(const [i,pid,enabled] of [[0,m.player1_id,m.has_avatar1],[1,m.player2_id,m.has_avatar2]]){
     if(!pid||!enabled)continue;
     const panel=document.getElementById('p'+i);if(!panel||panel.querySelector('.v2-player-photo'))continue;
     const img=document.createElement('img');img.className='v2-player-photo';img.alt='Spielerfoto';
     img.src='/dart/v2/api/players/'+encodeURIComponent(pid)+'/avatar';panel.prepend(img);
   }
   S=normalize(m);entry='';showMatch();
 }).catch(e=>{oldScreen('loginView');err(e.message+' – Bitte zur Wettbewerbsübersicht zurückkehren.');});
})();

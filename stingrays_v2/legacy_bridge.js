/* Original Stingrays scorer UI, V2 Neon transport; no legacy-session dependency. */
(()=>{'use strict';
 const qs=new URLSearchParams(location.search),mid=qs.get('match');
 if(!mid){location.replace('/dart/v2/');return}
 let version=0,completed=false,meta={};
 const back=()=>location.assign('/dart/v2/?competition='+encodeURIComponent(qs.get('competition')||''));
 const base='/dart/v2/api/matches/'+encodeURIComponent(mid);
 async function req(path='',data){const r=await fetch(base+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json','Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const txt=await r.text();let obj={};try{obj=JSON.parse(txt)}catch{}if(!r.ok)throw Error(obj.error||txt||'HTTP '+r.status);return obj}
 function normalize(raw){
   const state=typeof raw.state==='string'?JSON.parse(raw.state||'{}'):(raw.state||{}),rules=state.rules||(typeof meta.rules==='string'?JSON.parse(meta.rules):meta.rules)||{},rest=state.remaining||[rules.start_score||501,rules.start_score||501],visits=state.visits||[];
   version=raw.state_version??raw.version??version;
   const current=state.current||0;
   const stats=[0,1].map(i=>{const items=visits.filter(v=>v.player===i&&!v.bust),d=items.reduce((v,x)=>v+(x.darts||3),0);return {average:d?items.reduce((v,x)=>v+(x.score||0),0)*3/d:0}});
   return {...state,kind:'x01',names:state.names||[meta.player1,meta.player2],rules,remaining:rest,current,
      legs:state.legs||[raw.legs1||0,raw.legs2||0],sets:state.sets||[raw.sets1||0,raw.sets2||0],
      done:!!state.done||raw.status==='finished',can_checkout:state.done?[]:possible(rest[current]),
      current_stats:stats,last:visits.slice(-8),can_undo:raw.status==='running'&&visits.length>0,summary:raw.summary||null};
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
 const oldResult=result;
 result=function(){
   if(completed||!S?.done)return;
   completed=true;
   if(S.summary?.players?.length===2){
     oldResult();
     const newReport=document.getElementById('newReport');
     if(newReport){newReport.textContent='ZUM WETTBEWERB';newReport.onclick=back;}
     const close=document.getElementById('closeReport');
     if(close){close.textContent='ZUM WETTBEWERB';close.onclick=back;}
   } else {
     modal('<h2>Match beendet</h2><p>Das Ergebnis ist in Neon gespeichert.</p><div class="actions"><button id="returnV2" class="green">ZUM WETTBEWERB</button></div>');
     document.getElementById('returnV2').onclick=back;
   }
 };
 const originalShow=showMatch;showMatch=function(){originalShow();document.getElementById('context').textContent='STINGRAYS · WETTBEWERB';};
 const oldScreen=screen;screen=function(id){if(id==='loginView'||id==='menuView'||id==='configView'){back();return}oldScreen(id)};
 for(const id of ['homebtn','logout'])document.getElementById(id).onclick=back;
 const undo=document.createElement('button');undo.textContent='↶ LETZTE AUFNAHME ZURÜCK';undo.type='button';undo.style.cssText='background:#37495f;border:1px solid #c7a86a;color:white;font-weight:800';
 undo.onclick=async()=>{if(!S?.can_undo||!confirm('Letzte Aufnahme zurücknehmen?'))return;try{S=await api('undo',{});entry='';closeModal();showMatch()}catch(e){err(e.message)}};
 document.querySelector('#scorerView .columns .box')?.append(undo);
 const showWithUndo=showMatch;showMatch=function(){showWithUndo();undo.disabled=!S?.can_undo};

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

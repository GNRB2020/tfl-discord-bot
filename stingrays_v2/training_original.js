/* V2 login + Neon persistence; original Sau/Tauziehen scorers remain in dart_ui. */
(()=>{'use strict';
const mode=new URLSearchParams(location.search).get('kind')||'sau';
const storageKey='stingrays-v2-training-'+mode;
let currentId=sessionStorage.getItem(storageKey)||null;
const $=id=>document.getElementById(id);
const http=async(url,payload)=>{
 const opts={credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}};
 if(payload!==undefined){opts.method='POST';opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(payload)}
 const res=await fetch(url,opts),txt=await res.text();let obj={};try{obj=JSON.parse(txt)}catch{}
 if(!res.ok)throw Error(obj.error||txt||'HTTP '+res.status);
 return obj;
};
const base='/dart/v2/api/training-games';
const request=(url,data)=>http(base+url,data);
api=async function(path,data){
 if(path==='state')return currentId?request('/'+currentId):{kind:null};
 if(path==='new'){const result=await request('',data);currentId=result.game_id;sessionStorage.setItem(storageKey,currentId);return result}
 if(['throw','undo','next-sau'].includes(path)){
   if(!currentId)throw Error('Kein aktives Training');return request('/'+currentId+'/'+path,data||{});
 }
 throw Error('Diese Funktion gehört zur alten Anmeldung: '+path);
};
// Hide legacy login, config and logout. Keep the original scoring controls.
$('loginView').classList.add('hide');$('logout').classList.add('hide');
$('homebtn').onclick=()=>{location.assign('/dart/v2/?view=training')};
$('homebtn').textContent='ZURÜCK ZUM TRAINING';
const userHeader=document.createElement('div');userHeader.className='v2-training-top';
userHeader.innerHTML='<strong>DSV STINGRAYS · TRAINING</strong><button type="button" id="v2TrainingBack">ZUR ÜBERSICHT</button>';
document.querySelector('.root').prepend(userHeader);
$('v2TrainingBack').onclick=()=>location.assign('/dart/v2/?view=training');
async function choose(k){
 const players=await request('/players');
 const isSau=k==='sau',isTug=k==='tug';
 modal('<h2>'+(isSau?'Gegen die Sau':isTug?'Tauziehen':'Bobs 27')+'</h2>'+ 
   '<p>'+(isSau?'Einen oder mehrere Spieler als Team auswählen.':'Spieler auswählen.')+'</p>'+ 
   '<div class="v2-training-players" id="v2Players"></div>'+ 
   (isSau||isTug?'<label>Rundenzahl <input type="number" min="1" max="100" id="v2Rounds" value="'+(isSau?10:5)+'"></label>':'')+
   '<div class="actions"><button type="button" id="v2Cancel">Zurück</button><button type="button" class="green" id="v2Go">TRAINING STARTEN</button></div>');
 const panel=$('v2Players');
 for(const p of players){const line=document.createElement('label');line.className='v2-player-choice';const cb=document.createElement('input');cb.type=(isSau||isTug)?'checkbox':'radio';cb.name='player';cb.value=p.id;line.append(cb,document.createTextNode(p.display_name));panel.append(line)}
 $('v2Cancel').onclick=()=>{closeModal();location.assign('/dart/v2/?view=training')};
 $('v2Go').onclick=async()=>{
  const ids=[...panel.querySelectorAll('input:checked')].map(x=>x.value);
  if(!ids.length||(isTug&&ids.length!==2)){err(isTug?'Für Tauziehen zwei Spieler wählen':'Mindestens einen Spieler auswählen');return}
  try{
   const r=await api('new',{kind:k,player_ids:ids,rounds:$('v2Rounds')?.value||10});
   S=r;entry='';sauEntry='';closeModal();display(r);
  }catch(e){err(e.message)}
 };
}
function display(r){
 S=r;
 if(r.kind==='sau')showSau();
 else if(r.kind==='tug' && window.__v2ShowTug)window.__v2ShowTug();
 else if(r.kind==='bobs27')renderBobs();
 else screen('menuView');
}
// Preserve original Phase 11 visual layout and actions for tug-of-war.
// Override the legacy menu action so the V2 session and member profiles are used.
const tugMenu=[...document.querySelectorAll('#menuView .menu button')].find(b=>b.textContent.includes('Tauziehen'));
if(tugMenu)tugMenu.onclick=()=>choose('tug');
$('sau').onclick=()=>choose('sau');
// Bobs 27 was not implemented in the old normal scorer: provide a dedicated,
// full-screen scorer, not a generic admin-form replacement.
const bobs=document.createElement('section');bobs.id='bobs27View';bobs.className='screen hide';
bobs.innerHTML='<div class="v2-bobs-top"><h2>BOBS 27</h2><strong id="bobsName"></strong><div class="v2-bobs-total" id="bobsScore">27</div><small id="bobsTarget">Doppel 1</small></div><div class="v2-bobs-grid" id="bobsGrid"></div><div class="v2-bobs-actions"><button type="button" data-hits="0">0 TREFFER</button><button type="button" data-hits="1">1 TREFFER</button><button type="button" data-hits="2">2 TREFFER</button><button type="button" data-hits="3">3 TREFFER</button></div><button type="button" id="bobsUndo">LETZTE AUFNAHME ZURÜCK</button>';
document.querySelector('.root').append(bobs);
async function bobsScore(hits){try{const r=await request('/'+currentId+'/throw',{hits});display(r)}catch(e){err(e.message)}}
bobs.querySelectorAll('[data-hits]').forEach(b=>b.onclick=()=>bobsScore(Number(b.dataset.hits)));
$('bobsUndo').onclick=async()=>{try{display(await request('/'+currentId+'/undo',{}))}catch(e){err(e.message)}};
function renderBobs(){screen('bobs27View');$('bobsName').textContent=S.name;$('bobsScore').textContent=S.score;
 const doubles=[...Array.from({length:20},(_,i)=>i+1),25];
 $('bobsTarget').textContent=S.finished?'TRAINING BEENDET':'JETZT: '+(doubles[S.target_index]===25?'BULL': 'DOPPEL '+doubles[S.target_index]);
 const grid=$('bobsGrid');grid.replaceChildren();for(let i=0;i<doubles.length;i++){
  const x=document.createElement('div');x.className='v2-bobs-round'+(S.target_index===i?' active':'')+(S.target_index>i?' done':'');
  x.textContent=(doubles[i]===25?'BULL':'D'+doubles[i])+' · '+(S.visits[i]?S.visits[i].hits+' Treffer':'–');grid.append(x);
 }
 bobs.querySelectorAll('[data-hits]').forEach(b=>b.disabled=S.finished);
 $('bobsUndo').disabled=!S.can_undo;
}
// Reuse current training after accidental refresh; all visits live in Neon.
(async()=>{try{
 if(currentId){try{display(await api('state'))}catch{currentId=null;sessionStorage.removeItem(storageKey);await choose(mode)}}
 else await choose(mode);
}catch(e){err(e.message);screen('menuView')}})();
})();

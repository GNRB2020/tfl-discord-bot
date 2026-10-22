/* League matches run in the existing X01 tablet scorer. */
(()=>{'use strict';const p=new URLSearchParams(location.search),lid=p.get('league'),mid=p.get('match');if(!lid||!mid)return;
 const base='/dart/api/league/'+encodeURIComponent(lid)+'/matches/'+encodeURIComponent(mid);let version=0,starterShown=false;
 const priorApi=api,normalize=d=>{version=d.version;return {...d,kind:'x01'}};
 async function remote(path,data){const r=await fetch(base+path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.error||'HTTP '+r.status);return j}
 api=async function(path,data){if(path==='state')return normalize(await remote(''));if(path==='throw')return normalize(await remote('/throw',{...data,version}));if(path==='undo')return normalize(await remote('/undo',{}));return priorApi(path,data)};
 const baseShow=showMatch;showMatch=function(){baseShow();const context=document.getElementById('context');if(context)context.textContent='STINGRAY LEAGUE · '+S.names.join(' – ');if(S.starter===null&&!S.done&&!starterShown){starterShown=true;setTimeout(chooseStarter,0)}if(S.done){const b=document.getElementById('newReport');if(b){b.textContent='ZUM SPIELPLAN';b.onclick=()=>location.href='/dart/league/#'+lid}}};
 async function chooseStarter(){modal('<h2>Ausbullen – wer beginnt?</h2><p>Ersten Anwurf auswählen.</p><div class="actions" id="leagueSelectStarter"></div>');for(let i=0;i<2;i++){const b=document.createElement('button');b.textContent=S.names[i];b.onclick=async()=>{b.disabled=true;try{S=normalize(await remote('/start',{starter:i}));closeModal();showMatch()}catch(e){starterShown=false;closeModal();err(e.message)}};document.getElementById('leagueSelectStarter').append(b)}}
 for(const id of ['homebtn','logout']){const b=document.getElementById(id);if(b)b.onclick=()=>location.href='/dart/league/#'+lid}
 api('state').then(d=>{S=d;entry='';showMatch()}).catch(e=>err(e.message));
})();

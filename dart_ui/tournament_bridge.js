/* One X01 scorer for training and tournament matches (same DOM, shortcuts and reports). */
(() => {
  'use strict';
  const params = new URLSearchParams(location.search);
  const tid=params.get('tournament'), mid=params.get('match');
  if (!tid || !mid) return;
  const base='/dart/api/tournaments/'+encodeURIComponent(tid)+'/matches/'+encodeURIComponent(mid);
  let version=0, starterShown=false;
  const priorApi=api;
  const normalise = data => {version=data.version;return {...data,kind:'x01'};};
  async function remote(url, payload) {
    const response=await fetch(url, {method:payload===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload)});
    const json=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(json.error||'HTTP '+response.status);
    return json;
  }
  api=async function(path,data){
    if (path==='state') return normalise(await remote(base));
    if (path==='throw') return normalise(await remote(base+'/throw',{...data,version}));
    if (path==='undo') return normalise(await remote(base+'/undo',{}));
    return priorApi(path,data);
  };
  const priorShow=showMatch;
  showMatch=function(){priorShow();document.getElementById('context').textContent='TRAININGSTURNIER · '+S.names.join(' – ');
    if(S.starter===null && !S.done && !starterShown){starterShown=true;setTimeout(chooseStarter,0)}
    if(S.done){const nr=document.getElementById('newReport');if(nr){nr.textContent='ZUM SPIELPLAN';nr.onclick=()=>location.href='/dart/tournaments/#'+encodeURIComponent(tid)}}
  };
  async function chooseStarter(){
    modal('<h2>Ausbullen – wer beginnt?</h2><p>Spieler antippen, der das erste Leg beginnt.</p><div class="actions" id="selectStarter"></div>');
    [0,1].forEach(i=>{const b=document.createElement('button');b.textContent=S.names[i];b.onclick=async()=>{
      b.disabled=true;
      try{S=normalise(await remote(base+'/start',{starter:i}));closeModal();showMatch()}
      catch(e){b.disabled=false;starterShown=false;err(e.message);closeModal()}
    };document.getElementById('selectStarter').appendChild(b)});
  }
  document.getElementById('homebtn').onclick=()=>location.href='/dart/tournaments/#'+encodeURIComponent(tid);
  document.getElementById('logout').onclick=()=>location.href='/dart/tournaments/#'+encodeURIComponent(tid);
  // State request after all enhancements, using tournament API rather than local training tab.
  api('state').then(data=>{S=data;entry='';showMatch()}).catch(e=>err(e.message));
})();

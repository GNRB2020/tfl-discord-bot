/* Phase 16 – Mitgliederprofile im X01-, Sau-, Tauziehen- und Turnierformular */
(()=>{'use strict';
const css=document.createElement('style');css.textContent=`
.profile-wrap{display:flex;gap:6px;align-items:stretch;width:100%;min-width:0}
.profile-wrap input{min-width:0;flex:1;width:100%}
.profile-plus{flex:0 0 38px;min-width:38px!important;min-height:36px;border:1px solid #b69b58!important;border-radius:7px;background:#8d1b27!important;color:#fff1c2!important;font-size:25px!important;font-weight:800!important;padding:0!important}
.profile-overlay{position:fixed;inset:0;background:rgba(0,0,0,.78);display:grid;place-items:center;z-index:99999;padding:14px}
.profile-dialog{width:min(95vw,520px);max-height:88vh;display:flex;flex-direction:column;gap:10px;overflow:hidden;background:#232323;color:#f7f4ee;border:2px solid #b69b58;border-radius:12px;padding:16px}
.profile-dialog h2{margin:0;color:#eac870}.profile-dialog input{width:100%;min-height:43px;color:#fff;background:#333;border:1px solid #888;padding:8px;border-radius:6px}
.profile-list{overflow:auto;min-height:100px;flex:1;display:grid;gap:5px;align-content:start}
.profile-list button{background:#353535;border:1px solid #666;color:white;padding:11px;text-align:left;border-radius:6px}
.profile-list button:focus,.profile-list button:hover{border-color:#ddb96c;background:#5b2730}
.profile-close{align-self:end;background:#7e1a26!important;border:1px solid #bd9c62!important;color:#fff;padding:8px 16px;border-radius:6px}
.profile-dialog{position:relative}.profile-close-x{position:absolute;right:12px;top:12px;min-width:38px;min-height:38px;padding:0 8px;background:#7e1a26!important;color:#fff;border:1px solid #bd9c62!important;border-radius:7px;font-size:26px;line-height:1}.profile-dialog h2{padding-right:42px}
`;document.head.appendChild(css);
let cached=null,loading=null;
async function getProfiles(){if(cached)return cached;if(!loading)loading=fetch('/dart/profiles.json',{credentials:'same-origin',cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Profilliste nicht erreichbar ('+r.status+')');return r.json()}).then(d=>{cached=d;return d}).finally(()=>{loading=null});return loading}
function openPicker(input){
 const layer=document.createElement('div');layer.className='profile-overlay';layer.setAttribute('role','dialog');layer.setAttribute('aria-modal','true');
 const box=document.createElement('div');box.className='profile-dialog';const h=document.createElement('h2');h.textContent='Spielerprofil auswählen';const query=document.createElement('input');query.placeholder='Mitglied suchen …';query.setAttribute('aria-label','Mitglied suchen');const list=document.createElement('div');list.className='profile-list';list.textContent='Lade Profile …';const close=document.createElement('button');close.className='profile-close';close.type='button';close.textContent='SCHLIESSEN';const dismiss=()=>{layer.remove();input.focus()};close.onclick=dismiss;const x=document.createElement('button');x.className='profile-close-x';x.type='button';x.textContent='×';x.title='Fenster schließen';x.setAttribute('aria-label','Fenster schließen');x.onclick=dismiss;box.append(x,h,query,list,close);layer.append(box);document.body.append(layer);query.focus();
 getProfiles().then(profiles=>{const draw=()=>{const q=query.value.toLocaleLowerCase('de').trim();list.replaceChildren();const subset=profiles.filter(p=>(p.display_name+' '+p.source_name).toLocaleLowerCase('de').includes(q));for(const p of subset){const b=document.createElement('button');b.type='button';b.textContent=p.display_name;b.onclick=()=>{const inputs=[...document.querySelectorAll('#a,#b,#ta,#tb,#names input')].filter(x=>x!==input);if(inputs.some(x=>x.dataset.profileId===p.id)){alert('Dieses Profil ist bereits einem anderen Spieler zugeordnet.');return;}input.value=p.display_name;input.dataset.profileId=p.id;input.dataset.profileLabel=p.display_name;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));dismiss()};list.append(b)}if(!subset.length)list.textContent='Keine Mitglieder gefunden';};query.addEventListener('input',draw);draw()}).catch(err=>list.textContent=err.message);
}
function attach(){const candidates=[...document.querySelectorAll('#a,#b,#sauName,#ta,#tb,#names input')];for(const input of candidates){if(input.dataset.profileAttached==='1')continue;input.dataset.profileAttached='1';input.addEventListener('input',()=>{if(input.dataset.profileId && input.value!==input.dataset.profileLabel)delete input.dataset.profileId});const wrap=document.createElement('span');wrap.className='profile-wrap';input.parentNode.insertBefore(wrap,input);wrap.append(input);const plus=document.createElement('button');plus.type='button';plus.className='profile-plus';plus.textContent='+';plus.title='Spieler aus Mitgliederliste auswählen';plus.setAttribute('aria-label','Spielerprofil auswählen');plus.onclick=()=>openPicker(input);wrap.append(plus)}}
// Transmit stable profile IDs along with name-based game creation requests.
const nativeFetch=window.fetch.bind(window);
window.fetch=function(url,opts){
  const path=typeof url==='string'?url:(url?.url||'');
  if(opts?.method==='POST' && opts.body && (path.endsWith('/dart/api/new') || path.endsWith('/dart/api/tournaments'))){
    try{
      const data=JSON.parse(opts.body);
      let fields=[];
      if(path.endsWith('/dart/api/tournaments'))fields=[...document.querySelectorAll('#names input')];
      else if(data.kind==='sau')fields=[document.querySelector('#sauName')||document.querySelector('#a')];
      else if(data.kind==='tug')fields=[document.querySelector('#ta'),document.querySelector('#tb')];
      else fields=[document.querySelector('#a'),document.querySelector('#b')];
      data.profile_ids=fields.map(el=>el?.dataset.profileId||null);
      const selected=data.profile_ids.filter(Boolean);
      if(new Set(selected).size!==selected.length){alert('Jedes Profil darf nur einmal pro Spiel oder Turnier ausgewählt werden.');return Promise.reject(new Error('Doppelte Profilwahl'));}
      return nativeFetch(url,{...opts,body:JSON.stringify(data)});
    }catch(e){console.warn('Profilbindung nicht verfügbar:',e)}
  }
  return nativeFetch(url,opts)
};
attach();let pending=false;const observer=new MutationObserver(()=>{if(pending)return;pending=true;queueMicrotask(()=>{pending=false;attach()})});observer.observe(document.body,{subtree:true,childList:true});
})();

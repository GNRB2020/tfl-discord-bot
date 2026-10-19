/* Phase 18: archive and delete controls in the training tournament overview. */
(()=>{'use strict';
const previous=listing;
listing=async function(){
 try{
  const response=await api('');const host=document.getElementById('tournaments');host.replaceChildren();
  const toggle=document.createElement('label');toggle.style.cssText='display:flex;align-items:center;gap:8px;margin-bottom:14px';
  const check=document.createElement('input');check.type='checkbox';check.style.width='auto';check.checked=window.__showArchived||false;
  toggle.append(check,document.createTextNode(' Archivierte Turniere anzeigen'));host.append(toggle);
  const display=()=>{host.querySelectorAll('.turnRow').forEach(n=>n.remove());const items=response.items.filter(x=>check.checked||!x.archived);if(!items.length){const p=document.createElement('p');p.className='turnRow';p.textContent='Keine Turniere in dieser Ansicht';host.append(p)}
   for(const item of items){const row=document.createElement('div');row.className='turnRow';row.style.cssText='display:flex;gap:5px;margin:7px 0;flex-wrap:wrap';const open=document.createElement('button');open.textContent=item.title+(item.archived?' [ARCHIV]':'');open.onclick=()=>load(item.id);row.append(open);
    const archive=document.createElement('button');archive.textContent=item.archived?'REAKTIVIEREN':'ARCHIVIEREN';archive.onclick=async()=>{if(!confirm('Turnierstatus ändern? Spielstände und Statistiken bleiben erhalten.'))return;try{await api('/'+encodeURIComponent(item.id)+'/archive',{archived:!item.archived});await listing()}catch(e){err(e)}};row.append(archive);
    const del=document.createElement('button');del.textContent='LÖSCHEN';del.style.background='#8c1825';del.onclick=async()=>{if(!confirm('Testturnier dauerhaft aus der Übersicht und allen Statistiken entfernen?'))return;const pin=prompt('Admin-PIN zur Bestätigung');if(pin===null)return;try{await api('/'+encodeURIComponent(item.id)+'/delete',{pin});await listing()}catch(e){err(e)}};row.append(del);host.append(row)}
  };check.onchange=()=>{window.__showArchived=check.checked;display()};display();
 }catch(e){err(e)}
};
listing();
})();

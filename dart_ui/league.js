'use strict';const $=id=>document.getElementById(id);let current=null,selected=null,profiles=[];
function error(e){$('message').textContent=e?.message||String(e);window.scrollTo(0,0)}
async function req(path,body){const res=await fetch('/dart/api/league'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});const j=await res.json().catch(()=>({}));if(!res.ok)throw Error(j.error||'HTTP '+res.status);return j}
async function loadAll(){try{const r=await req('');$('seasons').replaceChildren();if(!r.items.length)$('seasons').textContent='Noch keine Saisons';for(const s of r.items){const b=document.createElement('button');b.textContent=s.name+' · '+s.status;b.style.margin='5px';b.onclick=()=>openSeason(s.id);$('seasons').append(b)}}catch(e){error(e)}}
function profileSelect(){const select=document.createElement('select');select.innerHTML='<option value="">Manuell / Gast auswählen</option>';for(const p of profiles){const o=document.createElement('option');o.value=p.id;o.textContent=p.display_name;select.append(o)}return select}
function groupForm(){const div=document.createElement('div');div.className='box';const h=document.createElement('label');h.textContent='Staffelname';const name=document.createElement('input');name.placeholder='Staffel A';h.append(name);div.append(h);const rows=document.createElement('div');rows.className='roster';div.append(rows);const add=document.createElement('button');add.textContent='+ SPIELER';add.onclick=()=>{const row=document.createElement('div');row.className='grid playerrow';const sel=profileSelect();const inp=document.createElement('input');inp.placeholder='Name';sel.onchange=()=>{const p=profiles.find(p=>p.id===sel.value);if(p)inp.value=p.display_name};row.append(sel,inp);const remove=document.createElement('button');remove.textContent='ENTFERNEN';remove.onclick=()=>row.remove();row.append(remove);rows.append(row)};div.append(add);const drop=document.createElement('button');drop.textContent='STAFFEL ENTFERNEN';drop.onclick=()=>div.remove();div.append(drop);$('groups').append(div);for(let i=0;i<4;i++)add.click()}
$('newToggle').onclick=()=>{$('create').classList.toggle('hidden')};$('addGroup').onclick=groupForm;groupForm();
$('make').onclick=async()=>{try{const groups=[...$('groups').children].map(g=>({name:g.querySelector('label input').value.trim(),players:[...g.querySelectorAll('.playerrow')].map(r=>({id:r.querySelector('select').value||undefined,name:r.querySelector('input').value.trim()})).filter(x=>x.name)}));const r=await req('',{admin_pin:$('createPin').value,name:$('seasonName').value,mode:$('mode').value,best_of:+$('best').value,start_score:+$('startScore').value,points_win:+$('winPoints').value,points_draw:+$('drawPoints').value,groups});$('createPin').value='';$('create').classList.add('hidden');await loadAll();render(r)}catch(e){error(e)}};
async function openSeason(id){try{render(await req('/'+encodeURIComponent(id)))}catch(e){error(e)}}
function nameMap(s){const map=new Map();for(const g of s.groups)for(const p of g.players)map.set(p.id,p.name);return map}
function render(s){location.hash=encodeURIComponent(s.id);current=s;$('overview').classList.add('hidden');$('season').classList.remove('hidden');$('resultPanel').classList.add('hidden');$('title').textContent=s.name;$('summary').textContent=s.groups.length+' Staffeln · '+s.fixtures.filter(f=>f.legs!==null).length+'/'+s.fixtures.length+' Matches erledigt';$('tables').replaceChildren();$('schedule').replaceChildren();const names=nameMap(s);
 for(const g of s.groups){const block=document.createElement('div');block.className='box';const h=document.createElement('h2');h.textContent='Tabelle · '+g.name;block.append(h);const section=document.createElement('section');const table=document.createElement('table');let row=document.createElement('tr');for(const k of ['#','Spieler','Sp.','S','U','N','Legs','Diff.','Pkt.']){const th=document.createElement('th');th.textContent=k;row.append(th)}table.append(row);g.standings.forEach((p,i)=>{const tr=document.createElement('tr');for(const v of [i+1,p.name,p.played,p.wins,p.draws,p.losses,p.for+':'+p.against,p.for-p.against,p.points]){const td=document.createElement('td');td.textContent=v;tr.append(td)}table.append(tr)});section.append(table);block.append(section);$('tables').append(block);
 const matches=s.fixtures.filter(f=>f.group_id===g.id);const plan=document.createElement('div');plan.className='box';const title=document.createElement('h2');title.textContent='Spielplan · '+g.name;plan.append(title);for(const round of [...new Set(matches.map(m=>m.round))]){const h=document.createElement('h3');h.textContent='Runde '+round;plan.append(h);for(const f of matches.filter(x=>x.round===round)){const line=document.createElement('div');line.className='match';const desc=document.createElement('span');desc.textContent=names.get(f.a)+' gegen '+names.get(f.b)+(f.legs?' · '+f.legs.join(':'):' · offen')+(f.source==='legacy'?' · ALTRESULTAT':'');line.append(desc);if(f.source!=='legacy'){const play=document.createElement('button');play.className='good';play.textContent='SCORER';play.onclick=()=>location.href='/dart/?league='+encodeURIComponent(s.id)+'&match='+encodeURIComponent(f.id);line.append(play)}const edit=document.createElement('button');edit.textContent=f.source==='legacy'?'BEARBEITEN':'ALTES ERGEBNIS';edit.onclick=()=>selectResult(f);line.append(edit);plan.append(line)}}$('schedule').append(plan)}
}
function selectResult(f){selected=f;const nm=nameMap(current);$('pair').textContent=nm.get(f.a)+' gegen '+nm.get(f.b);$('legsA').value=f.legs?.[0]??'';$('legsB').value=f.legs?.[1]??'';$('note').value=f.import_note||'';$('removeResult').classList.toggle('hidden',f.source!=='legacy');$('resultPanel').classList.remove('hidden');$('resultPanel').scrollIntoView({behavior:'smooth'})}
$('cancelResult').onclick=()=>$('resultPanel').classList.add('hidden');$('saveResult').onclick=async()=>{try{const s=await req('/'+current.id+'/matches/'+selected.id+'/result',{a:+$('legsA').value,b:+$('legsB').value,note:$('note').value,admin_pin:$('resultPin').value});$('resultPin').value='';render(s)}catch(e){error(e)}};
$('removeResult').onclick=async()=>{if(!confirm('Historisches Ergebnis zurücksetzen?'))return;try{const s=await req('/'+current.id+'/matches/'+selected.id+'/clear',{admin_pin:$('resultPin').value});$('resultPin').value='';render(s)}catch(e){error(e)}};
$('back').onclick=()=>{$('overview').classList.remove('hidden');$('season').classList.add('hidden');loadAll()};
fetch('/dart/api/profiles',{cache:'no-store'}).then(r=>r.ok?r.json():[]).then(x=>profiles=x).catch(()=>{});loadAll();if(location.hash.length>1)openSeason(decodeURIComponent(location.hash.slice(1)));


/* Phase 20: übersichtlicher Spielplan, Sammelimport, Finalturnier */
(()=>{'use strict';
const h=document.createElement('style');h.textContent=`
.league-toolbar{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin:10px 0}
.league-toolbar select,.league-toolbar input{width:auto;min-width:150px;flex:1}
.league-fixture{display:flex;gap:10px;align-items:center;padding:11px;border-bottom:1px solid #555;flex-wrap:wrap}
.league-fixture strong{min-width:200px;flex:1}
.league-fixture button{font-size:13px}
.league-summary{color:#e8c98a;font-size:14px;margin:10px 0}
.league-import textarea{height:210px;white-space:pre;line-height:1.5}
.league-import-results{max-height:320px;overflow:auto}
.league-ok{color:#8bd7aa}.league-err{color:#ff9494}
.league-pager{display:flex;gap:8px;align-items:center;justify-content:center;padding:13px}
`;document.head.append(h);
const escText=v=>String(v??'');
const tool=document.createElement('div');tool.className='box';tool.id='leagueTools';tool.innerHTML=`<h2>Ligaverwaltung</h2>
<details class="league-import"><summary>Telegram-Ergebnisse gesammelt importieren</summary>
<p>Eine Begegnung pro Zeile, z. B. <code>Marian 3:3 Michel</code>. Die Vorschau zeigt unklare Namen und bereits belegte Begegnungen.</p>
<textarea id="bulkText" placeholder="Marian 3:3 Michel\nManuel A. 4:0 Lars H."></textarea><label>Namenszuordnungen (optional, eine pro Zeile: Telegram-Kürzel = Spielername im Ligaplan)<textarea id="bulkAliases" style="height:100px" placeholder="Manuel A. = Manuel Andrae\nLars H. = Lars Heeger"></textarea></label>
<label>Admin-PIN (nur zum endgültigen Import)<input type="password" id="bulkPin" autocomplete="off"></label>
<button type="button" id="bulkPreview">VORSCHAU PRÜFEN</button> <button type="button" id="bulkCommit" class="good" disabled>GEPRÜFTE ERGEBNISSE IMPORTIEREN</button>
<p id="bulkStatus"></p><div class="league-import-results" id="bulkResults"></div></details>
<details><summary>Finalturnier aus Staffelplatzierungen erstellen</summary>
<p>Platz 1 und 2 beider Staffeln qualifizieren sich. Halbfinale: A1–B2 und B1–A2. Die Finalpaarung wird nach beiden Halbfinals angelegt.</p>
<label>Best of X Legs<input type="number" id="finalBest" value="5" min="1" max="51" step="2"></label>
<label><input type="checkbox" id="finalEarly" style="width:auto"> Finalturnier vor Abschluss der Liga starten</label>
<label>Admin-PIN<input type="password" id="finalPin" autocomplete="off"></label>
<button type="button" id="finalCreate">FINALTURNIER ERSTELLEN</button></details>`;
const season=document.getElementById('season');season.insertBefore(tool,document.getElementById('tables'));
const guard=document.createElement('div');guard.className='box';guard.id='fixtureFilters';guard.innerHTML=`<h2>Spielplan</h2><div class="league-toolbar">
<label>Staffel<select id="fixtureGroup"></select></label>
<label>Runde<select id="fixtureRound"></select></label>
<label>Spieler<select id="fixturePlayer"></select></label>
<label>Status<select id="fixtureStatus"><option value="all">Alle</option><option value="open">Offen</option><option value="finished">Gespielt</option></select></label></div>
<div class="league-summary" id="fixtureCounts"></div><div id="fixtureRows"></div><div class="league-pager" id="fixturePager"></div>`;
season.insertBefore(guard,document.getElementById('schedule'));
let page=0;const PAGE_SIZE=12;
function filterValues(){if(!current)return;const group=document.getElementById('fixtureGroup'),round=document.getElementById('fixtureRound'),player=document.getElementById('fixturePlayer');
const old={g:group.value,r:round.value,p:player.value};
const set=(node,items)=>{node.replaceChildren();for(const [value,name] of items){const o=document.createElement('option');o.value=value;o.textContent=name;node.append(o)}};
set(group,[['','Alle Staffeln'],...current.groups.map(g=>[g.id,g.name])]);if([...group.options].some(x=>x.value===old.g))group.value=old.g;
const scoped=current.fixtures.filter(f=>!group.value||f.group_id===group.value);
set(round,[['','Alle Runden'],...[...new Set(scoped.map(f=>f.round))].sort((a,b)=>a-b).map(r=>[String(r),'Runde '+r])]);if([...round.options].some(x=>x.value===old.r))round.value=old.r;
const players=current.groups.filter(g=>!group.value||g.id===group.value).flatMap(g=>g.players);
set(player,[['','Alle Spieler'],...players.map(p=>[p.id,p.name])]);if([...player.options].some(x=>x.value===old.p))player.value=old.p;
}
function drawFixtures(){if(!current)return;const names=nameMap(current),g=document.getElementById('fixtureGroup').value,r=document.getElementById('fixtureRound').value,p=document.getElementById('fixturePlayer').value,status=document.getElementById('fixtureStatus').value;
let matches=current.fixtures.filter(f=>(!g||f.group_id===g)&&(!r||f.round===+r)&&(!p||f.a===p||f.b===p)&&(status==='all'||(status==='open'?f.legs===null:f.legs!==null)));
const all=matches.length,pages=Math.max(1,Math.ceil(all/PAGE_SIZE));page=Math.min(page,pages-1);
document.getElementById('fixtureCounts').textContent=all+' Begegnungen · '+matches.filter(f=>f.legs!==null).length+' gespielt · '+matches.filter(f=>f.legs===null).length+' offen';
const host=document.getElementById('fixtureRows');host.replaceChildren();for(const f of matches.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)){
 const line=document.createElement('div');line.className='league-fixture';const label=document.createElement('strong');label.textContent='Runde '+f.round+' · '+names.get(f.a)+' – '+names.get(f.b)+' · '+(f.legs?f.legs.join(':'):'offen');line.append(label);
 if(f.source!=='legacy'){const play=document.createElement('button');play.textContent='SCORER';play.className='good';play.onclick=()=>location.href='/dart/?league='+encodeURIComponent(current.id)+'&match='+encodeURIComponent(f.id);line.append(play)}
 const edit=document.createElement('button');edit.textContent=f.source==='legacy'?'ERGEBNIS BEARBEITEN':'ALT-ERGEBNIS';edit.onclick=()=>selectResult(f);line.append(edit);host.append(line)}
const pager=document.getElementById('fixturePager');pager.replaceChildren();const back=document.createElement('button');back.textContent='←';back.disabled=page===0;back.onclick=()=>{page--;drawFixtures()};const txt=document.createElement('span');txt.textContent='Seite '+(page+1)+' / '+pages;const next=document.createElement('button');next.textContent='→';next.disabled=page>=pages-1;next.onclick=()=>{page++;drawFixtures()};pager.append(back,txt,next);
}
for(const id of ['fixtureGroup','fixtureRound','fixturePlayer','fixtureStatus'])document.getElementById(id).onchange=()=>{page=0;filterValues();drawFixtures()};
const original=render;render=function(s){original(s);document.getElementById('schedule').replaceChildren();filterValues();drawFixtures();document.getElementById('leagueTools').querySelector('details').open=false;document.getElementById('bulkCommit').disabled=true};
const preview=document.getElementById('bulkPreview'),commit=document.getElementById('bulkCommit'),output=document.getElementById('bulkResults'),message=document.getElementById('bulkStatus');
let checkedText='',checkedAliases=null;
function aliases(){const out={};for(const line of document.getElementById('bulkAliases').value.split(/\r?\n/)){if(!line.trim())continue;const pos=line.indexOf('=');if(pos<1)throw Error('Ungültiger Alias: '+line);out[line.slice(0,pos).trim()]=line.slice(pos+1).trim()}return out}
function drawReport(rows){output.replaceChildren();for(const row of rows){const x=document.createElement('div');x.className=row.status==='ok'?'league-ok':'league-err';x.textContent='Zeile '+row.line+': '+row.text+' → '+row.message;output.append(x)}}
preview.onclick=async()=>{commit.disabled=true;checkedText='';try{const raw=document.getElementById('bulkText').value;const result=await req('/'+current.id+'/bulk-import',{preview:true,text:raw,aliases:aliases()});drawReport(result.rows);message.textContent=result.ready+' übernehmbar · '+result.errors+' Probleme';if(result.ready>0&&result.errors===0){checkedText=raw;checkedAliases=aliases();commit.disabled=false}}catch(e){error(e)}};
for(const id of ['bulkText','bulkAliases'])document.getElementById(id).oninput=()=>{commit.disabled=true;checkedText=''};
commit.onclick=async()=>{if(!checkedText||!confirm('Alle geprüften Ergebnisse endgültig in die Ligatabelle übernehmen?'))return;commit.disabled=true;try{const result=await req('/'+current.id+'/bulk-import',{preview:false,text:checkedText,aliases:checkedAliases,admin_pin:document.getElementById('bulkPin').value});document.getElementById('bulkPin').value='';document.getElementById('bulkText').value='';checkedText='';alert(result.imported+' Ergebnisse importiert');render(result.season)}catch(e){error(e)}};
document.getElementById('finalCreate').onclick=async()=>{if(!confirm('Finalturnier aus aktuellen Staffelplatzierungen erzeugen? Die Qualifikanten werden fixiert.'))return;try{const s=await req('/'+current.id+'/finals',{best_of:+document.getElementById('finalBest').value,early:document.getElementById('finalEarly').checked,admin_pin:document.getElementById('finalPin').value});document.getElementById('finalPin').value='';render(s)}catch(e){error(e)}};
})();

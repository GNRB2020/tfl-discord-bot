(()=>{'use strict';
const $=id=>document.getElementById(id);let user=null,players=[],competitions=[],selected=null,playing=null,previewId=null;
function notice(text,error=false){$('message').textContent=text||'';$('message').className=error?'error':'';if(error)window.scrollTo(0,0)}
async function api(path,data){const options={credentials:'same-origin',headers:{'Accept':'application/json'}};if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const res=await fetch('/dart/v2/api'+path,options);const txt=await res.text();let j={};try{j=JSON.parse(txt)}catch{}if(!res.ok)throw Error(j.error||txt||'HTTP '+res.status);return j}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
function clear(node){node.replaceChildren()}
function el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x}
function btn(label,fn){const x=el('button',label);x.type='button';x.onclick=fn;return x}
function tile(title,sub,fn){const x=btn('',fn);x.className='tile';x.append(el('strong',title),el('small',sub));return x}
function section(name){for(const id of ['setup','login','changePassword','dashboard','training','ladder','competitions','boards','members','statistics','admin','scorer'])$(id).hidden=id!==name;$('nav').hidden=!user||['login','setup','changePassword'].includes(name);for(const b of document.querySelectorAll('nav [data-view]')){b.classList.toggle('active',b.dataset.view===name);b.style.display=b.classList.contains('admin')&&user?.role!=='admin'?'none':''}notice('')}
async function session(){try{user=await api('/me');if(user.must_change_password){section('changePassword');return}section('dashboard');await show('dashboard')}catch{user=null;section('login')}}
async function show(view){section(view);try{if(view==='dashboard')await dashboard();if(view==='competitions')await loadCompetitions();if(view==='ladder')await loadLadder();if(view==='boards')await loadBoards();if(view==='members')await loadPlayers();if(view==='statistics'){await loadPlayers();fillPlayerSelect('statPlayer',false)}if(view==='admin'){if(user.role!=='admin')throw Error('Nur Administratoren');await loadPlayers();fillPlayerSelect('accountPlayer',true);fillPlayerSelect('previewPlayer',false)}}catch(e){notice(e.message,true)}}
for(const b of document.querySelectorAll('nav [data-view]'))b.onclick=()=>show(b.dataset.view);
$('firstAdmin').onclick=()=>section('setup');
$('setupForm').onsubmit=async e=>{e.preventDefault();try{await api('/bootstrap',formData(e.target));section('login');notice('Administrator erstellt. Bitte anmelden.')}catch(err){notice(err.message,true)}};
$('loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/login',formData(e.target));await session()}catch(err){notice(err.message,true)}};
$('passwordForm').onsubmit=async e=>{e.preventDefault();try{await api('/password',formData(e.target));await session()}catch(err){notice(err.message,true)}};
$('logout').onclick=async()=>{try{await api('/logout',{})}catch{}user=null;section('login')};
async function dashboard(){const d=await api('/dashboard'+(previewId?'?player_id='+encodeURIComponent(previewId):''));const label=$('previewLabel');label.hidden=!previewId;$('previewBack').hidden=!previewId;if(previewId)label.textContent='SCHREIBGESCHÜTZTE VORSCHAU: '+(players.find(p=>p.id===previewId)?.display_name||previewId)+' – Spiele starten ist als Vorschau nicht möglich.';const host=$('summary');clear(host);for(const c of d.competitions)host.append(tile(c.title,c.kind+' · '+c.status+' · '+c.open_games+' offen',()=>openCompetition(c.id)));const list=$('myOpen');clear(list);if(!d.own_open.length)list.append(el('p','Keine offenen Begegnungen'));for(const m of d.own_open){const x=el('div',undefined,'matchrow');x.append(el('span',m.title+': '+m.player1+' – '+m.player2),btn(previewId?'Nur ansehen':'Spielen',()=>{if(previewId){notice('Spieleransicht ist schreibgeschützt. Zum Spielen Vorschau verlassen.',true);return}openScorer(m.id)}));list.append(x)}}
async function loadPlayers(){players=await api('/players');renderPlayers()}
function renderPlayers(){const q=$('memberSearch').value.toLocaleLowerCase('de');const host=$('membersList');clear(host);for(const p of players.filter(p=>p.display_name.toLocaleLowerCase('de').includes(q))){const t=el('article',undefined,'tile');t.append(el('strong',p.display_name),el('small',(p.legacy_profile_id||'Neues Profil')+' · '+(p.username?p.username+' / '+p.role:'Noch kein Konto')));host.append(t)}}
$('memberSearch').oninput=renderPlayers;
function fillPlayerSelect(id,blank){const host=$(id);clear(host);if(blank)host.append(new Option('Turnierkonto ohne Spieler',''));for(const p of players)host.append(new Option(p.display_name,p.id))}
async function loadCompetitions(){competitions=await api('/competitions');const host=$('competitionsList');clear(host);for(const c of competitions)host.append(tile(c.title,c.kind+' · '+c.status+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)))}
async function loadLadder(){const data=await api('/competitions'),host=$('ladderList');clear(host);const ladders=data.filter(c=>c.kind==='ladder');for(const c of ladders)host.append(tile(c.title,(c.status||'')+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)));if(!ladders.length)host.append(el('p','Noch keine Ladder-Saison angelegt. Administratoren können hier die erste Saison erstellen.'));$('ladderCreate').hidden=user.role!=='admin'}
$('ladderForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);d.kind='ladder';d.starts_at=new Date(d.starts_at).toISOString();d.ends_at=new Date(d.ends_at).toISOString();try{const c=await api('/competitions',d);await api('/competitions/'+c.id+'/phases',{kind:'ladder',name:'Ladder-Saison'});e.target.reset();await loadLadder();notice('Ladder-Saison angelegt. Teilnehmer unter Wettbewerbe hinzufügen; anschließend Saison aktivieren.')}catch(err){notice(err.message,true)}};
$('newTraining').onclick=()=>{show(user.role==='admin'?'admin':'competitions');notice(user.role==='admin'?'V2-Trainingsturniere werden über das Formular Neuer Wettbewerb angelegt.':'Bestehende Trainingsturniere erreichst du über den Trainingsbereich. Neue V2-Turniere können bislang über die Adminverwaltung angelegt werden.')};
$('previewOpen').onclick=async()=>{if(user?.role!=='admin')return;previewId=$('previewPlayer').value;await show('dashboard')};
$('previewExit').onclick=async()=>{previewId=null;await show('dashboard')};$('previewBack').onclick=$('previewExit').onclick;
async function loadBoards(){const boards=await api('/boards'),host=$('boardsList');clear(host);for(const b of boards){const t=el('article',undefined,'board '+(!b.enabled?'inactive':b.match_id?'busy':''));t.append(el('strong',b.label),el('p',!b.enabled?'Deaktiviert':b.match_id?'Belegt: '+b.competition:'Frei'));host.append(t)}}
const table=(headers,rows)=>{const outer=el('div',undefined,'scroll'),tab=el('table',undefined,'data-table'),head=el('thead'),tr=el('tr');for(const h of headers)tr.append(el('th',h));head.append(tr);tab.append(head);const tb=el('tbody');for(const row of rows){const line=el('tr');for(const val of row)line.append(el('td',String(val??'–')));tb.append(line)}tab.append(tb);outer.append(tab);return outer};
const kindNames={league:'Stingray League',cup:'Stingray Cup',ladder:'Stingray Ladder',vm:'Vereinsmeisterschaft',training_tournament:'Trainingsturnier',final_tournament:'Finalrunde'};
let competitionTab='table',schedulePage=0;
function action(text,fn,style=''){const b=btn(text,fn);if(style)b.className=style;return b}
function picker(items,selectedValue,callback){const select=el('select');for(const [v,t] of items)select.append(new Option(t,v));select.value=selectedValue;select.onchange=()=>callback(select.value);return select}
function labelFor(m,names){return (names.get(m.player1_id)||'Offen')+' – '+(names.get(m.player2_id)||'Offen')}
async function openCompetition(id){
  selected=await api('/competitions/'+id);section('competitions');
  const c=selected.competition,host=$('competitionDetail');host.hidden=false;clear(host);
  host.className='competition-view';
  const header=el('div',undefined,'competition-header');
  const h=el('div');h.append(el('span',kindNames[c.kind]||c.kind,'eyebrow'),el('h2',c.title));
  const summary=el('div',undefined,'competition-chips');
  const played=selected.matches.filter(m=>m.status==='finished').length;
  for(const x of [selected.entries.length+' Teilnehmer',played+' / '+selected.matches.length+' gespielt',c.status])summary.append(el('span',x,'chip'));
  h.append(summary);header.append(h,action('← Alle Wettbewerbe',()=>{$('competitionDetail').hidden=true;loadCompetitions()},'subtle'));host.append(header);
  const tabs=el('div',undefined,'competition-tabs');
  const content=el('div',undefined,'competition-content');
  host.append(tabs,content);
  async function view(tab){competitionTab=tab;clear(content);for(const b of tabs.children)b.classList.toggle('selected',b.dataset.tab===tab);
    try{if(tab==='table')await showTables(content);if(tab==='schedule')showSchedule(content);if(tab==='participants')showParticipants(content);if(tab==='management')showManagement(content)}
    catch(e){content.append(el('p',e.message,'error'))}
  }
  for(const [tab,name] of [['table',c.kind==='ladder'?'ELO-Rangliste':'Tabellen'],['schedule','Spielplan'],['participants','Teilnehmer'],...(user.role==='admin'?[['management','Verwaltung']]:[])]){
    const b=action(name,()=>view(tab));b.dataset.tab=tab;tabs.append(b);
  }
  const names=new Map(selected.entries.map(e=>[e.player_id,e.display_name]));
  async function showTables(box){
    if(c.kind==='ladder'){
      const rows=await api('/competitions/'+id+'/standings');box.append(el('p','ELO · Ausgangswert 1000 · K-Faktor 64 · ein Spiel zählt ab Abschluss','helper'));
      box.append(renderTable(['Pl.','Spieler','Sp.','S','U','N','Legs','Diff.','ELO','Siegquote'],rows.map((r,i)=>[i+1,r.display_name,r.played,r.wins,r.draws,r.losses,r.legs_for+':'+r.legs_against,signed(r.legs_for-r.legs_against),r.elo,(r.win_percent??0)+' %'])));return;
    }
    if(!selected.groups.length){box.append(el('p','Noch keine Gruppen angelegt. Die Einteilung erfolgt unter Verwaltung.','empty'));return}
    const switcher=el('div',undefined,'filterline');switcher.append(el('span','Staffel anzeigen'));
    const chosen=picker(selected.groups.map(g=>[g.id,g.name]),selected.groups[0].id,()=>fill());switcher.append(chosen);box.append(switcher);
    const area=el('div');box.append(area);
    async function fill(){clear(area);const g=selected.groups.find(g=>g.id===chosen.value);if(!g)return;
      const rows=await api('/competitions/'+id+'/standings?group_id='+g.id);
      const withdrawals=new Set(selected.entries.filter(e=>e.status==='withdrawn').map(e=>e.player_id));
      area.append(el('h3',g.name),renderTable(['Platz','Name','Ges.','S','U','N','Legs','Dif.','Pkt'],rows.map(r=>[
          r.rank,r.name+(withdrawals.has(r.player_id)?' · ausgetreten':''),r.played,r.wins,r.draws,r.losses,
          String(r.legs_for)+':'+String(r.legs_against),signed(r.legs_for-r.legs_against),r.points
      ]),true));
      const games=selected.matches.filter(m=>m.group_id===g.id&&m.status==='finished').length;
      area.append(el('p',games+' gewertete Spiele in dieser Staffel','helper'));
      if(games&&!rows.some(r=>r.played))area.append(el('p','Die Spiele sind gespeichert, aber nicht den Tabellenmitgliedern zugeordnet. Bitte die Gruppenzuordnung unter Verwaltung prüfen.','error'));
    }
    await fill();
  }
  function showSchedule(box){
    if(c.kind==='ladder'&&user.role!=='tournament'){
      const add=el('div',undefined,'filterline');add.append(el('strong','Neues Ladder-Match'));const first=picker([['','Spieler 1 wählen'],...selected.entries.filter(e=>e.status!=='withdrawn').map(e=>[e.player_id,e.display_name])],'',()=>{});
      const second=picker([['','Spieler 2 wählen'],...selected.entries.filter(e=>e.status!=='withdrawn').map(e=>[e.player_id,e.display_name])],'',()=>{});
      add.append(first,second,action('Match vereinbaren',async()=>{if(!first.value||!second.value||first.value===second.value)return notice('Zwei verschiedene Spieler auswählen.',true);
        try{await api('/competitions/'+id+'/matches',{player1_id:first.value,player2_id:second.value});await openCompetition(id);notice('Match angelegt')}catch(e){notice(e.message,true)}
      }));box.append(add);
    }
    const filters=el('div',undefined,'schedule-controls');
    const g=picker([['','Alle Staffeln'],...selected.groups.map(x=>[x.id,x.name])],'',()=>reset());
    const p=picker([['','Alle Spieler'],...selected.entries.map(e=>[e.player_id,e.display_name])],'',()=>reset());
    const status=picker([['','Alle Spiele'],['open','Offen'],['running','Laufend'],['finished','Beendet']],'',()=>reset());
    for(const [caption,select] of [['Staffel',g],['Spieler',p],['Status',status]]){const label=el('label',caption);label.append(select);filters.append(label)}
    const pages=el('div',undefined,'pagination');const list=el('div',undefined,'schedule-list');
    box.append(filters,list,pages);
    function reset(){schedulePage=0;draw()}
    function draw(){clear(list);clear(pages);
      const matches=selected.matches.filter(m=>(!g.value||m.group_id===g.value)&&(!p.value||m.player1_id===p.value||m.player2_id===p.value)&&(!status.value||m.status===status.value));
      const pageCount=Math.max(1,Math.ceil(matches.length/12));schedulePage=Math.max(0,Math.min(schedulePage,pageCount-1));
      box.querySelector('.schedule-controls').setAttribute('data-total',String(matches.length));
      list.append(el('p',matches.length+' Begegnungen','helper'));
      if(!matches.length)list.append(el('p','Keine Spiele mit diesen Filtern','empty'));
      for(const m of matches.slice(schedulePage*12,(schedulePage+1)*12)){
        const line=el('article',undefined,'fixture');const desc=el('div',undefined,'fixture-title');
        const group=selected.groups.find(g=>g.id===m.group_id)?.name||selected.phases.find(x=>x.id===m.phase_id)?.name||'Spiel';
        desc.append(el('small',group+(m.round_number?' · Runde '+m.round_number:'')),el('strong',labelFor(m,names)));
        const score=m.status==='finished'?(m.sets1!==null&&m.sets1!==undefined?'Sets '+m.sets1+':'+m.sets2+' · ':'')+(m.legs1??0)+':'+(m.legs2??0):m.status==='running'?'Laufend':'Offen';
        const actions=el('div',undefined,'fixture-actions');actions.append(el('span',score,'fixture-score'));
        if(m.source==='forfeit')actions.append(el('small','Wertung'));
        else if(m.source==='legacy')actions.append(el('small','Altbestand'));
        else actions.append(action(m.status==='finished'?'Spiel ansehen':'Scorer',()=>openScorer(m.id),'primary'));
        if(user.role==='admin'&&m.status==='open')actions.append(action('Altes Ergebnis',async()=>{
          const raw=prompt('Endergebnis als Legs, z. B. 4:2');if(raw===null)return;
          const match=/^\s*(\d+)\s*:\s*(\d+)\s*$/.exec(raw);if(!match){notice('Format: 4:2',true);return}
          try{await api('/matches/'+m.id+'/manual',{legs1:Number(match[1]),legs2:Number(match[2])});await openCompetition(id)}catch(e){notice(e.message,true)}
        },'subtle'));
        line.append(desc,actions);list.append(line);
      }
      pages.append(action('← Vorherige',()=>{schedulePage--;draw()},'subtle'),el('span','Seite '+(schedulePage+1)+' / '+pageCount),action('Nächste →',()=>{schedulePage++;draw()},'subtle'));
      pages.firstChild.disabled=schedulePage===0;pages.lastChild.disabled=schedulePage>=pageCount-1;
    }
    draw();
  }
  function showParticipants(box){
    const grid=el('div',undefined,'members-grid');
    for(const entry of selected.entries){const item=el('article',undefined,'member-tile');item.append(el('strong',entry.display_name),el('small',entry.status==='withdrawn'?'Ausgetreten':'Aktiv'));grid.append(item)}
    box.append(grid);
  }
  function showManagement(box){
    const ad=el('p','Administrative Werkzeuge – Änderungen betreffen den Wettbewerb und seine Ergebnisse.','helper');box.append(ad);
    const management=el('div',undefined,'management-grid');box.append(management);
    function panel(title,description){const panel=el('section',undefined,'manage-card');panel.append(el('h3',title),el('p',description,'helper'));management.append(panel);return panel}
    const people=panel('Teilnehmer','Mitglieder hinzufügen, einteilen und Austritte verwalten.');
    people.append(action('Teilnehmer hinzufügen',async()=>{
      await loadPlayers();const free=players.filter(p=>!selected.entries.some(e=>e.player_id===p.id));const name=prompt('Spielername:\n'+free.map(p=>p.display_name).join('\n'));
      const person=free.find(p=>p.display_name===name);if(!person)return;
      try{await api('/competitions/'+id+'/entries',{player_ids:[person.id]});await openCompetition(id)}catch(e){notice(e.message,true)}
    }));
    if(c.kind==='league'){
      const active=selected.entries.filter(e=>e.status!=='withdrawn');
      const drop=picker([['','Spieler auswählen'],...active.map(e=>[e.player_id,e.display_name])],'',()=>{});
      people.append(el('label','Spieler ausgeschieden – alle Begegnungen 0:4 werten'),drop);
      people.append(action('Rückwertung durchführen',async()=>{
        if(!drop.value)return notice('Bitte Spieler auswählen',true);
        const name=active.find(x=>x.player_id===drop.value)?.display_name;
        if(!confirm('ALLE bisherigen und offenen Spiele von '+name+' als 0:4 werten? Bereits gespielte Ergebnisse werden für die Tabelle ersetzt.'))return;
        try{const r=await api('/competitions/'+id+'/withdraw',{player_id:drop.value,forfeit_legs:4});await openCompetition(id);notice(r.revalued+' Spiele neu gewertet.')}catch(e){notice(e.message,true)}
      },'danger'));
    }
    const phases=panel('Gruppen & Spielmodus','Phasen und Gruppen werden unabhängig voneinander verwaltet.');
    phases.append(action('Neue Phase',async()=>{
      const mode=prompt('Phasenart: league, groups, knockout oder ladder','groups');if(!mode)return;
      const name=prompt('Bezeichnung',mode);if(!name)return;
      try{await api('/competitions/'+id+'/phases',{kind:mode,name});await openCompetition(id)}catch(e){notice(e.message,true)}
    }));
    for(const ph of selected.phases){
      const group=el('details',undefined,'manage-details');const summary=el('summary',ph.name+' · '+ph.kind+' · '+ph.status);group.append(summary);
      group.append(action('Gruppe anlegen',async()=>{const name=prompt('Gruppenname','Gruppe A');if(!name)return;try{await api('/phases/'+ph.id+'/groups',{name});await openCompetition(id)}catch(e){notice(e.message,true)}}));
      for(const g of selected.groups.filter(g=>g.phase_id===ph.id)){
        const sub=el('div',undefined,'group-edit');sub.append(el('strong',g.name));
        const current=selected.memberships.filter(x=>x.group_id===g.id).map(x=>selected.entries.find(e=>e.entry_id===x.entry_id)?.display_name).filter(Boolean);
        sub.append(el('small',current.join(', ')||'Keine Teilnehmer'));
        sub.append(action('Einteilung bearbeiten',async()=>{
          const names=prompt('Spielernamen mit Komma trennen',current.join(', '));if(names===null)return;
          const picks=names.split(',').map(x=>x.trim()).filter(Boolean).map(x=>selected.entries.find(e=>e.display_name.toLowerCase()===x.toLowerCase()));
          if(picks.some(x=>!x))return notice('Unbekannter Spielername',true);
          try{await api('/groups/'+g.id+'/entries',{entry_ids:picks.map(x=>x.entry_id)});await openCompetition(id)}catch(e){notice(e.message,true)}
        },'subtle'));
        sub.append(action('Spielplan erzeugen',async()=>{
          if(!confirm('Spielplan für '+g.name+' erzeugen?'))return;
          try{await api('/groups/'+g.id+'/fixtures',{double_round:confirm('Hin- und Rückrunde?')});await openCompetition(id)}catch(e){notice(e.message,true)}
        },'subtle'));group.append(sub);
      }
      if(ph.kind==='knockout')group.append(action('K.O. aus Teilnehmerliste',async()=>{try{await api('/phases/'+ph.id+'/bracket',{player_ids:selected.entries.map(e=>e.player_id)});await openCompetition(id)}catch(e){notice(e.message,true)}}),action('Nächste Runde',async()=>{try{await api('/phases/'+ph.id+'/advance',{});await openCompetition(id)}catch(e){notice(e.message,true)}}));
      group.append(action('Phase schließen',async()=>{if(!confirm('Diese Phase schließen?'))return;try{await api('/phases/'+ph.id+'/close',{});await openCompetition(id)}catch(e){notice(e.message,true)}},'subtle'));
      phases.append(group);
    }
    const general=panel('Export & Status','Offene Begegnungen exportieren und Wettbewerbsstatus verwalten.');
    if(c.kind!=='training_tournament')general.append(action('CSV exportieren',()=>location.href='/dart/v2/api/competitions/'+id+'/export?format=csv'),action('Excel exportieren',()=>location.href='/dart/v2/api/competitions/'+id+'/export?format=xlsx'));
    general.append(picker([['','Status ändern …'],...['active','finished','archived'].map(v=>[v,v])],'',async state=>{if(!state||!confirm('Status auf '+state+' ändern?'))return;try{await api('/competitions/'+id+'/status',{status:state});await openCompetition(id)}catch(e){notice(e.message,true)}}));
    general.append(action('Wettbewerb ausblenden',async()=>{if(prompt('Zur Bestätigung DAUERHAFT AUSBLENDEN eingeben')!=='DAUERHAFT AUSBLENDEN')return;try{await api('/competitions/'+id+'/delete',{confirm:'DAUERHAFT AUSBLENDEN'});host.hidden=true;await loadCompetitions()}catch(e){notice(e.message,true)}},'danger'));
    if(c.kind==='ladder'){
      const ladder=panel('Ladder','Laufzeit und Matchabschluss verwalten.');
      ladder.append(action('Ladder abschließen',async()=>{if(!confirm('Ladder beenden und offene Spiele abbrechen?'))return;try{await api('/competitions/'+id+'/end-ladder',{});await openCompetition(id)}catch(e){notice(e.message,true)}},'danger'));
    }
  }
  if(c.kind==='ladder'&&user.role!=='admin'){};
  await view(competitionTab==='management'&&user.role!=='admin'?'table':competitionTab);
}
function signed(n){return n>0?'+'+n:String(n)}
function renderTable(headers,rows,emphasize=false){
 const outer=el('div',undefined,'scroll table-frame'),t=el('table',undefined,'data-table polished'),thead=el('thead'),tr=el('tr');
 for(const h of headers)tr.append(el('th',h));thead.append(tr);t.append(thead);
 const tbody=el('tbody');for(const row of rows){const tr=el('tr');if(emphasize&&row[0]===1)tr.className='leader';for(const cell of row)tr.append(el('td',String(cell??'–')));tbody.append(tr)}
 t.append(tbody);outer.append(t);return outer;
}

async function openScorer(id){
 if(previewId){notice('Die Spieleransicht ist schreibgeschützt.',true);return}
 location.href='/dart/v2/spiel/?match='+encodeURIComponent(id)+'&competition='+encodeURIComponent(selected?.competition?.id||'');
}
function drawScore(){if(!playing)return;const s=playing.state||{},names=s.names||[playing.player1,playing.player2],rest=s.remaining||[501,501];$('playerOne').textContent=names[0];$('playerTwo').textContent=names[1];$('remainOne').textContent=rest[0];$('remainTwo').textContent=rest[1];$('resultOne').textContent='Legs '+(s.legs?.[0]??playing.legs1??0)+' · Sets '+(s.sets?.[0]??0);$('resultTwo').textContent='Legs '+(s.legs?.[1]??playing.legs2??0)+' · Sets '+(s.sets?.[1]??0);for(let i=0;i<2;i++)document.querySelectorAll('.scorecard')[i].classList.toggle('current',s.current===i&&!s.done);$('toThrow').textContent=s.done?'Spiel beendet':names[s.current??0]+' wirft';$('throwForm').hidden=s.done||playing.status==='finished'||!playing.can_score;$('scoreStatus').textContent='Version '+playing.state_version;const host=$('visits');clear(host);for(const v of (s.visits||[]).slice().reverse())host.append(el('p',names[v.player]+': '+v.score+' / '+v.darts+' Darts'+(v.checkout?' · Checkout':'')+(v.bust?' · Bust':'')))}
$('throwForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);try{const r=await api('/matches/'+playing.id+'/throw',{points:Number(d.points),darts:Number(d.darts),checkout:!!d.checkout,bullfinish:!!d.bullfinish,version:playing.state_version});playing.state=r.state;playing.state_version=r.version;e.target.reset();e.target.elements.darts.value=3;drawScore()}catch(err){notice(err.message,true)}};
$('backToCompetition').onclick=()=>selected?openCompetition(selected.competition.id):show('dashboard');
$('statsLoad').onclick=async()=>{try{const s=await api('/players/'+$('statPlayer').value+'/stats?kind='+$('statKind').value);const host=$('statsResult');clear(host);for(const [k,v] of Object.entries(s))host.append(tile(k,String(v??'Keine Wurfdaten'),()=>{}))}catch(e){notice(e.message,true)}};
$('memberForm').onsubmit=async e=>{e.preventDefault();try{await api('/players',formData(e.target));e.target.reset();await loadPlayers();notice('Mitglied erstellt')}catch(err){notice(err.message,true)}};
$('accountForm').onsubmit=async e=>{e.preventDefault();try{await api('/accounts',formData(e.target));e.target.reset();notice('Konto erstellt. Erstpasswort nur direkt an die betreffende Person weitergeben.')}catch(err){notice(err.message,true)}};
const migrationPanel=el('div',undefined,'panel');migrationPanel.append(el('h2','Vorhandene League und Profile übernehmen'),el('p','Übernahme erfolgt ausdrücklich als Kopie nach Neon. Die alte League bleibt unverändert.'));migrationPanel.append(btn('Aktive Google-Sheets-Profile nach Neon kopieren',async()=>{if(!confirm('Aktive Profile mit ihren bisherigen IDs importieren?'))return;try{const result=await api('/legacy/sync-profiles',{});notice(result.synced_active_profiles+' Profile kopiert');await loadPlayers()}catch(e){notice(e.message,true)}}));migrationPanel.append(btn('League-Migration: Vorschau',async()=>{try{const result=await api('/legacy/preview');if(!result.leagues.length){notice('Keine alten Liga-Snapshots gefunden');return}const choice=prompt('Gewünschte League-ID eingeben:\n'+result.leagues.map(l=>l.legacy_id+' – '+l.name+' ('+l.completed+'/'+l.fixtures+' gespielt, '+l.in_progress+' laufen)').join('\n'));if(!choice)return;const source=result.leagues.find(l=>l.legacy_id===choice);if(!source){notice('Unbekannte ID',true);return}if(!confirm('Die League '+source.name+' mit '+source.fixtures+' Spielen als SEPARATE KOPIE importieren?'))return;const r=await api('/legacy/import',{legacy_id:choice,confirm:true});notice(r.fixtures+' Begegnungen in Neon kopiert');await show('competitions')}catch(e){notice(e.message,true)}}));$('admin').append(migrationPanel);
$('competitionForm').onsubmit=async e=>{e.preventDefault();let d=formData(e.target);for(const key of ['starts_at','ends_at']){if(d[key])d[key]=new Date(d[key]).toISOString();else delete d[key]}try{await api('/competitions',d);e.target.reset();notice('Wettbewerb erstellt');await show('competitions')}catch(err){notice(err.message,true)}};
session().then(()=>{const c=new URLSearchParams(location.search).get('competition');if(c&&user)openCompetition(c).catch(e=>notice(e.message,true))});
})();

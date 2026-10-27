(()=>{'use strict';
const $=id=>document.getElementById(id);let user=null,players=[],competitions=[],selected=null,playing=null,previewId=null;
const avatarPlayers=new Set();function setAvatarMetadata(rows){for(const r of rows)if(r.has_avatar)avatarPlayers.add(String(r.id));}
function notice(text,error=false){$('message').textContent=text||'';$('message').className=error?'error':'';if(error)window.scrollTo(0,0)}
async function api(path,data){const options={credentials:'same-origin',headers:{'Accept':'application/json'}};if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const res=await fetch('/dart/v2/api'+path,options);const txt=await res.text();let j={};try{j=JSON.parse(txt)}catch{}if(!res.ok)throw Error(j.error||txt||'HTTP '+res.status);return j}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
function clear(node){node.replaceChildren()}
function el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x}
function btn(label,fn){const x=el('button',label);x.type='button';x.onclick=fn;return x}
// Every popup is dismissed only by its own explicit controls, never its backdrop.
function popupCloseButton(onClose){const x=btn('×',onClose);x.className='sheet-close';x.setAttribute('aria-label','Fenster schließen');x.title='Fenster schließen';return x}
function tile(title,sub,fn){const x=btn('',fn);x.className='tile';x.append(el('strong',title),el('small',sub));return x}
// Compact navigation: at most a single viewport of records, with explicit page controls.
const letterBands=[['AF','A–F'],['GL','G–L'],['MR','M–R'],['SZ','S–Z'],['other','Sonstige']];
function bandOf(name){const v=String(name||'').trim().normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();const initial=v[0]||'';if(initial>='A'&&initial<='F')return 'AF';if(initial>='G'&&initial<='L')return 'GL';if(initial>='M'&&initial<='R')return 'MR';if(initial>='S'&&initial<='Z')return 'SZ';return 'other'}
function makeTabs(host,items,current,onChange){clear(host);for(const [value,label] of items){const b=btn(label,()=>onChange(value));b.className='ui-tab'+(value===current?' selected':'');b.dataset.tab=value;b.setAttribute('role','tab');b.setAttribute('aria-selected',String(value===current));host.append(b)}}
function makeTable(host,headers,records,renderRow){clear(host);const table=el('table',undefined,'data-table polished density-table'),head=el('thead'),tr=el('tr');for(const name of headers){const th=el('th',name);th.scope='col';tr.append(th)}head.append(tr);table.append(head);const body=el('tbody');records.forEach((entry,i)=>body.append(renderRow(entry,i)));table.append(body);host.append(table)}
function compactPager(host,total,page,setPage,per=9){clear(host);const max=Math.max(1,Math.ceil(total/per));if(max===1)return;const back=btn('← Zurück',()=>setPage(page-1)),next=btn('Weiter →',()=>setPage(page+1));back.disabled=page===0;next.disabled=page>=max-1;host.append(back,el('span','Seite '+(page+1)+' / '+max),next)}
let dashboardTab='overview';function displayDashboardTab(tab){dashboardTab=tab;makeTabs($('dashboardTabs'),[['overview','Kennzahlen'],['matches','Spiele'],['competitions','Wettbewerbe'],['live','Live']],tab,displayDashboardTab);for(const node of document.querySelectorAll('[data-dashboard-pane]'))node.hidden=node.dataset.dashboardPane!==tab;if(tab==='live'&&user)refreshLive().catch(()=>{})}
$('dashboardTabs')?.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;const buttons=[...$('dashboardTabs').querySelectorAll('button')];const i=buttons.indexOf(document.activeElement);if(i<0)return;e.preventDefault();const next=buttons[(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length];next.click();next.focus()});
displayDashboardTab('overview');
function setupSettingsTabs(){
 const form=$('settingsForm'),panels=[...form.children].filter(n=>n.classList.contains('panel'));
 const tabs=el('div',undefined,'ui-tabs settings-tabs'),container=el('div',undefined,'settings-tab-container');
 form.before(tabs);form.prepend(container);
 const map={profile:el('div',undefined,'settings-pane'),widgets:el('div',undefined,'settings-pane'),security:el('div',undefined,'settings-pane')};
 // Original order: personal details, dashboard widgets, password, optional admin linking.
 panels.forEach((p,i)=>map[["profile","widgets","security","profile"][i]||'profile'].append(p));
 for(const pane of Object.values(map))container.append(pane);
 let current='profile';function activate(key){current=key;makeTabs(tabs,[['profile','Profil'],['widgets','Dashboard-Auswahl'],['security','Passwort & Sicherheit']],key,activate);for(const [name,pane] of Object.entries(map))pane.hidden=name!==key}
 activate(current);
}
setupSettingsTabs();
let trainingTab='games';function displayTrainingTab(kind){trainingTab=kind;makeTabs($('trainingTabs'),[['games','Trainingsspiele'],['tournaments','Trainingsturniere']],kind,displayTrainingTab);$('trainingPaneGames').hidden=kind!=='games';$('trainingPaneTournaments').hidden=kind!=='tournaments'}
displayTrainingTab('games');
const fullscreenButton=$('fullscreenToggle');function syncFullscreen(){const active=!!document.fullscreenElement;fullscreenButton.textContent=active?'⛶ Vollbild verlassen':'⛶ Vollbild';fullscreenButton.setAttribute('aria-pressed',String(active));document.body.classList.toggle('is-fullscreen',active)}
fullscreenButton.onclick=async()=>{try{if(document.fullscreenElement){await document.exitFullscreen()}else if(document.documentElement.requestFullscreen){await document.documentElement.requestFullscreen()}else{notice('Dieser Browser unterstützt den Vollbildmodus hier nicht. Auf Mobilgeräten kann die App zum Startbildschirm hinzugefügt werden.',true)}}catch(e){notice('Vollbild konnte nicht aktiviert werden: '+e.message,true)}};
document.addEventListener('fullscreenchange',syncFullscreen);syncFullscreen();
const defaultDashboardWidgets=['open_matches','last10','ladder_rank','elo'];
const widgetLabels={open_matches:'Offene Begegnungen',last10:'Bilanz letzte 10 Spiele',ladder_rank:'Platzierung Ladder',elo:'Aktueller ELO-Wert',competitions:'Aktive Wettbewerbe',average:'Ø Average',first9:'Ø First 9','180':'180er','95plus':'95+'};
function portrait(playerId,large=false){const shell=el('span',undefined,'player-portrait'+(large?' portrait-large':''));
 if(!playerId||!avatarPlayers.has(String(playerId))){shell.textContent='◈';return shell}
 const img=document.createElement('img');img.loading='lazy';img.alt='Profilbild';img.src='/dart/v2/api/players/'+encodeURIComponent(playerId)+'/avatar';
 img.onerror=()=>{img.remove();shell.textContent='◈'};shell.append(img);return shell;
}
function participantName(id,name){const row=el('span',undefined,'participant-name');row.append(portrait(id),el('span',name||'Spieler'));return row}
// Jede Partie bekommt die gesamte aktuelle Browseransicht – KEIN zweiter Tab.
// Zur Verwaltung gelangt man über den Zurück-Link des Scorers.
function openGameWindow(url){window.location.assign(url);return true}
function launchTrainingWindow(kind){
 if(kind==='sau'||kind==='tug'||kind==='bobs')return window.location.assign('/dart/v2/training/scorer/?kind='+encodeURIComponent(kind==='bobs'?'bobs27':kind));
 window.location.assign('/dart/v2/?training='+encodeURIComponent(kind));
}


async function refreshLive(){
 const liveArea=$('dashboardLive');if(liveArea){clear(liveArea);
  try{const live=await api('/live-games');const head=el('div',undefined,'live-heading');head.append(el('h3','Gerade live · '+live.length+' Spiele'),action('Aktualisieren',()=>dashboard(),'subtle'));liveArea.append(head);
   const grid=el('div',undefined,'live-grid');for(const m of live){
    const card=el('article',undefined,'live-game');
    const subtitle=el('div',undefined,'live-game-caption');
    subtitle.append(el('span',m.title+' · '+({ladder:'Ladder',league:'Liga',training_tournament:'Trainingsturnier',cup:'Cup',vm:'Vereinsmeisterschaft'}[m.kind]||m.kind||'Wettbewerb')));
    const status=el('span','LIVE','live-indicator');subtitle.append(status);card.append(subtitle);
    const score=el('div',undefined,'live-scoreboard');
    const left=el('div',undefined,'live-team');left.append(el('strong',m.player1));
    const result=el('div',undefined,'live-result');const sets=Array.isArray(m.sets)&&m.sets.some(Number);
    result.append(el('span',(sets?m.sets:m.legs||[0,0]).map(x=>Number(x)||0).join(' : '),'live-score-digits'));
    if(sets)result.append(el('small','Sets · Legs '+(m.legs||[0,0]).join(' : ')));
    const right=el('div',undefined,'live-team live-team-right');right.append(el('strong',m.player2));
    score.append(left,result,right);card.append(score);
    const averages=el('div',undefined,'live-averages');
    averages.append(el('span','Ø '+(m.averages?.[0]===null||m.averages?.[0]===undefined?'–':Number(m.averages[0]).toFixed(2))));
    averages.append(el('small','MATCH-AVERAGE'));
    averages.append(el('span','Ø '+(m.averages?.[1]===null||m.averages?.[1]===undefined?'–':Number(m.averages[1]).toFixed(2))));
    card.append(averages);grid.append(card);
   }
   if(!live.length)grid.append(el('p','Momentan wird keine Begegnung gespielt.','helper'));
   liveArea.append(grid);
  }catch(e){liveArea.append(el('small','Live-Spiele derzeit nicht verfügbar.'))}
 }

}
setInterval(()=>{if(user&&!$('dashboard').hidden)refreshLive().catch(()=>{})},45000);
// In-app configuration sheet: never uses blocking browser prompts.
function configure(title,fields,submitText='Speichern'){
 return new Promise(resolve=>{
  const shade=el('div',undefined,'sheet-shade'),panel=el('section',undefined,'config-sheet'),heading=el('h2',title),form=el('form',undefined,'sheet-form');
  form.append(heading);
  const conditional=[];
  for(const f of fields){const label=el('label',f.label||f.name);let control;
   if(f.type==='select'){control=el('select');for(const [id,name] of f.options||[])control.append(new Option(name,id));if(f.value!==undefined)control.value=String(f.value)}
   else if(f.type==='multi'){
    control=el('div',undefined,'checklist-search');const search=document.createElement('input');search.type='search';
    search.placeholder='Spieler suchen …';search.setAttribute('aria-label','Liste durchsuchen');
    const selectedCount=el('small',undefined,'checklist-count'),items=el('div',undefined,'checklist checklist-options');
    for(const [id,name] of f.options||[]){const l=el('label');const cb=document.createElement('input');cb.type='checkbox';cb.name=f.name;cb.value=id;cb.checked=(f.value||[]).includes(id);l.append(cb,el('span',name));items.append(l)}
    const update=()=>{const term=search.value.trim().toLocaleLowerCase('de');for(const l of items.children)l.hidden=!l.textContent.toLocaleLowerCase('de').includes(term);
      selectedCount.textContent=items.querySelectorAll('input:checked').length+' von '+items.querySelectorAll('input').length+' ausgewählt';};
    search.oninput=update;items.addEventListener('change',update);
    const controls=el('div',undefined,'checklist-toolbar');const visible=()=>[...items.querySelectorAll('label:not([hidden]) input')];
    controls.append(btn('Sichtbare wählen',()=>{for(const checkbox of visible())checkbox.checked=true;update()}),btn('Sichtbare abwählen',()=>{for(const checkbox of visible())checkbox.checked=false;update()}));
    control.append(search,selectedCount,controls,items);update();
   }
   else if(f.type==='textarea'){control=el('textarea');control.value=f.value||''}
   else {control=document.createElement('input');control.type=f.type||'text';control.value=f.value??'';if(f.min!==undefined)control.min=f.min;if(f.max!==undefined)control.max=f.max;if(f.step!==undefined)control.step=f.step;}
   if(f.type!=='multi'){control.name=f.name;control.required=!!f.required}
   if(f.readonly)control.readOnly=true;
   label.append(control);form.append(label);
   if(f.when)conditional.push({label,control,when:f.when,required:!!f.required});
  }
  const refreshFields=()=>{for(const row of conditional){
   const field=form.elements[row.when[0]],visible=!!field&&String(field.value)===String(row.when[1]);
   row.label.hidden=!visible;
   const elements=row.control.matches?.('input,select,textarea')?[row.control]:[...row.control.querySelectorAll('input,select,textarea')];
   for(const input of elements){input.disabled=!visible;input.required=visible&&row.required}
  }};
  form.addEventListener('change',refreshFields);refreshFields();
  const foot=el('div',undefined,'sheet-actions'),cancel=btn('Abbrechen',()=>finish(null)),ok=document.createElement('button');ok.type='submit';ok.textContent=submitText;
  const previousFocus=document.activeElement;
  const finish=data=>{shade.remove();if(previousFocus?.isConnected)previousFocus.focus();resolve(data)};
  panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label',title);
  foot.append(cancel,ok);form.append(foot);panel.append(popupCloseButton(()=>finish(null)),form);
  shade.append(panel);document.body.append(shade);
  // Clicks on the shaded area or Escape must not discard a multi-step form.
  shade.addEventListener('click',e=>{if(e.target===shade)e.stopPropagation()});
  form.onsubmit=e=>{e.preventDefault();const result=Object.fromEntries(new FormData(form).entries());for(const f of fields)if(f.type==='multi')result[f.name]=[...form.querySelectorAll('input[name="'+f.name+'"]:checked')].map(x=>x.value);finish(result)};
  form.querySelector('input,select,textarea')?.focus();
 })
}
async function approve(title,text){return !!await configure(title,[{name:'ack',label:text,type:'select',options:[['','Bitte wählen'],['yes','Ja, ausführen']],required:true}],'Bestätigen').then(x=>x?.ack==='yes')}
const amAdmin=()=>user?.role==='admin';
const trainingOwner=()=>selected?.competition?.kind==='training_tournament'&&selected?.competition?.created_by===user?.id;
function section(name){for(const id of ['setup','login','changePassword','dashboard','settings','training','ladder','competitions','boards','members','statistics','admin','scorer'])$(id).hidden=id!==name;$('nav').hidden=!user||['login','setup','changePassword'].includes(name);$('mobileMenu').hidden=$('nav').hidden;$('nav').classList.remove('mobile-open');$('mobileMenu').setAttribute('aria-expanded','false');for(const b of document.querySelectorAll('nav [data-view]')){b.classList.toggle('active',b.dataset.view===name);b.style.display=b.classList.contains('admin')&&!amAdmin()?'none':(b.dataset.view==='boards'&&user?.role==='member'?'none':'')}notice('')}
async function session(){try{user=await api('/me');if(user.must_change_password){section('changePassword');return}section('dashboard');await show('dashboard')}catch{user=null;section('login')}}
async function show(view){section(view);try{if(view==='dashboard')await dashboard();if(view==='settings')await loadSettings();if(view==='competitions')await loadCompetitions();if(view==='training')await loadTraining();if(view==='ladder')await loadLadder();if(view==='boards')await loadBoards();if(view==='members')await loadPlayers();if(view==='statistics'){await loadPlayers();fillPlayerSelect('statPlayer',false);renderStatisticsProfiles();}if(view==='admin'){if(user.role!=='admin')throw Error('Nur Administratoren');await loadPlayers();fillPlayerSelect('accountPlayer',true);fillPlayerSelect('previewPlayer',false);await Promise.all([loadOnlineSessions(),loadAuditLog(true),loadStatSources(),loadPasswordRequests()])}}catch(e){notice(e.message,true)}}
$('mobileMenu').onclick=()=>{const expanded=$('nav').classList.toggle('mobile-open');$('mobileMenu').setAttribute('aria-expanded',String(expanded))};
for(const b of document.querySelectorAll('nav [data-view]'))b.onclick=()=>show(b.dataset.view);
$('firstAdmin').onclick=()=>section('setup');
$('setupForm').onsubmit=async e=>{e.preventDefault();try{await api('/bootstrap',formData(e.target));section('login');notice('Administrator erstellt. Bitte anmelden.')}catch(err){notice(err.message,true)}};
$('forgotPassword').onclick=async()=>{
 const prefill=$('loginForm').elements.username.value||'';
 const data=await configure('Passwort zurücksetzen',[
  {name:'username',label:'Dein Benutzername',value:prefill,required:true}
 ],'Anfrage senden');
 if(!data)return;
 try{await api('/password-reset/request',{username:data.username});notice('Anfrage übermittelt. Falls das Konto existiert, kann die Administration ein neues Startpasswort vergeben. Es wird dir persönlich mitgeteilt.')}catch(e){notice(e.message,true)}
};
async function loadPasswordRequests(){
 const host=$('passwordRequests');if(!host)return;clear(host);
 try{const result=await api('/admin/password-reset-requests');if(!result.items.length){host.append(el('p','Keine offenen Passwort-Anfragen.','helper'));return}
  const table=el('div',undefined,'request-list');for(const item of result.items){const row=el('div',undefined,'request-row');row.append(el('strong',item.username),el('small',new Date(item.requested_at).toLocaleString('de-DE')));
    row.append(action('Startpasswort vergeben',async()=>{
      const values=await configure('Passwort zurücksetzen · '+item.username,[{name:'initial_password',label:'Neues Startpasswort (mindestens 12 Zeichen)',type:'password',required:true}], 'Zurücksetzen');
      if(!values)return;if(values.initial_password.length<12)return notice('Mindestens 12 Zeichen erforderlich.',true);
      if(!await approve('Passwortwechsel bestätigen','Alle bestehenden Sitzungen von '+item.username+' werden beendet. Das Startpasswort muss der Person persönlich mitgeteilt werden.'))return;
      try{await api('/admin/password-reset-requests/'+item.id+'/complete',{initial_password:values.initial_password});await loadPasswordRequests();notice('Startpasswort für '+item.username+' vergeben. Bitte der Person persönlich mitteilen.')}catch(e){notice(e.message,true)}
    },'subtle'));table.append(row)}host.append(table);
 }catch(e){host.append(el('p','Passwort-Anfragen konnten nicht geladen werden: '+e.message,'helper'))}
}
$('refreshPasswordRequests').onclick=loadPasswordRequests;
$('loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/login',formData(e.target));await session()}catch(err){notice(err.message,true)}};
$('passwordForm').onsubmit=async e=>{e.preventDefault();try{await api('/password',formData(e.target));await session()}catch(err){notice(err.message,true)}};
$('logout').onclick=async()=>{try{await api('/logout',{})}catch{}user=null;section('login')};
async function dashboard(){
 const d=await api('/dashboard'+(previewId?'?player_id='+encodeURIComponent(previewId):''));
 if(!players.length){try{players=await api('/players');setAvatarMetadata(players)}catch(e){console.warn('Profilbilder nicht geladen',e)}}
 if(d.profile?.has_avatar)avatarPlayers.add(String(d.viewed_player_id));
 const profile=d.profile||{},nickname=profile.nickname||user.username||profile.display_name||'Mitglied';
 const label=$('previewLabel');label.hidden=!previewId;$('previewBack').hidden=!previewId;
 if(previewId)label.textContent='SCHREIBGESCHÜTZTE VORSCHAU: '+(profile.display_name||'Spieler')+' – keine Spiele im Namen dieses Mitglieds starten.';
 $('dashboardGreeting').textContent='Hallo '+nickname+', willkommen in deinem Dashboard.';
 await refreshLive();
 $('dashFullName').textContent=[profile.first_name,profile.nickname,profile.last_name].filter(Boolean).join(' · ')||(profile.display_name||'');
 const clock=()=>{$('dashboardDate').textContent=new Intl.DateTimeFormat('de-DE',{dateStyle:'full',timeStyle:'short'}).format(new Date())};clock();
 clear($('dashPortrait'));$('dashPortrait').append(portrait(d.viewed_player_id,true));
 $('dashSettings').hidden=!!previewId;$('dashQuickLadder').hidden=!!previewId;
 const selectedWidgets=new Set(Array.isArray(profile.widgets)?profile.widgets:defaultDashboardWidgets);
 $('dashOpenGroup').hidden=!selectedWidgets.has('open_matches');
 $('dashLadderGroup').hidden=!(selectedWidgets.has('ladder_rank')||selectedWidgets.has('elo'));
 const summary=$('summary');clear(summary);
 let performance={};if(d.viewed_player_id){try{performance=await api('/players/'+d.viewed_player_id+'/stats?kind=overall')}catch(e){console.warn('Dashboard-Statistik nicht abrufbar',e)}}
 const l=d.ladder.find(x=>x.played>0)||d.ladder[0];
 const stats={open_matches:d.own_open.length,last10:d.recent_totals.wins+' S / '+d.recent_totals.draws+' U / '+d.recent_totals.losses+' N',
  ladder_rank:l&&l.played?l.position:'–',elo:l?Number(l.elo).toFixed(1):'–',
  competitions:d.competitions.filter(c=>c.status==='active').length,average:performance.average??'–',first9:performance.first9??'–',
  '180':performance['180']??'–','95plus':performance['95plus']??'–'};
 for(const key of Object.keys(widgetLabels)){if(!selectedWidgets.has(key))continue;
  const x=el('article',undefined,'dash-kpi');x.append(el('span',widgetLabels[key]),el('strong',String(stats[key])));summary.append(x)}
 if(!summary.children.length)summary.append(el('p','Du hast noch keine Kennzahlen ausgewählt. Unter Persönliche Einstellungen kannst du sie aktivieren.','helper'));
 const ladders=$('dashboardLadder');clear(ladders);
 for(const l of d.ladder){const card=el('article',undefined,'dash-ladder-card');const ladderValue=[selectedWidgets.has('elo')?Number(l.elo).toFixed(1)+' ELO':null,selectedWidgets.has('ladder_rank')?(l.played?'Platz '+l.position:'Noch nicht platziert'):null].filter(Boolean).join(' · ');card.append(el('strong',l.title),el('b',ladderValue));card.append(action('Rangliste',()=>openCompetition(l.competition_id),'subtle'));ladders.append(card)}
 if(!d.ladder.length)ladders.append(el('p','Keine Ladder-Teilnahme vorhanden.','helper'));
 const tournaments=$('dashboardCompetitions');clear(tournaments);
 for(const c of d.competitions.filter(c=>c.status==='active'||c.open_games>0)){const x=el('article',undefined,'dash-competition');x.append(el('strong',c.title),el('small',(kindNames[c.kind]||c.kind)+' · '+c.open_games+' offene Spiele'));
  x.append(action('Öffnen',()=>openCompetition(c.id),'subtle'));tournaments.append(x)}
 if(!tournaments.children.length)tournaments.append(el('p','Keine laufenden Wettbewerbe eingetragen.','helper'));
 const list=$('myOpen');clear(list);
 for(const m of d.own_open){const x=el('div',undefined,'dash-match');const names=el('div',undefined,'dash-player-pair');names.append(participantName(m.player1_id,m.player1),el('span','–'),participantName(m.player2_id,m.player2));
  const heading=el('div');heading.append(el('small',m.title),names);x.append(heading,el('span',m.status==='running'?'Laufend':m.status==='cancelled'?'Abgesagt':'Offen','chip'));
  x.append(action(previewId?'Spiel ansehen':m.status==='running'?'Fortsetzen':'Scorer starten',()=>previewId?notice('Die Vorschau ist schreibgeschützt.',true):
   m.kind==='free_x01'?openGameWindow('/dart/v2/spiel/?free=1&match='+encodeURIComponent(m.id)):openScorer(m.id),'primary'));
  if(m.status==='running'&&!previewId)x.append(action('Abbrechen',async()=>{
    if(!await approve('Laufendes Spiel abbrechen','Die bisherigen Aufnahmen dieses Spiels werden verworfen. Das Spiel zählt nicht für Statistiken.'))return;
    try{await api(m.kind==='free_x01'?'/free-x01/'+m.id+'/abort':'/matches/'+m.id+'/abort',
       m.kind==='free_x01'?{confirm:'ABBRECHEN'}:{mode:'reset',confirm:'ABBRECHEN',reason:'Im Dashboard abgebrochen'});
       await dashboard();notice('Spiel abgebrochen.')}catch(e){notice('Spielabbruch fehlgeschlagen: '+e.message,true)}
   },'subtle'));
  list.append(x)}
 if(!d.own_open.length)list.append(el('p','Keine offenen Begegnungen','helper'));
 const recent=$('dashboardRecent');clear(recent);
 for(const m of d.recent){const left=m.player1_id===d.viewed_player_id;const value1=(m.sets1||m.sets2)?m.sets1:m.legs1,value2=(m.sets1||m.sets2)?m.sets2:m.legs2;
  const win=left?value1>value2:value2>value1,draw=value1===value2;
  const x=el('article',undefined,'dash-result'),names=el('div',undefined,'dash-result-players');names.append(participantName(m.player1_id,m.player1),el('span','–'),participantName(m.player2_id,m.player2));
  const outcome=el('strong',(value1??0)+':'+(value2??0)+(draw?' · U':win?' · S':' · N'));outcome.classList.add(win?'result-win':draw?'result-draw':'result-loss');
  x.append(names,outcome,el('small',m.title+' · '+(m.finished_at?new Date(m.finished_at).toLocaleDateString('de-DE'):'Abgeschlossen')));recent.append(x)}
 if(!d.recent.length)recent.append(el('p','Noch keine abgeschlossenen Spiele.','helper'));
}
async function quickLadder(){
 if(!user?.player_id)return notice('Bitte zuerst ein aktives Vereinsprofil mit deinem Account verbinden.',true);
 try{const all=await api('/competitions');const now=Date.now();const ladders=all.filter(c=>c.kind==='ladder'&&c.status==='active'&&(!c.starts_at||new Date(c.starts_at).getTime()<=now)&&(!c.ends_at||new Date(c.ends_at).getTime()>now));
  if(!ladders.length)return notice('Keine aktuell aktive Ladder vorhanden.',true);
  const season=ladders[0],detail=await api('/competitions/'+season.id);
  const other=detail.entries.filter(x=>x.player_id!==user.player_id&&x.status==='active');
  if(!detail.entries.some(x=>x.player_id===user.player_id&&x.status==='active'))return notice('Dein Vereinsprofil ist in dieser Ladder nicht angemeldet. Bitte die Profilverknüpfung prüfen.',true);
  if(!other.length)return notice('Keine Gegner in dieser Ladder vorhanden.',true);
  const fields=[{name:'opponent',label:'Gegner',type:'select',options:other.map(x=>[x.player_id,x.display_name]),required:true},
    {name:'best',label:'Best of X Legs (mindestens 5)',type:'number',value:5,min:5,max:101,required:true}];
  let d=await configure('Schnelles Ladderspiel',fields,'Scorer starten');if(!d)return;
  const n=Number(d.best);if(!Number.isInteger(n)||n<5||n>101)return notice('Best of X muss eine ganze Zahl ab 5 sein.',true);
  const seasonId=season.id;
  const match=await api('/competitions/'+seasonId+'/matches',{player1_id:user.player_id,player2_id:d.opponent,rules:{mode:'legs',max_legs:n,allow_draw:n%2===0}});
  location.assign('/dart/v2/spiel/?match='+encodeURIComponent(match.id)+'&competition='+encodeURIComponent(seasonId));
 }catch(err){notice('Ladderspiel konnte nicht gestartet werden: '+err.message,true)}
}
async function loadSettings(){
 if(previewId){await show('dashboard');return notice('Die Vorschau ist schreibgeschützt.',true)}
 const data=await api('/profile');const form=$('settingsForm');if(data.has_avatar)avatarPlayers.add(String(user.player_id));
 for(const key of ['first_name','last_name','nickname','email','username'])form.elements[key].value=data[key]||'';
 form.elements.old_password.value='';form.elements.new_password.value='';form.elements.avatar.value='';
 const wrap=$('settingsWidgets');clear(wrap);
 for(const [key,label] of Object.entries(widgetLabels)){const l=el('label',undefined,'widget-choice'),i=document.createElement('input');i.type='checkbox';i.value=key;i.name='widgets';i.checked=(data.widgets||defaultDashboardWidgets).includes(key);l.append(i,el('span',label));wrap.append(l)}
 const av=$('settingsAvatar');clear(av);av.append(portrait(user.player_id,true));
 const link=$('profileLinkPanel');link.hidden=!amAdmin();
 if(amAdmin()){
  const list=await api('/players'),select=$('settingsLinkPlayer');clear(select);
  for(const player of list.filter(p=>p.is_active&&p.is_member&&(!p.username||p.id===user.player_id))){select.append(new Option(player.display_name,player.id))}
  select.value=user.player_id;
 }
}
$('dashQuickLadder').onclick=quickLadder;
$('dashSettings').onclick=()=>show('settings');
$('settingsBack').onclick=()=>show('dashboard');
$('settingsLinkAction').onclick=async()=>{
 const target=$('settingsLinkPlayer').value;
 if(!target||target===user.player_id)return notice('Dieses Profil ist bereits verbunden.',true);
 const text='Dieses Konto künftig mit dem gewählten Vereinsprofil verbinden? Alte Testspiele werden nicht automatisch umgeschrieben.';
 if(!await approve('Vereinsprofil ändern',text))return;
 try{await api('/profile/link',{player_id:target});user=await api('/me');await show('dashboard');notice('Vereinsprofil verknüpft. Alte Trainingsdaten bleiben unverändert.')}catch(e){notice(e.message,true)}
};
$('settingsForm').onsubmit=async e=>{
 e.preventDefault();if(previewId)return notice('Die Vorschau ist schreibgeschützt.',true);
 const form=e.target,photo=form.elements.avatar.files?.[0],old=form.elements.old_password.value,newPass=form.elements.new_password.value;
 if(photo&&photo.size>1000000)return notice('Das Profilbild darf höchstens 1 MB groß sein.',true);
 if((!!old)!=(!!newPass))return notice('Zum Passwortwechsel müssen altes und neues Kennwort ausgefüllt sein.',true);
 if(newPass&&newPass.length<12)return notice('Das neue Kennwort benötigt mindestens 12 Zeichen.',true);
 if(!await approve('Persönliche Einstellungen übernehmen','Angaben, Dashboard-Auswahl, Bild und gegebenenfalls Passwort speichern?'))return;
 try{
  const settings={first_name:form.elements.first_name.value,last_name:form.elements.last_name.value,
    nickname:form.elements.nickname.value,email:form.elements.email.value,
    widgets:[...form.querySelectorAll('input[name="widgets"]:checked')].map(x=>x.value)};
  await api('/profile',settings);
  const nextUsername=form.elements.username.value.trim();
  if(nextUsername!==user.username){const result=await api('/profile/username',{username:nextUsername});user.username=result.username;}
  if(photo){const res=await fetch('/dart/v2/api/profile/avatar',{method:'POST',credentials:'same-origin',headers:{'Content-Type':photo.type},body:photo});
   if(!res.ok)throw Error('Profilbild: '+(await res.text()).slice(0,200));avatarPlayers.add(String(user.player_id));}
  if(newPass)await api('/password',{old_password:old,new_password:newPass});
  await show('dashboard');notice('Persönliche Einstellungen gespeichert.');
 }catch(error){notice('Speichern nicht vollständig abgeschlossen: '+error.message,true)}
};
async function editMemberRole(player){
 if(!amAdmin()||!player.account_id)return notice('Dieses Mitglied hat noch kein Konto.',true);
 if(player.account_id===user.id)return notice('Die eigene Adminrolle kann hier nicht geändert werden.',true);
 const options=[['member','Mitglied – eigene Spiele und Training'],['tournament','Turnieraccount – alle Boards'],['admin','Administrator – volle Rechte']];
 const d=await configure('Berechtigung ändern · '+player.display_name,[
   {name:'role',label:'Neue Rolle',type:'select',value:player.role,options}
 ],'Weiter');if(!d||d.role===player.role)return;
 const previous=options.find(x=>x[0]===player.role)?.[1]||player.role;
 const target=options.find(x=>x[0]===d.role)?.[1]||d.role;
 if(!await approve('Rollenwechsel bestätigen',player.display_name+': '+previous+' → '+target+'. Das Konto muss sich anschließend neu anmelden.'))return;
 try{await api('/accounts/'+player.account_id+'/role',{role:d.role});await loadPlayers();
   notice('Rolle von '+player.display_name+' auf '+target+' geändert. Alle Sitzungen dieses Kontos wurden beendet.');}
 catch(e){notice(e.message,true)}
}
async function loadPlayers(){players=await api('/players');setAvatarMetadata(players);renderPlayers();if(!$('statistics').hidden)renderStatisticsProfiles()}
async function newAccountForPlayer(player){
 if(!amAdmin())return notice('Nur Administratoren dürfen Konten vergeben.',true);
 if(player.username)return notice('Dieses Mitglied besitzt bereits ein Konto.',true);
 const username=player.display_name.toLocaleLowerCase('de').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'.').replace(/^\.|\.$/g,'').slice(0,60);
 const d=await configure('Benutzerkonto für '+player.display_name,[
  {name:'username',label:'Benutzername',value:username,required:true},
  {name:'initial_password',label:'Erstpasswort (mindestens 12 Zeichen)',type:'password',required:true},
  {name:'role',label:'Benutzerrolle',type:'select',options:[['member','Mitglied · eigene Spiele und Training'],['tournament','Turnieraccount · alle Boards'],['admin','Administrator · volle Verwaltung']]}],
  'Konto für Mitglied erstellen');
 if(!d)return;
 if(d.initial_password.length<12)return notice('Das Erstpasswort muss mindestens 12 Zeichen enthalten.',true);
 try{await api('/accounts',{player_id:player.id,username:d.username,initial_password:d.initial_password,role:d.role});
  await loadPlayers();notice('Zugang für '+player.display_name+' angelegt. Beim ersten Login muss das Passwort geändert werden.');}
 catch(e){notice(e.message,true)}
}
let memberBand='AF',memberPage=0;
function renderPlayers(){
 const term=$('memberSearch').value.trim().toLocaleLowerCase('de'),all=players.filter(p=>p.display_name.toLocaleLowerCase('de').includes(term));
 const available=letterBands.filter(([key])=>all.some(p=>bandOf(p.display_name)===key));
 if(!available.some(([key])=>key===memberBand))memberBand=available[0]?.[0]||'AF';
 makeTabs($('memberAlphabet'),available.map(([k,label])=>[k,label+' ('+all.filter(p=>bandOf(p.display_name)===k).length+')']),memberBand,key=>{memberBand=key;memberPage=0;renderPlayers()});
 const rows=all.filter(p=>bandOf(p.display_name)===memberBand).sort((a,b)=>a.display_name.localeCompare(b.display_name,'de'));
 const per=window.innerHeight<800?6:window.innerHeight<950?9:12,max=Math.max(1,Math.ceil(rows.length/per));memberPage=Math.min(memberPage,max-1);
 $('memberCount').textContent=all.length+' Profile · '+rows.length+' im Bereich';
 makeTable($('membersList'),['Mitglied','Benutzername','Recht','Zugang','Aktionen'],rows.slice(memberPage*per,(memberPage+1)*per),(p)=>{
  const tr=el('tr'),name=el('td');name.append(participantName(p.id,p.display_name));tr.append(name,el('td',p.username||'–'));
  const role=p.username?(p.role||'member'):'none',caption={admin:'ADMIN',tournament:'TURNIERACCOUNT',member:'MITGLIED',none:'KEIN ZUGANG'}[role]||'UNBEKANNT';
  const right=el('td'),badge=el('span',caption,'member-role-badge role-'+role);right.append(badge);tr.append(right);
  tr.append(el('td',p.username?(p.is_enabled?'Aktiv':'Gesperrt'):'–'));
  const actions=el('td'),box=el('div',undefined,'row-actions');
  if(amAdmin()&&!p.username)box.append(action('Zugang erstellen',()=>newAccountForPlayer(p),'subtle'));
  if(amAdmin()&&p.username){box.append(action('Recht ändern',()=>editMemberRole(p),'subtle'));
    box.append(action(p.is_enabled?'Sperren':'Freigeben',async()=>{
      const desired=!p.is_enabled;
      if(!await approve('Kontozugang ändern',(desired?'Zugang von ':'Zugang für ')+p.display_name+(desired?' wieder aktivieren?':' deaktivieren? Das Mitglied wird auf allen Geräten abgemeldet.')))return;
      try{await api('/accounts/'+p.account_id,{is_enabled:desired});await loadPlayers();notice('Kontostatus geändert.')}catch(e){notice(e.message,true)}
    },'subtle'));
  }
  actions.append(box);tr.append(actions);return tr;
 });
 compactPager($('memberPager'),rows.length,memberPage,p=>{memberPage=p;renderPlayers()},per);
}
// Profile statistics inclusion and non-destructive reset. Admin access is enforced server-side.
async function loadStatSources(){
 const host=$('statSourcesList');if(!host)return;
 clear(host);host.append(el('p','Statistikquellen werden geladen …','helper'));
 try{
  const data=await api('/admin/stat-sources');clear(host);
  const stamp=$('statResetStamp');if(stamp)stamp.textContent=data.reset_at?
     'Letzter Statistik-Neustart: '+new Date(data.reset_at).toLocaleString('de-DE'):
     'Noch kein Statistik-Neustart durchgeführt';
  const groups=[['Formate','Wettbewerbsarten'],['Training','Freie Trainingsformate'],['Wettbewerbe','Einzelne Wettbewerbe']];
  for(const [kind,title] of groups){
   const section=el('div',undefined,'stat-source-group');section.append(el('h3',title));
   const rows=data.sources.filter(x=>x.group===kind);
   for(const item of rows){
    const row=el('div',undefined,'stat-source-row');
    const copy=el('div',undefined,'stat-source-copy');copy.append(el('strong',item.label));
    let extra=item.finished+' bisher abgeschlossene '+(kind==='Training'?'Trainings':'Spiele')+' (historisch)';
    if(item.kind)extra+=' · '+({league:'Liga',cup:'Cup',ladder:'Ladder',vm:'Vereinsmeisterschaft',training_tournament:'Trainingsturnier',final_tournament:'Finalturnier'}[item.kind]||item.kind);
    if(item.deleted)extra+=' · Wettbewerb gelöscht';
    if(item.enabled&&!item.effective_enabled&&!item.deleted)extra+=' · durch Format ausgeschlossen';
    copy.append(el('small',extra));
    const label=el('label',undefined,'stat-source-switch');
    const cb=document.createElement('input');cb.type='checkbox';cb.checked=item.enabled;cb.disabled=!!item.deleted;
    const state=el('span',item.deleted?'Gelöscht':item.effective_enabled?'Zählt mit':'Ausgeblendet','stat-source-status '+(item.effective_enabled?'is-on':'is-off'));
    label.append(cb,state);row.append(copy,label);section.append(row);
    cb.onchange=async()=>{
     cb.disabled=true;try{
      await api('/admin/stat-sources',{key:item.key,enabled:cb.checked});
      await loadStatSources();notice('Statistikquelle '+(cb.checked?'aktiviert':'ausgeschlossen')+'. Bestehende Ergebnisse bleiben unverändert.');
     }catch(e){cb.checked=!cb.checked;cb.disabled=false;notice(e.message,true)}
    };
   }
   host.append(section)
  }
 }catch(e){clear(host);host.append(el('p','Statistikquellen konnten nicht geladen werden: '+e.message,'helper'));}
}
$('statSourcesReload').onclick=()=>loadStatSources();
$('statResetAll').onclick=async()=>{
 if(!amAdmin())return;
 const value=await configure('Profilstatistiken auf Null setzen',[
   {name:'confirm',label:'Alle Profilstatistiken beginnen ab jetzt neu. Spiele, Ergebnisse, ELO und Bestenlisten bleiben erhalten. Zur Bestätigung exakt STATISTIKEN ZURÜCKSETZEN eingeben.',required:true}
 ],'Statistiken zurücksetzen');
 if(!value)return;
 if(value.confirm!=='STATISTIKEN ZURÜCKSETZEN')return notice('Bestätigung stimmt nicht überein. Nichts verändert.',true);
 try{await api('/admin/stats-reset',{confirm:value.confirm});await loadStatSources();notice('Alle Profilstatistiken starten jetzt wieder bei null. Alte Spielresultate bleiben gespeichert.')}catch(e){notice(e.message,true)}
};

$('memberSearch').oninput=()=>{memberPage=0;renderPlayers()};
function fillPlayerSelect(id,blank){const host=$(id);clear(host);if(blank)host.append(new Option('Turnierkonto ohne Spieler',''));for(const p of players)host.append(new Option(p.display_name,p.id))}
const roleLabels={member:'Mitglied',tournament:'Turnieraccount',admin:'Administrator'};
let auditOffset=0;
function formatWhen(value){return value?new Date(value).toLocaleString('de-DE',{dateStyle:'short',timeStyle:'short'}):'Noch keine Aktivität'}
function auditDescription(item){
 const d=item.details||{};
 if(item.action==='login')return 'Anmeldung';
 if(item.action==='logout')return 'Abmeldung';
 if(item.action==='change_role')return 'Rolle: '+(roleLabels[d.old_role]||d.old_role)+' → '+(roleLabels[d.new_role]||d.new_role)+' · '+(d.username||'Konto');
 if(item.action==='change_username')return 'Benutzername: '+(d.old_username||'–')+' → '+(d.new_username||'–');
 if(item.action==='create_account')return 'Benutzerkonto angelegt';
 if(item.action==='soft_delete')return 'Wettbewerb gelöscht / ausgeblendet: '+(d.title||'');
 if(item.action==='link_player_profile')return 'Vereinsprofil verknüpft';
 if(item.action==='api_change'){
  const p=d.path||item.target_id||'';
  if(/\/matches\/[^/]+\/throw$/.test(p))return 'Aufnahme im Scorer gebucht';
  if(/\/matches\/[^/]+\/undo$/.test(p))return 'Aufnahme zurückgenommen';
  if(/\/matches\/[^/]+\/reset$/.test(p))return 'Match zurückgesetzt';
  if(/\/matches\/[^/]+\/start$/.test(p))return 'Match gestartet';
  if(/\/matches\/[^/]+\/manual$/.test(p))return 'Ergebnis manuell erfasst';
  if(/\/competitions\/[^/]+\/matches$/.test(p))return 'Begegnung angelegt';
  if(/\/competitions\/[^/]+\/ladder-conditions$/.test(p))return 'Ladder-Qualifikation konfiguriert';
  if(/\/competitions\/[^/]+\/delete$/.test(p))return 'Wettbewerb ausgeblendet';
  if(/\/accounts\/[^/]+\/role$/.test(p))return 'Benutzerrolle geändert';
  if(p.endsWith('/profile/username'))return 'Benutzername geändert';
  if(p.endsWith('/profile/avatar'))return 'Profilbild geändert';
  if(p.endsWith('/profile'))return 'Profil und Dashboard-Einstellungen bearbeitet';
  if(p.endsWith('/password'))return 'Passwort geändert';
  if(p.endsWith('/accounts'))return 'Benutzerkonto angelegt';
  if(p.endsWith('/players'))return 'Mitglied angelegt';
  if(p.includes('/training/'))return 'Trainingsspiel bearbeitet';
  if(p.includes('/boards/'))return 'Board konfiguriert';
  if(p.includes('/competitions/'))return 'Wettbewerb bearbeitet';
  return 'Änderung: '+p.replace('/dart/v2/api/','');
 }
 return ({bootstrap:'Administrator eingerichtet',create_account:'Benutzerkonto angelegt'}[item.action])||item.action;
}
async function loadOnlineSessions(){
 const host=$('onlineSessions');clear(host);host.append(el('p','Sitzungen werden geladen…','helper'));
 try{const data=await api('/admin/sessions');clear(host);
  const active=data.sessions.filter(s=>s.active_now).length;
  host.append(el('p',active+' gerade aktiv · '+data.sessions.length+' gültige Anmeldungen. Aktiv bedeutet eine Anfrage in den letzten '+data.active_minutes+' Minuten.','helper'));
  if(!data.sessions.length){host.append(el('p','Derzeit keine gültigen Sitzungen.','empty'));return}
  const wrap=el('div',undefined,'admin-table-scroll'),table=el('table',undefined,'data-table polished admin-small-table');
  const hd=el('tr');for(const h of ['Benutzer','Rolle','Status','Letzte Aktivität','Sitzung bis'])hd.append(el('th',h));const thead=el('thead');thead.append(hd);table.append(thead);
  const body=el('tbody');for(const s of data.sessions){const tr=el('tr');
   const vals=[s.username+(s.display_name?' · '+s.display_name:''),roleLabels[s.role]||s.role,s.active_now?'Aktiv':'Angemeldet',formatWhen(s.last_seen_at),formatWhen(s.expires_at)];
   for(let i=0;i<vals.length;i++){const td=el('td',vals[i]);if(i===2)td.className=s.active_now?'session-active':'session-idle';tr.append(td)}body.append(tr)}table.append(body);wrap.append(table);host.append(wrap)
 }catch(e){clear(host);host.append(el('p',e.message,'error'))}
}
async function loadAuditLog(reset=true){
 const host=$('auditLog');if(reset){auditOffset=0;clear(host)}
 try{const data=await api('/admin/audit?limit=75&offset='+auditOffset);
  if(reset&&!data.items.length)host.append(el('p','Noch keine protokollierten Aktionen.','empty'));
  for(const x of data.items){const line=el('article',undefined,'audit-entry');line.append(el('time',formatWhen(x.created_at)),el('strong',x.actor_name),el('span',auditDescription(x)));
    if(x.target_id&&x.action!=='api_change'){line.append(el('small','Objekt: '+x.target_type+' · '+x.target_id))}host.append(line)}
  auditOffset+=data.items.length;$('auditMore').hidden=!data.more;
 }catch(e){host.append(el('p',e.message,'error'));$('auditMore').hidden=true}
}
$('onlineRefresh').onclick=loadOnlineSessions;
$('auditRefresh').onclick=()=>loadAuditLog(true);
$('auditMore').onclick=()=>loadAuditLog(false);
let competitionListTab='running',competitionListPage=0;
async function loadCompetitions(){
 $('createCompetitionWizard').hidden=!amAdmin();
 competitions=await api('/competitions');const host=$('competitionsList');clear(host);
 const detail=$('competitionDetail');detail.hidden=true;
 host.className='competition-directory';host.hidden=false;
 const allowed=competitions.filter(x=>x.kind!=='training_tournament'||amAdmin()||x.created_by===user.id||x.owner===user.id);
 const groups=[['planned','Geplante'],['running','Laufende'],['completed','Abgeschlossene']];
 const bucket=c=>['finished','archived','cancelled'].includes(c.status)?'completed':
   ['draft','planned','scheduled'].includes(c.status)?'planned':'running';
 const tabs=el('div',undefined,'competition-directory-tabs'),info=el('div',undefined,'competition-directory-info'),body=el('div',undefined,'competition-directory-body'),pager=el('div',undefined,'compact-pager');
 host.append(tabs,info,body,pager);
 const labels={draft:'Geplant',planned:'Geplant',scheduled:'Geplant',active:'Laufend',running:'Laufend',finished:'Abgeschlossen',archived:'Archiviert',cancelled:'Abgesagt'};
 function draw(){clear(body);clear(info);clear(pager);for(const b of tabs.children)b.classList.toggle('selected',b.dataset.tab===competitionListTab);
  const rows=allowed.filter(c=>bucket(c)===competitionListTab).sort((a,b)=>{
   const aTime=a.starts_at||a.created_at||'',bTime=b.starts_at||b.created_at||'';
   return competitionListTab==='completed'?bTime.localeCompare(aTime):aTime.localeCompare(bTime);
  });
  info.append(el('p',rows.length+' Wettbewerbe · '+groups.find(x=>x[0]===competitionListTab)[1],'helper'));
  if(!rows.length){body.append(el('p','Keine Wettbewerbe in diesem Bereich.','empty'));return}
  const frame=el('div',undefined,'scroll competition-directory-scroll');const table=el('table',undefined,'data-table polished competition-directory-table');
  const thead=el('thead'),tr=el('tr');for(const title of ['Wettbewerb','Art','Teilnehmer','Beginn','Status',''])tr.append(el('th',title));thead.append(tr);table.append(thead);
  const pageSize=window.innerHeight<800?6:9;competitionListPage=Math.min(competitionListPage,Math.max(0,Math.ceil(rows.length/pageSize)-1));
  const tbody=el('tbody');for(const c of rows.slice(competitionListPage*pageSize,(competitionListPage+1)*pageSize)){const line=el('tr');
   const name=el('td');name.append(action(c.title,()=>openCompetition(c.id),'competition-directory-name'));line.append(name);
   line.append(el('td',kindNames[c.kind]||c.kind),el('td',String(c.players??0)),el('td',c.starts_at?new Date(c.starts_at).toLocaleDateString('de-DE'):'–'));
   const state=el('td');state.append(el('span',labels[c.status]||c.status,'competition-status '+bucket(c)));line.append(state);
   const controls=el('td');controls.append(action('Öffnen',()=>openCompetition(c.id),'subtle'));line.append(controls);tbody.append(line);
  }table.append(tbody);frame.append(table);body.append(frame);compactPager(pager,rows.length,competitionListPage,n=>{competitionListPage=n;draw()},pageSize);
 }
 for(const [key,label] of groups){const b=action(label+' ('+allowed.filter(c=>bucket(c)===key).length+')',()=>{competitionListTab=key;competitionListPage=0;draw()},'subtle');b.dataset.tab=key;tabs.append(b)}
 draw();
}
async function loadLadder(){
 const data=await api('/competitions'),host=$('ladderList');clear(host);
 const now=Date.now();const ladders=data.filter(c=>c.kind==='ladder');
 const active=ladders.filter(c=>c.status==='active'&&(!c.starts_at||new Date(c.starts_at).getTime()<=now)&&(!c.ends_at||new Date(c.ends_at).getTime()>now));
 const current=active[0]||ladders.find(c=>c.status==='active');
 $('ladderCreate').hidden=true;
 if(current){await openCompetition(current.id);return}
 host.append(el('p','Aktuell läuft keine Ladder-Saison.','helper'));
 if(ladders.length)for(const c of ladders)host.append(tile(c.title,c.status+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)));
 if(user.role==='admin'){host.append(action('Neue Ladder-Saison anlegen',()=>{$('ladderCreate').hidden=false;$('ladderCreate').scrollIntoView({block:'start'});},'primary'))}
}
async function createCompetitionWizard(){
 if(!amAdmin())return notice('Nur Administratoren dürfen Vereinswettbewerbe anlegen.',true);
 if(!players.length)players=await api('/players');
 const first=await configure('1 / 3 · Neuen Wettbewerb anlegen',[
  {name:'kind',label:'Wettbewerbsart',type:'select',options:[['league','Stingray League'],['cup','Stingray Cup'],['vm','Vereinsmeisterschaft'],['ladder','Stingray Ladder']]},
  {name:'title',label:'Name des Wettbewerbs',value:'',required:true}], 'Weiter');
 if(!first)return;
 let schedule={},participantIds=[];
 if(first.kind==='ladder'){
   schedule=await configure('2 / 3 · Ladder-Saison',[
    {name:'starts_at',label:'Saisonbeginn',type:'datetime-local',required:true},
    {name:'ends_at',label:'Saisonende',type:'datetime-local',required:true},
    {name:'min_games',label:'Mindestspiele für Finalqualifikation',type:'number',value:5,min:1,max:250,required:true},
    {name:'min_opponents',label:'Unterschiedliche Gegner mindestens',type:'number',value:3,min:1,max:200,required:true},
    {name:'finalists',label:'Anzahl Finalplätze',type:'number',value:8,min:2,max:128,required:true}], 'Weiter');
   if(!schedule)return;
   if(new Date(schedule.ends_at)<=new Date(schedule.starts_at))return notice('Saisonende muss nach dem Beginn liegen.',true);
 }else{
   const roster=await configure('2 / 3 · Teilnehmer auswählen',[
    {name:'members',label:'Vereinsmitglieder für '+first.title,type:'multi',options:players.filter(p=>p.is_active).map(p=>[p.id,p.display_name]),value:[]}], 'Weiter');
   if(!roster)return;participantIds=roster.members;
 }
 const desc=first.kind==='ladder'?`Alle aktiven Vereinsmitglieder werden automatisch angemeldet. Finalplätze: ${schedule.finalists}; mindestens ${schedule.min_games} Spiele gegen ${schedule.min_opponents} Gegner. Rematch nach 7 Tagen.`:
    `${participantIds.length} Spieler werden angemeldet. Gruppen, Spielplan und K.O. werden anschließend über die Wettbewerbsverwaltung konfiguriert.`;
 if(!await approve('3 / 3 · '+first.title+' erstellen',desc))return;
 try{
  const payload={...first};
  if(first.kind==='ladder'){
   payload.starts_at=new Date(schedule.starts_at).toISOString();payload.ends_at=new Date(schedule.ends_at).toISOString();
   payload.rules={min_games:Number(schedule.min_games),min_opponents:Number(schedule.min_opponents),finalists:Number(schedule.finalists)};
  }
  const created=await api('/competitions',payload);
  if(participantIds.length)await api('/competitions/'+created.id+'/entries',{player_ids:participantIds});
  await loadCompetitions();await openCompetition(created.id);notice('Wettbewerb angelegt. Konfiguriere jetzt Phasen und Gruppen im Tab Verwaltung.');
 }catch(e){notice('Erstellen fehlgeschlagen: '+e.message,true)}
}

$('ladderForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);d.kind='ladder';d.starts_at=new Date(d.starts_at).toISOString();d.ends_at=new Date(d.ends_at).toISOString();d.rules={min_games:Number(d.min_games),min_opponents:Number(d.min_opponents),finalists:Number(d.finalists)};delete d.min_games;delete d.min_opponents;delete d.finalists;try{const c=await api('/competitions',d);e.target.reset();await loadLadder();notice('Ladder angelegt – '+c.enrolled_members+' aktive Mitglieder automatisch übernommen. Die Tabelle zeigt Spieler erst nach dem ersten Match.')}catch(err){notice(err.message,true)}};
async function createTraining(){
 if(!players.length){players=await api('/players');setAvatarMetadata(players)}
 const title=await configure('1 / 6 · Trainingsturnier',[{name:'title',label:'Turniername',required:true,value:'Trainingsturnier'},{name:'expected_count',label:'Wie viele Spieler nehmen teil?',type:'number',min:2,max:128,value:6,required:true}],'Weiter');if(!title)return;
 const selection=await configure('2 / 6 · Teilnehmer',[{name:'members',label:'Spieler auswählen',type:'multi',options:players.filter(p=>p.is_active).map(p=>[p.id,p.display_name]),value:[]}],'Weiter');if(!selection)return;
 if(selection.members.length!==Number(title.expected_count))return notice('Bitte genau '+title.expected_count+' Teilnehmer auswählen.',true);
 const stage=await configure('3 / 6 · Vorrunde',[{name:'format',label:'Turniermodus',type:'select',options:[['league','Liga'],...(selection.members.length>=4?[['groups','Gruppen']]:[]),['single_ko','Single KO'],['double_ko','Double KO']]}],'Weiter');if(!stage)return;
 const grouped=stage.format==='groups',rounds=grouped||stage.format==='league',ko=!rounds;
 let settings={};
 if(rounds){const inputs=[];if(grouped)inputs.push({name:'group_count',label:'Anzahl Gruppen (mindestens 2 Personen je Gruppe)',type:'number',min:2,max:Math.floor(selection.members.length/2),value:2,required:true});
 inputs.push({name:'rounds',label:'Begegnungen',type:'select',options:[['single','Hinrunde'],['double','Hin- und Rückrunde']]});
 settings=await configure('4 / 6 · Spielplan',inputs,'Weiter');if(!settings)return;}
 const lengths=await configure('5 / 6 · Spielmodus und Matchlänge',[
  {name:'start_score',label:'Startscore',type:'select',options:[170,301,501,701,1001,5001,10001].map(x=>[String(x),String(x)]),value:'501'},
  {name:'mode',label:'Spielart',type:'select',options:[['legs','Legmodus'],['sets','Setmodus']],value:'legs'},
  {name:'max_legs',label:'Best of X Legs'+(ko?' (ungerade)':''),type:'number',min:1,max:101,value:5,required:true,when:['mode','legs']},
  {name:'best_of_sets',label:'Best of X Sets (ungerade)',type:'number',min:1,max:21,value:3,required:true,when:['mode','sets']},
  {name:'best_of_legs_per_set',label:'Legs pro Set (ungerade)',type:'number',min:1,max:21,value:3,required:true,when:['mode','sets']}
 ],'Weiter');if(!lengths)return;
 const isSets=lengths.mode==='sets';
 const m={start_score:Number(lengths.start_score),mode:lengths.mode,
  ...(isSets?{best_of_sets:Number(lengths.best_of_sets),best_of_legs_per_set:Number(lengths.best_of_legs_per_set)}:
          {max_legs:Number(lengths.max_legs),allow_draw:!ko&&Number(lengths.max_legs)%2===0})};
 if(isSets&&(m.best_of_sets%2!==1||m.best_of_legs_per_set%2!==1)||ko&&!isSets&&m.max_legs%2===0)
  return notice('K.O. benötigt eine ungerade Leganzahl; Sets und Legs pro Set ebenfalls.',true);
 let next={follow:false,consolation:false};
 if(rounds){next=await configure('6 / 6 · Folgerunden',[{name:'follow',label:'Gibt es eine Finalrunde?',type:'select',options:[['no','Nein'],['yes','Ja']]}],'Weiter');if(!next)return;
 if(next.follow==='yes'){
  const q=await configure('Finalrunde',[{name:'qualifiers',label:'Wie viele je Gruppe qualifizieren sich?',type:'select',options:[['1','1'],['2','2'],['4','4'],['8','8'],['all','Alle']]},
   {name:'follow_format',label:'Wie wird weitergespielt?',type:'select',options:[['single_ko','Single KO'],['double_ko','Double KO'],['league','Liga'],['groups','Gruppenrunde']]}],'Weiter');if(!q)return;
  Object.assign(next,q);
  if(grouped && q.qualifiers!=='all'){
   const third=await configure('Beste Gruppennachrücker',[{name:'best_third_count',label:'Zusätzlich beste nächstplatzierte Spieler aus verschiedenen Gruppen',type:'number',min:0,max:Number(settings.group_count||2),value:0,required:true}], 'Weiter');
   if(!third)return;Object.assign(next,third);
  }
  if(q.follow_format==='groups'){const nc=await configure('Gruppenanzahl der Finalrunde',[{name:'follow_group_count',label:'Anzahl Finalgruppen',type:'number',min:1,max:16,value:2,required:true}],'Weiter');if(!nc)return;Object.assign(next,nc)}
  const co=await configure('Trostrunde',[{name:'consolation',label:'Ausgeschiedene in Trostrunde übernehmen?',type:'select',options:[['no','Nein'],['yes','Ja']]}],'Weiter');if(!co)return;
  next.consolation=co.consolation;
  if(co.consolation==='yes'){const cf=await configure('Trostrunde: Modus',[{name:'consolation_format',label:'Wie wird die Trostrunde gespielt?',type:'select',options:[['single_ko','Single KO'],['double_ko','Double KO'],['league','Liga'],['groups','Gruppenrunde']]}],'Weiter');if(!cf)return;Object.assign(next,cf);
   if(cf.consolation_format==='groups'){const nc=await configure('Gruppenanzahl der Trostrunde',[{name:'consolation_group_count',label:'Anzahl Trostgruppen',type:'number',min:1,max:16,value:2,required:true}],'Weiter');if(!nc)return;Object.assign(next,nc)}
  }
 }}
 if(next.follow==='yes' && ['single_ko','double_ko'].includes(next.follow_format)){
  const third=await configure('Spiel um Platz 3',[{name:'third_place',label:'Spiel um Platz 3?',type:'select',options:[['no','Nein'],['yes','Ja']]}],'Weiter');
  if(!third)return;next.third_place=third.third_place;
 }
 const roundLengths={};
 if(m.mode==='legs'){
  // The initial group/league length was already entered above; ask only
  // for additional knockout rounds that can actually occur.
  const lengthFields=[];
  if(ko||next.follow==='yes'){
   if(!ko||selection.members.length>4)lengthFields.push({name:'quarterfinal',label:'Viertelfinale · Best of Legs (ungerade)',type:'number',value:5,min:1,max:101,step:2,required:true});
   if(!ko||selection.members.length>2)lengthFields.push({name:'semifinal',label:'Halbfinale · Best of Legs (ungerade)',type:'number',value:7,min:1,max:101,step:2,required:true});
   if(next.third_place==='yes'&&(!ko||selection.members.length>2))lengthFields.push({name:'third_place',label:'Spiel um Platz 3 · Best of Legs (ungerade)',type:'number',value:5,min:1,max:101,step:2,required:true});
   lengthFields.push({name:'final',label:'Finale · Best of Legs (ungerade)',type:'number',value:9,min:1,max:101,step:2,required:true});
  }
  if(lengthFields.length){
   const choices=await configure('Matchlängen der weiteren K.O.-Runden',lengthFields,'Weiter');if(!choices)return;
   for(const [key,value] of Object.entries(choices)){
    const n=Number(value);if(!Number.isInteger(n)||n<1||n>101||n%2===0)return notice('K.O.-Matchlängen müssen ungerade sein.',true);
    roundLengths[key]=n;
   }
  }
 }
 if(!await approve('Turnier anlegen',selection.members.length+' Spieler · '+stage.format+' · '+m.start_score+' Punkte · '+(isSets?'Best of '+m.best_of_sets+' Sets / '+m.best_of_legs_per_set+' Legs':'Best of '+m.max_legs+' Legs')+' · Spielplan wird automatisch erzeugt.'))return;
 try{
  const payload={title:title.title,player_ids:selection.members,format:stage.format,group_count:Number(settings.group_count||1),double_round:settings.rounds==='double',rules:m,
   round_lengths:roundLengths,third_place:next.third_place==='yes',follow:next.follow==='yes',consolation:next.consolation==='yes',qualifiers:next.qualifiers||'1',best_third_count:Number(next.best_third_count||0),follow_format:next.follow_format||'single_ko',consolation_format:next.consolation_format||'single_ko',follow_group_count:Number(next.follow_group_count||1),consolation_group_count:Number(next.consolation_group_count||1)};
  const c=await api('/training/tournament/setup',payload);await show('training');await openCompetition(c.id);notice('Turnier mit '+c.created+' Begegnungen erstellt.');
 }catch(e){notice('Turnieranlage: '+e.message,true)}
}
$('newTraining').onclick=createTraining;
$('dashTraining').onclick=()=>show('training');
$('createCompetitionWizard').onclick=createCompetitionWizard;
$('createCompetitionAdmin').onclick=createCompetitionWizard;
async function quickTraining(){
 try{
  if(!players.length)players=await api('/players');
  const own=user.player_id,opts=players.filter(p=>p.is_active && p.id!==own);
  const d=await configure('X01-Trainingsmatch',[
      {name:'other',label:'Gegner',type:'select',options:opts.map(p=>[p.id,p.display_name]),required:true},
      {name:'mode',label:'Spielmodus',type:'select',options:[['legs','Legmodus'],['sets','Setmodus']],value:'legs'},
      {name:'best',label:'Best of X Legs',type:'number',value:5,min:1,max:101,required:true,when:['mode','legs']},
      {name:'sets',label:'Best of X Sets (ungerade)',type:'number',value:3,min:1,max:21,required:true,when:['mode','sets']},
      {name:'per',label:'Legs pro Set (ungerade)',type:'number',value:3,min:1,max:21,required:true,when:['mode','sets']}], 'Training starten');
  if(!d)return;if(!own)return notice('Deinem Konto ist kein Spielerprofil zugeordnet.',true);
  const best=Number(d.mode==='sets'?d.sets:d.best),per=Number(d.per||3);
  if(d.mode==='sets'&&(best%2!==1||per%2!==1))return notice('Setmodus benötigt ungerade Werte.',true);
  if(!Number.isInteger(best)||best<1||best>101)return notice('Ungültige Matchlänge.',true);
  const rules={start_score:501,mode:d.mode,...(d.mode==='sets'?
    {best_of_sets:best,best_of_legs_per_set:per}:
    {max_legs:best,allow_draw:best%2===0})};
  const m=await api('/free-x01',{other_id:d.other,rules});
  location.assign('/dart/v2/spiel/?free=1&match='+encodeURIComponent(m.id));
 }catch(err){notice(err.message,true)}
}
// Same V2 account, results saved to Neon after finishing each solo discipline.
async function startSolo(kind){
 if(!players.length)players=await api('/players');
 let team=[],minRounds=10;
 if(kind==='sau'){
   const own=user?.player_id;
   const active=players.filter(p=>p.is_active&&p.is_member);
   const config=await configure('Gegen die Sau – Spieler oder Team',[
     {name:'members',label:'Mitspieler (mindestens einen auswählen)',type:'multi',options:active.map(p=>[p.id,p.display_name]),value:own?[own]:[]},
     {name:'rounds',label:'Mindestzahl Durchgänge',type:'number',value:10,min:1,max:10000,required:true}
   ],'Training starten');
   if(!config)return;
   minRounds=Number(config.rounds);
   if(!Number.isInteger(minRounds)||minRounds<1||minRounds>10000)return notice('Ungültige Rundenzahl',true);
   team=(config.members||[]).filter(id=>active.some(p=>p.id===id));
   if(!team.length)return notice('Mindestens ein Mitglied auswählen',true);
 }
 const box=$('trainingMode');box.hidden=false;clear(box);const back=action('← Training',()=>window.location.assign('/dart/v2/'));back.className='training-back';box.append(back);let visits=[],marks={sau:0},round=1,rest=201,points=kind==='bobs'?27:201,finished=false;
 for(let i=4;i<=12;i++)marks[i]=0;
 const isBobs=kind==='bobs',target=10;
 box.append(el('h2',isBobs?'Bobs 27':'Gegen die Sau'));
 const teamNames=team.map(id=>players.find(p=>p.id===id)?.display_name||'Spieler');
 if(teamNames.length)box.append(el('div','Team: '+teamNames.join(' · '),'solo-team')); 
 const stat=el('div',undefined,'solo-score'),info=el('p',undefined,'helper'),history=el('div');box.append(stat,info);
 const form=el('form',undefined,'solo-form'),control=document.createElement('input');control.type='number';control.required=true;control.min='0';control.max=isBobs?'3':'180';
 const l=el('label',isBobs?'Treffer auf Doppel':'Score (0–180)');l.append(control);form.append(l);
 const checkout=document.createElement('input');checkout.type='checkbox';checkout.id='soloCheckout';
 const ckLabel=el('label','Checkout (bei Gegen die Sau)');ckLabel.append(checkout);if(!isBobs)form.append(ckLabel);
 const numDarts=document.createElement('select');for(let n=1;n<=3;n++)numDarts.append(new Option(n+' Darts',String(n)));numDarts.value='3';
 if(!isBobs){const label=el('label','Checkout mit');label.append(numDarts);form.append(label)}
 const button=document.createElement('button');button.type='submit';button.textContent='Aufnahme eintragen';form.append(button);box.append(form,history);
 function draw(){
   stat.textContent=isBobs?'Punktestand: '+points:'Rest: '+rest+' · Runde '+round;
   info.textContent=isBobs?'Doppel '+(round===21?'Bull':round)+' · Start bei 27 Punkten':
     'Sau-Striche: '+marks.sau+'/'+target+' · Checkouts: '+Object.entries(marks).filter(([k])=>k!=='sau').reduce((n,[k,v])=>n+v,0)+' · 4 Aufnahmen je Runde, 201 Rest';
   clear(history);for(const v of visits.slice(-12).reverse())history.append(el('p',v));
 }
 async function finish(){finished=true;button.disabled=true;form.hidden=true;const result=isBobs?{points,rounds:round-1}:{sau:marks.sau,checkouts:Object.entries(marks).filter(([k])=>k!=='sau').reduce((a,[,v])=>a+v,0),marks,rounds:round-1,team_ids:team,team_names:teamNames};
   try{await api('/training/sessions',{kind:isBobs?'bobs27':'sau',result});info.textContent+=' · Ergebnis in Neon gespeichert'}catch(e){info.textContent+=' · Speicherung fehlgeschlagen: '+e.message;box.append(action('Erneut speichern',async()=>{await api('/training/sessions',{kind:isBobs?'bobs27':'sau',result});notice('Ergebnis gespeichert')}))}}
 const scoringKeys=el('div',undefined,'solo-pad');
 const undoButton=action('Letzte Aufnahme rückgängig',()=>{});
 const undoStack=[];
 function saveSnapshot(){undoStack.push({visits:[...visits],marks:{...marks},round,rest,points,formDarts:form.dataset.darts,formTurn:form.dataset.turn});undoButton.disabled=false}
 undoButton.onclick=()=>{if(finished||!undoStack.length)return;const old=undoStack.pop();visits=old.visits;marks=old.marks;round=old.round;rest=old.rest;points=old.points;form.dataset.darts=old.formDarts||'0';form.dataset.turn=old.formTurn||'0';draw();undoButton.disabled=!undoStack.length};
 undoButton.disabled=true;
 if(isBobs){form.hidden=true;
   for(let n=0;n<=3;n++)scoringKeys.append(action(n+' Treffer',()=>{control.value=String(n);form.onsubmit({preventDefault(){}})}));
 }else{
   const entry=el('div','–','solo-entry');scoringKeys.append(entry);
   let digits='';
   for(const key of ['1','2','3','4','5','6','7','8','9','⌫','0','C'])scoringKeys.append(action(key,()=>{digits=key==='C'?'':key==='⌫'?digits.slice(0,-1):(digits+key).slice(0,3);entry.textContent=digits||'–';control.value=digits}));
   const quick=el('div',undefined,'solo-quick');
   for(const n of [26,41,45,57,60,81,85,95,100,133,140,180])quick.append(action(String(n),()=>{digits=String(n);entry.textContent=digits;control.value=digits}));
   const book=action('Aufnahme buchen',()=>{if(!digits)return;checkout.checked=false;form.onsubmit({preventDefault(){}});digits='';entry.textContent='–'});
   const check=action('CHECK',()=>{if(rest>170||rest<2)return notice('Kein gültiger Checkout möglich',true);
      const choices=Array.from({length:3},(_,i)=>i+1).filter(d=>rest<=50*d&&!(rest===169||rest===168||rest===166||rest===165||rest===163||rest===162||rest===159));
      configure('Checkout · '+rest+' Rest',[{name:'darts',label:'Darts bis Checkout',type:'select',options:choices.map(d=>[String(d),d+' Dart'+(d>1?'s':'')]),required:true}], 'Checkout buchen').then(d=>{if(!d)return;checkout.checked=true;numDarts.value=d.darts;control.value=String(rest);form.onsubmit({preventDefault(){}});digits='';entry.textContent='–'})
   },'primary');
   scoringKeys.append(book,check,quick);
   form.hidden=true;
 }
 box.append(scoringKeys,undoButton);
 form.onsubmit=async e=>{e.preventDefault();if(finished)return;let n=Number(control.value);if(!Number.isInteger(n))return;
   if(isBobs){if(n<0||n>3)return;saveSnapshot();const d=round===21?25:round;points+=n?2*n*d:-d;visits.push('D'+(round===21?'Bull':round)+': '+n+' Treffer');round++;if(points<0||round>21)await finish()}
   else {if(n<0||n>180)return;const darts=checkout.checked?Number(numDarts.value):3;
     const totalDarts=(form.dataset.darts?Number(form.dataset.darts):0)+darts;
     if(checkout.checked&&(n!==rest||totalDarts<4||totalDarts>12)){notice('Checkout nur bei passender Restzahl mit 4–12 Darts',true);return}
     saveSnapshot();const bust=!checkout.checked&&(n>=rest||rest-n===1);if(bust)n=0;
     rest-=n;visits.push('Runde '+round+': '+n+' Punkte'+(checkout.checked?' · Checkout':''));
     const turn=Number(form.dataset.turn||0)+1;form.dataset.turn=String(turn);form.dataset.darts=String(totalDarts);
     if(checkout.checked){marks[totalDarts]++;form.dataset.turn='0';form.dataset.darts='0';round++;rest=201}
     else if(turn>=4){marks.sau++;form.dataset.turn='0';form.dataset.darts='0';round++;rest=201}
     if(round>minRounds&&marks.sau>=target)await finish();
   }
   control.value='';checkout.checked=false;draw();
 };
 draw();
}
$('sauTraining').onclick=()=>launchTrainingWindow('sau');$('bobsTraining').onclick=()=>launchTrainingWindow('bobs');

// Tauziehen: same 181 -> 0 / 362 rules and per-round winner logic as the legacy scorer.
async function startTug(){
 if(!players.length)players=await api('/players');
 const own=user?.player_id;if(!own)return notice('Deinem Konto muss ein Spielerprofil zugeordnet sein.',true);
 const d=await configure('Tauziehen',[{name:'opponent',label:'Gegner',type:'select',options:players.filter(p=>p.is_active&&p.id!==own).map(p=>[p.id,p.display_name]),required:true},
  {name:'rounds',label:'Rundenzahl',type:'number',value:5,min:1,max:100,required:true}],'Tauziehen starten');
 if(!d)return;const opponent=players.find(p=>p.id===d.opponent);if(!opponent)return;
 const max=Number(d.rounds);if(!Number.isInteger(max)||max<1||max>100)return notice('Rundenzahl ungültig',true);
 const names=[players.find(p=>p.id===own)?.display_name||user.username,opponent.display_name];
 const box=$('trainingMode');box.hidden=false;clear(box);const back=action('← Training',()=>window.location.assign('/dart/v2/'));back.className='training-back';box.append(back);
 const title=el('h2','TAUZIEHEN');const playersPanel=el('div',undefined,'tug-player-grid');
 const score=el('strong',undefined,'tug-position'),turn=el('p',undefined,'helper'),wins=el('p',undefined,'helper'),history=el('div',undefined,'tug-history');
 const form=el('form',undefined,'tug-entry'),inp=document.createElement('input');inp.type='number';inp.required=true;inp.min=0;inp.max=180;inp.placeholder='Score (0–180)';
 const book=document.createElement('button');book.type='submit';book.textContent='Aufnahme buchen';book.className='primary';
 form.append(inp,book);const quick=el('div',undefined,'tug-quick');
 box.append(title,playersPanel,score,turn,wins,form,quick,history);
 let position=181,current=0,round=1,victories=[0,0],visits=[],finished=false;
 const snapshot=()=>({position,current,round,wins:[...victories],visits:[...visits]});
 const rewind=el('button','Letzte Aufnahme zurücknehmen');rewind.type='button';box.append(rewind);
 function display(){score.textContent='Gemeinsamer Score '+position;
  turn.textContent=names[current]+' wirft · Runde '+round+' / '+max;
  wins.textContent=names[0]+' '+victories[0]+' : '+victories[1]+' '+names[1];
  clear(playersPanel);for(let i=0;i<2;i++){const card=el('div',undefined,'tug-player '+(current===i?'active':''));card.append(el('h3',names[i]),el('b',i===0?String(position):String(362-position)));playersPanel.append(card)}
  clear(history);for(const v of visits.slice(-8).reverse())history.append(el('p',names[v.player]+': '+v.points+' ('+v.before+' → '+v.after+')'));
  rewind.disabled=finished||!visits.length;book.disabled=finished;
 }
 const historyStates=[];
 async function submit(points){if(finished||!Number.isInteger(points)||points<0||points>180)return;
  historyStates.push(snapshot());const before=position;const raw=position+(current===0?-points:points);
  position=Math.max(0,Math.min(362,raw));visits.push({round,player:current,points,before,after:position});
  if(raw<=0||raw>=362){victories[raw<=0?0:1]++;if(round>=max){finished=true}
   else{round++;position=181;current=0}}
  else current=1-current;
  display();inp.value='';
  if(finished){form.hidden=true;quick.hidden=true;
   const result={names,rounds:max,wins:victories,visits};
   try{await api('/training/tug',{opponent_id:d.opponent,result});box.append(el('p','Tauziehen abgeschlossen und im Spielerprofil gespeichert.'))}
   catch(e){notice('Tauziehen abgeschlossen, aber Speichern fehlgeschlagen: '+e.message,true);box.append(action('Speichern erneut versuchen',async()=>{await api('/training/tug',{opponent_id:d.opponent,result});notice('Gespeichert')}))}
  }
 }
 form.onsubmit=e=>{e.preventDefault();submit(Number(inp.value))};
 for(const n of [0,26,41,45,57,60,81,85,95,100,133,140,180])quick.append(action(String(n),()=>submit(n)));
 rewind.onclick=()=>{if(!historyStates.length||finished)return;const prev=historyStates.pop();position=prev.position;round=prev.round;current=prev.current;victories=prev.wins;visits=prev.visits;display()};
 display();
}
$('tugTraining').onclick=()=>launchTrainingWindow('tug');
$('quickTraining').onclick=()=>launchTrainingWindow('x01');


// V2 mini games: use profiles and the existing session login; X01 stats remain untouched.
async function startMiniTraining(kind){
 try{
  if(!window.StingrayMiniGames)throw Error('Trainingsmodul konnte nicht geladen werden');
  if(!user?.player_id)throw Error('Bitte zuerst ein Spielerprofil mit deinem Konto verknüpfen');
  if(!players.length){players=await api('/players');setAvatarMetadata(players)}
  const me=players.find(p=>String(p.id)===String(user.player_id));
  if(!me)throw Error('Eigenes Spielerprofil nicht gefunden');
  const others=players.filter(p=>p.id!==user.player_id&&p.is_member!==false&&p.is_active!==false);
  if(kind!=='minigolf'&&!others.length)throw Error('Kein Gegnerprofil verfügbar');
  const fields=[];
  if(kind==='minigolf')fields.push({name:'returnMode',label:'Phase 2 – Rückweg (optional)',type:'select',value:'none',options:[['none','Ohne Rückweg – nur Phase 1'],['final','Endscore checken'],['all','Alle Zwischenscores checken (rückwärts)']]});
  if(kind==='tictactoe')fields.push({name:'variant',label:'Spielvariante',type:'select',value:'doubles',options:[['doubles','Variante A – 9 zufällige Doppel'],['checks','Variante B – 9 unterschiedliche Checks']]});
  if(kind==='tictactoe'||kind==='connect4'){
   fields.push({name:'low',label:'Checkbereich von (für Doppelvariante ignoriert)',type:'number',value:kind==='connect4'?58:40,min:2,max:170,required:true});
   fields.push({name:'high',label:'Checkbereich bis (für Doppelvariante ignoriert)',type:'number',value:kind==='connect4'?100:80,min:2,max:170,required:true});
  }
  fields.push({name:'opponent',label:'Gegner',type:'select',options:kind==='minigolf'?[['','Alleine'],...others.map(p=>[p.id,p.display_name])]:others.map(p=>[p.id,p.display_name])});
  fields.push({name:'first',label:'Wer beginnt?',type:'select',value:'me',options:[['me','Ich'],['opponent','Gegner (falls vorhanden)'],['random','Zufall']]});
  const choice=await configure(window.StingrayMiniGames.games[kind],fields,'Spiel starten');if(!choice)return;
  const opp=others.find(p=>p.id===choice.opponent);
  if(kind!=='minigolf'&&!opp)throw Error('Bitte Gegner auswählen');
  const ids=[me.id,...(opp?[opp.id]:[])],names=[me.display_name,...(opp?[opp.display_name]:[])];
  if(opp&&(choice.first==='opponent'||(choice.first==='random'&&Math.random()<0.5))){ids.reverse();names.reverse()}
  const settings={};
  if(kind==='minigolf'){settings.returnMode=choice.returnMode;settings.format='doubles21'}
  if(kind==='tictactoe')settings.variant=choice.variant;
  if(kind==='connect4'||kind==='tictactoe'&&choice.variant==='checks'){
   settings.low=Number(choice.low);settings.high=Number(choice.high);
   window.StingrayMiniGames.engine.validRange(settings.low,settings.high,kind==='connect4'?42:9,kind);
  }
  const host=$('trainingMode');host.hidden=false;
  clear(host);
  const back=action('← Zurück zum Training',()=>location.assign('/dart/v2/?view=training'),'subtle');back.className='training-back';host.append(back);
  const board=el('section');host.append(board);
  await window.StingrayMiniGames.mount({host:board,kind,settings,ids,names,save:data=>api('/training/minigames',{kind,players:ids,result:data}),loadScores:mode=>api('/training/highscores?kind='+encodeURIComponent(mode))});
  // The back link belongs outside the game renderer and survives re-renders.
 }catch(e){notice(e.message,true)}
}
for(const kind of ['football','minigolf','tictactoe','connect4']){
 const target=$(kind+'Training');if(target)target.onclick=()=>launchTrainingWindow(kind);
}

async function loadTraining(){
 const host=$('trainingList');clear(host);const data=await api('/competitions');
 for(const c of data.filter(x=>x.kind==='training_tournament'&&(amAdmin()||x.created_by===user.id)))host.append(tile(c.title,c.players+' Teilnehmer · '+c.status,()=>openCompetition(c.id)));
 if(!host.children.length)host.append(el('p','Du hast noch kein Trainingsturnier erstellt.'));
}

$('previewOpen').onclick=async()=>{if(user?.role!=='admin')return;previewId=$('previewPlayer').value;await show('dashboard')};
$('previewExit').onclick=async()=>{previewId=null;await show('dashboard')};$('previewBack').onclick=$('previewExit').onclick;
let boardBand=0;
async function loadBoards(){const boards=await api('/boards'),host=$('boardsList');
 const groups=[boards.slice(0,11),boards.slice(11,22)];if(boardBand>=groups.length)boardBand=0;
 makeTabs($('boardTabs'),groups.map((g,i)=>[String(i),i===0?'Board 1–11':'Board 12–22']),String(boardBand),v=>{boardBand=Number(v);draw()});
 function draw(){clear(host);makeTabs($('boardTabs'),groups.map((g,i)=>[String(i),i===0?'Board 1–11':'Board 12–22']),String(boardBand),v=>{boardBand=Number(v);draw()});
 for(const b of groups[boardBand]){const t=el('article',undefined,'board '+(!b.enabled?'inactive':b.match_id?'busy':''));t.append(el('strong',b.label),el('p',!b.enabled?'Deaktiviert':b.match_id?'Belegt: '+b.competition:'Frei'));
 if(b.match_id&&user.role!=='member')t.append(action('Scorer öffnen',()=>openScorer(b.match_id),'primary'));
 if(amAdmin())t.append(action('Bearbeiten',async()=>{const d=await configure('Board '+b.id,[{name:'label',label:'Bezeichnung',value:b.label,required:true},{name:'enabled',type:'select',label:'Status',value:String(b.enabled),options:[['true','Aktiv'],['false','Deaktiviert']]}]);if(!d)return;try{await api('/boards/'+b.id,{label:d.label,enabled:d.enabled==='true'});await loadBoards()}catch(e){notice(e.message,true)}}));host.append(t)}
 }draw();
}
const table=(headers,rows)=>{const outer=el('div',undefined,'scroll'),tab=el('table',undefined,'data-table'),head=el('thead'),tr=el('tr');for(const h of headers)tr.append(el('th',h));head.append(tr);tab.append(head);const tb=el('tbody');for(const row of rows){const line=el('tr');for(const val of row)line.append(el('td',String(val??'–')));tb.append(line)}tab.append(tb);outer.append(tab);return outer};
const kindNames={league:'Stingray League',cup:'Stingray Cup',ladder:'Stingray Ladder',vm:'Vereinsmeisterschaft',training_tournament:'Trainingsturnier',final_tournament:'Finalrunde'};
let competitionTab='table',schedulePage=0;
function action(text,fn,style=''){const b=btn(text,fn);if(style)b.className=style;return b}
function picker(items,selectedValue,callback){const select=el('select');for(const [v,t] of items)select.append(new Option(t,v));select.value=selectedValue;select.onchange=()=>callback(select.value);return select}
function labelFor(m,names){return (names.get(m.player1_id)||'Offen')+' – '+(names.get(m.player2_id)||'Offen')}
const groupSelections=new Map();
async function openCompetition(id){
  selected=await api('/competitions/'+id);if(!players.length||amAdmin()||trainingOwner()){players=await api('/players');setAvatarMetadata(players)}section('competitions');$('competitionsList').hidden=true;
  const c=selected.competition,host=$('competitionDetail');host.hidden=false;clear(host);
  host.className='competition-view';
  const header=el('div',undefined,'competition-header');
  const h=el('div');h.append(el('span',kindNames[c.kind]||c.kind,'eyebrow'),el('h2',c.title));
  const summary=el('div',undefined,'competition-chips');
  const played=selected.matches.filter(m=>m.status==='finished').length;
  for(const x of [selected.entries.length+' Teilnehmer',played+' / '+selected.matches.length+' gespielt',c.status])summary.append(el('span',x,'chip'));
  if(c.kind==='ladder'&&c.rules?.final_competition_id){h.append(action('Finalturnier öffnen',()=>openCompetition(c.rules.final_competition_id),'primary'));}
  h.append(summary);header.append(h,action('← Alle Wettbewerbe',()=>{$('competitionDetail').hidden=true;loadCompetitions()},'subtle'));host.append(header);
  const tabs=el('div',undefined,'competition-tabs');
  const content=el('div',undefined,'competition-content');
  host.append(tabs,content);
  async function view(tab){competitionTab=tab;clear(content);for(const b of tabs.children)b.classList.toggle('selected',b.dataset.tab===tab);
    try{if(tab==='table')await showTables(content);if(tab==='schedule')showSchedule(content);if(tab==='participants')showParticipants(content);if(tab==='records')showRecords(content);if(tab==='rules')showLadderRules(content);if(tab==='management')showManagement(content);if(tab==='placements')await showPlacements(content);if(tab==='bracket')showBracket(content)}
    catch(e){content.append(el('p',e.message,'error'))}
  }
  const hasTable=c.kind==='ladder'||(selected.phases||[]).some(p=>p.kind==='groups'||p.kind==='league');
  for(const [tab,name] of [...(hasTable?[['table',c.kind==='ladder'?'ELO-Rangliste':'Tabellen']]:[]),['schedule','Spielplan'],['participants','Teilnehmer'],['records','Bestleistungen & Statistik'],...(c.kind==='ladder'?[['rules','Regelwerk']]:[]),...((selected.phases||[]).some(p=>p.kind==='knockout')||(c.rules?.follow&&['single_ko','double_ko'].includes(c.rules?.follow_format))?[['bracket','Turnierbaum']]:[]),...(['finished','archived'].includes(c.status)&&c.kind!=='ladder'?[['placements','Platzierungen']]:[]),...((amAdmin()||trainingOwner())?[['management','Verwaltung']]:[])]){
    const b=action(name,()=>view(tab));b.dataset.tab=tab;tabs.append(b);
  }
  const names=new Map(selected.entries.map(e=>[e.player_id,e.display_name]));
  function showBracket(box){
    const phases=(selected.phases||[]).filter(p=>p.kind==='knockout');
    const pending=c.rules?.follow&&['single_ko','double_ko'].includes(c.rules?.follow_format);
    if(!phases.length){box.append(el('p',pending?'Der KO-Baum wird nach der Vorrunde erzeugt.':'Noch keine K.O.-Runde vorhanden.','helper'));return}
    const namesMap=new Map(selected.entries.map(e=>[String(e.player_id),e.display_name]));
    const selector=el('div',undefined,'bracket-stage-tabs competition-group-tabs');box.append(selector);
    const stage=el('div',undefined,'bracket-content');box.append(stage);
    const scoreOf=m=>(Number(m.sets1||0)||Number(m.sets2||0))?[m.sets1,m.sets2]:[m.legs1,m.legs2];
    const won=m=>{if(m.status!=='finished')return null;const [x,y]=scoreOf(m).map(Number);return x===y?null:String(x>y?m.player1_id:m.player2_id)};
    const other=(m,p)=>String(m.player1_id)===p?String(m.player2_id):String(m.player1_id);
    function draw(phase){
      clear(stage);
      let rules={};try{rules=typeof phase.rules==='string'?JSON.parse(phase.rules||'{}'):(phase.rules||{})}catch{}
      const matches=selected.matches.filter(m=>String(m.phase_id)===String(phase.id)).sort((a,b)=>Number(a.round_number||1)-Number(b.round_number||1)||Number(a.bracket_position||0)-Number(b.bracket_position||0));
      if(!matches.length){stage.append(el('p','Noch keine KO-Begegnungen.','helper'));return}
      const isDouble=rules.format==='double_ko';
      const loss=new Map();const groups={winner:[],loser:[],crossover:[],final:[]};
      // Die bestehende DB speichert keinen Bracket-Typ. Die Einordnung basiert auf
      // den Niederlagen VOR jeder Begegnung, nicht auf ihrem Endergebnis.
      const perRound=new Map();for(const m of matches){const r=Number(m.round_number||1);if(!perRound.has(r))perRound.set(r,[]);perRound.get(r).push(m)}
      for(const [round,ms] of [...perRound].sort((a,b)=>a[0]-b[0])){
        for(const m of ms){const l1=loss.get(String(m.player1_id))||0,l2=loss.get(String(m.player2_id))||0;
          const tagged=(typeof m.rules==='string'?(()=>{try{return JSON.parse(m.rules||'{}')}catch{return {}}})():m.rules||{}).bracket;
          m._bracketGroup=!isDouble?'winner':tagged==='grand_final'||tagged==='grand_final_reset'?'crossover':tagged==='winner'||tagged==='loser'?tagged:l1===0&&l2===0?'winner':l1===1&&l2===1?'loser':'crossover';
          groups[m._bracketGroup].push(m);
        }
        for(const m of ms){const w=won(m);if(w){const loser=other(m,w);loss.set(loser,(loss.get(loser)||0)+1)}}
      }
      const hasCross=groups.crossover.length>0;
      if(isDouble){const message=el('p','Doppel-KO: Die Partien werden getrennt nach Winner-Bracket und Loser-Bracket dargestellt. Im Grand Final trifft der Sieger des Winner-Brackets auf den Sieger des Loser-Brackets. Gewinnt zunächst der Loser-Bracket-Sieger, folgt ein Reset-Finale.','bracket-explanation');stage.append(message)}
      function renderSection(list,title,kind){if(!list.length)return;
        const head=el('h3',title,'bracket-section-title');stage.append(head);
        const scroll=el('div',undefined,'bracket-scroll');const canvas=el('div',undefined,'sting-bracket-canvas');const wires=document.createElementNS('http://www.w3.org/2000/svg','svg');wires.setAttribute('class','sting-bracket-wires');wires.setAttribute('aria-hidden','true');canvas.append(wires);
        const rounds=[...new Set(list.map(m=>Number(m.round_number||1)))].sort((a,b)=>a-b);
        const grouped=rounds.map(r=>list.filter(m=>Number(m.round_number||1)===r).sort((a,b)=>Number(a.bracket_position||0)-Number(b.bracket_position||0)));
        const maxMatches=Math.max(...grouped.map(v=>v.length));const unit=94;const height=Math.max(160,maxMatches*unit+40);
        canvas.style.height=height+'px';canvas.style.width=(rounds.length*258+24)+'px';const nodeMap=new Map();
        grouped.forEach((ms,colIndex)=>{
          const col=el('div',undefined,'sting-bracket-column');col.style.left=(colIndex*258+12)+'px';col.style.height=height+'px';
          const label=(!isDouble&&ms.length===1?'Finale':!isDouble&&ms.length===2?'Halbfinale':!isDouble&&ms.length===4?'Viertelfinale':!isDouble&&ms.length===8?'Achtelfinale':'Runde '+rounds[colIndex]);
          col.append(el('h4',label,'sting-bracket-round-title'));
          ms.forEach((m,index)=>{
            const top=50+(index+.5)*((height-90)/ms.length)-35;
            const card=el('button',undefined,'sting-bracket-card '+(m.status==='finished'?'completed':m.status==='running'?'live':'open'));card.type='button';card.style.top=top+'px';card.title='Begegnung öffnen';card.onclick=()=>openScorer(m.id);card.setAttribute('aria-label','Begegnung '+(namesMap.get(String(m.player1_id))||'Offen')+' gegen '+(namesMap.get(String(m.player2_id))||'Offen'));
            const [v1,v2]=scoreOf(m);const winner=won(m);
            [[m.player1_id,v1],[m.player2_id,v2]].forEach(([pid,value])=>{const row=el('div',undefined,'sting-bracket-player'+(winner===String(pid)?' winner':''));row.append(el('span',namesMap.get(String(pid))||'Noch offen'),el('strong',m.status==='finished'?String(value??0):'–'));card.append(row)});
            const meta=el('div',undefined,'sting-bracket-meta');meta.append(el('span',m.status==='finished'?'Beendet':m.status==='running'?'Live':'Offen'),el('span','Spiel öffnen ›'));card.append(meta);col.append(card);nodeMap.set(String(m.id),{card,m,colIndex});
          });canvas.append(col)
        });
        function lines(){const existing=wires.querySelectorAll('path');existing.forEach(x=>x.remove());
          const width=rounds.length*258+24;wires.setAttribute('viewBox',`0 0 ${width} ${height}`);wires.setAttribute('width',String(width));wires.setAttribute('height',String(height));
          // Nur reale, aus den Datensätzen belegbare Spielerpfade verbinden.
          for(const {card,m,colIndex} of nodeMap.values()){
            const w=won(m);if(!w)continue;
            const next=[...nodeMap.values()].filter(n=>n.colIndex>colIndex&&[String(n.m.player1_id),String(n.m.player2_id)].includes(w)).sort((a,b)=>a.colIndex-b.colIndex)[0];
            if(!next)continue;const x1=12+colIndex*258+226,y1=card.offsetTop+35,x2=12+next.colIndex*258,y2=next.card.offsetTop+35,mid=x1+(x2-x1)/2;
            const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',`M${x1},${y1} H${mid} V${y2} H${x2}`);path.setAttribute('class','sting-bracket-path');wires.append(path)
          }
        }
        lines();scroll.append(canvas);stage.append(scroll);
      }
      if(isDouble){renderSection(groups.winner,'Winner-Bracket','winner');renderSection(groups.loser,'Loser-Bracket','loser');renderSection(groups.crossover,'Final- / Übergangsspiele','crossover');}
      else renderSection(matches,'K.O.-Turnierbaum','winner');
      if(rules.bye_players?.length)stage.append(el('p','Freilose: '+rules.bye_players.map(id=>namesMap.get(String(id))||String(id)).join(', '),'helper'));
    }
    for(const p of [...phases].sort((a,b)=>Number(a.phase_order||0)-Number(b.phase_order||0))){const b=action(p.name||'K.O.',()=>{for(const x of selector.children)x.classList.toggle('selected',x===b);draw(p)});selector.append(b)}
    selector.firstChild?.click();
  }
  async function showPlacements(box){
   box.append(el('h3','Endplatzierungen · '+c.title));
   const intro=el('p','Die Platzierung richtet sich nach der erreichten Endrunde. Ohne Platzierungsspiel können Teilnehmer denselben Rang belegen.','helper');box.append(intro);
   const data=await api('/competitions/'+id+'/final-report');
   if(!data.placements?.length){box.append(el('p','Noch keine gewerteten Spiele.','empty'));return}
   const rows=data.placements.map(p=>[String(p.place)+(p.tied?' (geteilt)':''),{player_id:p.player_id,name:p.name},p.reached||'–',p.wins,p.losses,p.average===null?'–':Number(p.average).toFixed(2)]);
   box.append(renderTable(['Platz','Spieler','Erreichte Runde','Siege','Niederlagen','Ø Turnieraverage'],rows));
   if(data.provisional)box.append(el('p','Hinweis: Bei unvollständigen oder nicht eindeutig zuordenbaren Phasen sind einzelne Platzierungen vorläufig.','helper'));
  }
  async function showTables(box){
    if(c.kind==='ladder'){
      const data=await api('/competitions/'+id+'/standings');const rules=data.conditions;
      const wrap=el('div',undefined,'ladder-table-page');box.append(wrap);
      const expl=el('div',undefined,'qualification-explanation');
      expl.append(el('strong','Qualifikation · Top '+rules.finalists),el('span','Min. '+rules.min_games+' Spiele · '+rules.min_opponents+' verschiedene Gegner · 7 Tage Sperre je Paarung'));
      wrap.append(expl);
      const controls=el('div',undefined,'ladder-filters'),area=el('div'),history=el('section',undefined,'ladder-history');
      const filter=picker([['all','Alle Spieler'],['eligible','Mindestbedingungen erfüllt'],['qualified','Aktuelle Finalplätze']],
        'all',()=>draw());controls.append(el('label','Rangliste filtern'),filter);wrap.append(controls,area,history);
      async function showPlayerHistory(row){
       clear(history);history.append(el('h3','Ladder-Spiele · '+row.display_name),el('p','Alle gewerteten Ergebnisse und die ELO-Entwicklung dieses Spielers.','helper'));
       const close=action('Schließen',()=>clear(history),'subtle');history.append(close);
       try{
        const details=await api('/competitions/'+id+'/players/'+row.player_id+'/history');
        if(!details.matches.length)history.append(el('p','Noch keine abgeschlossenen Spiele.','helper'));
        for(const m of details.matches){const x=el('article',undefined,'ladder-history-match');
          x.append(el('span',(m.finished_at?new Date(m.finished_at).toLocaleDateString('de-DE'):'Ohne Datum')+' · '+m.opponent),
           el('b',m.result+' · '+m.score),el('strong',m.elo_change===null?'ELO noch nicht berechnet':signed(Number(m.elo_change).toFixed(1))+' ELO'),
           el('small',m.elo_before===null?'Kein ELO-Datensatz':'ELO '+Number(m.elo_before).toFixed(1)+' → '+Number(m.elo_after).toFixed(1)+' · Gegner vor Spiel: '+(m.opponent_elo??'–')));
          history.append(x)
        }
       }catch(e){history.append(el('p',e.message,'error'))}
       history.scrollIntoView({block:'nearest',behavior:'smooth'});
      }
      function draw(){clear(area);clear(history);
       const rows=data.rows.filter(r=>filter.value==='all'||(filter.value==='eligible'&&r.eligible)||(filter.value==='qualified'&&r.qualified));
       const info=el('p',`${data.eligible_count} erfüllen die Mindestbedingungen · ${data.qualified_count} derzeit auf einem Finalplatz. Die Platzierung ist bis Saisonende vorläufig.`,'helper');area.append(info);
       if(!rows.length){area.append(el('p','Noch keine Spieler mit dieser Qualifikation.','empty'));return}
       const host=el('div',undefined,'scroll ladder-table-wrap'),table=el('table',undefined,'data-table polished ladder-table'),head=el('thead'),hr=el('tr');
       for(const h of ['PL','Name','Sp.','S','U','N','Legs','Diff','ELO','Siegquote','Ø ELO Gegner','Ø Average','Ø Average Gegner','Gegner'])hr.append(el('th',h));head.append(hr);table.append(head);
       const body=el('tbody');for(const [i,r] of rows.entries()){
        const tr=el('tr');if(r.qualified)tr.className='final-place';else if(r.eligible)tr.className='qualifying-ready';
        const rank=data.rows.indexOf(r)+1;
        if((filter.value==='all'&&rank===Number(rules.finalists)) ||
           (filter.value!=='all'&&i===Math.min(Number(rules.finalists),rows.length)-1))tr.classList.add('ladder-cutoff');
        const cells=[data.rows.indexOf(r)+1,null,r.played,r.wins,r.draws,r.losses,r.legs_for+':'+r.legs_against,signed(r.legs_for-r.legs_against),Number(r.elo).toFixed(1),(r.win_percent??0)+' %',r.average_opponent_elo??'–',r.own_average??'–',r.opponent_average??'–',r.distinct_opponents];
        for(const cell of cells){const td=el('td');if(cell===null){const link=action('',()=>showPlayerHistory(r),'ladder-name');link.append(participantName(r.player_id,r.display_name));td.append(link)}else td.textContent=String(cell);tr.append(td)}body.append(tr)
       }
       if(rows.length<Number(rules.finalists)&&filter.value==='all'){
         const remaining=Number(rules.finalists)-rows.length;
         const tr=el('tr',undefined,'ladder-open-slots'),td=el('td','Noch '+remaining+' mögliche Finalplätze bis Top '+rules.finalists);
         td.colSpan=14;tr.append(td);body.append(tr);
       }
       table.append(body);host.append(table);area.append(host);
       area.append(el('p','Gestrichelte goldene Linie = Grenze der Top '+rules.finalists+' (direkt aus den Ladder-Regeln). Goldener Name = aktuelle Finalqualifikation nach Mindestspielen und verschiedenen Gegnern.','helper'));
      }draw();return;
    }
    if(!selected.groups.length){box.append(el('p','Noch keine Gruppen angelegt. Die Einteilung erfolgt unter Verwaltung.','empty'));return}
    const switcher=el('div',undefined,'competition-group-tabs');
    const savedGroup=groupSelections.get(id);
    let currentGroup=selected.groups.some(g=>g.id===savedGroup)?savedGroup:selected.groups[0].id;
    const area=el('div');box.append(switcher,area);
    for(const g of selected.groups){const b=action(g.name,()=>{currentGroup=g.id;groupSelections.set(id,g.id);for(const tab of switcher.children)tab.classList.toggle('selected',tab===b);fill()},'subtle');b.classList.toggle('selected',g.id===currentGroup);switcher.append(b)}
    async function fill(){clear(area);const g=selected.groups.find(g=>g.id===currentGroup);if(!g)return;
      const rows=await api('/competitions/'+id+'/standings?group_id='+g.id);
      const withdrawals=new Set(selected.entries.filter(e=>e.status==='withdrawn').map(e=>e.player_id));
      const rawRules=typeof c.rules==='string'?JSON.parse(c.rules||'{}'):(c.rules||{});
      const qualifierSetting=String(rawRules.qualifiers??'1').toLowerCase();
      const qualifyCount=rawRules.follow? (qualifierSetting==='all'?rows.length:Math.min(rows.length,Math.max(0,Number(qualifierSetting)||0))) : 0;
      area.append(el('h3',g.name));
      if(qualifyCount){area.append(el('p','Finalrunde: '+(qualifyCount===rows.length?'Alle '+rows.length+' Plätze':'Platz 1–'+qualifyCount)+' qualifizieren sich'+(Number(rawRules.best_third_count||0)?' · zusätzlich '+rawRules.best_third_count+' beste Nächstplatzierte im Gruppenvergleich':'')+(rawRules.consolation?' · übrige Spieler: Trostrunde':''),'qualification-notice'))}
      const tableWrap=renderTable(['Platz','Name','Ges.','S','U','N','Legs','Dif.','Pkt',...(qualifyCount?['Qualifikation']:[])],rows.map((r,i)=>[
          r.rank,{player_id:r.player_id,name:r.name+(withdrawals.has(r.player_id)?' · ausgetreten':'')},r.played,r.wins,r.draws,r.losses,
          String(r.legs_for)+':'+String(r.legs_against),signed(r.legs_for-r.legs_against),r.points,
          ...(qualifyCount?[i<qualifyCount?'Finalrunde':i===qualifyCount&&Number(rawRules.best_third_count||0)?'Drittenvergleich':'–']:[])
      ]),true);
      if(qualifyCount){const bodyRows=tableWrap.querySelectorAll('tbody tr');bodyRows.forEach((line,i)=>{
         if(i<qualifyCount){line.classList.add('tournament-qualified');line.title='Qualifiziert für die Finalrunde (vorläufig)';}
         if(i===qualifyCount-1&&qualifyCount<rows.length)line.classList.add('tournament-cutoff');
      })}
      area.append(tableWrap);
      const games=selected.matches.filter(m=>m.group_id===g.id&&m.status==='finished').length;
      area.append(el('p',games+' gewertete Spiele in dieser Staffel','helper'));
      if(games&&!rows.some(r=>r.played))area.append(el('p','Die Spiele sind gespeichert, aber nicht den Tabellenmitgliedern zugeordnet. Bitte die Gruppenzuordnung unter Verwaltung prüfen.','error'));
    }
    await fill();
  }
  async function showRecords(box){
    box.append(el('p','Alle Teilnehmer dieses Wettbewerbs. Nur abgeschlossene Spiele zählen; Averages nur aus aufgezeichneten Aufnahmen.','helper'));
    const data=await api('/competitions/'+id+'/statistics');
    if(!data.players?.length){box.append(el('p','Noch keine Turnierdaten vorhanden.','empty'));return}
    const ranked=[...data.players].sort((a,b)=>(b.average??-1)-(a.average??-1));
    const fmt=x=>x===null||x===undefined?'–':Number(x).toLocaleString('de-DE',{minimumFractionDigits:2,maximumFractionDigits:2});
    const tabs=el('div',undefined,'competition-tabs');const output=el('div');box.append(tabs,output);
    const views=[['stats','Statistiken'],['best','Bestleistungen']];
    function draw(view){clear(output);for(const b of tabs.children)b.classList.toggle('selected',b.dataset.tab===view);
      if(view==='stats')output.append(renderTable(['Spieler','Sp.','S','U','N','Legs','Ø Average','First 9'],ranked.map(r=>[
         {player_id:r.player_id,name:r.name},r.games,r.wins,r.draws,r.losses,r.legs_for+':'+r.legs_against,fmt(r.average),fmt(r.first9)
      ])));
      else {
        output.append(el('h3','Scoring & Specials'));
        output.append(el('p','Jede Aufnahme zählt genau in eine der fünf Kategorien. 180er werden zusätzlich als Bestleistung ausgewiesen.','helper'));
        output.append(renderTable(['Spieler','60–79','80–99','100–139','140–170','171–180','180er','BF gesamt'],ranked.map(r=>[
          {player_id:r.player_id,name:r.name},r['60plus'],r['80plus'],r['100plus'],r['140plus'],r['171plus'],r['180'],r.bullfinishes
        ])));
        output.append(el('h3','Bestleistungen im Detail'));
        output.append(el('p','Alle Leistungen aus abgeschlossenen Scorer-Spielen. Identische Werte werden zusammengezählt (z. B. 2×141 oder 3×18).','helper'));
        output.append(renderTable(['Spieler','Highfinishes (100+)','Lowdarts (9–18)','Bullfinishes','Highscores (171+)'],ranked.map(r=>[
          {player_id:r.player_id,name:r.name},multiplicities(r.highfinish_details),multiplicities(r.lowdart_details,true),multiplicities(r.bullfinish_details),multiplicities(r.highscores)
        ])));
      }
    }
    for(const [key,title] of views){const b=action(title,()=>draw(key));b.dataset.tab=key;tabs.append(b)}
    draw('stats');
  }

  function showLadderRules(box){
    const q=c.rules||{};const block=el('article',undefined,'panel ladder-rules');
    block.append(el('h2','Regelwerk · '+c.title));
    const list=[
      ['Teilnahme','Alle aktiven Vereinsmitglieder nehmen automatisch teil. In der ELO-Rangliste erscheint ein Spieler erst nach dem ersten gewerteten Match.'],
      ['Spielvereinbarung','Zwei Mitglieder vereinbaren ihre Partie am Board. Vor dem Start werden die Spieler und die Matchlänge (mindestens Best of 5 Legs) ausgewählt. Das Ergebnis wird über den integrierten Scorer erfasst.'],
      ['Matchmodus','Die Matchlänge wird vor dem Spiel vereinbart. Bei gerader Leganzahl ist ein Unentschieden möglich.'],
      ['ELO-Wertung','Jeder Spieler startet mit 1.000 ELO-Punkten. Der K-Faktor beträgt '+(q.k_factor??64)+'. Ein Sieg, eine Niederlage oder ein Unentschieden verändert die Wertung abhängig vom ELO-Abstand beider Spieler.'],
      ['Wiederholungssperre','Dieselbe Paarung darf erst '+(q.rematch_cooldown_days??7)+' Tage nach dem letzten abgeschlossenen Ladder-Spiel erneut antreten. Gleichzeitig offene Doppelbegegnungen sind nicht zulässig.'],
      ['Mindestqualifikation','Für die Finalrunde sind mindestens '+(q.min_games??5)+' gewertete Spiele gegen mindestens '+(q.min_opponents??3)+' unterschiedliche Gegner erforderlich.'],
      ['Finalplätze','Aktuell sind '+(q.finalists??8)+' Finalplätze vorgesehen. Die Rangliste markiert die Qualifikationszone; nur Spieler mit erfüllten Mindestbedingungen sind dort qualifiziert. Bis Saisonende sind die Plätze vorläufig.'],
      ['Saisonende','Die Turnierleitung kann die Ladder auch vor dem Enddatum abschließen. Die qualifizierten Spieler ziehen dann in ein eigenes Finalturnier mit Gruppenphase und anschließender K.O.-Runde ein.'],
      ['Spielabbruch','Ein versehentlich gestartetes, noch nicht abgeschlossenes Spiel kann auf OFFEN zurückgesetzt werden; sämtliche bis dahin eingegebenen Aufnahmen dieses Spiels werden verworfen. Abgeschlossene Ergebnisse bleiben bestehen.'],
      ['Fair Play','Alle Spiele werden vor Ort am Dartboard ausgetragen. Beide Spieler prüfen das Ergebnis vor dem Spielabschluss. Streitfälle entscheidet die Vereins- bzw. Turnierleitung.']
    ];
    for(const [heading,txt] of list){const section=el('section',undefined,'ladder-rule-item');section.append(el('h3',heading),el('p',txt));block.append(section)}
    box.append(block)
  }
  function scheduleKey(){return 'stingrays_schedule_'+id}
  function showSchedule(box){
    if(c.kind==='training_tournament'&&(amAdmin()||trainingOwner())){
      const panel=el('div',undefined,'panel ladder-create');panel.append(el('h3','Trainingsmatch anlegen'));
      const people=selected.entries.filter(x=>x.status==='active');const one=picker([['','Spieler 1'],...people.map(x=>[x.player_id,x.display_name])],'',()=>{}),two=picker([['','Spieler 2'],...people.map(x=>[x.player_id,x.display_name])],'',()=>{});
      const mode=picker([['legs','Legmodus'],['sets','Setmodus']],'legs',()=>{perLabel.hidden=mode.value!=='sets';bestLabel.firstChild.textContent=mode.value==='sets'?'Best of X Sets':'Best of X Legs';length.value=mode.value==='sets'?'3':'5'});
      const length=document.createElement('input');length.type='number';length.min='1';length.max='101';length.value='5';
      for(const [l,f] of [['Spieler 1',one],['Spieler 2',two],['Modus',mode]]){const label=el('label',l);label.append(f);panel.append(label)}
      const bestLabel=el('label','Best of X Legs');bestLabel.append(length);panel.append(bestLabel);
      const per=document.createElement('input');per.type='number';per.min='1';per.max='21';per.step='2';per.value='3';
      const perLabel=el('label','Legs pro Set');perLabel.append(per);perLabel.hidden=true;panel.append(perLabel);
      panel.append(action('Trainingsmatch hinzufügen',async()=>{if(!one.value||!two.value||one.value===two.value)return notice('Zwei verschiedene Spieler wählen',true);
        const n=Number(length.value),sets=mode.value==='sets';if(!Number.isInteger(n)||n<1||n>101||sets&&(n%2!==1||Number(per.value)%2!==1))return notice('Ungültige Matchlänge',true);
        const rules={mode:mode.value,...(sets?{best_of_sets:n,best_of_legs_per_set:Number(per.value)}:{max_legs:n,allow_draw:n%2===0})};
        try{await api('/competitions/'+id+'/matches',{player1_id:one.value,player2_id:two.value,rules});await openCompetition(id)}catch(e){notice(e.message,true)}
      }));box.append(panel);
    }
    if(c.kind==='ladder'){
      const add=el('div',undefined,'panel ladder-create');add.append(el('h3','Ladder-Match vereinbaren'));
      const first=picker([['','Spieler 1'],...selected.entries.filter(e=>e.status!=='withdrawn').map(e=>[e.player_id,e.display_name])],'',()=>{});
      const second=picker([['','Spieler 2'],...selected.entries.filter(e=>e.status!=='withdrawn').map(e=>[e.player_id,e.display_name])],'',()=>{});
      const best=document.createElement('input');best.type='number';best.min='5';best.max='101';best.value='6';best.step='1';best.setAttribute('aria-label','Best of X Legs');
      const mode=picker([['legs','Legmodus'],['sets','Setmodus']],'legs',()=>{lengthLabel.firstChild.textContent=mode.value==='sets'?'Best of X Sets (ungerade)':'Best of X Legs (mind. 5)';best.min=mode.value==='sets'?'1':'5';best.value=mode.value==='sets'?'3':'6';perLabel.hidden=mode.value!=='sets'});
      for(const [label,input] of [['Spieler 1',first],['Spieler 2',second],['Modus',mode]]){const l=el('label',label);l.append(input);add.append(l)}
      const lengthLabel=el('label','Best of X Legs (mind. 5)');lengthLabel.append(best);add.append(lengthLabel);
      const per=document.createElement('input');per.type='number';per.min='1';per.max='21';per.step='2';per.value='3';
      const perLabel=el('label','Legs pro Set');perLabel.append(per);perLabel.hidden=true;add.append(perLabel);
      add.append(action('Match vereinbaren',async()=>{
        if(!first.value||!second.value||first.value===second.value)return notice('Zwei verschiedene Spieler auswählen.',true);
        if(Number(best.value)<(mode.value==='sets'?1:5)||Number(best.value)>101||mode.value==='sets'&&Number(best.value)%2===0)return notice('Legs ab 5, Sets nur ungerade (bis 101).',true);
        const sets=mode.value==='sets',n=Number(best.value),legPer=Number(per.value);
        if(!Number.isInteger(n)||sets&&(!Number.isInteger(legPer)||legPer<1||legPer>21||legPer%2!==1))return notice('Bitte gültige ungerade Set- und Legzahlen wählen.',true);
        const rules={mode:mode.value,...(sets?{best_of_sets:n,best_of_legs_per_set:legPer}:{max_legs:n,allow_draw:n%2===0})};
        try{await api('/competitions/'+id+'/matches',{player1_id:first.value,player2_id:second.value,rules});await openCompetition(id);notice('Match angelegt – im Spielplan auf Scorer klicken.')}catch(e){notice(e.message,true)}
      },'primary'));box.append(add);
    }
    let storedFilters={};try{storedFilters=JSON.parse(sessionStorage.getItem(scheduleKey())||'{}')}catch{}
    const filters=el('div',undefined,'schedule-controls');
    const g=picker([['','Alle Staffeln'],...selected.groups.map(x=>[x.id,x.name])],'',()=>reset());
    const p=picker([['','Alle Spieler'],...selected.entries.map(e=>[e.player_id,e.display_name])],'',()=>reset());
    const status=picker([['','Alle Spiele'],['open','Offen'],['running','Laufend'],['finished','Beendet'],['cancelled','Abgesagt']],'',()=>reset());
    g.value=storedFilters.group||'';p.value=storedFilters.player||'';status.value=storedFilters.status||'';
    for(const [caption,select] of [...(c.kind==='ladder'?[]:[['Staffel',g]]),['Spieler',p],['Status',status]]){const label=el('label',caption);label.append(select);filters.append(label)}
    filters.append(action('Filter zurücksetzen',()=>{g.value='';p.value='';status.value='';sessionStorage.removeItem(scheduleKey());schedulePage=0;draw()},'subtle'));
    const pages=el('div',undefined,'pagination');const list=el('div',undefined,'schedule-table-wrap');
    box.append(filters,list,pages);
    function reset(){sessionStorage.setItem(scheduleKey(),JSON.stringify({group:g.value,player:p.value,status:status.value}));schedulePage=0;draw()}
    function draw(){clear(list);clear(pages);
      const matches=selected.matches.filter(m=>(!g.value||m.group_id===g.value)&&(!p.value||m.player1_id===p.value||m.player2_id===p.value)&&(!status.value||m.status===status.value));
      const pageCount=Math.max(1,Math.ceil(matches.length/8));schedulePage=Math.max(0,Math.min(schedulePage,pageCount-1));
      box.querySelector('.schedule-controls').setAttribute('data-total',String(matches.length));
      const sorted=matches.slice().sort((a,b)=>{
        const groupName=m=>selected.groups.find(g=>g.id===m.group_id)?.name||selected.phases.find(x=>x.id===m.phase_id)?.name||'Spiel';
        return groupName(a).localeCompare(groupName(b),'de',{numeric:true})||(Number(a.round_number)||0)-(Number(b.round_number)||0);
      });
      const count=el('div',matches.length+' Begegnungen','schedule-count');list.append(count);
      if(!matches.length)list.append(el('p','Keine Spiele mit diesen Filtern','empty'));
      const table=el('table',undefined,'fixture-table');const head=el('thead');const heading=el('tr');
      for(const label of ['Gruppe / Phase','Runde','Spieler 1','Spieler 2','Ergebnis / Status','Aktionen'])heading.append(el('th',label));
      head.append(heading);table.append(head);const tbody=el('tbody');table.append(tbody);if(matches.length)list.append(table);
      for(const m of sorted.slice(schedulePage*8,(schedulePage+1)*8)){
        const line=el('tr',undefined,'fixture-row '+m.status);const group=selected.groups.find(g=>g.id===m.group_id)?.name||selected.phases.find(x=>x.id===m.phase_id)?.name||'Spiel';
        line.append(el('td',group),el('td',m.round_number?'Runde '+m.round_number:'–'));
        const first=el('td');first.append(participantName(m.player1_id,names.get(m.player1_id)||'Spieler 1'));
        const second=el('td');second.append(participantName(m.player2_id,names.get(m.player2_id)||'Spieler 2'));
        line.append(first,second);
        const score=m.status==='finished'?(m.sets1!==null&&m.sets1!==undefined?'Sets '+m.sets1+':'+m.sets2+' · ':'')+(m.legs1??0)+':'+(m.legs2??0):m.status==='running'?'Laufend':m.status==='cancelled'?'Abgesagt':'Offen';
        const actions=el('div',undefined,'fixture-actions');const result=el('td');result.append(el('span',score,'fixture-status '+m.status));line.append(result);
        if(m.source==='forfeit')actions.append(el('small','Wertung'));
        else if(m.source==='legacy')actions.append(el('small','Altbestand'));
        else if(m.status==='finished'||amAdmin()||user.role==='tournament'||[m.player1_id,m.player2_id].includes(user.player_id))actions.append(action(m.status==='finished'?'Spiel ansehen':'Scorer',()=>openScorer(m.id),'primary'));
        if((amAdmin()||trainingOwner())&&['running','cancelled'].includes(m.status))actions.append(action('Auf OPEN zurücksetzen',async()=>{
          const data=await configure('Begegnung zurücksetzen',[
            {name:'reason',label:'Grund (Audit-Protokoll)',value:'Testspiel neu starten',required:true},
            {name:'confirmation',label:'Dabei gehen alle erfassten Aufnahmen dieses Spiels verloren.',type:'select',required:true,options:[['','Bitte auswählen'],['yes','Spiel zurücksetzen']]}], 'Zurücksetzen');
          if(!data||data.confirmation!=='yes')return;
          try{await api('/matches/'+m.id+'/reset',{reason:data.reason,confirm:'ZURUECKSETZEN'});await openCompetition(id);notice('Begegnung ist wieder OPEN.')}catch(e){notice(e.message,true)}
        },'danger'));
        if(m.status==='running'&&(amAdmin()||user.role==='tournament'||trainingOwner()||[m.player1_id,m.player2_id].includes(user.player_id))){
          actions.append(action('Spiel abbrechen',async()=>{
            if(!await approve('Laufendes Spiel abbrechen','Alle bisherigen Aufnahmen verwerfen und diese Begegnung wieder auf OFFEN setzen?'))return;
            try{await api('/matches/'+m.id+'/abort',{mode:'reset',confirm:'ABBRECHEN',reason:'Versehendlich gestartet'});await openCompetition(id);notice('Spiel abgebrochen – Status wieder OFFEN.')}catch(e){notice(e.message,true)}
          },'subtle'));
        }
        if(amAdmin()&&['open','running'].includes(m.status)){
          actions.append(action('Begegnung absagen',async()=>{
            if(!await approve('Begegnung absagen','Begegnung auf ABGESAGT setzen? Noch nicht abgeschlossene Aufnahmen werden gelöscht; das Spiel zählt nicht für ELO und Tabellen.'))return;
            try{await api('/matches/'+m.id+'/abort',{mode:'cancel',confirm:'ABBRECHEN',reason:'Durch Administrator abgesagt'});await openCompetition(id);notice('Begegnung abgesagt.')}catch(e){notice(e.message,true)}
          },'danger'));
        }
        if(user.role==='admin'&&m.status==='finished'&&m.legs1===m.legs2&&selected.phases.some(ph=>ph.id===m.phase_id&&ph.kind==='knockout')){
          actions.append(action('Fehlergebnis korrigieren',async()=>{
            const d=await configure('K.O.-Fehlergebnis korrigieren',[{name:'score',label:'Korrigierter Endstand (z.B. 3:2)',required:true},{name:'reason',label:'Korrekturgrund',value:'Ungültiges Unentschieden im K.O.-Spiel',required:true}]);
            if(!d)return;const match=/^\s*(\d+)\s*:\s*(\d+)\s*$/.exec(d.score);
            if(!match||Number(match[1])===Number(match[2]))return notice('K.O.-Spiele brauchen einen eindeutigen Sieger.',true);
            try{await api('/matches/'+m.id+'/correct-ko',{legs1:Number(match[1]),legs2:Number(match[2]),reason:d.reason,confirm:'KORRIGIEREN'});await openCompetition(id);notice('Ergebnis korrigiert. K.O.-Runden wurden aktualisiert.')}catch(e){notice(e.message,true)}
          },'danger'));
        }
        if(user.role==='admin'&&m.status==='open')actions.append(action('Altes Ergebnis',async()=>{
          const d=await configure('Altes Ergebnis erfassen',[{name:'score',label:'Endstand (z.B. 4:2)',required:true}]);if(!d)return;const raw=d.score;
          const match=/^\s*(\d+)\s*:\s*(\d+)\s*$/.exec(raw);if(!match){notice('Format: 4:2',true);return}
          const x=Number(match[1]),y=Number(match[2]);const phase=selected.phases.find(ph=>ph.id===m.phase_id);
          if(phase?.kind==='knockout'&&x===y)return notice('In der K.O.-Runde ist ein Unentschieden nicht erlaubt.',true);
          try{await api('/matches/'+m.id+'/manual',{legs1:x,legs2:y});await openCompetition(id)}catch(e){notice(e.message,true)}
        },'subtle'));
        const actionCell=el('td',undefined,'fixture-action-cell');actionCell.append(actions);line.append(actionCell);tbody.append(line);
      }
      pages.append(action('← Vorherige',()=>{schedulePage--;draw()},'subtle'),el('span','Seite '+(schedulePage+1)+' / '+pageCount),action('Nächste →',()=>{schedulePage++;draw()},'subtle'));
      pages.firstChild.disabled=schedulePage===0;pages.lastChild.disabled=schedulePage>=pageCount-1;
    }
    draw();
  }
  function showParticipants(box){
    const heading=el('p',selected.entries.length+' angemeldete Teilnehmer','helper'),holder=el('div',undefined,'table-frame compact-table'),pager=el('div',undefined,'compact-pager');box.append(heading,holder,pager);
    const entries=[...selected.entries].sort((a,b)=>a.display_name.localeCompare(b.display_name,'de'));let page=0;
    function draw(){const per=window.innerHeight<800?6:window.innerHeight<950?9:12;makeTable(holder,['#','Teilnehmer','Status'],entries.slice(page*per,(page+1)*per),(e,i)=>{const tr=el('tr');tr.append(el('td',String(page*per+i+1)));const name=el('td');name.append(participantName(e.player_id,e.display_name));tr.append(name,el('td',e.status==='withdrawn'?'Ausgetreten':'Aktiv'));return tr;});compactPager(pager,entries.length,page,n=>{page=n;draw()},per)}draw();
  }
  function showLadderAdmin(box){
    box.append(el('p','Ladder-Verwaltung · Freie Matchvereinbarung, ELO und Finalqualifikation. Keine künstlichen Gruppen für die Vorrunde.','helper'));
    const q=c.rules||{},panel=el('article',undefined,'manage-card');panel.append(el('h3','Qualifikation fürs Finale'));
    const current=el('p',`Mindestspiele: ${q.min_games??5} · Verschiedene Gegner: ${q.min_opponents??3} · Finalplätze: ${q.finalists??8} · Rematch: 7 Tage`,'helper');panel.append(current);
    panel.append(action('Qualifikationsbedingungen bearbeiten',async()=>{
      const data=await configure('Finalqualifikation konfigurieren',[
        {name:'min_games',label:'Mindestens gespielte Matches',type:'number',min:1,max:250,value:q.min_games??5,required:true},
        {name:'min_opponents',label:'Mindestens verschiedene Gegner',type:'number',min:1,max:200,value:q.min_opponents??3,required:true},
        {name:'finalists',label:'Spieler im Finale (Top X)',type:'number',min:2,max:128,value:q.finalists??8,required:true}], 'Speichern');
      if(!data)return;
      try{await api('/competitions/'+id+'/ladder-conditions',data);await openCompetition(id);notice('Neue Qualifikationsgrenzen gespeichert. Die Rangliste ist aktualisiert.')}catch(e){notice(e.message,true)}
    },'primary'));box.append(panel);
    const status=picker([['active','Aktiv'],['finished','Beendet'],['archived','Archiviert']],c.status,async value=>{try{await api('/competitions/'+id+'/status',{status:value});await openCompetition(id)}catch(e){notice(e.message,true)}});
    const l=el('label','Ladder-Status');l.append(status);box.append(l);
    if(c.rules?.final_competition_id){
      box.append(el('p','Zu dieser Ladder wurde bereits ein Finalturnier erzeugt. Das Zurücksetzen des Ladder-Status alleine gibt keine neue Finalerzeugung frei.','helper'));
      box.append(action('Finalturnier öffnen',()=>openCompetition(c.rules.final_competition_id),'primary'));
      box.append(action('Finalturnier für erneuten Test freigeben',async()=>{
        if(!await approve('Finalturnier für Test neu erzeugen','Das bisherige Finalturnier wird inklusive seiner Ergebnisse archiviert und als vorheriger Testlauf gekennzeichnet. Die Ladder-Ergebnisse und ELO-Werte bleiben erhalten. Danach kannst du ein neues Finalturnier erzeugen. Wirklich fortfahren?'))return;
        try{await api('/competitions/'+id+'/reset-ladder-final-test',{confirm:'FINALE NEU TESTEN'});await openCompetition(id);notice('Altes Finale archiviert. Du kannst die Ladder erneut abschließen und ein neues Finale erzeugen.');}catch(e){notice(e.message,true)}
      },'danger'));
    }
    else if(c.status==='active')box.append(action('Ladderphase jetzt abschließen und Finale erstellen',async()=>{
      const d=await configure('Ladder abschließen · Finalturnier',[
        {name:'group_count',label:'Anzahl Finalgruppen',type:'number',value:2,min:1,max:16,required:true},
        {name:'advance_per_group',label:'Qualifikanten pro Gruppe für die KO-Runde',type:'number',value:2,min:1,max:8,required:true},
        {name:'group_legs',label:'Gruppenphase · Best of X Legs',type:'number',value:4,min:1,max:101,required:true},
        {name:'ko_legs',label:'KO-Vorrunde · Best of X Legs',type:'number',value:5,min:1,max:101,step:2,required:true},
        {name:'quarter_legs',label:'Viertelfinale · Best of X Legs',type:'number',value:5,min:1,max:101,step:2,required:true},
        {name:'semi_legs',label:'Halbfinale · Best of X Legs',type:'number',value:7,min:1,max:101,step:2,required:true},
        {name:'final_legs',label:'Finale · Best of X Legs',type:'number',value:9,min:1,max:101,step:2,required:true},
        {name:'third_place',label:'Spiel um Platz 3',type:'select',options:[['false','Nein'],['true','Ja']],value:'true',required:true},
        {name:'third_legs',label:'Spiel um Platz 3 · Best of X Legs',type:'number',value:5,min:1,max:101,step:2,required:true}
      ],'Qualifikation prüfen und abschließen');if(!d)return;
      if(!await approve('Ladder endgültig abschließen','Die aktuell qualifizierten Top-Spieler werden eingefroren, offene Ladder-Spiele abgebrochen und das Finalturnier erzeugt. Dieser Schritt ist nicht rückgängig zu machen. Fortfahren?'))return;
      try{const result=await api('/competitions/'+id+'/end-ladder',d);await openCompetition(result.final_competition_id);notice(result.qualified_count+' qualifizierte Spieler ins Finalturnier übernommen.');}catch(e){notice(e.message,true)}
    },'danger'));
    box.append(action('Wettbewerb archivieren',async()=>{if(!await approve('Ladder archivieren','Saison aus der aktiven Übersicht ins Archiv verschieben?'))return;try{await api('/competitions/'+id+'/status',{status:'archived'});await openCompetition(id)}catch(e){notice(e.message,true)}}));
    box.append(action('Testwettbewerb löschen',async()=>{if(!await approve('Ladder ausblenden','Achtung: Dieser Wettbewerb wird aus der Statistik entfernt.'))return;try{await api('/competitions/'+id+'/delete',{confirm:'DAUERHAFT AUSBLENDEN'});$('competitionDetail').hidden=true;await loadCompetitions()}catch(e){notice(e.message,true)}},'danger'));
  }
  function showManagement(box){
    if(!amAdmin()&&!trainingOwner())return;
    if(c.kind==='ladder'){showLadderAdmin(box);return}
    if(c.kind==='training_tournament'){
      const r=typeof c.rules==='string'?JSON.parse(c.rules||'{}'):(c.rules||{});
      const config=el('section',undefined,'manage-card');
      config.append(el('h3','Final- und Trostrunde nachträglich ändern'),
        el('p','Die Qualifikation lässt sich bis zur tatsächlichen Anlage der nächsten Phase korrigieren. Bereits laufende Finalrunden bleiben geschützt.','helper'));
      config.append(el('p','Aktuell: '+(r.follow?'Finalrunde · '+(r.qualifiers==='all'?'Alle':(r.qualifiers||1)+' je Gruppe')+(r.best_third_count?' + '+r.best_third_count+' beste Nächstplatzierte':'')+' · '+(r.follow_format||'single_ko'):'Keine Finalrunde')+(r.consolation?' · mit Trostrunde':''),'helper'));
      config.append(action('Qualifikation und Folgerunden bearbeiten',async()=>{
        const bool=[['no','Nein'],['yes','Ja']];
        const first=await configure('Turnierregeln nachträglich bearbeiten',[
          {name:'follow',label:'Finalrunde?',type:'select',options:bool,value:r.follow?'yes':'no'}
        ],'Weiter');if(!first)return;
        const payload={follow:first.follow==='yes',consolation:false,
          qualifiers:String(r.qualifiers||'1'),best_third_count:Number(r.best_third_count||0),best_third_manual_ids:[],follow_format:r.follow_format||'single_ko',
          consolation_format:r.consolation_format||'single_ko',
          follow_group_count:Number(r.follow_group_count||1),consolation_group_count:Number(r.consolation_group_count||1)};
        if(payload.follow){
          const second=await configure('Finalrunde konfigurieren',[
            {name:'qualifiers',label:'Qualifikanten je Gruppe',type:'select',value:payload.qualifiers,
             options:[['1','1'],['2','2'],['4','4'],['8','8'],['all','Alle']]},
            {name:'follow_format',label:'Finalmodus',type:'select',value:payload.follow_format,
             options:[['single_ko','Single KO'],['double_ko','Double KO'],['league','Liga'],['groups','Gruppenrunde']]}
          ],'Weiter');if(!second)return;Object.assign(payload,second);
          if(r.format==='groups' && payload.qualifiers!=='all'){
            const third=await configure('Beste Gruppennachrücker',[
             {name:'best_third_count',label:'Zusätzliche Qualifikanten aus verschiedenen Gruppen',type:'number',value:payload.best_third_count,min:0,max:selected.groups.filter(g=>selected.phases.find(p=>p.id===g.phase_id)?.phase_order===1).length||16,required:true}
            ],'Weiter');if(!third)return;Object.assign(payload,third);
          } else payload.best_third_count=0;
          if(payload.follow_format==='groups'){
            const groups=await configure('Gruppenanzahl der Finalrunde',[
              {name:'follow_group_count',label:'Gruppenanzahl',type:'number',value:payload.follow_group_count,min:1,max:16,required:true}
            ],'Weiter');if(!groups)return;Object.assign(payload,groups);
          }
          const third=await configure('Trostrunde',[
            {name:'consolation',label:'Trostrunde für nicht Qualifizierte?',type:'select',options:bool,value:r.consolation?'yes':'no'}
          ],'Weiter');if(!third)return;payload.consolation=third.consolation==='yes';
          if(payload.consolation){
            const fourth=await configure('Trostrunde konfigurieren',[
              {name:'consolation_format',label:'Trostrundenmodus',type:'select',value:payload.consolation_format,
               options:[['single_ko','Single KO'],['double_ko','Double KO'],['league','Liga'],['groups','Gruppenrunde']]}
            ],'Weiter');if(!fourth)return;Object.assign(payload,fourth);
            if(payload.consolation_format==='groups'){
              const tg=await configure('Gruppenanzahl der Trostrunde',[
                {name:'consolation_group_count',label:'Gruppenanzahl',type:'number',value:payload.consolation_group_count,min:1,max:16,required:true}
              ],'Weiter');if(!tg)return;Object.assign(payload,tg);
            }
          }
        }
        if(!await approve('Turnierregeln aktualisieren','Die Tabellen- und Qualifikationsmarkierungen werden angepasst. Bereits absolvierte Vorrundenspiele bleiben bestehen.'))return;
        try{await api('/competitions/'+id+'/tournament-settings',payload);await openCompetition(id);notice('Qualifikationsregeln gespeichert.')}
        catch(e){notice(e.message,true)}
      },'primary'));
      if(r.format==='groups' && r.follow && Number(r.best_third_count||0)>0){
        config.append(action('Beste Nachrücker bei Gleichstand manuell auswählen',async()=>{
          try{
            const prelim=(selected.phases||[]).find(p=>p.phase_order===1);
            if(!prelim)return notice('Vorrunde nicht gefunden.',true);
            if((selected.phases||[]).some(p=>p.phase_order>1))return notice('Die Final- oder Trostrunde wurde bereits erzeugt.',true);
            const n=r.qualifiers==='all'?0:Number(r.qualifiers||1),candidates=[];
            for(const group of selected.groups.filter(g=>g.phase_id===prelim.id)){
              const standing=await api('/competitions/'+id+'/standings?group_id='+group.id);
              if(standing.length>n){const candidate=standing[n];candidates.push([candidate.player_id,group.name+' · '+candidate.name])}
            }
            if(!candidates.length)return notice('Keine nächstplatzierten Spieler verfügbar.',true);
            const values=await configure('Manuelle Nachrücker-Auswahl',[
              {name:'ids',label:'Bei gleichem Rang '+r.best_third_count+' Kandidaten auswählen',type:'multi',options:candidates,value:r.best_third_manual_ids||[]}
            ],'Festlegen');if(!values)return;
            if(values.ids.length!==Number(r.best_third_count))return notice('Bitte genau '+r.best_third_count+' Spieler wählen.',true);
            await api('/competitions/'+id+'/tournament-settings',{best_third_manual_ids:values.ids});await openCompetition(id);
            notice('Manuelle Auswahl für die Finalrunde gespeichert.');
          }catch(e){notice(e.message,true)}
        },'subtle'));
      }
      box.append(config);
    }
    const steps=el('div',undefined,'setup-steps');steps.append(el('b','1. Teilnehmer'),el('b','2. Phasen & Gruppen'),el('b','3. Spielplan'),el('b','4. Ergebnisse & Abschluss'));box.append(steps);
    const ad=el('p','Administrative Werkzeuge – Änderungen betreffen den Wettbewerb und seine Ergebnisse.','helper');box.append(ad);
    const management=el('div',undefined,'management-grid');box.append(management);
    function panel(title,description){const panel=el('section',undefined,'manage-card');panel.append(el('h3',title),el('p',description,'helper'));management.append(panel);return panel}
    const people=panel('Teilnehmer','Mitglieder hinzufügen, einteilen und Austritte verwalten.');
    const free=players.filter(p=>!selected.entries.some(e=>e.player_id===p.id));
    const add=picker([['','Mitglied auswählen'],...free.map(p=>[p.id,p.display_name])],'',()=>{});
    const addRow=el('div',undefined,'filterline');addRow.append(add,action('Hinzufügen',async()=>{
      if(!add.value)return notice('Bitte ein Mitglied wählen',true);
      try{await api('/competitions/'+id+'/entries',{player_ids:[add.value]});await openCompetition(id)}catch(e){notice(e.message,true)}
    }));people.append(addRow);
    if(c.kind==='league'){
      const active=selected.entries.filter(e=>e.status!=='withdrawn');
      const drop=picker([['','Spieler auswählen'],...active.map(e=>[e.player_id,e.display_name])],'',()=>{});
      people.append(el('label','Spieler ausgeschieden – alle Begegnungen 0:4 werten'),drop);
      people.append(action('Rückwertung durchführen',async()=>{
        if(!drop.value)return notice('Bitte Spieler auswählen',true);
        const name=active.find(x=>x.player_id===drop.value)?.display_name;
        if(!await approve('Rückwertung '+name,'Alle alten und offenen Spiele auf 0:4 setzen?'))return;
        try{const r=await api('/competitions/'+id+'/withdraw',{player_id:drop.value,forfeit_legs:4});await openCompetition(id);notice(r.revalued+' Spiele neu gewertet.')}catch(e){notice(e.message,true)}
      },'danger'));
    }
    const phases=panel('Gruppen & Spielmodus','Phasen und Gruppen werden unabhängig voneinander verwaltet.');
    phases.append(action('Neue Phase',async()=>{
      const data=await configure('Neue Phase',[{name:'kind',label:'Phasenart',type:'select',options:[['groups','Gruppenphase'],['league','Liga'],['knockout','K.O.-Phase']]},{name:'name',label:'Bezeichnung',value:'Gruppenphase',required:true}]);if(!data)return;const mode=data.kind,name=data.name;
      try{await api('/competitions/'+id+'/phases',{kind:mode,name});await openCompetition(id)}catch(e){notice(e.message,true)}
    }));
    for(const ph of selected.phases){
      const group=el('details',undefined,'manage-details');const summary=el('summary',ph.name+' · '+ph.kind+' · '+ph.status);group.append(summary);
      group.append(action('Gruppe anlegen',async()=>{const data=await configure('Gruppe hinzufügen',[{name:'name',label:'Gruppenname',value:'Gruppe A',required:true}]);if(!data)return;const name=data.name;try{await api('/phases/'+ph.id+'/groups',{name});await openCompetition(id)}catch(e){notice(e.message,true)}}));
      for(const g of selected.groups.filter(g=>g.phase_id===ph.id)){
        const sub=el('div',undefined,'group-edit');sub.append(el('strong',g.name));
        const current=selected.memberships.filter(x=>x.group_id===g.id).map(x=>selected.entries.find(e=>e.entry_id===x.entry_id)?.display_name).filter(Boolean);
        sub.append(el('small',current.join(', ')||'Keine Teilnehmer'));
        sub.append(action('Einteilung bearbeiten',async()=>{
          const selectedIds=selected.memberships.filter(x=>x.group_id===g.id).map(x=>x.entry_id);
          const data=await configure('Gruppe '+g.name+' einteilen',[{name:'entries',label:'Teilnehmer',type:'multi',options:selected.entries.map(x=>[x.entry_id,x.display_name]),value:selectedIds}]);if(!data)return;
          try{await api('/groups/'+g.id+'/entries',{entry_ids:data.entries});await openCompetition(id)}catch(e){notice(e.message,true)}
        },'subtle'));
        sub.append(action('Spielplan erzeugen',async()=>{
          const data=await configure('Spielplan '+g.name,[{name:'rounds',label:'Spielmodus',type:'select',options:[['single','Einfach'],['double','Hin- und Rückrunde']]}],'Spielplan erzeugen');if(!data)return;
          try{await api('/groups/'+g.id+'/fixtures',{double_round:data.rounds==='double'});await openCompetition(id)}catch(e){notice(e.message,true)}
        },'subtle'));group.append(sub);
      }
      if(ph.kind==='knockout')group.append(action('K.O. aus Teilnehmerliste',async()=>{try{await api('/phases/'+ph.id+'/bracket',{player_ids:selected.entries.map(e=>e.player_id)});await openCompetition(id)}catch(e){notice(e.message,true)}}),action('Nächste Runde',async()=>{try{await api('/phases/'+ph.id+'/advance',{});await openCompetition(id)}catch(e){notice(e.message,true)}}));
      group.append(action('Phase schließen',async()=>{if(!await approve('Phase schließen','Die Phase abschließen?'))return;try{await api('/phases/'+ph.id+'/close',{});await openCompetition(id)}catch(e){notice(e.message,true)}},'subtle'));
      phases.append(group);
    }
    const general=panel('Export & Status','Offene Begegnungen exportieren und Wettbewerbsstatus verwalten.');
    if(c.kind!=='training_tournament')general.append(action('CSV exportieren',()=>location.href='/dart/v2/api/competitions/'+id+'/export?format=csv'),action('Excel exportieren',()=>location.href='/dart/v2/api/competitions/'+id+'/export?format=xlsx'));
    if(amAdmin()){
    general.append(picker([['','Status ändern …'],...['active','finished','archived'].map(v=>[v,v])],'',async state=>{if(!state||!await approve('Wettbewerbsstatus','Status ändern auf '+state+'?'))return;try{await api('/competitions/'+id+'/status',{status:state});await openCompetition(id)}catch(e){notice(e.message,true)}}));
    general.append(action('Testwettbewerb löschen',async()=>{if(!await approve('Testwettbewerb löschen (Soft-Delete)','Wettbewerb aus der Anwendung und allen Statistiken entfernen? Daten werden nicht endgültig zerstört, sondern für eine mögliche Wiederherstellung aufbewahrt.'))return;try{await api('/competitions/'+id+'/delete',{confirm:'DAUERHAFT AUSBLENDEN'});host.hidden=true;await loadCompetitions()}catch(e){notice(e.message,true)}},'danger'));
    }
    if(c.kind==='ladder'){
      const ladder=panel('Ladder','Laufzeit und Matchabschluss verwalten.');
      ladder.append(el('p','Abschluss und Finalturnier über den Tab Verwaltung konfigurieren.','helper'));
    }
  }
  if(c.kind==='ladder'&&user.role!=='admin'){};
  const allowedTabs=[...tabs.children].map(b=>b.dataset.tab);
  const requestedTab=competitionTab==='management'&&user.role!=='admin'?'table':competitionTab;
  await view(allowedTabs.includes(requestedTab)?requestedTab:(allowedTabs.includes('bracket')?'bracket':allowedTabs[0]));
  if(['training_tournament','final_tournament'].includes(c.kind)&&c.status==='finished'&&!sessionStorage.getItem('tournament-report-'+id)){
   sessionStorage.setItem('tournament-report-'+id,'seen');
   try{const report=await api('/competitions/'+id+'/final-report');const result=el('div',undefined,'tournament-end-report');
    result.append(el('h2','Turnier abgeschlossen: '+report.title));
    const grid=el('div',undefined,'report-grid');for(const p of report.placements){const row=el('div',undefined,'report-row');
     row.append(el('strong',p.place+'. '+p.name),el('span',p.wins+' Siege · Turnieraverage: '+(p.average??'–')));grid.append(row)}
    result.append(grid);
    const shade=el('div',undefined,'sheet-shade'),modal=el('section',undefined,'config-sheet');
    modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');
    modal.append(popupCloseButton(()=>shade.remove()),el('h2','Turnier abgeschlossen · '+report.title));
    const grid2=el('div',undefined,'report-grid');for(const p of report.placements){const line=el('div',undefined,'report-row');
       line.append(el('strong',p.place+'. '+p.name),el('span','S '+p.wins+' · N '+p.losses+' · Ø '+(p.average??'–')));grid2.append(line)}
    modal.append(grid2,action('Platzierungen dauerhaft anzeigen',()=>{shade.remove();view('placements')},'subtle'));
    const close=action('Schließen',()=>shade.remove(),'primary');modal.append(close);shade.append(modal);document.body.append(shade);
   }catch(e){console.warn('Turnierbericht',e)}
  }
}
function signed(n){return n>0?'+'+n:String(n)}
function renderTable(headers,rows,emphasize=false){
 const outer=el('div',undefined,'scroll table-frame'),t=el('table',undefined,'data-table polished'),thead=el('thead'),tr=el('tr');
 for(const h of headers)tr.append(el('th',h));thead.append(tr);t.append(thead);
 const tbody=el('tbody');for(const row of rows){const tr=el('tr');if(emphasize&&row[0]===1)tr.className='leader';for(const cell of row){const td=el('td');if(cell&&typeof cell==='object'&&cell.player_id)td.append(participantName(cell.player_id,cell.name));else td.textContent=String(cell??'–');tr.append(td)}tbody.append(tr)}
 t.append(tbody);outer.append(t);return outer;
}

async function openScorer(id){
 if(previewId){notice('Die Spieleransicht ist schreibgeschützt.',true);return}
 openGameWindow('/dart/v2/spiel/?match='+encodeURIComponent(id)+'&competition='+encodeURIComponent(selected?.competition?.id||''),id);
}
function drawScore(){if(!playing)return;const s=playing.state||{},names=s.names||[playing.player1,playing.player2],rest=s.remaining||[501,501];$('playerOne').textContent=names[0];$('playerTwo').textContent=names[1];$('remainOne').textContent=rest[0];$('remainTwo').textContent=rest[1];$('resultOne').textContent='Legs '+(s.legs?.[0]??playing.legs1??0)+(s.rules?.mode==='sets'?' · Sets '+(s.sets?.[0]??0):'');$('resultTwo').textContent='Legs '+(s.legs?.[1]??playing.legs2??0)+(s.rules?.mode==='sets'?' · Sets '+(s.sets?.[1]??0):'');for(let i=0;i<2;i++)document.querySelectorAll('.scorecard')[i].classList.toggle('current',s.current===i&&!s.done);$('toThrow').textContent=s.done?'Spiel beendet':names[s.current??0]+' wirft';$('throwForm').hidden=s.done||playing.status==='finished'||!playing.can_score;$('scoreStatus').textContent='Version '+playing.state_version;const host=$('visits');clear(host);for(const v of (s.visits||[]).slice().reverse())host.append(el('p',names[v.player]+': '+v.score+' / '+v.darts+' Darts'+(v.checkout?' · Checkout':'')+(v.bust?' · Bust':'')))}
$('throwForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);try{const r=await api('/matches/'+playing.id+'/throw',{points:Number(d.points),darts:Number(d.darts),checkout:!!d.checkout,bullfinish:!!d.bullfinish,version:playing.state_version});playing.state=r.state;playing.state_version=r.version;e.target.reset();e.target.elements.darts.value=3;drawScore()}catch(err){notice(err.message,true)}};
$('backToCompetition').onclick=()=>selected?openCompetition(selected.competition.id):show('dashboard');
const statsLabels={tournament_wins:'Turniersiege',tournament_seconds:'2. Plätze',tournament_thirds:'3. Plätze',matches:'Spiele',wins:'Siege',draws:'Unentschieden',losses:'Niederlagen',legs_for:'Gewonnene Legs',legs_against:'Verlorene Legs',scored_visits:'Aufnahmen',average:'Ø Average',first9:'Ø First 9',lowdarts:'Lowdarts (9–18)',highfinishes:'Highfinishes (100+)',bullfinishes:'Bullfinishes',highscores:'Highscores (171+)',training_sau_sessions:'Gegen die Sau',training_bobs_sessions:'Bobs 27',training_tug_sessions:'Tauziehen',training_football_sessions:'Fußball',training_minigolf_sessions:'Minigolf',training_tictactoe_sessions:'Tic Tac Toe',training_connect4_sessions:'Vier gewinnt',training_bobs_best:'Bobs 27 – Bestwert',training_sau_marks:'Sau-Striche',training_sau_success:'Sau – Checkouts','180':'180er','60plus':'60–79','80plus':'80–99','100plus':'100–139','140plus':'140–170','171plus':'171–180','95plus':'95–99 (Detail)','133plus':'133–139 (Detail)','exact133':'133 exakt',missing_throw_stats_matches:'Spiele ohne Wurfdaten'};
function multiplicities(values,ascending=false){const counts=new Map();for(const x of values||[])counts.set(String(x),(counts.get(String(x))||0)+1);return [...counts.entries()].sort((a,b)=>ascending?Number(a[0])-Number(b[0]):Number(b[0])-Number(a[0])).map(([value,n])=>n+'×'+value).join(' · ')||'–'}
function statValue(k,v){if(Array.isArray(v))return multiplicities(v);if(v===null||v===undefined)return '–';if(typeof v==='number')return String(v).replace('.',',');return String(v)}
let statProfileId=null,statProfileBand='AF',statProfilePage=0,statDetailTab='balance';
const statScopes=[['overall','Gesamt'],['training_tournament','Training'],['league','League'],['cup','Cup'],['ladder','Ladder'],['vm','Vereinsmeisterschaft']];
function renderStatisticsProfiles(){
 const term=$('statsProfileSearch').value.trim().toLocaleLowerCase('de'),all=players.filter(p=>p.display_name.toLocaleLowerCase('de').includes(term));
 const available=letterBands.filter(([k])=>all.some(p=>bandOf(p.display_name)===k));
 if(!available.some(([k])=>k===statProfileBand))statProfileBand=available[0]?.[0]||'AF';
 makeTabs($('statsAlphabet'),available.map(([k,label])=>[k,label+' ('+all.filter(p=>bandOf(p.display_name)===k).length+')']),statProfileBand,k=>{statProfileBand=k;statProfilePage=0;renderStatisticsProfiles()});
 const rows=all.filter(p=>bandOf(p.display_name)===statProfileBand).sort((a,b)=>a.display_name.localeCompare(b.display_name,'de'));
 const per=window.innerHeight<800?6:window.innerHeight<950?9:12,max=Math.max(1,Math.ceil(rows.length/per));statProfilePage=Math.min(statProfilePage,max-1);
 $('statsProfileCount').textContent=all.length+' Profile · Profil antippen für Details';
 makeTable($('statsProfiles'),['Spielerprofil','Status','Statistik'],rows.slice(statProfilePage*per,(statProfilePage+1)*per),p=>{
  const tr=el('tr');if(p.id===statProfileId)tr.className='selected-profile';
  const name=el('td');name.append(participantName(p.id,p.display_name));tr.append(name,el('td',p.is_active?'Aktiv':'Inaktiv'));
  const cell=el('td');cell.append(action('Anzeigen',()=>openProfileStats(p.id),'subtle'));tr.append(cell);return tr;
 });
 compactPager($('statsProfilePager'),rows.length,statProfilePage,p=>{statProfilePage=p;renderStatisticsProfiles()},per);
}
async function openProfileStats(id){
 statProfileId=id;$('statPlayer').value=id;$('statsDetail').hidden=false;$('statistics').classList.add('detail-open');
 $('statsSelectedTitle').textContent='Statistik · '+(players.find(p=>p.id===id)?.display_name||'Profil');
 renderStatisticsProfiles();renderStatScopeTabs();await loadProfileStatistics();
}
function renderStatScopeTabs(){const kind=$('statKind').value;makeTabs($('statsKindTabs'),statScopes,kind,async value=>{$('statKind').value=value;renderStatScopeTabs();statDetailTab='balance';await loadProfileStatistics()})}
let statLoadingId=0;
async function loadProfileStatistics(){const seq=++statLoadingId;const pid=$('statPlayer').value,kind=$('statKind').value;
 if(!pid)return;const host=$('statsResult');clear(host);host.append(el('p','Statistik wird geladen …','helper'));
 try{const [s,h,podium]=await Promise.all([api('/players/'+pid+'/stats?kind='+kind),api('/players/'+pid+'/h2h?kind='+kind),kind==='overall'?api('/players/'+pid+'/podiums'):Promise.resolve(null)]);
  if(seq!==statLoadingId)return;if(podium){s.podiums=podium;s.tournament_wins=podium.wins;s.tournament_seconds=podium.second;s.tournament_thirds=podium.third}
  statisticsPanels(host,s,h,kind);
 }catch(e){if(seq===statLoadingId)notice(e.message,true)}
}
function statisticsPanels(host,stats,h2h,scope){
 clear(host);host.className='stats-dashboard';
 const tabs=el('div',undefined,'ui-tabs stat-detail-tabs');host.append(tabs);
 const blocks=el('div',undefined,'stat-panels');host.append(blocks);
 const show=key=>stats[key]!==null&&stats[key]!==undefined;
 const pretty=key=>statValue(key,stats[key]);
 function panel(title,tab){const p=el('section',undefined,'stat-block stat-wide');p.dataset.statPane=tab;p.append(el('h3',title));blocks.append(p);return p}
 function cards(p,keys){const grid=el('div',undefined,'stat-cards');for(const k of keys){if(!show(k))continue;const card=el('article',undefined,'stat-card');card.append(el('span',statsLabels[k]||k),el('strong',pretty(k)));grid.append(card)}p.append(grid)}
 cards(panel('Spielbilanz','balance'),['matches','wins','draws','losses','legs_for','legs_against']);
 cards(panel('Durchschnitt & Aufnahmen','average'),['average','first9','scored_visits','missing_throw_stats_matches']);
 cards(panel('Scoring & Specials','scoring'),['60plus','80plus','100plus','140plus','171plus','180','bullfinishes']);
 const best=panel('Bestleistungen im Detail','best');
 for(const [label,k] of [['Highfinishes','highfinish_details'],['Lowdarts','lowdart_details'],['Bullfinishes','bullfinish_details'],['Highscores','highscores']]){
  if(!show(k))continue;const row=el('div',undefined,'stat-detail-row');row.append(el('b',label),el('span',multiplicities(stats[k])));best.append(row)}
 if(scope==='overall'||scope==='training_tournament')cards(panel('Training','training'),['training_sau_sessions','training_sau_success','training_sau_marks','training_bobs_sessions','training_bobs_best','training_tug_sessions','training_football_sessions','training_minigolf_sessions','training_tictactoe_sessions','training_connect4_sessions']);
 if(stats.podiums)cards(panel('Turniererfolge','podiums'),['tournament_wins','tournament_seconds','tournament_thirds']);
 const h=panel('Head to Head','h2h');
 if(!h2h.length)h.append(el('p','Noch keine direkten Duelle in diesem Bereich.'));
 else{const list=el('div',undefined,'h2h-rows');for(const o of h2h){const row=el('div',undefined,'h2h-row');row.append(el('b',o.opponent),el('span',o.played+' Spiele'),el('span',o.wins+' S · '+o.draws+' U · '+o.losses+' N'),el('span',o.legs_for+':'+o.legs_against+' Legs'));list.append(row)}h.append(list)}
 const nav=[['balance','Bilanz'],['average','Averages'],['scoring','Scoring'],['best','Bestleistungen'],['training','Training'],['podiums','Erfolge'],['h2h','Head-to-Head']].filter(([k])=>blocks.querySelector('[data-stat-pane="'+k+'"]'));
 if(!nav.some(([k])=>k===statDetailTab))statDetailTab='balance';
 function activate(tab){statDetailTab=tab;makeTabs(tabs,nav,tab,activate);for(const p of blocks.children)p.hidden=p.dataset.statPane!==tab}
 activate(statDetailTab);
}
$('statsBackToProfiles').onclick=()=>{$('statistics').classList.remove('detail-open');$('statsDetail').hidden=true};
$('statsProfileSearch').oninput=()=>{statProfilePage=0;renderStatisticsProfiles()};
$('statsLoad').onclick=loadProfileStatistics;
$('memberForm').onsubmit=async e=>{e.preventDefault();if(!amAdmin())return;try{await api('/players',formData(e.target));e.target.reset();await loadPlayers();notice('Mitglied erstellt')}catch(err){notice(err.message,true)}};
$('accountForm').onsubmit=async e=>{e.preventDefault();try{await api('/accounts',formData(e.target));e.target.reset();notice('Konto erstellt. Erstpasswort nur direkt an die betreffende Person weitergeben.')}catch(err){notice(err.message,true)}};
const migrationPanel=el('div',undefined,'panel');migrationPanel.append(el('h2','Vorhandene League und Profile übernehmen'),el('p','Übernahme erfolgt ausdrücklich als Kopie nach Neon. Die alte League bleibt unverändert.'));migrationPanel.append(btn('Aktive Google-Sheets-Profile nach Neon kopieren',async()=>{if(!await approve('Profile importieren','Aktive Profile nach Neon kopieren?'))return;try{const result=await api('/legacy/sync-profiles',{});notice(result.synced_active_profiles+' Profile kopiert');await loadPlayers()}catch(e){notice(e.message,true)}}));migrationPanel.append(btn('League-Migration: Vorschau',async()=>{try{const result=await api('/legacy/preview');if(!result.leagues.length){notice('Keine alten Liga-Snapshots gefunden');return}const d=await configure('League-Kopie nach Neon',[{name:'legacy_id',label:'Quellliga',type:'select',required:true,options:result.leagues.map(l=>[l.legacy_id,l.name+' ('+l.completed+'/'+l.fixtures+' gespielt)'])}],'Kopie prüfen');if(!d)return;
const choice=d.legacy_id;const source=result.leagues.find(l=>l.legacy_id===choice);
if(!source||!await approve('Import bestätigen','Liga '+source.name+' als eigenständige Kopie übernehmen?'))return;
const r=await api('/legacy/import',{legacy_id:choice,confirm:true});notice(r.fixtures+' Begegnungen in Neon kopiert');await show('competitions')}catch(e){notice(e.message,true)}}));$('admin').append(migrationPanel);
session().then(async()=>{
 const params=new URLSearchParams(location.search),c=params.get('competition'),training=params.get('training');
 if(!user)return;
 if(training){
   document.body.classList.add('standalone-training');
   await show('training');
   $('trainingList').hidden=true;
   if(['sau','tug','bobs'].includes(training)){launchTrainingWindow(training);return}
   if(['football','minigolf','tictactoe','connect4'].includes(training)){await startMiniTraining(training);return}
   if(training==='x01')await quickTraining();
   else if(training==='tug')await startTug();
   else if(training==='sau'||training==='bobs')startSolo(training);
   else notice('Unbekannter Trainingsmodus',true);
   return;
 }
 if(params.get('view')==='training'){await show('training');return}
 if(c)openCompetition(c).catch(e=>notice(e.message,true));
});
})();

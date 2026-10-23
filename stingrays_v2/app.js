(()=>{'use strict';
const $=id=>document.getElementById(id);let user=null,players=[],competitions=[],selected=null,playing=null,previewId=null;
function notice(text,error=false){$('message').textContent=text||'';$('message').className=error?'error':'';if(error)window.scrollTo(0,0)}
async function api(path,data){const options={credentials:'same-origin',headers:{'Accept':'application/json'}};if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const res=await fetch('/dart/v2/api'+path,options);const txt=await res.text();let j={};try{j=JSON.parse(txt)}catch{}if(!res.ok)throw Error(j.error||txt||'HTTP '+res.status);return j}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
function clear(node){node.replaceChildren()}
function el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x}
function btn(label,fn){const x=el('button',label);x.type='button';x.onclick=fn;return x}
function tile(title,sub,fn){const x=btn('',fn);x.className='tile';x.append(el('strong',title),el('small',sub));return x}
// Jede Partie bekommt die gesamte aktuelle Browseransicht – KEIN zweiter Tab.
// Zur Verwaltung gelangt man über den Zurück-Link des Scorers.
function openGameWindow(url){window.location.assign(url);return true}
function launchTrainingWindow(kind){
 if(kind==='sau'||kind==='tug'||kind==='bobs')return window.location.assign('/dart/v2/training/scorer/?kind='+encodeURIComponent(kind==='bobs'?'bobs27':kind));
 window.location.assign('/dart/v2/?training='+encodeURIComponent(kind));
}

// In-app configuration sheet: never uses blocking browser prompts.
function configure(title,fields,submitText='Speichern'){
 return new Promise(resolve=>{
  const shade=el('div',undefined,'sheet-shade'),panel=el('section',undefined,'config-sheet'),heading=el('h2',title),form=el('form',undefined,'sheet-form');
  form.append(heading);
  for(const f of fields){const label=el('label',f.label||f.name);let control;
   if(f.type==='select'){control=el('select');for(const [id,name] of f.options||[])control.append(new Option(name,id));if(f.value!==undefined)control.value=String(f.value)}
   else if(f.type==='multi'){control=el('div',undefined,'checklist');for(const [id,name] of f.options||[]){const l=el('label');const cb=document.createElement('input');cb.type='checkbox';cb.name=f.name;cb.value=id;cb.checked=(f.value||[]).includes(id);l.append(cb,el('span',name));control.append(l)}}
   else if(f.type==='textarea'){control=el('textarea');control.value=f.value||''}
   else {control=document.createElement('input');control.type=f.type||'text';control.value=f.value??'';if(f.min!==undefined)control.min=f.min;if(f.max!==undefined)control.max=f.max;if(f.step!==undefined)control.step=f.step;}
   if(f.type!=='multi'){control.name=f.name;control.required=!!f.required}
   if(f.readonly)control.readOnly=true;
   label.append(control);form.append(label)}
  const foot=el('div',undefined,'sheet-actions'),cancel=btn('Abbrechen',()=>finish(null)),ok=document.createElement('button');ok.type='submit';ok.textContent=submitText;
  foot.append(cancel,ok);form.append(foot);panel.append(form);shade.append(panel);document.body.append(shade);
  const finish=data=>{shade.remove();resolve(data)};
  shade.onclick=e=>{if(e.target===shade)finish(null)};
  form.onsubmit=e=>{e.preventDefault();const result=Object.fromEntries(new FormData(form).entries());for(const f of fields)if(f.type==='multi')result[f.name]=[...form.querySelectorAll('input[name="'+f.name+'"]:checked')].map(x=>x.value);finish(result)};
  form.querySelector('input,select,textarea')?.focus();
 })
}
async function approve(title,text){return !!await configure(title,[{name:'ack',label:text,type:'select',options:[['','Bitte wählen'],['yes','Ja, ausführen']],required:true}],'Bestätigen').then(x=>x?.ack==='yes')}
const amAdmin=()=>user?.role==='admin';
const trainingOwner=()=>selected?.competition?.kind==='training_tournament'&&selected?.competition?.created_by===user?.id;
function section(name){for(const id of ['setup','login','changePassword','dashboard','training','ladder','competitions','boards','members','statistics','admin','scorer'])$(id).hidden=id!==name;$('nav').hidden=!user||['login','setup','changePassword'].includes(name);for(const b of document.querySelectorAll('nav [data-view]')){b.classList.toggle('active',b.dataset.view===name);b.style.display=b.classList.contains('admin')&&!amAdmin()?'none':(b.dataset.view==='boards'&&user?.role==='member'?'none':'')}notice('')}
async function session(){try{user=await api('/me');if(user.must_change_password){section('changePassword');return}section('dashboard');await show('dashboard')}catch{user=null;section('login')}}
async function show(view){section(view);try{if(view==='dashboard')await dashboard();if(view==='competitions')await loadCompetitions();if(view==='training')await loadTraining();if(view==='ladder')await loadLadder();if(view==='boards')await loadBoards();if(view==='members')await loadPlayers();if(view==='statistics'){await loadPlayers();fillPlayerSelect('statPlayer',false)}if(view==='admin'){if(user.role!=='admin')throw Error('Nur Administratoren');await loadPlayers();fillPlayerSelect('accountPlayer',true);fillPlayerSelect('previewPlayer',false)}}catch(e){notice(e.message,true)}}
for(const b of document.querySelectorAll('nav [data-view]'))b.onclick=()=>show(b.dataset.view);
$('firstAdmin').onclick=()=>section('setup');
$('setupForm').onsubmit=async e=>{e.preventDefault();try{await api('/bootstrap',formData(e.target));section('login');notice('Administrator erstellt. Bitte anmelden.')}catch(err){notice(err.message,true)}};
$('loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/login',formData(e.target));await session()}catch(err){notice(err.message,true)}};
$('passwordForm').onsubmit=async e=>{e.preventDefault();try{await api('/password',formData(e.target));await session()}catch(err){notice(err.message,true)}};
$('logout').onclick=async()=>{try{await api('/logout',{})}catch{}user=null;section('login')};
async function dashboard(){
 const d=await api('/dashboard'+(previewId?'?player_id='+encodeURIComponent(previewId):''));
 const label=$('previewLabel');label.hidden=!previewId;$('previewBack').hidden=!previewId;
 if(previewId)label.textContent='SCHREIBGESCHÜTZTE VORSCHAU: '+(d.profile?.display_name||'Spieler')+' – keine Spiele im Namen dieses Mitglieds starten.';
 $('dashboardGreeting').textContent=d.profile?'Dein Dashboard · '+d.profile.display_name:'Dashboard · '+user.username;
 const summary=$('summary');clear(summary);
 let performance={};if(d.viewed_player_id){try{performance=await api('/players/'+d.viewed_player_id+'/stats?kind=overall')}catch(e){console.warn('Dashboard-Statistik nicht abrufbar',e)}}
 const tiles=[['Aktive Wettbewerbe',d.competitions.filter(c=>c.status==='active').length],
  ['Offene Begegnungen',d.own_open.length],['Letzte 12 · Siege',d.recent_totals.wins],
  ['Letzte 12 · Bilanz',d.recent_totals.wins+' / '+d.recent_totals.draws+' / '+d.recent_totals.losses],
  ['Ø Average',performance.average??'–'],['Ø First 9',performance.first9??'–'],
  ['180er',performance['180']??'–'],['95+',performance['95plus']??'–']];
 for(const [title,value] of tiles){const x=el('article',undefined,'dash-kpi');x.append(el('span',title),el('strong',String(value)));summary.append(x)}
 const ladders=$('dashboardLadder');clear(ladders);
 for(const l of d.ladder){const card=el('article',undefined,'dash-ladder-card');card.append(el('strong',l.title),el('b',l.played?Number(l.elo).toFixed(1)+' ELO · Platz '+l.position:'1000 ELO · Noch kein Spiel'),el('small',l.played+' Spiele · '+l.wins+' S / '+l.draws+' U / '+l.losses+' N'));card.append(action('Rangliste',()=>openCompetition(l.competition_id),'subtle'));ladders.append(card)}
 if(!d.ladder.length)ladders.append(el('p','Keine aktive Ladder-Teilnahme vorhanden.','helper'));
 const tournaments=$('dashboardCompetitions');clear(tournaments);
 for(const c of d.competitions){const x=el('article',undefined,'dash-competition');x.append(el('strong',c.title),el('small',(kindNames[c.kind]||c.kind)+' · '+c.status+' · '+c.open_games+' eigene offene Spiele'));
 x.append(action('Öffnen',()=>openCompetition(c.id),'subtle'));tournaments.append(x)}
 if(!d.competitions.length)tournaments.append(el('p','Noch keine Wettbewerbe eingetragen.','helper'));
 const list=$('myOpen');clear(list);
 for(const m of d.own_open){const x=el('div',undefined,'dash-match');x.append(el('div',m.title+' · '+m.player1+' – '+m.player2),el('span',m.status==='running'?'Laufend':'Offen','chip'));
 x.append(action(previewId?'Spiel ansehen':'Scorer starten',()=>previewId?notice('Die Vorschau ist schreibgeschützt.',true):openScorer(m.id),'primary'));list.append(x)}
 if(!d.own_open.length)list.append(el('p','Keine offenen Begegnungen','helper'));
 const recent=$('dashboardRecent');clear(recent);
 for(const m of d.recent){const ownLeft=m.player1_id===d.viewed_player_id;const score=((m.sets1||m.sets2)?m.sets1:m.legs1)+':'+((m.sets1||m.sets2)?m.sets2:m.legs2);
 const x=el('article',undefined,'dash-result');x.append(el('div',m.player1+' – '+m.player2+' · '+m.title),el('strong',score),el('small',m.finished_at?new Date(m.finished_at).toLocaleDateString('de-DE'):'Abgeschlossen'));recent.append(x)}
 if(!d.recent.length)recent.append(el('p','Noch keine abgeschlossenen Wettbewerbsspiele.','helper'));
}
async function loadPlayers(){players=await api('/players');renderPlayers()}
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
function renderPlayers(){
 const q=$('memberSearch').value.toLocaleLowerCase('de');const host=$('membersList');clear(host);
 for(const p of players.filter(p=>p.display_name.toLocaleLowerCase('de').includes(q))){
  const t=el('article',undefined,'member-tile');t.append(el('strong',p.display_name),el('small',p.username?'Konto: '+p.username+' · '+p.role:'Ohne Benutzerkonto'));
  const foot=el('div',undefined,'member-actions');if(amAdmin()&&!p.username)foot.append(action('Zugang erstellen',()=>newAccountForPlayer(p),'primary'));
  if(amAdmin()&&p.username)foot.append(el('span',p.is_enabled?'Zugang aktiv':'Zugang gesperrt','helper'));
  t.append(foot);host.append(t)
 }
}
$('memberSearch').oninput=renderPlayers;
function fillPlayerSelect(id,blank){const host=$(id);clear(host);if(blank)host.append(new Option('Turnierkonto ohne Spieler',''));for(const p of players)host.append(new Option(p.display_name,p.id))}
async function loadCompetitions(){
 $('createCompetitionWizard').hidden=!amAdmin();competitions=await api('/competitions');const host=$('competitionsList');clear(host);for(const c of competitions.filter(x=>x.kind!=='training_tournament'||amAdmin()||x.created_by===user.id||x.owner===user.id))host.append(tile(c.title,(kindNames[c.kind]||c.kind)+' · '+c.status+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)))}
async function loadLadder(){const data=await api('/competitions'),host=$('ladderList');clear(host);const ladders=data.filter(c=>c.kind==='ladder');for(const c of ladders)host.append(tile(c.title,(c.status||'')+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)));if(!ladders.length)host.append(el('p','Noch keine Ladder-Saison angelegt. Administratoren können hier die erste Saison erstellen.'));$('ladderCreate').hidden=user.role!=='admin'}
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
 const d=await configure('Neues Trainingsturnier',[{name:'title',label:'Turniername',required:true,value:'Trainingsturnier'}],'Turnier erstellen');if(!d)return;
 try{const c=await api('/competitions',{kind:'training_tournament',title:d.title});await show('training');await openCompetition(c.id)}catch(e){notice(e.message,true)}
}
$('newTraining').onclick=createTraining;
$('dashTraining').onclick=()=>show('training');
$('createCompetitionWizard').onclick=createCompetitionWizard;
$('createCompetitionAdmin').onclick=createCompetitionWizard;
async function quickTraining(){
 try{
  if(!players.length)players=await api('/players');
  const own=user.player_id,opts=players.filter(p=>p.is_active && p.id!==own);
  const d=await configure('X01-Trainingsmatch',[{name:'other',label:'Gegner',type:'select',options:opts.map(p=>[p.id,p.display_name]),required:true},
      {name:'mode',label:'Spielmodus',type:'select',options:[['legs','Legs'],['sets','Sets']]},
      {name:'best',label:'Best of Legs / Sets',type:'number',value:5,min:1,max:101,required:true},
      {name:'per',label:'Legs pro Set (nur Setmodus)',type:'number',value:3,min:1,max:21}], 'Training starten');
  if(!d)return;if(!own)return notice('Deinem Konto ist kein Spielerprofil zugeordnet.',true);
  const best=Number(d.best),per=Number(d.per);if(d.mode==='sets'&&(best%2!==1||per%2!==1))return notice('Setmodus benötigt ungerade Werte.',true);
  // A free training game is not a competition and must never appear in tournament tables.
  const m=await api('/free-x01',{other_id:d.other,rules:{start_score:501,mode:d.mode,
    max_legs:best,best_of_sets:best,best_of_legs_per_set:per,allow_draw:d.mode==='legs'&&best%2===0}});
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


async function loadTraining(){
 const host=$('trainingList');clear(host);const data=await api('/competitions');
 for(const c of data.filter(x=>x.kind==='training_tournament'&&(amAdmin()||x.created_by===user.id)))host.append(tile(c.title,c.players+' Teilnehmer · '+c.status,()=>openCompetition(c.id)));
 if(!host.children.length)host.append(el('p','Du hast noch kein Trainingsturnier erstellt.'));
}

$('previewOpen').onclick=async()=>{if(user?.role!=='admin')return;previewId=$('previewPlayer').value;await show('dashboard')};
$('previewExit').onclick=async()=>{previewId=null;await show('dashboard')};$('previewBack').onclick=$('previewExit').onclick;
async function loadBoards(){const boards=await api('/boards'),host=$('boardsList');clear(host);for(const b of boards){const t=el('article',undefined,'board '+(!b.enabled?'inactive':b.match_id?'busy':''));t.append(el('strong',b.label),el('p',!b.enabled?'Deaktiviert':b.match_id?'Belegt: '+b.competition:'Frei'));
 if(b.match_id&&user.role!=='member')t.append(action('Scorer öffnen',()=>openScorer(b.match_id),'primary'));
 if(amAdmin())t.append(action('Bearbeiten',async()=>{const d=await configure('Board '+b.id,[{name:'label',label:'Bezeichnung',value:b.label,required:true},{name:'enabled',type:'select',label:'Status',value:String(b.enabled),options:[['true','Aktiv'],['false','Deaktiviert']]}]);if(!d)return;try{await api('/boards/'+b.id,{label:d.label,enabled:d.enabled==='true'});await loadBoards()}catch(e){notice(e.message,true)}}));host.append(t)}}
const table=(headers,rows)=>{const outer=el('div',undefined,'scroll'),tab=el('table',undefined,'data-table'),head=el('thead'),tr=el('tr');for(const h of headers)tr.append(el('th',h));head.append(tr);tab.append(head);const tb=el('tbody');for(const row of rows){const line=el('tr');for(const val of row)line.append(el('td',String(val??'–')));tb.append(line)}tab.append(tb);outer.append(tab);return outer};
const kindNames={league:'Stingray League',cup:'Stingray Cup',ladder:'Stingray Ladder',vm:'Vereinsmeisterschaft',training_tournament:'Trainingsturnier',final_tournament:'Finalrunde'};
let competitionTab='table',schedulePage=0;
function action(text,fn,style=''){const b=btn(text,fn);if(style)b.className=style;return b}
function picker(items,selectedValue,callback){const select=el('select');for(const [v,t] of items)select.append(new Option(t,v));select.value=selectedValue;select.onchange=()=>callback(select.value);return select}
function labelFor(m,names){return (names.get(m.player1_id)||'Offen')+' – '+(names.get(m.player2_id)||'Offen')}
async function openCompetition(id){
  selected=await api('/competitions/'+id);if(amAdmin()||trainingOwner())players=await api('/players');section('competitions');
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
    try{if(tab==='table')await showTables(content);if(tab==='schedule')showSchedule(content);if(tab==='participants')showParticipants(content);if(tab==='records')showRecords(content);if(tab==='management')showManagement(content)}
    catch(e){content.append(el('p',e.message,'error'))}
  }
  for(const [tab,name] of [['table',c.kind==='ladder'?'ELO-Rangliste':'Tabellen'],['schedule','Spielplan'],['participants','Teilnehmer'],['records','Bestleistungen & Statistik'],...((amAdmin()||trainingOwner())?[['management','Verwaltung']]:[])]){
    const b=action(name,()=>view(tab));b.dataset.tab=tab;tabs.append(b);
  }
  const names=new Map(selected.entries.map(e=>[e.player_id,e.display_name]));
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
        const cells=[data.rows.indexOf(r)+1,null,r.played,r.wins,r.draws,r.losses,r.legs_for+':'+r.legs_against,signed(r.legs_for-r.legs_against),Number(r.elo).toFixed(1),(r.win_percent??0)+' %',r.average_opponent_elo??'–',r.own_average??'–',r.opponent_average??'–',r.distinct_opponents];
        for(const cell of cells){const td=el('td');if(cell===null){const link=action(r.display_name,()=>showPlayerHistory(r),'ladder-name');td.append(link)}else td.textContent=String(cell);tr.append(td)}body.append(tr)
       }table.append(body);host.append(table);area.append(host);
       area.append(el('p','Gold = aktuell innerhalb der Finalplätze und Mindestbedingungen erfüllt. Die eigene Ansicht zeigt bei Bedarf nur berechtigte Spieler.','helper'));
      }draw();return;
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
  async function showRecords(box){
    const row=el('div',undefined,'filterline');box.append(el('p','Matchstatistiken werden nur aus tatsächlich erfassten Aufnahmen berechnet. Importierte Altdaten enthalten keine erfundenen Wurfwerte.','helper'));
    const who=picker([['','Spieler wählen'],...selected.entries.map(e=>[e.player_id,e.display_name])],'',()=>{});
    row.append(who,action('Auswerten',async()=>{if(!who.value)return;const stats=await api('/players/'+who.value+'/stats?kind='+c.kind+'&competition_id='+encodeURIComponent(id));const head=await api('/players/'+who.value+'/h2h?kind='+c.kind+'&competition_id='+encodeURIComponent(id));const dest=$('currentStats');clear(dest);
      statisticsPanels(dest,stats,head,c.kind);
    }));box.append(row);const out=el('div');out.id='currentStats';box.append(out);
  }
  function showSchedule(box){
    if(c.kind==='training_tournament'&&(amAdmin()||trainingOwner())){
      const panel=el('div',undefined,'panel ladder-create');panel.append(el('h3','Trainingsmatch anlegen'));
      const people=selected.entries.filter(x=>x.status==='active');const one=picker([['','Spieler 1'],...people.map(x=>[x.player_id,x.display_name])],'',()=>{}),two=picker([['','Spieler 2'],...people.map(x=>[x.player_id,x.display_name])],'',()=>{});
      const mode=picker([['legs','Legs'],['sets','Sets']],'legs',()=>{});const length=document.createElement('input');length.type='number';length.min='1';length.max='101';length.value='5';
      for(const [l,f] of [['Spieler 1',one],['Spieler 2',two],['Modus',mode],['Best of X',length]]){const label=el('label',l);label.append(f);panel.append(label)}
      panel.append(action('Trainingsmatch hinzufügen',async()=>{if(!one.value||!two.value||one.value===two.value)return notice('Zwei verschiedene Spieler wählen',true);
        const n=Number(length.value);if(n<1||n>101||mode.value==='sets'&&n%2===0)return notice('Ungültige Matchlänge',true);
        try{await api('/competitions/'+id+'/matches',{player1_id:one.value,player2_id:two.value,rules:{mode:mode.value,max_legs:n,best_of_sets:n,best_of_legs_per_set:3,allow_draw:mode.value==='legs'&&n%2===0}});await openCompetition(id)}catch(e){notice(e.message,true)}
      }));box.append(panel);
    }
    if(c.kind==='ladder'){
      const add=el('div',undefined,'panel ladder-create');add.append(el('h3','Ladder-Match vereinbaren'));
      const first=picker([['','Spieler 1'],...selected.entries.filter(e=>e.status!=='withdrawn').map(e=>[e.player_id,e.display_name])],'',()=>{});
      const second=picker([['','Spieler 2'],...selected.entries.filter(e=>e.status!=='withdrawn').map(e=>[e.player_id,e.display_name])],'',()=>{});
      const best=document.createElement('input');best.type='number';best.min='5';best.max='101';best.value='6';best.step='1';best.setAttribute('aria-label','Best of X Legs');
      const mode=picker([['legs','Best of X Legs'],['sets','Best of X Sets (je 3 Legs)']],'legs',()=>{});
      for(const [label,input] of [['Spieler 1',first],['Spieler 2',second],['Modus',mode],['Best of X (mind. 5)',best]]){const l=el('label',label);l.append(input);add.append(l)}
      add.append(action('Match vereinbaren',async()=>{
        if(!first.value||!second.value||first.value===second.value)return notice('Zwei verschiedene Spieler auswählen.',true);
        if(Number(best.value)<(mode.value==='sets'?1:5)||Number(best.value)>101||mode.value==='sets'&&Number(best.value)%2===0)return notice('Legs ab 5, Sets nur ungerade (bis 101).',true);
        try{const r=await api('/competitions/'+id+'/matches',{player1_id:first.value,player2_id:second.value,rules:{mode:mode.value,max_legs:Number(best.value),best_of_sets:Number(best.value),best_of_legs_per_set:3,allow_draw:mode.value==='legs'&&Number(best.value)%2===0}});await openCompetition(id);notice('Match angelegt – im Spielplan auf Scorer klicken.')}catch(e){notice(e.message,true)}
      },'primary'));box.append(add);
    }
    const filters=el('div',undefined,'schedule-controls');
    const g=picker([['','Alle Staffeln'],...selected.groups.map(x=>[x.id,x.name])],'',()=>reset());
    const p=picker([['','Alle Spieler'],...selected.entries.map(e=>[e.player_id,e.display_name])],'',()=>reset());
    const status=picker([['','Alle Spiele'],['open','Offen'],['running','Laufend'],['finished','Beendet']],'',()=>reset());
    for(const [caption,select] of [...(c.kind==='ladder'?[]:[['Staffel',g]]),['Spieler',p],['Status',status]]){const label=el('label',caption);label.append(select);filters.append(label)}
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
        else if(m.status==='finished'||amAdmin()||user.role==='tournament'||[m.player1_id,m.player2_id].includes(user.player_id))actions.append(action(m.status==='finished'?'Spiel ansehen':'Scorer',()=>openScorer(m.id),'primary'));
        if((amAdmin()||trainingOwner())&&['running','cancelled'].includes(m.status))actions.append(action('Auf OPEN zurücksetzen',async()=>{
          const data=await configure('Begegnung zurücksetzen',[
            {name:'reason',label:'Grund (Audit-Protokoll)',value:'Testspiel neu starten',required:true},
            {name:'confirmation',label:'Dabei gehen alle erfassten Aufnahmen dieses Spiels verloren.',type:'select',required:true,options:[['','Bitte auswählen'],['yes','Spiel zurücksetzen']]}], 'Zurücksetzen');
          if(!data||data.confirmation!=='yes')return;
          try{await api('/matches/'+m.id+'/reset',{reason:data.reason,confirm:'ZURUECKSETZEN'});await openCompetition(id);notice('Begegnung ist wieder OPEN.')}catch(e){notice(e.message,true)}
        },'danger'));
        if(user.role==='admin'&&m.status==='open')actions.append(action('Altes Ergebnis',async()=>{
          const d=await configure('Altes Ergebnis erfassen',[{name:'score',label:'Endstand (z.B. 4:2)',required:true}]);if(!d)return;const raw=d.score;
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
    box.append(action('Ladder nach Saisonende abschließen',async()=>{if(!await approve('Ladder abschließen','Offene Matches nach Saisonende abbrechen und ELO einfrieren?'))return;try{await api('/competitions/'+id+'/end-ladder',{});await openCompetition(id)}catch(e){notice(e.message,true)}},'danger'));
    box.append(action('Wettbewerb archivieren',async()=>{if(!await approve('Ladder archivieren','Saison aus der aktiven Übersicht ins Archiv verschieben?'))return;try{await api('/competitions/'+id+'/status',{status:'archived'});await openCompetition(id)}catch(e){notice(e.message,true)}}));
    box.append(action('Testwettbewerb löschen',async()=>{if(!await approve('Ladder ausblenden','Achtung: Dieser Wettbewerb wird aus der Statistik entfernt.'))return;try{await api('/competitions/'+id+'/delete',{confirm:'DAUERHAFT AUSBLENDEN'});$('competitionDetail').hidden=true;await loadCompetitions()}catch(e){notice(e.message,true)}},'danger'));
  }
  function showManagement(box){
    if(!amAdmin()&&!trainingOwner())return;
    if(c.kind==='ladder'){showLadderAdmin(box);return}
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
      ladder.append(action('Ladder abschließen',async()=>{if(!await approve('Ladder beenden','Offene Spiele nach Saisonende abbrechen?'))return;try{await api('/competitions/'+id+'/end-ladder',{});await openCompetition(id)}catch(e){notice(e.message,true)}},'danger'));
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
 openGameWindow('/dart/v2/spiel/?match='+encodeURIComponent(id)+'&competition='+encodeURIComponent(selected?.competition?.id||''),id);
}
function drawScore(){if(!playing)return;const s=playing.state||{},names=s.names||[playing.player1,playing.player2],rest=s.remaining||[501,501];$('playerOne').textContent=names[0];$('playerTwo').textContent=names[1];$('remainOne').textContent=rest[0];$('remainTwo').textContent=rest[1];$('resultOne').textContent='Legs '+(s.legs?.[0]??playing.legs1??0)+' · Sets '+(s.sets?.[0]??0);$('resultTwo').textContent='Legs '+(s.legs?.[1]??playing.legs2??0)+' · Sets '+(s.sets?.[1]??0);for(let i=0;i<2;i++)document.querySelectorAll('.scorecard')[i].classList.toggle('current',s.current===i&&!s.done);$('toThrow').textContent=s.done?'Spiel beendet':names[s.current??0]+' wirft';$('throwForm').hidden=s.done||playing.status==='finished'||!playing.can_score;$('scoreStatus').textContent='Version '+playing.state_version;const host=$('visits');clear(host);for(const v of (s.visits||[]).slice().reverse())host.append(el('p',names[v.player]+': '+v.score+' / '+v.darts+' Darts'+(v.checkout?' · Checkout':'')+(v.bust?' · Bust':'')))}
$('throwForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);try{const r=await api('/matches/'+playing.id+'/throw',{points:Number(d.points),darts:Number(d.darts),checkout:!!d.checkout,bullfinish:!!d.bullfinish,version:playing.state_version});playing.state=r.state;playing.state_version=r.version;e.target.reset();e.target.elements.darts.value=3;drawScore()}catch(err){notice(err.message,true)}};
$('backToCompetition').onclick=()=>selected?openCompetition(selected.competition.id):show('dashboard');
const statsLabels={matches:'Spiele',wins:'Siege',draws:'Unentschieden',losses:'Niederlagen',legs_for:'Gewonnene Legs',legs_against:'Verlorene Legs',scored_visits:'Aufnahmen',average:'Ø Average',first9:'Ø First 9',lowdarts:'Lowdarts (9–18)',highfinishes:'Highfinishes (100+)',bullfinishes:'Bullfinishes',highscores:'Highscores (171+)',training_sau_sessions:'Gegen die Sau',training_bobs_sessions:'Bobs 27',training_tug_sessions:'Tauziehen',training_bobs_best:'Bobs 27 – Bestwert',training_sau_marks:'Sau-Striche',training_sau_success:'Sau – Checkouts','180':'180er','100plus':'100+','140plus':'140+','171plus':'171+','95plus':'95+','133plus':'133+','exact133':'133 exakt',missing_throw_stats_matches:'Spiele ohne Wurfdaten'};
function multiplicities(values){const counts=new Map();for(const x of values||[])counts.set(String(x),(counts.get(String(x))||0)+1);return [...counts.entries()].sort((a,b)=>Number(b[0])-Number(a[0])).map(([value,n])=>n+'× '+value).join(' · ')||'–'}
function statValue(k,v){if(Array.isArray(v))return multiplicities(v);if(v===null||v===undefined)return '–';if(typeof v==='number')return String(v).replace('.',',');return String(v)}
function statisticsPanels(host,stats,h2h,scope){
 clear(host);host.className='stats-dashboard';
 const show=(key)=>stats[key]!==null&&stats[key]!==undefined;
 const pretty=(key)=>statValue(key,stats[key]);
 function panel(title,classname='') {const p=el('section',undefined,'stat-block '+classname);p.append(el('h3',title));host.append(p);return p}
 function cards(p,keys){const grid=el('div',undefined,'stat-cards');for(const k of keys){if(!show(k))continue;
   const card=el('article',undefined,'stat-card');card.append(el('span',statsLabels[k]||k),el('strong',pretty(k)));grid.append(card)}p.append(grid)}
 cards(panel('Spielbilanz','stat-wide'),['matches','wins','draws','losses','legs_for','legs_against']);
 cards(panel('Durchschnitt & Aufnahmen','stat-wide'),['average','first9','scored_visits','missing_throw_stats_matches']);
 cards(panel('Scoring & Specials','stat-wide'),['95plus','100plus','133plus','exact133','140plus','171plus','180','bullfinishes']);
 const best=panel('Bestleistungen im Detail','stat-wide');
 for(const [label,k] of [['Highfinishes','highfinish_details'],['Lowdarts','lowdart_details'],['Bullfinishes','bullfinish_details'],['Highscores','highscores']]){
  if(!show(k))continue;const row=el('div',undefined,'stat-detail-row');row.append(el('b',label),el('span',multiplicities(stats[k])));best.append(row)}
 if(scope==='overall'||scope==='training_tournament')cards(panel('Training','stat-wide'),['training_sau_sessions','training_sau_success','training_sau_marks','training_bobs_sessions','training_bobs_best','training_tug_sessions']);
 const h=panel('Head to Head','stat-wide');
 if(!h2h.length)h.append(el('p','Noch keine direkten Duelle in diesem Bereich.'));
 else{const list=el('div',undefined,'h2h-rows');for(const o of h2h){const row=el('div',undefined,'h2h-row');row.append(el('b',o.opponent),el('span',o.played+' Spiele'),el('span',o.wins+' S · '+o.draws+' U · '+o.losses+' N'),el('span',o.legs_for+':'+o.legs_against+' Legs'));list.append(row)}h.append(list)}
}
$('statsLoad').onclick=async()=>{try{const pid=$('statPlayer').value,kind=$('statKind').value,s=await api('/players/'+pid+'/stats?kind='+kind),h=await api('/players/'+pid+'/h2h?kind='+kind);statisticsPanels($('statsResult'),s,h,kind)}catch(e){notice(e.message,true)}};
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

(()=>{'use strict';
const $=id=>document.getElementById(id);let user=null,players=[],competitions=[],selected=null,playing=null,previewId=null;
function notice(text,error=false){$('message').textContent=text||'';$('message').className=error?'error':'';if(error)window.scrollTo(0,0)}
async function api(path,data){const options={credentials:'same-origin',headers:{'Accept':'application/json'}};if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const res=await fetch('/dart/v2/api'+path,options);const txt=await res.text();let j={};try{j=JSON.parse(txt)}catch{}if(!res.ok)throw Error(j.error||txt||'HTTP '+res.status);return j}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
function clear(node){node.replaceChildren()}
function el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x}
function btn(label,fn){const x=el('button',label);x.type='button';x.onclick=fn;return x}
function tile(title,sub,fn){const x=btn('',fn);x.className='tile';x.append(el('strong',title),el('small',sub));return x}
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
async function dashboard(){const d=await api('/dashboard'+(previewId?'?player_id='+encodeURIComponent(previewId):''));const label=$('previewLabel');label.hidden=!previewId;$('previewBack').hidden=!previewId;if(previewId)label.textContent='SCHREIBGESCHÜTZTE VORSCHAU: '+(players.find(p=>p.id===previewId)?.display_name||previewId)+' – Spiele starten ist als Vorschau nicht möglich.';const host=$('summary');clear(host);for(const c of d.competitions)host.append(tile(c.title,c.kind+' · '+c.status+' · '+c.open_games+' offen',()=>openCompetition(c.id)));const list=$('myOpen');clear(list);if(!d.own_open.length)list.append(el('p','Keine offenen Begegnungen'));for(const m of d.own_open){const x=el('div',undefined,'matchrow');x.append(el('span',m.title+': '+m.player1+' – '+m.player2),btn(previewId?'Nur ansehen':'Spielen',()=>{if(previewId){notice('Spieleransicht ist schreibgeschützt. Zum Spielen Vorschau verlassen.',true);return}openScorer(m.id)}));list.append(x)}}
async function loadPlayers(){players=await api('/players');renderPlayers()}
function renderPlayers(){const q=$('memberSearch').value.toLocaleLowerCase('de');const host=$('membersList');clear(host);for(const p of players.filter(p=>p.display_name.toLocaleLowerCase('de').includes(q))){const t=el('article',undefined,'tile');t.append(el('strong',p.display_name),el('small',(p.legacy_profile_id||'Neues Profil')+' · '+(p.username?p.username+' / '+p.role:'Noch kein Konto')));host.append(t)}}
$('memberSearch').oninput=renderPlayers;
function fillPlayerSelect(id,blank){const host=$(id);clear(host);if(blank)host.append(new Option('Turnierkonto ohne Spieler',''));for(const p of players)host.append(new Option(p.display_name,p.id))}
async function loadCompetitions(){competitions=await api('/competitions');const host=$('competitionsList');clear(host);for(const c of competitions.filter(x=>x.kind!=='training_tournament'||amAdmin()||x.created_by===user.id||x.owner===user.id))host.append(tile(c.title,(kindNames[c.kind]||c.kind)+' · '+c.status+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)))}
async function loadLadder(){const data=await api('/competitions'),host=$('ladderList');clear(host);const ladders=data.filter(c=>c.kind==='ladder');for(const c of ladders)host.append(tile(c.title,(c.status||'')+' · '+c.players+' Teilnehmer',()=>openCompetition(c.id)));if(!ladders.length)host.append(el('p','Noch keine Ladder-Saison angelegt. Administratoren können hier die erste Saison erstellen.'));$('ladderCreate').hidden=user.role!=='admin'}
$('ladderForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);d.kind='ladder';d.starts_at=new Date(d.starts_at).toISOString();d.ends_at=new Date(d.ends_at).toISOString();try{const c=await api('/competitions',d);e.target.reset();await loadLadder();notice('Ladder angelegt – '+c.enrolled_members+' aktive Mitglieder automatisch übernommen. Die Tabelle zeigt Spieler erst nach dem ersten Match.')}catch(err){notice(err.message,true)}};
async function createTraining(){
 const d=await configure('Neues Trainingsturnier',[{name:'title',label:'Turniername',required:true,value:'Trainingsturnier'}],'Turnier erstellen');if(!d)return;
 try{const c=await api('/competitions',{kind:'training_tournament',title:d.title});await show('training');await openCompetition(c.id)}catch(e){notice(e.message,true)}
}
$('newTraining').onclick=createTraining;
$('quickTraining').onclick=async()=>{
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
  location.href='/dart/v2/spiel/?free=1&match='+encodeURIComponent(m.id);
 }catch(err){notice(err.message,true)}
};
// Same V2 account, results saved to Neon after finishing each solo discipline.
function startSolo(kind){
 const box=$('trainingMode');box.hidden=false;clear(box);let visits=[],marks={sau:0},round=1,rest=201,points=kind==='bobs'?27:201,finished=false;
 for(let i=4;i<=12;i++)marks[i]=0;
 const isBobs=kind==='bobs',target=10;
 box.append(el('h2',isBobs?'Bobs 27':'Gegen die Sau'));
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
 async function finish(){finished=true;button.disabled=true;form.hidden=true;const result=isBobs?{points,rounds:round-1}:{sau:marks.sau,checkouts:Object.entries(marks).filter(([k])=>k!=='sau').reduce((a,[,v])=>a+v,0),marks,rounds:round};
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
     if(round>10&&marks.sau>=target)await finish();
   }
   control.value='';checkout.checked=false;draw();
 };
 draw();
}
$('sauTraining').onclick=()=>startSolo('sau');$('bobsTraining').onclick=()=>startSolo('bobs');

// Tauziehen: same 181 -> 0 / 362 rules and per-round winner logic as the legacy scorer.
async function startTug(){
 if(!players.length)players=await api('/players');
 const own=user?.player_id;if(!own)return notice('Deinem Konto muss ein Spielerprofil zugeordnet sein.',true);
 const d=await configure('Tauziehen',[{name:'opponent',label:'Gegner',type:'select',options:players.filter(p=>p.is_active&&p.id!==own).map(p=>[p.id,p.display_name]),required:true},
  {name:'rounds',label:'Rundenzahl',type:'number',value:5,min:1,max:100,required:true}],'Tauziehen starten');
 if(!d)return;const opponent=players.find(p=>p.id===d.opponent);if(!opponent)return;
 const max=Number(d.rounds);if(!Number.isInteger(max)||max<1||max>100)return notice('Rundenzahl ungültig',true);
 const names=[players.find(p=>p.id===own)?.display_name||user.username,opponent.display_name];
 const box=$('trainingMode');box.hidden=false;clear(box);
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
$('tugTraining').onclick=startTug;


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
      const rows=await api('/competitions/'+id+'/standings');box.append(el('p','ELO · Ausgangswert 1000 · K-Faktor 64 · ein Spiel zählt ab Abschluss','helper'));
      box.append(renderTable(['PL','Name','Sp.','S','U','N','Legs','Diff','ELO','Siegquote','Ø ELO Gegner','Ø Average','Ø Average Gegner'],rows.map((r,i)=>[i+1,r.display_name,r.played,r.wins,r.draws,r.losses,r.legs_for+':'+r.legs_against,signed(r.legs_for-r.legs_against),r.elo,(r.win_percent??0)+' %',r.average_opponent_elo??'–',r.own_average??'–',r.opponent_average??'–'])));return;
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
      const labels={matches:'Spiele',wins:'Siege',draws:'Unentschieden',losses:'Niederlagen',legs_for:'Legs gewonnen',legs_against:'Legs verloren',average:'Ø Average',first9:'Ø First 9',lowdarts:'Lowdarts',highfinishes:'Highfinishes',bullfinishes:'Bullfinishes',scored_visits:'Aufnahmen',highscores:'Highscores',missing_throw_stats_matches:'Alte Spiele ohne Wurfdaten'};
      const entries=Object.entries(stats).filter(([k])=>!k.startsWith('training_')&&!['lowdart_details','highfinish_details','bullfinish_details'].includes(k));
      dest.append(el('h3','Bestleistungen / Kennzahlen'),renderTable(['Kennzahl','Ergebnis'],entries.map(([k,v])=>[labels[k]||k,Array.isArray(v)?(v.join(', ')||'–'):(v??'–')])));
      dest.append(el('h3','Head to Head'),renderTable(['Gegner','Spiele','S','U','N','Legs'],head.map(x=>[x.opponent,x.played,x.wins,x.draws,x.losses,x.legs_for+':'+x.legs_against])));
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
    box.append(el('p','Ladder: keine Gruppeneinteilung, keine automatische Paarungsliste. Matches können im Spielplan frei vereinbart werden.','helper'));
    const status=picker([['active','Aktiv'],['finished','Beendet'],['archived','Archiviert']],c.status,async value=>{try{await api('/competitions/'+id+'/status',{status:value});await openCompetition(id)}catch(e){notice(e.message,true)}});
    const l=el('label','Ladder-Status');l.append(status);box.append(l);
    box.append(action('Ladder nach Saisonende abschließen',async()=>{if(!await approve('Ladder abschließen','Offene Matches nach Saisonende abbrechen und ELO einfrieren?'))return;try{await api('/competitions/'+id+'/end-ladder',{});await openCompetition(id)}catch(e){notice(e.message,true)}},'danger'));
    box.append(action('Wettbewerb archivieren',async()=>{if(!await approve('Ladder archivieren','Saison aus der aktiven Übersicht ins Archiv verschieben?'))return;try{await api('/competitions/'+id+'/status',{status:'archived'});await openCompetition(id)}catch(e){notice(e.message,true)}}));
    box.append(action('Wettbewerb ausblenden',async()=>{if(!await approve('Ladder ausblenden','Achtung: Dieser Wettbewerb wird aus der Statistik entfernt.'))return;try{await api('/competitions/'+id+'/delete',{confirm:'DAUERHAFT AUSBLENDEN'});$('competitionDetail').hidden=true;await loadCompetitions()}catch(e){notice(e.message,true)}},'danger'));
  }
  function showManagement(box){
    if(!amAdmin()&&!trainingOwner())return;
    if(c.kind==='ladder'){showLadderAdmin(box);return}
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
    general.append(action('Wettbewerb ausblenden',async()=>{if(!await approve('Wettbewerb ausblenden','Wettbewerb dauerhaft aus aktiven Ansichten und Statistiken entfernen?'))return;try{await api('/competitions/'+id+'/delete',{confirm:'DAUERHAFT AUSBLENDEN'});host.hidden=true;await loadCompetitions()}catch(e){notice(e.message,true)}},'danger'));
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
 location.href='/dart/v2/spiel/?match='+encodeURIComponent(id)+'&competition='+encodeURIComponent(selected?.competition?.id||'');
}
function drawScore(){if(!playing)return;const s=playing.state||{},names=s.names||[playing.player1,playing.player2],rest=s.remaining||[501,501];$('playerOne').textContent=names[0];$('playerTwo').textContent=names[1];$('remainOne').textContent=rest[0];$('remainTwo').textContent=rest[1];$('resultOne').textContent='Legs '+(s.legs?.[0]??playing.legs1??0)+' · Sets '+(s.sets?.[0]??0);$('resultTwo').textContent='Legs '+(s.legs?.[1]??playing.legs2??0)+' · Sets '+(s.sets?.[1]??0);for(let i=0;i<2;i++)document.querySelectorAll('.scorecard')[i].classList.toggle('current',s.current===i&&!s.done);$('toThrow').textContent=s.done?'Spiel beendet':names[s.current??0]+' wirft';$('throwForm').hidden=s.done||playing.status==='finished'||!playing.can_score;$('scoreStatus').textContent='Version '+playing.state_version;const host=$('visits');clear(host);for(const v of (s.visits||[]).slice().reverse())host.append(el('p',names[v.player]+': '+v.score+' / '+v.darts+' Darts'+(v.checkout?' · Checkout':'')+(v.bust?' · Bust':'')))}
$('throwForm').onsubmit=async e=>{e.preventDefault();const d=formData(e.target);try{const r=await api('/matches/'+playing.id+'/throw',{points:Number(d.points),darts:Number(d.darts),checkout:!!d.checkout,bullfinish:!!d.bullfinish,version:playing.state_version});playing.state=r.state;playing.state_version=r.version;e.target.reset();e.target.elements.darts.value=3;drawScore()}catch(err){notice(err.message,true)}};
$('backToCompetition').onclick=()=>selected?openCompetition(selected.competition.id):show('dashboard');
$('statsLoad').onclick=async()=>{try{const pid=$('statPlayer').value,kind=$('statKind').value,s=await api('/players/'+pid+'/stats?kind='+kind),h=await api('/players/'+pid+'/h2h?kind='+kind),host=$('statsResult');clear(host);const titles={matches:'Spiele',wins:'Siege',draws:'Unentschieden',losses:'Niederlagen',legs_for:'Gewonnene Legs',legs_against:'Verlorene Legs',scored_visits:'Aufnahmen',average:'Ø Average',first9:'Ø First 9',lowdarts:'Lowdarts',highfinishes:'Highfinishes',bullfinishes:'Bullfinishes',highscores:'Highscores',training_sau_sessions:'Gegen die Sau',training_bobs_sessions:'Bobs 27',training_tug_sessions:'Tauziehen',training_bobs_best:'Bobs 27 – Bestwert',training_sau_marks:'Sau-Striche',training_sau_success:'Sau – Checkouts'};
 host.append(el('h2','Leistungen & Bestleistungen'),renderTable(['Kennzahl','Wert'],Object.entries(s).filter(([k])=>kind==='overall'||kind==='training_tournament'||!k.startsWith('training_')).map(([k,v])=>[titles[k]||k,Array.isArray(v)?(v.join(', ')||'–'):(v??'–')])));host.append(el('h2','Head to Head'),renderTable(['Gegner','Spiele','S','U','N','Legs'],h.map(o=>[o.opponent,o.played,o.wins,o.draws,o.losses,o.legs_for+':'+o.legs_against])))}catch(e){notice(e.message,true)}};
$('memberForm').onsubmit=async e=>{e.preventDefault();if(!amAdmin())return;try{await api('/players',formData(e.target));e.target.reset();await loadPlayers();notice('Mitglied erstellt')}catch(err){notice(err.message,true)}};
$('accountForm').onsubmit=async e=>{e.preventDefault();try{await api('/accounts',formData(e.target));e.target.reset();notice('Konto erstellt. Erstpasswort nur direkt an die betreffende Person weitergeben.')}catch(err){notice(err.message,true)}};
const migrationPanel=el('div',undefined,'panel');migrationPanel.append(el('h2','Vorhandene League und Profile übernehmen'),el('p','Übernahme erfolgt ausdrücklich als Kopie nach Neon. Die alte League bleibt unverändert.'));migrationPanel.append(btn('Aktive Google-Sheets-Profile nach Neon kopieren',async()=>{if(!await approve('Profile importieren','Aktive Profile nach Neon kopieren?'))return;try{const result=await api('/legacy/sync-profiles',{});notice(result.synced_active_profiles+' Profile kopiert');await loadPlayers()}catch(e){notice(e.message,true)}}));migrationPanel.append(btn('League-Migration: Vorschau',async()=>{try{const result=await api('/legacy/preview');if(!result.leagues.length){notice('Keine alten Liga-Snapshots gefunden');return}const d=await configure('League-Kopie nach Neon',[{name:'legacy_id',label:'Quellliga',type:'select',required:true,options:result.leagues.map(l=>[l.legacy_id,l.name+' ('+l.completed+'/'+l.fixtures+' gespielt)'])}],'Kopie prüfen');if(!d)return;
const choice=d.legacy_id;const source=result.leagues.find(l=>l.legacy_id===choice);
if(!source||!await approve('Import bestätigen','Liga '+source.name+' als eigenständige Kopie übernehmen?'))return;
const r=await api('/legacy/import',{legacy_id:choice,confirm:true});notice(r.fixtures+' Begegnungen in Neon kopiert');await show('competitions')}catch(e){notice(e.message,true)}}));$('admin').append(migrationPanel);
$('competitionForm').onsubmit=async e=>{e.preventDefault();let d=formData(e.target);for(const key of ['starts_at','ends_at']){if(d[key])d[key]=new Date(d[key]).toISOString();else delete d[key]}try{await api('/competitions',d);e.target.reset();notice('Wettbewerb erstellt');await show('competitions')}catch(err){notice(err.message,true)}};
session().then(()=>{const c=new URLSearchParams(location.search).get('competition');if(c&&user)openCompetition(c).catch(e=>notice(e.message,true))});
})();

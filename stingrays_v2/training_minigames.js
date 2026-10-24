/* Stingrays V2 training games – rules and UI, no external dependencies. */
(()=>{'use strict';
const GAMES={football:'Fußball',minigolf:'Minigolf',tictactoe:'Tic Tac Toe',connect4:'Vier gewinnt'};
const DOUBLE_TARGETS=[...Array.from({length:20},(_,i)=>i+1),25];
const LINES=[[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
const NODE=(tag,text,klass)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(klass)e.className=klass;return e};
const clone=o=>JSON.parse(JSON.stringify(o));
const validDartScores=[...new Set([0,25,50,...Array.from({length:20},(_,i)=>i+1),...Array.from({length:20},(_,i)=>(i+1)*2),...Array.from({length:20},(_,i)=>(i+1)*3)])];
const finishingDoubles=[...Array.from({length:20},(_,i)=>(i+1)*2),50];
const reachable=(doublesOnly)=>{const out=new Set();for(const a of validDartScores)for(const b of validDartScores)for(const c of (doublesOnly?finishingDoubles:validDartScores))if(a+b+c>0)out.add(a+b+c);return out};
const DOUBLE_CHECKS=reachable(true),SINGLE_CHECKS=reachable(false);
const validRange=(low,high,min,mode)=>{low=Number(low);high=Number(high);if(!Number.isInteger(low)||!Number.isInteger(high)||low<2||high>170||high<low)throw Error('Ungültiger Checkbereich (2 bis 170).');
 const pool=[];for(let i=low;i<=high;i++)if(DOUBLE_CHECKS.has(i))pool.push(i);
 if(pool.length<min||mode==='connect4'&&high-low<42)throw Error('Die Range braucht mindestens '+min+' unterschiedliche 3-Dart-Checks'+(mode==='connect4'?' und eine Spannweite von mindestens 42 Punkten':'')+'.');return pool};
const shuffle=(a,rng=Math.random)=>{const b=a.slice();for(let i=b.length-1;i>0;i--){const j=Math.floor(rng()*(i+1));[b[i],b[j]]=[b[j],b[i]]}return b};
const doubleName=t=>t===25?'Bull':'D'+t;
function ready(kind,settings,names,ids,rng=Math.random){
 if(!GAMES[kind]||!Array.isArray(ids)||!ids.length)throw Error('Ungültiger Trainingsmodus');
 const s={kind,settings:clone(settings),names:clone(names),ids:clone(ids),turn:0,dart:0,throws:[],winner:null,done:false,
  board:[],targets:[],possession:-1,goals:[0,0],doubleIndex:0,hitDoubles:[],phase:'outbound',targetIndex:0,
  golfScores:ids.map(()=>[]),golfSnapshots:ids.map(()=>[]),checkPositions:ids.map(()=>0),checkAttempts:ids.map(()=>0)};
 if(kind==='football'&&ids.length!==2)throw Error('Fußball benötigt zwei Spieler');
 if(kind==='minigolf'&&!['none','final','all'].includes(settings.returnMode))throw Error('Minigolf-Rückweg ungültig');
 if(kind==='tictactoe'){s.board=Array(9).fill(-1);s.targets=shuffle(settings.variant==='checks'?validRange(settings.low,settings.high,9,kind):DOUBLE_TARGETS,rng).slice(0,9)}
 if(kind==='connect4'){s.board=Array.from({length:6},()=>Array(7).fill(-1));s.targets=shuffle(validRange(settings.low,settings.high,42,kind),rng).slice(0,42)}
 return s;
}
function win(s){
 if(s.kind==='tictactoe'){for(const line of LINES)if(s.board[line[0]]>=0&&line.every(i=>s.board[i]===s.board[line[0]]))return s.board[line[0]];if(s.board.every(x=>x>=0))return -2}
 if(s.kind==='connect4'){for(let r=0;r<6;r++)for(let c=0;c<7;c++){const p=s.board[r][c];if(p<0)continue;for(const [dr,dc] of [[1,0],[0,1],[1,1],[1,-1]])if(Array.from({length:4},(_,i)=>[r+i*dr,c+i*dc]).every(([y,x])=>y>=0&&y<6&&x>=0&&x<7&&s.board[y][x]===p))return p}
  if(s.board.every(row=>row.every(x=>x>=0)))return -2}
 return null;
}
function advanceGolf(s){
 s.dart=0;
 if(s.turn+1<s.ids.length){s.turn++;return}
 s.turn=0;s.targetIndex++;
 if(s.targetIndex<21)return;
 if(s.settings.returnMode==='none'){finishGolf(s);return}
 s.phase='return';s.targetIndex=20;
}
function finishGolf(s){const totals=s.golfScores.map(x=>x.reduce((a,b)=>a+b,0));s.done=true;s.phase='done';s.winner=totals.length===1?0:totals[0]===totals[1]?-2:totals[0]<totals[1]?0:1}
function golfChecks(s,p){return s.settings.returnMode==='final'?[s.golfSnapshots[p][20]]:s.golfSnapshots[p].slice().reverse()}
function nextReturnPlayer(s){
 const done=s.ids.every((_,i)=>s.checkPositions[i]>=golfChecks(s,i).length);
 if(done){finishGolf(s);return}
 for(let k=0;k<s.ids.length;k++){const i=(s.turn+1+k)%s.ids.length;if(s.checkPositions[i]<golfChecks(s,i).length){s.turn=i;return}}
}
function record(s,operation,target,label){s.throws.push({player:s.turn,operation,target:target??null,label,phase:s.phase,dartsInVisit:s.dart+1})}
function throwDart(s,op,target){
 if(s.done)throw Error('Dieses Spiel ist beendet');let label='';
 if(s.kind==='football'){
  if(!['singlebull','bullseye','double','miss'].includes(op))throw Error('Ungültiger Fußball-Wurf');
  if(op==='singlebull'){s.possession=s.turn;label='Single Bull: Ball erobert'}
  else if(op==='bullseye'){s.possession=s.turn;s.goals[s.turn]++;label='Vollbull: Ball erobert + 1 Tor';
   if(s.doubleIndex===20){s.hitDoubles.push({target:25,player:s.turn});s.doubleIndex=21;s.done=true;s.winner=s.goals[0]===s.goals[1]?-2:s.goals[0]>s.goals[1]?0:1}}
  else if(op==='double'){if(s.doubleIndex>=20)throw Error('Jetzt muss Vollbull getroffen werden');if(s.possession!==s.turn)throw Error('Zuerst den Ball durch Bull erobern');
   const t=DOUBLE_TARGETS[s.doubleIndex];s.hitDoubles.push({target:t,player:s.turn});s.doubleIndex++;s.goals[s.turn]++;label=doubleName(t)+' getroffen – Tor'}
  else label='Fehlwurf';
 }else if(s.kind==='minigolf'){
  if(s.phase==='outbound'){
   if(!['hit','miss'].includes(op))throw Error('Treffer oder Fehlwurf auswählen');
   const t=DOUBLE_TARGETS[s.targetIndex];label=doubleName(t)+': '+(op==='hit'?'getroffen':'verfehlt');
   if(op==='hit'){const pts=s.dart+1;s.golfScores[s.turn].push(pts);s.golfSnapshots[s.turn].push(s.golfScores[s.turn].reduce((a,b)=>a+b,0));record(s,op,t,label+' mit Dart '+pts);advanceGolf(s);return s}
   if(s.dart===5){s.golfScores[s.turn].push(7);s.golfSnapshots[s.turn].push(s.golfScores[s.turn].reduce((a,b)=>a+b,0));record(s,op,t,label+' – 7 Punkte (inkl. Strafpunkt)');advanceGolf(s);return s}
  }else{
   const targetValue=golfChecks(s,s.turn)[s.checkPositions[s.turn]];
   if(!['check','miss'].includes(op))throw Error('Check oder Fehlaufnahme auswählen');
   if(op==='check'&&!SINGLE_CHECKS.has(targetValue))throw Error('Dieser Zwischenstand ist mit 3 Darts nicht checkbar');
   label=op==='check'?'Check '+targetValue+' geschafft':'Check '+targetValue+' verfehlt';
   if(op==='check'){s.checkPositions[s.turn]++;record(s,op,targetValue,label);nextReturnPlayer(s);return s}
   s.checkAttempts[s.turn]++;record(s,op,targetValue,label);nextReturnPlayer(s);return s;
  }
 }else if(s.kind==='tictactoe'){
  if(!Number.isInteger(target)||target<0||target>=9||s.board[target]!==-1)throw Error('Freies Spielfeld auswählen');
  if(!['hit','miss'].includes(op))throw Error('Ungültiger Wurf');
  label=(s.settings.variant==='checks'?'Check ':'Doppel ')+s.targets[target]+(op==='hit'?' geschafft':' verfehlt');
  if(op==='hit'){s.board[target]=s.turn;record(s,op,target,label);const w=win(s);if(w!==null){s.done=true;s.winner=w}else{s.dart=0;s.turn=1-s.turn}return s}
 }else if(s.kind==='connect4'){
  if(!Number.isInteger(target)||target<0||target>=7)throw Error('Spalte auswählen');
  if(!['hit','miss'].includes(op))throw Error('Ungültiger Wurf');
  let row=5;while(row>=0&&s.board[row][target]>=0)row--;if(row<0)throw Error('Spalte voll');
  const check=s.targets[row*7+target];label='Check '+check+(op==='hit'?' geschafft':' verfehlt');
  if(op==='hit'){s.board[row][target]=s.turn;record(s,op,check,label);const w=win(s);if(w!==null){s.done=true;s.winner=w}else{s.dart=0;s.turn=1-s.turn}return s}
 }else throw Error('Trainingsmodus unbekannt');
 record(s,op,target,label);s.dart++;if(s.kind!=='minigolf'&&s.dart===3){s.dart=0;s.turn=1-s.turn}return s;
}
async function mount({host,kind,settings,ids,names,save,loadScores}){
 let state=ready(kind,settings,names,ids),history=[],saved=false,saving=false,selection=0;
 const key='stingrays-mini-v2-'+kind+'-'+ids.join('-');let sessionId=typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(36).slice(2);
 try{const cached=JSON.parse(sessionStorage.getItem(key)||'null');if(cached?.state?.kind===kind&&!cached.saved&&cached.state.ids.join(',')===ids.join(',')&&JSON.stringify(cached.state.settings)===JSON.stringify(settings)){state=cached.state;history=cached.history||[];sessionId=cached.sessionId||sessionId;saved=!!cached.saved}}catch{}
 const notice=NODE('p',undefined,'mini-save');let topScores=[];
 if(loadScores&&kind==='minigolf')try{topScores=await loadScores('minigolf')}catch{topScores=[]}
 function cache(){try{if(saved)sessionStorage.removeItem(key);else sessionStorage.setItem(key,JSON.stringify({state,history,sessionId,saved}))}catch{}}
 async function persist(){if(saved||saving||!state.done)return;saving=true;notice.textContent='Speichere Ergebnis …';try{
  await save({kind,players:ids,winner_id:state.winner>=0?ids[state.winner]:null,draw:state.winner===-2,settings,score:kind==='minigolf'?state.golfScores.map(a=>a.reduce((x,y)=>x+y,0)):kind==='football'?state.goals:[],state:clone(state),session_id:sessionId});
  saved=true;cache();notice.textContent='In Neon gespeichert';if(kind==='minigolf'&&loadScores)topScores=await loadScores('minigolf');render();
 }catch(e){notice.textContent='Speichern fehlgeschlagen: '+e.message;const retry=button('Erneut speichern',persist);notice.append(retry)}finally{saving=false}}
 function button(label,fn,style='subtle'){const b=NODE('button',label,style);b.type='button';b.onclick=fn;return b}
 function perform(op,target){if(state.done)return;const prior=clone(state);try{throwDart(state,op,target)}catch(e){notice.textContent=e.message;return}history.push(prior);notice.textContent='';cache();render();if(state.done)persist()}
 function controls(items){const d=NODE('div',undefined,'mini-controls');for(const [label,op,target] of items)d.append(button(label,()=>perform(op,target),op==='hit'||op==='check'||op==='double'?'primary':'subtle'));return d}
 function scoreboard(){const wrap=NODE('div',undefined,'mini-players');for(let i=0;i<ids.length;i++){const card=NODE('div',undefined,'mini-player'+(!state.done&&state.turn===i?' on-turn':''));card.append(NODE('strong',names[i]));const score=kind==='minigolf'?state.golfScores[i].reduce((a,b)=>a+b,0)+' Punkte':kind==='football'?state.goals[i]+' Tore':state.throws.filter(x=>x.player===i).length+' Darts';card.append(NODE('span',score));wrap.append(card)}return wrap}
 function scoreTable(){const all=[...topScores];if(state.golfScores.every(x=>x.length===21))for(let i=0;i<ids.length;i++){const score=state.golfScores[i].reduce((a,b)=>a+b,0);if(!saved)all.push({name:names[i],score,preview:true})}
  all.sort((a,b)=>a.score-b.score);const wrap=NODE('div',undefined,'mini-highscores');wrap.append(NODE('h3','Minigolf – Bestenliste (niedrigster Score zuerst)'));const table=NODE('table',undefined,'mini-scorecard');const header=NODE('tr');for(const x of ['Platz','Spieler','Punkte'])header.append(NODE('th',x));table.append(header);all.slice(0,15).forEach((row,i)=>{const tr=NODE('tr');if(row.preview)tr.className='mini-preview';for(const x of [i+1,row.name+(row.preview?' · noch nicht gespeichert':''),row.score])tr.append(NODE('td',x));table.append(tr)});if(!all.length)wrap.append(NODE('p','Noch keine abgeschlossenen 21-Doppel-Runden.','helper'));else wrap.append(table);return wrap}
 function render(){host.replaceChildren();host.classList.add('mini-host');const head=NODE('div',undefined,'mini-top');head.append(NODE('h2',GAMES[kind]));head.append(NODE('p',state.done?'Training abgeschlossen':names[state.turn]+' · '+(kind==='minigolf'&&state.phase==='outbound'?'Aufnahme '+(1+Math.floor(state.dart/3))+'/2, Dart '+(1+state.dart%3)+'/3':kind==='minigolf'&&state.phase==='return'?'Checkversuch (max. 3 Darts)':'Aufnahme, Dart '+(state.dart+1)+'/3'),'mini-lead'));host.append(head,scoreboard());
  if(kind==='football'){
   const current=DOUBLE_TARGETS[state.doubleIndex];host.append(NODE('p','Ballbesitz: '+(state.possession<0?'Keiner':names[state.possession])+' · Nächstes Ziel: '+(current?doubleName(current):'Abgeschlossen')+' · Reihenfolge D1 bis D20, dann Vollbull','mini-hint'));
   const track=NODE('div',undefined,'mini-target-track');DOUBLE_TARGETS.forEach((d,i)=>{const x=NODE('span',doubleName(d)+(i<state.doubleIndex?' ✓':''),'mini-target '+(i<state.doubleIndex?'taken':i===state.doubleIndex?'current':''));track.append(x)});host.append(track);
   if(!state.done){const items=[['Single Bull · Ball erobern','singlebull'],['Vollbull · Ball + Tor','bullseye']];if(state.doubleIndex<20)items.push(['D'+current+' · Tor','double']);items.push(['Fehlwurf','miss']);const c=controls(items);if(state.possession!==state.turn&&state.doubleIndex<20)c.children[2].disabled=true;host.append(c)}
  }else if(kind==='minigolf'){
   if(state.phase==='outbound'){
    const target=DOUBLE_TARGETS[state.targetIndex];host.append(NODE('p','Phase 1 · '+doubleName(target)+' · 6 Darts (2 Aufnahmen) je Spieler. Treffer: Dartanzahl als Punkte; kein Treffer: 7 Punkte.','mini-hint'));
    if(!state.done)host.append(controls([['Doppel getroffen','hit',target],['Daneben','miss',target]]));
   }else if(state.phase==='return'){
    const checks=golfChecks(state,state.turn),index=state.checkPositions[state.turn];host.append(NODE('p','Phase 2 · '+(state.settings.returnMode==='all'?'Alle Zwischenstände rückwärts':'Endscore')+' · Jetzt '+checks[index]+' innerhalb von 3 Darts checken (Single-Out)','mini-hint'));
    if(!state.done)host.append(controls([['Check geschafft (max. 3 Darts)','check',checks[index]],['Nicht geschafft · nächster Versuch','miss',checks[index]]]));
   }
   const tbl=NODE('table',undefined,'mini-scorecard'),header=NODE('tr');for(const h of ['Doppel',...names])header.append(NODE('th',h));tbl.append(header);
   DOUBLE_TARGETS.forEach((t,i)=>{const tr=NODE('tr');tr.append(NODE('td',doubleName(t)));for(let p=0;p<ids.length;p++){const points=state.golfScores[p][i],cumulative=state.golfSnapshots[p][i];tr.append(NODE('td',points===undefined?'–':points+' P. · Σ '+cumulative))}tbl.append(tr)});
   const scroll=NODE('div',undefined,'mini-scroll');scroll.append(tbl);host.append(scroll);host.append(scoreTable());
  }else{
   if(kind==='tictactoe'&&state.board[selection]!==-1)selection=state.board.findIndex(x=>x===-1);
   if(kind==='connect4'&&state.board[0][selection]!==-1)selection=state.board[0].findIndex(x=>x===-1);
   const tic=kind==='tictactoe';host.append(NODE('p',tic?(settings.variant==='checks'?'9 unterschiedliche 3-Dart-Checks.':'9 zufällige, unterschiedliche Doppel.')+' Pro Aufnahme maximal ein Feld buchen. Drei in einer Reihe gewinnen.':'42 unterschiedliche Checkout-Zahlen. Nur das jeweils unterste freie Feld einer Spalte kann belegt werden. Vier in einer Reihe gewinnen.','mini-hint'));
   const board=NODE('div',undefined,tic?'mini-grid-tic':'mini-grid-four');
   if(tic)state.board.forEach((owner,i)=>{const b=button((owner===0?'● ':owner===1?'● ':'')+(state.settings.variant==='checks'?state.targets[i]:doubleName(state.targets[i])),()=>{selection=i;render()},'mini-cell '+(owner<0?'':'owner-'+owner)+(selection===i?' selected':''));b.disabled=state.done||owner>=0;board.append(b)});
   else for(let row=0;row<6;row++)for(let col=0;col<7;col++){const owner=state.board[row][col],b=button((owner===0?'● ':owner===1?'● ':'')+state.targets[row*7+col],()=>{selection=col;render()},'mini-cell '+(owner<0?'':'owner-'+owner)+(selection===col?' selected':''));b.disabled=state.done||state.board[0][col]>=0;board.append(b)}
   host.append(board);
   if(!state.done&&selection>=0)host.append(controls([[tic?(settings.variant==='checks'?'Check geschafft':'Doppel getroffen'):'Check geschafft','hit',selection],['Nicht getroffen','miss',selection]]));
  }
  const footer=NODE('div',undefined,'mini-footer');if(!state.done)footer.append(button('Letzten Dart / Check zurück',()=>{if(!history.length)return;state=history.pop();cache();render()}));
  if(state.done)footer.append(NODE('strong',state.winner===-2?'Unentschieden':ids.length===1?'Training abgeschlossen':names[state.winner]+' gewinnt','mini-winner'));
  footer.append(notice);host.append(footer);const hist=NODE('div',undefined,'mini-log');hist.append(NODE('h3','Letzte Würfe / Aufnahmen'));for(const v of state.throws.slice(-9).reverse())hist.append(NODE('p',names[v.player]+' · '+v.label));host.append(hist);
 }
 render();if(state.done)persist();return {state:()=>state,throwDart:perform};
}
window.StingrayMiniGames={mount,engine:{ready,throwDart,win,validRange,DOUBLE_CHECKS,SINGLE_CHECKS},games:GAMES};
})();

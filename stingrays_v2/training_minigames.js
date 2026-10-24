/* Stingrays V2: self-contained dart minigames (no external libraries). */
(()=>{'use strict';
 const GAMES={football:'Fußball',minigolf:'Minigolf',tictactoe:'Tic Tac Toe',connect4:'Vier gewinnt'};
 const TTT_TARGETS=[12,20,18,11,25,6,7,3,2];
 const C4_TARGETS=[20,19,18,17,16,15,'Bull'];
 const lines3=[[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
 const n=(tag,txt,cls)=>{const e=document.createElement(tag);if(txt!==undefined)e.textContent=txt;if(cls)e.className=cls;return e};
 const clone=state=>JSON.parse(JSON.stringify(state));
 const ready=(kind,settings,names,ids)=>({kind,settings,names,ids,turn:0,dart:0,throws:[],winner:null,done:false,
  board:kind==='tictactoe'?Array(9).fill(-1):kind==='connect4'?Array.from({length:6},()=>Array(7).fill(-1)):[],
  possession:-1,goals:[0,0],hole:1,holeShots:[],golfScores:ids.map(()=>[]),target:null});
 function evaluate(s){
  if(s.kind==='football'){
   if(s.goals[s.turn]>=Number(s.settings.goals))return s.turn;
   return null;
  }
  if(s.kind==='tictactoe'){
   for(const line of lines3)if(s.board[line[0]]!==-1&&line.every(i=>s.board[i]===s.board[line[0]]))return s.board[line[0]];
   if(s.board.every(v=>v!==-1))return -2;
  }
  if(s.kind==='connect4'){
   for(let r=0;r<6;r++)for(let c=0;c<7;c++){
    const p=s.board[r][c];if(p<0)continue;
    for(const [dr,dc] of [[1,0],[0,1],[1,1],[1,-1]]){
     if(Array.from({length:4},(_,k)=>[r+k*dr,c+k*dc]).every(([rr,cc])=>rr>=0&&rr<6&&cc>=0&&cc<7&&s.board[rr][cc]===p))return p;
    }
   }
   if(s.board.every(row=>row.every(v=>v!==-1)))return -2;
  }
  if(s.kind==='minigolf' && s.hole>Number(s.settings.holes)){
   const sums=s.golfScores.map(x=>x.reduce((a,b)=>a+b,0));
   return sums.length===1?0:sums.every(x=>x===sums[0])?-2:sums.indexOf(Math.min(...sums));
  }
  return null;
 }
 function throwDart(s,op,target){
  if(s.done)throw Error('Dieses Spiel ist beendet');
  const p=s.turn;let label='';
  if(s.kind==='football'){
   if(!['bull','double','miss'].includes(op))throw Error('Ungültiger Wurf');
   if(op==='bull'){
    s.possession=p;label='Bull – Ballbesitz';
   }else if(op==='double'){
    if(s.possession!==p)throw Error('Erst Ballbesitz durch Bull erlangen');
    s.goals[p]+=1;label='Doppel getroffen – Tor '+s.goals[p];
   }else label='Daneben';
  }else if(s.kind==='tictactoe'){
   if(!Number.isInteger(target)||target<0||target>=9||s.board[target]!==-1)throw Error('Freies Feld auswählen');
   if(!['hit','miss'].includes(op))throw Error('Ungültiger Wurf');
   if(op==='hit')s.board[target]=p;
   label=(op==='hit'?'Treffer ':'Fehlwurf ')+TTT_TARGETS[target];
  }else if(s.kind==='connect4'){
   if(!Number.isInteger(target)||target<0||target>=7)throw Error('Spalte auswählen');
   if(!['hit','miss'].includes(op))throw Error('Ungültiger Wurf');
   if(op==='hit'){
    let row=5;while(row>=0&&s.board[row][target]!==-1)row--;
    if(row<0)throw Error('Spalte bereits voll');
    s.board[row][target]=p;
   }
   label=(op==='hit'?'Treffer ':'Fehlwurf ')+(C4_TARGETS[target]==='Bull'?'Bullseye':'D'+C4_TARGETS[target]);
  }else if(s.kind==='minigolf'){
   if(!['miss','single','double','triple'].includes(op))throw Error('Ungültiger Wurf');
   s.holeShots.push(op);
   label='Bahn '+s.hole+': '+{miss:'Daneben',single:'Single',double:'Double',triple:'Triple'}[op];
  }else throw Error('Unbekanntes Spiel');
  s.throws.push({player:p,operation:op,target:target??null,hole:s.kind==='minigolf'?s.hole:null,label});
  const outcome=evaluate(s);
  if(outcome!==null){s.done=true;s.winner=outcome;return s}
  s.dart++;
  if(s.dart===3){
   if(s.kind==='minigolf'){
    const penalty={miss:5,single:3,double:2,triple:1};
    s.golfScores[p].push(Math.min(...s.holeShots.map(x=>penalty[x])));
    s.holeShots=[];
    s.turn++;
    if(s.turn>=s.ids.length){s.turn=0;s.hole++}
    const finish=evaluate(s);if(finish!==null){s.done=true;s.winner=finish;return s}
   }else s.turn=(s.turn+1)%2;
   s.dart=0;
  }
  return s;
 }
 async function mount({host,kind,settings,ids,names,save}){
  if(!GAMES[kind])throw Error('Trainingsmodus nicht verfügbar');
  let state=ready(kind,settings,names,ids),snapshots=[],selection=0,saved=false,saving=false;
  let sessionId=typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(36).slice(2);
  const saveStatus=n('div',undefined,'mini-save');
  function storageKey(){return 'stingrays-mini-'+kind+'-'+ids.join('-')}
  function store(){try{if(!saved)sessionStorage.setItem(storageKey(),JSON.stringify({state,snapshots,sessionId}));else sessionStorage.removeItem(storageKey())}catch{}}
  try{const cached=JSON.parse(sessionStorage.getItem(storageKey())||'null');if(cached?.state?.kind===kind&&cached.state.ids.join(',')===ids.join(',')&&JSON.stringify(cached.state.settings)===JSON.stringify(settings)){state=cached.state;snapshots=cached.snapshots||[];sessionId=cached.sessionId||sessionId}}catch{}
  async function persist(){if(saved||saving||!state.done)return;saving=true;saveStatus.textContent='Speichere in Neon …';try{
   await save({kind,players:ids,winner_id:state.winner>=0?ids[state.winner]:null,draw:state.winner===-2,settings,score:kind==='minigolf'?state.golfScores.map(x=>x.reduce((a,b)=>a+b,0)):kind==='football'?state.goals:[],state:clone(state),session_id:sessionId});
   saved=true;saveStatus.textContent='Ergebnis in Neon gespeichert';store();
  }catch(err){saveStatus.textContent='Speicherung fehlgeschlagen: '+err.message;const retry=n('button','Erneut speichern','subtle');retry.type='button';retry.onclick=()=>{retry.remove();persist()};saveStatus.append(retry)}finally{saving=false}}
  function perform(op,target){if(state.done)return;const before=clone(state);try{throwDart(state,op,target)}catch(e){saveStatus.textContent=e.message;return}snapshots.push(before);saveStatus.textContent='';store();render();if(state.done)persist()}
  function button(word,callback,style){const x=n('button',word,style||'subtle');x.type='button';x.onclick=callback;return x}
  function render(){host.replaceChildren();host.classList.add('mini-host');
   const top=n('div',undefined,'mini-top');top.append(n('h2',GAMES[kind]));top.append(n('p',state.done?'Spiel beendet':names[state.turn]+' am Wurf · Dart '+(state.dart+1)+'/3','mini-lead'));host.append(top);
   const strip=n('div',undefined,'mini-players');for(let i=0;i<ids.length;i++){
    const card=n('div',undefined,'mini-player '+(i===state.turn&&!state.done?'on-turn':''));card.append(n('strong',names[i]));
    const value=kind==='football'?state.goals[i]+' Tore':kind==='minigolf'?state.golfScores[i].reduce((a,b)=>a+b,0)+' Schläge':state.throws.filter(x=>x.player===i).length+' Darts';
    card.append(n('span',value));strip.append(card)}host.append(strip);
   if(kind==='football'){
    host.append(n('p','Ballbesitz: '+(state.possession<0?'Niemand':names[state.possession])+' · Ziel: '+settings.goals+' Tore','mini-hint'));
    const controls=n('div',undefined,'mini-controls');controls.append(button('Bull getroffen (Ball)',()=>perform('bull'),'primary'));
    controls.append(button('Doppel getroffen (Tor)',()=>perform('double'),state.possession===state.turn?'primary':'subtle'));
    controls.append(button('Daneben',()=>perform('miss')));
    if(state.possession!==state.turn)controls.children[1].disabled=true;
    host.append(controls);
   }else if(kind==='minigolf'){
    host.append(n('p','Bahn '+Math.min(state.hole,settings.holes)+' / '+settings.holes+' · Zielsegment '+Math.min(state.hole,settings.holes),'mini-hint'));
    host.append(n('p','3 Darts pro Bahn: Triple = 1, Double = 2, Single = 3, kein Treffer = 5. Der beste Dart zählt.','helper'));
    const controls=n('div',undefined,'mini-controls');for(const [k,v] of [['triple','Triple'],['double','Double'],['single','Single'],['miss','Daneben']])controls.append(button(v,()=>perform(k),k==='triple'?'primary':'subtle'));host.append(controls);
    const table=n('table',undefined,'mini-scorecard'),tr=n('tr');for(const h of ['Bahn',...names])tr.append(n('th',h));table.append(tr);
    for(let hole=1;hole<=settings.holes;hole++){
     const row=n('tr');row.append(n('td',String(hole)));
     for(let i=0;i<ids.length;i++)row.append(n('td',state.golfScores[i][hole-1]??'–'));table.append(row)
    }const scroll=n('div',undefined,'mini-scroll');scroll.append(table);host.append(scroll);
   }else{
    if(kind==='tictactoe'&&state.board[selection]!==-1)selection=state.board.findIndex(v=>v===-1);
    if(kind==='connect4'&&state.board[0][selection]!==-1)selection=state.board[0].findIndex(v=>v===-1);
    host.append(n('p',kind==='tictactoe'?'Ziel: Drei Felder in einer Reihe. Treffer auf die angezeigte Zahl belegt das Feld.':'Ziel: Vier Steine in einer Reihe. Treffer auf das Doppel der Spalte lässt einen Stein fallen.','mini-hint'));
    const board=n('div',undefined,kind==='tictactoe'?'mini-grid-tic':'mini-grid-four');
    if(kind==='tictactoe'){
     state.board.forEach((owner,i)=>{
      const b=button(owner>=0?(owner===0?'X':'O')+' · '+TTT_TARGETS[i]:String(TTT_TARGETS[i]),()=>{selection=i;render()},'mini-cell '+(owner>=0?'owner-'+owner:'')+(selection===i?' selected':''));
      b.disabled=state.done||owner>=0;board.append(b);
     });
    }else{
     for(let r=0;r<6;r++)for(let c=0;c<7;c++){
      const owner=state.board[r][c],label=r===0?(C4_TARGETS[c]==='Bull'?'Bull':'D'+C4_TARGETS[c])+'\n'+(owner<0?'·':owner===0?'●':'○'):(owner<0?'·':owner===0?'●':'○');
      board.append(button(label,()=>{selection=c;render()},'mini-cell '+(owner>=0?'owner-'+owner:'')+(selection===c?' selected':'')));
     }
    }host.append(board);
    if(!state.done){const controls=n('div',undefined,'mini-controls');controls.append(button('Treffer',()=>perform('hit',selection),'primary'));controls.append(button('Daneben',()=>perform('miss',selection)));host.append(controls)}
   }
   const footer=n('div',undefined,'mini-footer');
   if(!state.done)footer.append(button('Letzten Dart zurück',()=>{if(!snapshots.length)return;state=snapshots.pop();store();render()},'subtle'));
   if(state.done)footer.append(n('strong',state.winner===-2?'Unentschieden':ids.length===1?'Training abgeschlossen':names[state.winner]+' gewinnt!','mini-winner'));
   footer.append(saveStatus);host.append(footer);
   const log=n('div',undefined,'mini-log');log.append(n('h3','Letzte Würfe'));
   for(const v of state.throws.slice(-9).reverse())log.append(n('p',names[v.player]+' · '+v.label));host.append(log);
  }
  render();if(state.done)persist();return {state:()=>state,throwDart:perform};
 }
 window.StingrayMiniGames={mount,engine:{ready,throwDart,evaluate},games:GAMES};
})();

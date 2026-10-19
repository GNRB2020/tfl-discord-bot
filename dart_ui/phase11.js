/* Phase 11: training UX additions, loaded after phase6.js */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const style=document.createElement('style');style.textContent=`
#book{background:#07825d!important;border-color:#39c79a!important}
#xscorebar{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:stretch}
#xscorebar .player{min-width:0}#xscorebar #centerboard{min-width:112px;display:flex;flex-direction:column;justify-content:center;align-items:center;background:#132338;border:2px solid #9c2834;border-radius:12px;padding:8px;text-align:center}
#centerboard .result{font-size:clamp(27px,5vh,51px);font-weight:900;white-space:nowrap}
#centerboard .setscore{font-size:clamp(14px,2.7vh,25px);font-weight:900;color:#f4acb0}
#scorerView .liveavg{font-size:clamp(23px,3.9vh,38px)!important;font-weight:900}
#scorerView .meta:has(.liveavg){font-size:clamp(14px,2.3vh,21px)!important}
#historyX,#historySau{font-size:clamp(12px,1.9vh,17px);padding:5px;color:#c9d8ea;background:#0b1a2a;border-radius:7px}
#sauShortcuts{display:grid;grid-template-columns:repeat(6,1fr);gap:4px}
#sauShortcuts button{min-height:34px;font-size:clamp(12px,2.1vh,18px);padding:2px}
#tugView .tugscore{font-size:clamp(44px,8vh,90px);font-weight:900}
#tugView .tugplayers{display:grid;grid-template-columns:1fr 1fr;gap:8px}
#tugView .tugplayer{background:#172d42;border-radius:12px;border:2px solid #385169;padding:12px;text-align:center}
#tugView .tugplayer.active{border-color:#45c0eb}
#tugView .tuglayout{display:grid;grid-template-columns:1fr 1fr;gap:10px;min-height:0;flex:1}
#tugView .tugpad{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(4,1fr);gap:5px;flex:1}
#tugView .tugquick{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;flex:1}
@media(max-height:600px){#tugView .tugscore{font-size:40px}#tugView .panel{padding:6px}}
`;document.head.append(style);

// X01 scoreboard, larger averages, history, score correction, bust.
const players=$('scorerView')?.querySelector('.players');
if(players){players.id='xscorebar';const board=document.createElement('section');board.id='centerboard';board.innerHTML='<div id="centerCaption">LEGS</div><div class="result" id="centerLegs">0 : 0</div><div class="setscore" id="centerSets"></div>';players.insertBefore(board,$('p1'));}
const xPanel=$('book')?.parentElement;
if(xPanel){const rest=document.createElement('button');rest.id='bookRest';rest.textContent='RESTSCORE';rest.style.background='#285478';xPanel.append(rest);const zero=document.createElement('button');zero.id='noScore';zero.textContent='NO SCORE';zero.style.background='#475162';xPanel.append(zero);rest.onclick=()=>{if(!S||S.kind!=='x01'||S.done||!entry)return;const rem=S.remaining[S.current],desired=Number(entry),points=rem-desired;if(desired<0||points<0||points>180||desired===0){err('Restscore ungültig – Checkout über grüne Taste buchen');return}entry=String(points);$('entry').textContent=entry;$('book').click()};zero.onclick=()=>{if(S?.kind==='x01'&&!S.done)send(0)};}
const hx=document.createElement('div');hx.id='historyX';hx.textContent='Historie: –';$('quick')?.after(hx);
const oldMatch=showMatch;
showMatch=function(){oldMatch();if(S?.kind!=='x01')return;
  $('centerLegs').textContent=S.legs.join(' : ');
  $('centerCaption').textContent=S.rules.mode==='sets'?'LEGS IM SET':'LEGS';
  $('centerSets').textContent=S.rules.mode==='sets'?'SETS '+S.sets.join(' : '):'';
  ['l0','l1'].forEach(id=>{const el=$(id);if(el)el.style.display='none'});
  hx.textContent='Letzte Aufnahmen: '+(S.history||S.last||[]).slice(-8).map(v=>(S.names[v.player]||'?')+' '+v.score).join(' · ')||'–';
};
const configForm=$('configForm');if(configForm){const old=configForm.onsubmit;configForm.onsubmit=e=>{e.preventDefault();modal(`<h2>Ausbullen – wer beginnt?</h2><p>Wähle den Anwurf nach dem Ausbullen.</p><div class="actions"><button id="starter0">${escapeName($('a').value)}</button><button id="starter1">${escapeName($('b').value)}</button></div><div class="actions"><button id="starterCancel">ABBRECHEN</button></div>`);$('starterCancel').onclick=closeModal;[0,1].forEach(i=>{$('starter'+i).onclick=()=>{window.__dartStarter=i;closeModal();old({preventDefault(){}})}})};}
// Inject starter into the existing server-side match-creation call.
const oldApi=api;api=async function(path,data){if(path==='new'&&data?.kind==='x01') data={...data,starter:window.__dartStarter||0};return oldApi(path,data)};
function escapeName(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}

// Sau shows clear match score (successful checkouts : Sau marks) and fast buttons.
const sauInfo=document.createElement('div');sauInfo.id='sauScore';sauInfo.style.cssText='font-size:clamp(21px,4vh,38px);font-weight:900;text-align:center;color:#f5f7ff';$('saurest')?.before(sauInfo);
const hs=document.createElement('div');hs.id='historySau';$('sauentry')?.after(hs);
const sq=document.createElement('div');sq.id='sauShortcuts';$('saupad')?.after(sq);
[26,41,45,57,60,81,85,95,100,133,140,180].forEach(n=>{const b=document.createElement('button');b.textContent=n;b.onclick=()=>{if(S?.kind==='sau'&&!S.done&&n!==S.remaining)send(n)};sq.append(b)});
const oldSau=showSau;showSau=function(){oldSau();if(S?.kind!=='sau')return;const own=Object.entries(S.marks).filter(([k])=>k!=='sau').reduce((a,[,v])=>a+v,0);sauInfo.textContent='SPIELER '+own+' : '+S.marks.sau+' SAU';hs.textContent='Aufnahmen: '+(S.visits||[]).map(v=>v.score).join(' · ')+(S.history?.length?' | Zuletzt: '+S.history.slice(-4).map(v=>v.score).join(' · '):'');};

// Tug-of-war shares one position, target zero vs target 362.
const v=document.createElement('div');v.id='tugView';v.className='screen hide';v.innerHTML=`<div class="panel" style="height:100%;display:flex;flex-direction:column;gap:6px"><h2 style="margin:0">TAUZIEHEN · RUNDE <span id="tuground"></span></h2><div class="tugplayers"><section class="tugplayer" id="tp0"><b id="tn0"></b><div class="tugscore" id="tr0">181</div><small>bis 0</small></section><section class="tugplayer" id="tp1"><b id="tn1"></b><div class="tugscore" id="tr1">181</div><small>bis 362</small></section></div><div id="tugwins" class="hint"></div><div class="tuglayout"><div class="panel" style="display:flex;flex-direction:column"><div class="entry" id="tugentry">–</div><div class="tugpad" id="tugpad"></div><div class="actions"><button class="green" id="tugbook">BUCHEN</button><button id="tugzero">NO SCORE</button><button id="tugundo">ZURÜCK</button></div></div><div class="panel" style="display:flex;flex-direction:column"><div class="headline">SHORTCUTS</div><div class="tugquick" id="tugquick"></div><div class="hint" id="tughistory">Noch keine Aufnahme</div></div></div></div>`;document.querySelector('.root').append(v);
const tugMenu=document.createElement('button');tugMenu.className='menucard';tugMenu.innerHTML='Training · Tauziehen<small>181 Start · Ziel 0 gegen 362</small>';$('sau')?.after(tugMenu);
let tugDigits='';function showTug(){if(S?.kind!=='tug')return;screen('tugView');$('tuground').textContent=S.round+' / '+S.rounds;[0,1].forEach(i=>{$('tn'+i).textContent=S.names[i];$('tr'+i).textContent=S.remaining[i];$('tp'+i).classList.toggle('active',S.current===i&&!S.finished)});$('tugentry').textContent=tugDigits||'–';$('tugwins').textContent='Rundensiege: '+S.wins.join(' : ')+(S.finished?' · TRAINING BEENDET':'');$('tughistory').textContent='Historie: '+S.visits.slice(-7).map(w=>S.names[w.player]+' '+w.points+' ('+w.before+'→'+w.after+')').join(' · ');$('tugbook').disabled=S.finished;$('tugzero').disabled=S.finished;$('tugundo').disabled=!S.can_undo;}
function startTug(){modal(`<h2>Tauziehen starten</h2><label>Spieler 1<input id="ta" value="Spieler 1"></label><label>Spieler 2<input id="tb" value="Spieler 2"></label><label>Rundenzahl<input id="tRounds" type="number" min="1" max="100" value="5"></label><div class="actions"><button id="tCancel">ABBRECHEN</button><button class="green" id="tStart">STARTEN</button></div>`);$('tCancel').onclick=closeModal;$('tStart').onclick=async()=>{try{S=await api('new',{kind:'tug',a:$('ta').value,b:$('tb').value,rounds:+$('tRounds').value});tugDigits='';closeModal();showTug()}catch(e){err(e.message)}}}tugMenu.onclick=startTug;
for(const key of digits){const b=document.createElement('button');b.textContent=key;b.onclick=()=>{tugDigits=key==='C'?'':key==='⌫'?tugDigits.slice(0,-1):(tugDigits+key).slice(0,3);$('tugentry').textContent=tugDigits||'–'};$('tugpad').append(b)}
const tugSend=async(points)=>{try{S=await api('throw',{points});tugDigits='';showTug()}catch(e){err(e.message)}};
for(const n of [26,41,45,57,60,81,85,95,100,133,140,180]){const b=document.createElement('button');b.textContent=n;b.onclick=()=>{if(!S.finished)tugSend(n)};$('tugquick').append(b)}
$('tugbook').onclick=()=>{if(tugDigits!==''&&!S.finished)tugSend(+tugDigits)};$('tugzero').onclick=()=>tugSend(0);$('tugundo').onclick=async()=>{try{S=await api('undo',{});showTug()}catch(e){err(e.message)}};
const oldSend=send;send=async function(...args){await oldSend(...args);if(S?.kind==='tug')showTug()};
// Restore tug games after refresh.
const oldStateApi=api;api=async function(path,data){const out=await oldStateApi(path,data);if(path==='state'&&out.kind==='tug'){setTimeout(()=>{S=out;showTug()},0)}return out};
})();

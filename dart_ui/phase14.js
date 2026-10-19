/* Phase 14 – Unified match report, player history, tug score */
(()=>{'use strict';
const q=id=>document.getElementById(id);
const esc=s=>String(s??'–').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dt=v=>v?new Date(v).toLocaleString('de-DE'):'Nicht erfasst';
const list=v=>Array.isArray(v)?v.join(', ')||'–':(v==null?'–':String(v));
const histories=()=>S?.history||S?.last||[];
function playerHist(){
 if(S?.kind!=='x01')return;
 for(let i=0;i<2;i++){
  let h=q('stingHist'+i);if(!h){h=document.createElement('div');h.id='stingHist'+i;h.className='sting-history';q('n'+i)?.parentElement?.appendChild(h)}
  const scores=histories().filter(v=>Number(v.player)===i).slice(-3).map(v=>v.bust?'0 (Bust)':v.score);
  h.textContent='Letzte 3: '+(scores.length?scores.join(' · '):'–');
 }
}
const baseMatch=showMatch;
// Disable the legacy result dialog while the original renderer updates scores.
// Open our full report only after the legacy render path is finished.
showMatch=function(){
 const oldResult=result;
 result=function(){};
 try{baseMatch()}finally{result=report}
 playerHist();
 if(S?.kind==='x01'&&S.done)report();
};
// In Phase 11 the tug controller lives in a closure; observe its stable view instead.
const tug=q('tugView');
function tugWins(){if(!tug||S?.kind!=='tug')return;
 let e=q('tugWinsBoard');if(!e){e=document.createElement('div');e.id='tugWinsBoard';tug.querySelector('.tugplayers')?.before(e)}
 e.textContent=`RUNDSIEGE · ${S.wins?.[0]??0} : ${S.wins?.[1]??0}`;
}
if(tug)new MutationObserver(tugWins).observe(tug,{attributes:true,attributeFilter:['class']});
const oldApi=api;api=async function(...args){const response=await oldApi(...args);if(['throw','undo','state'].includes(args[0]))setTimeout(tugWins,0);return response};
function grid(title,cols,rows){return `<h3>${esc(title)}</h3><div style="overflow-x:auto"><table class="sting-table"><thead><tr>${cols.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function details(p,key){const val=p?.[key];return Array.isArray(val)?list(val):'–'}
function info(data){const rules=data.rules||{},names=data.names||[],history=histories();const matchId=data.id||'Freies Training';const mode=rules.mode==='sets'?'Setmodus':'Legmodus';return grid('Spielinformationen',['Feld','Wert'],[
 ['Spieler 1',names[0]],['Spieler 2',names[1]],['Endstand Legs',(data.legs||[]).join(' : ')],['Endstand Sets',(data.sets||[]).join(' : ')],['Spielart',mode],['Startpunkte',rules.start_score],['Best of',rules.mode==='sets'?rules.best_of_sets:rules.max_legs],['Anwurf',names[data.starter??0]||'Nicht erfasst'],['Spielstatus',data.done?'Beendet':'Läuft'],['Erfasste Aufnahmen',history.length],['Spielbeginn',dt(data.started_at)],['Spielende',dt(data.finished_at)],['Spieldauer',data.duration_minutes??'Nicht erfasst'],['Spiel-ID',matchId]
 ])}
function report(){if(!S?.summary?.players||!q('modal')?.classList.contains('hide'))return;
 const data=S,p=data.summary.players,hist=histories();const ns=data.names;
 const byLeg=Array.from(new Set(p.flatMap(x=>(x.by_leg||[]).map(y=>y.leg)))).sort((a,b)=>a-b);
 const overview=()=>{
  let html=grid('Scoring',['Spieler','60+','80+','100+','140+','180'],p.map(x=>[x.player,...['60','80','100','140','180'].map(k=>x.scoring_bands?.[k]??0)]));
  html+=grid('Averages',['Spieler','Avg','First 9D','First 12D','First 15D','First 18D'],p.map(x=>[x.player,x.average,...['9','12','15','18'].map(k=>x.first_darts?.[k]??'–')]));
  for(const [label,key] of [['Darts/Leg','darts'],['Averages/Leg','average'],['Checkouts/Leg','checkout']])html+=grid(label,['Spieler',...byLeg.map(String)],p.map(x=>[x.player,...byLeg.map(k=>x.by_leg?.find(z=>z.leg===k)?.[key]??'–')]));
  html+=grid('Specials – Einzelwerte',['Spieler','Lowdarts','Highfinishes','Bullfinishes','Highscores'],p.map(x=>[x.player,...['lowdart_details','highfinish_details','bullfinish_details','highscore_details'].map(k=>details(x,k))]));return html;
 };
 const best=()=>grid('Bestleistungen und Specials',['Spieler','Kategorie','Einzelwerte','Anzahl'],p.flatMap(x=>[
 [x.player,'Lowdarts',details(x,'lowdart_details'),x.lowdarts??0],
 [x.player,'Highfinishes',details(x,'highfinish_details'),x.highfinishes??0],
 [x.player,'Bullfinishes',details(x,'bullfinish_details'),x.bullfinishes??0],
 [x.player,'Highscores',details(x,'highscore_details'),x.highscores??0],
 [x.player,'180er',list(hist.filter(v=>v.player===ns.indexOf(x.player)&&v.score===180).map(v=>v.score)),hist.filter(v=>v.player===ns.indexOf(x.player)&&v.score===180).length]
 ]));
 const history=()=>grid('Aufnahmen',['#','Spieler','Leg','Punkte','Darts','Checkout'],hist.map((v,i)=>[i+1,ns[v.player]||'–',(v.leg_index??0)+1,v.score,v.darts,v.checkout?'Ja':'Nein']));
 modal(`<h2>Match beendet · ${esc(ns.join(' – '))}</h2><div class="sting-report-tabs"><button data-tab="info">Spielinfo</button><button data-tab="best">Bestleistungen</button><button data-tab="stats">Statistiken</button><button data-tab="history">Scoreboard</button></div><div class="sting-report-scroll" id="stingBody"></div><div class="sting-report-actions"><button id="stingClose">SCHLIESSEN</button><button id="newReport" class="green">${new URLSearchParams(location.search).has('tournament')?'ZUM SPIELPLAN':'NEUES MATCH'}</button></div>`);
 const views={info:()=>info(data),best,stats:overview,history};
 q('modalContent').querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{q('stingBody').innerHTML=views[b.dataset.tab]();q('modalContent').querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b))});
 q('modalContent').querySelector('[data-tab="stats"]').click();
 q('stingClose').onclick=closeModal;
 q('newReport').onclick=()=>{closeModal();const params=new URLSearchParams(location.search);if(params.has('tournament'))location.href='/dart/tournaments/#'+encodeURIComponent(params.get('tournament'));else screen('configView')};
}
result=report;
})();

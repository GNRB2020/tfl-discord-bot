/* Phase 11 tournament result screen, standings and aggregated statistics */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const css=document.createElement('style');css.textContent=`
.tstats{width:100%;border-collapse:collapse;font-size:clamp(12px,1.8vh,16px)}
.tstats th{background:#a01220;color:#fff}.tstats td,.tstats th{padding:7px;border:1px solid #3c4d60;text-align:center}
#reportContent{max-height:72vh;overflow:auto}#reportContent .tabbar{display:flex;gap:5px;flex-wrap:wrap;margin:10px 0}
#reportContent .tabbar button{background:#8e1720;flex:1}
#statsTournament{overflow:auto}
`;document.head.append(css);
const schedule=$('schedule');if(schedule){const box=document.createElement('div');box.className='card';box.innerHTML='<h2>Turnierstatistiken</h2><div id="statsTournament">Noch keine Ergebnisse</div>';schedule.append(box)}
const originalRender=renderTournament;
renderTournament=function(){originalRender();if(!t)return;
  if(t.mode!=='ko'){
    const tab=$('standings')?.querySelector('table');if(tab){const head=tab.querySelector('tr');const cell=document.createElement('th');cell.textContent='Legs';head?.insertBefore(cell,head.lastChild);tab.querySelectorAll('tr').forEach((tr,i)=>{if(i===0)return;const z=t.standings[i-1];if(!z)return;const td=document.createElement('td');td.textContent=z.for+':'+z.against;tr.insertBefore(td,tr.lastChild)})}
  }
  const items=t.statistics||[];const box=$('statsTournament');if(!box)return;
  const table=document.createElement('table');table.className='tstats';
  table.innerHTML='<tr><th>Spieler</th><th>Matches</th><th>Average</th><th>First 9</th><th>CO %</th><th>180</th><th>HF</th><th>LD</th><th>Specials</th></tr>';
  for(const z of items){const tr=document.createElement('tr');for(const val of [z.name,z.matches,z.average,z.first9,z.checkout_percentage,z.scores_180,z.highfinish||'–',z.lowdart??'–',z.specials]){const td=document.createElement('td');td.textContent=val;tr.append(td)}table.append(tr)}box.replaceChildren(table);
};
const oldRenderMatch=renderMatch;
let reportShownFor='';
renderMatch=function(){oldRenderMatch();if(!m?.done||!m.summary)return;
  const key=t.id+'/'+mid+'/'+m.version;if(reportShownFor===key)return;reportShownFor=key;showReport();
};
function showReport(){
 const stats=m.summary.players;
 modal('<div id="reportContent"><h2>Match beendet · '+esc(m.names.join(' – '))+'</h2><div class="tabbar"><button id="ri">Spielinfo</button><button id="rb">Bestleistungen</button><button id="rs">Statistiken</button><button id="rh">Scoreboard</button></div><div id="reportInner"></div><div class="row"><button id="rclose">SCHLIESSEN</button><button id="rplan" class="green">SPIELPLAN</button></div></div>');
 const table=(rows)=>'<table class="tstats"><tr><th>'+esc(m.names[0])+'</th><th>Statistik</th><th>'+esc(m.names[1])+'</th></tr>'+rows.map(([label,key])=>'<tr><td>'+esc(stats[0][key]??'–')+'</td><td>'+esc(label)+'</td><td>'+esc(stats[1][key]??'–')+'</td></tr>').join('')+'</table>';
 const render=(html)=>$('reportInner').innerHTML=html;
 const stage=(title,cols,rows)=>'<h3>'+esc(title)+'</h3><table class="tstats"><tr><th>Spieler</th>'+cols.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(([name,...values])=>'<tr><td>'+esc(name)+'</td>'+values.map(v=>'<td>'+esc(v??'–')+'</td>').join('')+'</tr>').join('')+'</table>';
 $('rs').onclick=()=>{
   const bands=['60','80','100','140','180'];
   let html=stage('Scoring',bands.map(x=>x+'+'),stats.map(p=>[p.player,...bands.map(b=>p.scoring_bands?.[b]??0)]));
   const first=['9','12','15','18'];
   html+=stage('Averages',['Avg',...first.map(x=>'First '+x+'D')],stats.map(p=>[p.player,p.average,...first.map(k=>p.first_darts?.[k]??'–')]));
   const legs=[...new Set(stats.flatMap(p=>(p.by_leg||[]).map(z=>z.leg)))].sort((a,b)=>a-b);
   for(const [title,key] of [['Darts/Leg','darts'],['Averages/Leg','average'],['Checkouts/Leg','checkout']]){
     html+=stage(title,legs.map(String),stats.map(p=>[p.player,...legs.map(n=>p.by_leg?.find(z=>z.leg===n)?.[key]??'–')]));
   }
   render(html);
 };
 $('rb').onclick=()=>{
   let html=table([['Lowdarts','lowdarts'],['Bullfinishes','bullfinishes'],['Highfinishes','highfinishes'],['Highscores','highscores']]);
   html+=stage('Einzelne Specials',['Lowdarts','Bullfinishes','Highfinishes','Highscores'],stats.map(p=>[p.player,...['lowdart_details','bullfinish_details','highfinish_details','highscore_details'].map(k=>(p[k]||[]).join(', ')||'–')]));
   render(html);
 };
 $('ri').onclick=()=>render('<p>Modus: '+esc(m.rules.mode)+' · Startpunkte: '+m.rules.start_score+' · Endstand '+m.legs.join(':')+'</p>');
 $('rh').onclick=()=>render('<table class="tstats"><tr><th>Spieler</th><th>Aufnahmen</th></tr>'+m.names.map((n,i)=>'<tr><td>'+esc(n)+'</td><td>'+esc((m.history||[]).filter(v=>v.player===i).map(v=>v.score).join(' · '))+'</td></tr>').join('')+'</table>');
 $('rs').click();$('rclose').onclick=close;$('rplan').onclick=()=>{close();$('toSchedule').click()};
}
function esc(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
})();

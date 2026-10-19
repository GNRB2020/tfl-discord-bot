/* Phase 15: match-wide tournament ranking fields, no checkout percentage. */
(()=>{'use strict';
const prior=renderTournament;
renderTournament=function(){
  prior();
  if(!t)return;
  const box=document.getElementById('statsTournament');if(!box)return;
  const table=document.createElement('table');table.className='tstats sting-table';
  const cols=['Name','Matches','Average','First 9','95+','133+','171+','BF','HF','LD','Specials'];
  const head=document.createElement('tr');for(const name of cols){const c=document.createElement('th');c.textContent=name;head.append(c)}table.append(head);
  for(const p of t.statistics||[]){
    const tr=document.createElement('tr');
    const values=[p.name,p.matches,p.average,p.first9,p.visits_95_plus??0,p.visits_133_plus??0,p.visits_171_plus??0,(p.bullfinish_details?.length?p.bullfinish_details.join(', '):'–'),p.highfinish||'–',p.lowdart??'–',p.specials??0];
    for(const val of values){const td=document.createElement('td');td.textContent=String(val);tr.append(td)}table.append(tr);
  }
  box.replaceChildren(table);
};
})();

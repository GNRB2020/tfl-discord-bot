/* Round-separated schedule, X01 tournament matches use the regular scorer. */
(()=>{'use strict';
const previous=renderTournament;
renderTournament=function(){previous();if(!t)return;
 const host=document.getElementById('matches');host.replaceChildren();
 const groups=new Map();for(const match of t.matches){const round=match.round; if(!groups.has(round))groups.set(round,[]);groups.get(round).push(match)}
 for(const [number,matches] of [...groups.entries()].sort((a,b)=>a[0]-b[0])){
  const block=document.createElement('section');block.className='fixtureRound';
  const heading=document.createElement('h3');heading.textContent='Runde '+number;block.appendChild(heading);
  for(const m of matches){const b=document.createElement('button');b.className='match '+m.status;b.disabled=m.status==='pending';
    b.textContent=(m.a||'Freilos')+' gegen '+(m.b||'Freilos')+(m.score?' · '+m.score.join(':'):'')+' · '+m.status;
    b.onclick=()=>loadMatch(m.id);block.appendChild(b)}host.appendChild(block)
 }
};
loadMatch=function(id){location.href='/dart/?tournament='+encodeURIComponent(t.id)+'&match='+encodeURIComponent(id)};
const style=document.createElement('style');style.textContent='.fixtureRound{margin-bottom:14px;border:1px solid #476078;border-radius:9px;overflow:hidden}.fixtureRound h3{margin:0;padding:11px;background:#85222d}.fixtureRound .match{display:block;width:100%;border-radius:0;text-align:left;border:0;border-top:1px solid #435365;padding:14px}';document.head.appendChild(style);
})();

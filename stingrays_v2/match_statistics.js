/* One source of truth for live and final X01 match statistics. No server calls. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.StingrayMatchStats=api;
})(typeof globalThis!=='undefined'?globalThis:null,function(){'use strict';
  const number=value=>Number.isFinite(Number(value))?Number(value):0;
  const format=value=>number(value).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1});
  const group=(values,ascending=false)=>{
    const counts=new Map();for(const value of values)counts.set(number(value),(counts.get(number(value))||0)+1);
    return [...counts.entries()].sort((a,b)=>ascending?a[0]-b[0]:b[0]-a[0]).map(([value,n])=>n+'×'+value).join(' · ')||'–';
  };
  // Each valid scoring visit belongs to exactly one score band.
  const band=(visit)=>{
    if(visit.bust)return null;
    const score=number(visit.score);
    if(score>=171)return '171+';
    if(score>=140)return '140+';
    if(score>=100)return '100+';
    if(score>=80)return '80+';
    if(score>=60)return '60+';
    return null;
  };
  const avg=(visits,limit=null)=>{
    const points=visits.reduce((sum,v)=>sum+(v.bust?0:number(v.score)),0);
    const darts=visits.reduce((sum,v)=>sum+number(v.darts||3),0);
    return darts?format(3*points/darts):'0,0';
  };
  const firstDarts=(visits,limit)=>{
    const byLeg=new Map();
    for(const v of visits){const key=number(v.leg_index);if(!byLeg.has(key))byLeg.set(key,[]);byLeg.get(key).push(v)}
    let points=0,darts=0;
    for(const items of byLeg.values()){
      let n=0;
      for(const v of items){const used=number(v.darts||3);if(n+used>limit)break;n+=used;darts+=used;points+=v.bust?0:number(v.score)}
    }
    return darts?format(3*points/darts):'–';
  };
  function summarize(history,names=['Spieler 1','Spieler 2'],legs=[0,0],sets=[0,0],rules={}){
    const visits=(history||[]).filter(v=>v&&[0,1].includes(number(v.player)));
    const own=[0,1].map(i=>visits.filter(v=>number(v.player)===i));
    const bands=['60+','80+','100+','140+','171+'];
    const counter=own.map(items=>Object.fromEntries(bands.map(x=>[x,items.filter(v=>band(v)===x).length])));
    const values=own.map(items=>{
      const byLeg=new Map(),highfinish=[],lowdarts=[],bullfinishes=[],highscores=[];
      for(const v of items){
        const key=number(v.leg_index);if(!byLeg.has(key))byLeg.set(key,[]);byLeg.get(key).push(v);
        if(!v.bust&&number(v.score)>=171)highscores.push(number(v.score));
        if(v.checkout&&!v.bust){if(number(v.score)>=100)highfinish.push(number(v.score));if(v.bullfinish)bullfinishes.push(number(v.score))}
      }
      for(const leg of byLeg.values()){
        if(!leg.some(v=>v.checkout))continue;
        const darts=leg.reduce((s,v)=>s+number(v.darts||3),0);
        if(darts>=9&&darts<=18)lowdarts.push(darts);
      }
      return {highfinish,lowdarts,bullfinishes,highscores};
    });
    const statisticalRows=[
      ['AVERAGE',...own.map(avg)],
      ...bands.map(x=>[x,counter[0][x],counter[1][x]]),
      ['FIRST 9',...own.map(x=>firstDarts(x,9))],
      ['FIRST 12',...own.map(x=>firstDarts(x,12))],
      ['FIRST 15',...own.map(x=>firstDarts(x,15))],
      ['FIRST 18',...own.map(x=>firstDarts(x,18))],
      ['Aufnahmen',...own.map(x=>x.length)],
      ['Gewonnene Legs',...legs],
      ...(rules.mode==='sets'?[['Gewonnene Sets',...sets]]:[])
    ];
    const bestRows=[
      ['Highfinishes (100+)',...values.map(x=>group(x.highfinish))],
      ['Lowdarts (9–18)',...values.map(x=>group(x.lowdarts,true))],
      ['Bullfinishes',...values.map(x=>group(x.bullfinishes))],
      ['Highscores (171+)',...values.map(x=>group(x.highscores))],
      ['180er',...own.map(x=>x.filter(v=>!v.bust&&number(v.score)===180).length)],
    ];
    const rounds=[...new Set(visits.map(v=>number(v.leg_index)))].sort((a,b)=>a-b);
    const scoreboard=rounds.map(idx=>{
      const per=own.map(items=>items.filter(v=>number(v.leg_index)===idx));
      const finish=per.map(items=>items.find(v=>v.checkout&&!v.bust));
      return {leg:idx+1,darts:per.map(items=>items.reduce((n,v)=>n+number(v.darts||3),0)),
        averages:per.map(avg),checkouts:finish.map(v=>v?number(v.score):'–'),
        winner:finish[0]?0:finish[1]?1:null};
    });
    return {names,legs,sets,rules,statisticalRows,bestRows,scoreboard,counter,values};
  }
  return {summarize,band,group};
});

// Run with: node --test tests_js/*.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const stats = require('../stingrays_v2/match_statistics.js');

test('each scoring visit belongs to exactly one interval',()=>{
 const scores=[[0,null],[59,null],[60,'60+'],[79,'60+'],[80,'80+'],[99,'80+'],[100,'100+'],[139,'100+'],[140,'140+'],[170,'140+'],[171,'171+'],[180,'171+']];
 for(const [score,expected] of scores)assert.equal(stats.band({score,bust:false}),expected);
 assert.equal(stats.band({score:180,bust:true}),null);
});

test('repeated highfinishes, lowdarts, bullfinishes remain in live and final summary',()=>{
 const history=[];
 // Two 141-finishes in distinct legs. Each leg has 5 visits of 3 darts => 15-darter.
 for(let leg=0;leg<2;leg++){
  for(let v=0;v<4;v++)history.push({player:0,leg_index:leg,score:90,darts:3,bust:false,checkout:false});
  history.push({player:0,leg_index:leg,score:141,darts:3,bust:false,checkout:true,bullfinish:false});
 }
 // Three 18-darters for player 1, different legs, with 1x bullfinish.
 for(let leg=0;leg<3;leg++){
  for(let v=0;v<5;v++)history.push({player:1,leg_index:leg,score:80,darts:3,bust:false,checkout:false});
  history.push({player:1,leg_index:leg,score:50,darts:3,bust:false,checkout:true,bullfinish:leg===2});
 }
 const summary=stats.summarize(history,['A','B'],[2,3]);
 const best=Object.fromEntries(summary.bestRows.map(([name,...counts])=>[name,counts]));
 assert.equal(best['Highfinishes (100+)'][0],'2×141');
 assert.equal(best['Lowdarts (9–18)'][1],'3×18');
 assert.equal(best['Bullfinishes'][1],'1×50');
 assert.equal(summary.counter[0]['140+'],2);
 assert.equal(summary.counter[0]['100+'],0);
 assert.equal(summary.counter[0]['60+'],0);
 assert.equal(summary.counter[0]['80+'],8);
});

test('same specials are grouped, ascending low darts',()=>{
 assert.equal(stats.group([18,17,18,16,17],true),'1×16 · 2×17 · 2×18');
 assert.equal(stats.group([141,141,120]),'2×141 · 1×120');
});

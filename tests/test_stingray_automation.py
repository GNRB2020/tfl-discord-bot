"""Regression tests for group ranking, set lengths and knockout seeding.

No production database connection; these run on each change and in CI.
"""
import unittest
from uuid import uuid4
from aiohttp import web
from stingrays_v2.competition_wizard import normalize, CUP_FIXED
from stingrays_v2.tournament_automation import (spread_groups_in_bracket,
    rank_wildcards,round_match_rules,winner)
from stingrays_v2.rules import bracket_pairs,round_robin


class TournamentAutomationTests(unittest.TestCase):
    @staticmethod
    def participants(n):
        return [uuid4() for _ in range(n)]

    def test_group_sizes_and_pairing_counts(self):
        for players, groups in [(30,10),(100,10),(64,8),(7,2)]:
            buckets=[[] for _ in range(groups)]
            for i,p in enumerate(range(players)):buckets[i%groups].append(p)
            matches=[(g,a,b) for g,part in enumerate(buckets) for _,a,b in round_robin(part)]
            expected=sum(len(p)*(len(p)-1)//2 for p in buckets)
            self.assertEqual(len(matches),expected)
            self.assertEqual(len({(g,frozenset((a,b))) for g,a,b in matches}),expected)
            if players==100:self.assertEqual(expected,450)

    def test_wildcard_comparison_normalizes_unequal_group_sizes(self):
        def candidate(points,played,delta,legs,order):
            return (uuid4(),{'points':points,'played':played,'legs_for':legs,
                    'legs_against':legs-delta},order,2)
        a=candidate(6,3,5,9,1)
        b=candidate(8,5,8,14,2)
        c=candidate(4,2,2,6,3)
        ranked=rank_wildcards([a,b,c])
        self.assertEqual([r[0] for r in ranked],[a[0],c[0],b[0]])

    def test_bracket_preserves_all_participants_including_byes(self):
        for n in (2,3,5,6,10,13,16,22,32,64):
            ids=self.participants(n)
            pairs=bracket_pairs(ids)
            flattened=[p for x,y in pairs for p in (x,y) if p is not None]
            self.assertCountEqual(flattened,ids)
            self.assertEqual(len(flattened),len(set(flattened)))
            self.assertEqual(len(pairs)&(len(pairs)-1),0)

    def test_origin_group_optimization_does_not_remove_players(self):
        for n,g in ((16,4),(22,10),(32,8)):
            ids=self.participants(n)
            origins={str(p):str(i%g) for i,p in enumerate(ids)}
            ordered=spread_groups_in_bracket(ids,origins)
            self.assertCountEqual(ordered,ids)
            self.assertEqual(spread_groups_in_bracket(ordered,origins),ordered)
            pairs=bracket_pairs(ordered)
            for a,b in pairs:
                if a and b and g>=n//2:
                    self.assertNotEqual(origins[str(a)],origins[str(b)])

    def test_match_lengths_preserve_set_mode(self):
        r={'mode':'sets','best_of_sets':5,'best_of_legs_per_set':5,'max_legs':5}
        v=round_match_rules(r,{'quarterfinal':7},'quarterfinal')
        self.assertEqual(v['best_of_sets'],7)
        self.assertEqual(v['best_of_legs_per_set'],5)
        self.assertEqual(r['best_of_sets'],5)

    def test_winner_uses_sets_when_present(self):
        a,b=self.participants(2)
        self.assertEqual(winner({'player1_id':a,'player2_id':b,'sets1':3,'sets2':2,'legs1':3,'legs2':9}),a)
        self.assertEqual(winner({'player1_id':a,'player2_id':b,'sets1':None,'sets2':None,'legs1':1,'legs2':3}),b)

    def test_cup_fixed_rules_and_reject_invalid_qualifications(self):
        self.assertEqual(CUP_FIXED['best_of_sets'],5)
        self.assertEqual(CUP_FIXED['best_of_legs_per_set'],5)
        valid={'group_count':3,'qualifiers':2,'best_third_count':2,'follow':True,
            'group_rules':{'mode':'sets','best_of_sets':5,'best_of_legs_per_set':5},
            'ko_rules':{'mode':'sets','best_of_sets':5,'best_of_legs_per_set':5},
            'groups':[[str(x) for x in self.participants(4)] for _ in range(3)]}
        result=normalize(valid,12,'cup')
        self.assertEqual(result['group_rules']['best_of_sets'],5)
        self.assertEqual(result['ko_rules']['best_of_legs_per_set'],5)
        for bad in ({'best_third_count':4},{'qualifiers':0},{'group_count':99},{'best_third_count':2,'follow':False}):
            cfg={**valid,**bad}
            with self.assertRaises(web.HTTPBadRequest):normalize(cfg,12,'cup')

if __name__=='__main__':unittest.main()

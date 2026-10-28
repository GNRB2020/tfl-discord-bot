"""Contract and property tests for the SAME planner used in production.

No external I/O or Neon access; exhaustive small brackets and randomized
larger brackets include byes, a two-loss grand final and invalid data.
"""
import random
import unittest
from stingrays_v2.rules import bracket_pairs
from stingrays_v2.ko_progression import BracketStateError, plan_next_ko_round


def game(a,b,rnd,pos,winner=None):
    winner=a if winner is None else winner
    return {'player1_id':a,'player2_id':b,'round_number':rnd,
            'bracket_position':pos,'status':'finished',
            'legs1':3 if winner==a else 0,'legs2':0 if winner==a else 3,
            'sets1':None,'sets2':None}


class KnockoutProgressionTests(unittest.TestCase):
    def test_single_ko_keeps_published_bracket_halves(self):
        roster=list(range(8))
        first=bracket_pairs(roster)
        games=[game(a,b,1,i) for i,(a,b) in enumerate(first,1)]
        next_round=plan_next_ko_round('single_ko',roster,games)
        # Winners of adjacent first-round bracket positions play each other.
        self.assertEqual(next_round['pairs'],[(first[0][0],first[1][0]),
                                              (first[2][0],first[3][0])])
        games += [game(a,b,2,i) for i,(a,b) in enumerate(next_round['pairs'],1)]
        final=plan_next_ko_round('single_ko',roster,games)
        self.assertEqual(final['pairs'],[(first[0][0],first[2][0])])

    def test_single_ko_uses_original_bye_slots(self):
        for size in (3,5,6,7,9,13,17,31,65,127):
            with self.subTest(size=size):
                roster=list(range(size))
                original=bracket_pairs(roster)
                games=[game(a,b,1,i) for i,(a,b) in enumerate(original,1) if a is not None and b is not None]
                byes=[p for a,b in original for p in (a,b) if p is not None and (a is None or b is None)]
                p=plan_next_ko_round('single_ko',roster,games,byes)
                slots=[a if b is None else b if a is None else a for a,b in original]
                self.assertEqual(p['pairs'],[(slots[i],slots[i+1]) for i in range(0,len(slots),2)])

    def test_single_ko_rejects_missing_or_wrong_survivors(self):
        roster=list(range(8))
        first=bracket_pairs(roster)
        games=[game(a,b,1,i) for i,(a,b) in enumerate(first,1)]
        # One expected winner is silently replaced by a first-round loser.
        games.append(game(first[0][1],first[1][0],2,1))
        games.append(game(first[2][0],first[3][0],2,2))
        with self.assertRaises(BracketStateError):
            plan_next_ko_round('single_ko',roster,games)

    def test_double_ko_requires_final_reset_if_undefeated_loses(self):
        games=[game(1,2,1,1,winner=1)]
        p=plan_next_ko_round('double_ko',[1,2],games)
        self.assertEqual(p['pairs'],[(1,2)])
        games.append(game(1,2,2,1,winner=2))
        p=plan_next_ko_round('double_ko',[1,2],games)
        self.assertEqual(p['pairs'],[(1,2)])
        self.assertTrue(p['reset_final'])
        games.append(game(1,2,3,1,winner=2))
        done=plan_next_ko_round('double_ko',[1,2],games)
        self.assertTrue(done['completed'])
        self.assertEqual(done['champion'],2)

    def test_double_ko_no_reset_when_undefeated_champion_wins(self):
        games=[game(1,2,1,1,winner=1),game(1,2,2,1,winner=1)]
        done=plan_next_ko_round('double_ko',[1,2],games)
        self.assertTrue(done['completed'])
        self.assertEqual(done['champion'],1)

    def test_full_tournaments_and_idempotent_round_plan(self):
        for kind in ('single_ko','double_ko'):
            for size in (2,3,4,5,6,7,8,10,13,16,17,22,30,64,100,127,128):
                for seed in (1,2,3):
                    with self.subTest(kind=kind,size=size,seed=seed):
                        rng=random.Random(seed*109+size)
                        roster=list(range(size))
                        first=bracket_pairs(roster)
                        games=[]
                        byes=[p for a,b in first for p in (a,b) if p is not None and (a is None or b is None)]
                        pairs=[(a,b) for a,b in first if a is not None and b is not None]
                        rnd=1
                        for _ in range(40):
                            for pos,(a,b) in enumerate(pairs,1):
                                winner=rng.choice((a,b))
                                games.append(game(a,b,rnd,pos,winner))
                            d=plan_next_ko_round(kind,roster,games,byes)
                            self.assertEqual(d,plan_next_ko_round(kind,roster,games,byes))
                            if d['completed']:
                                break
                            pairs=d['pairs']
                            rnd=d['round']
                            self.assertTrue(pairs)
                            self.assertEqual(len(set(p for a,b in pairs for p in (a,b))),len(pairs)*2)
                        else:self.fail('KO never completed')
                        self.assertIn(d['champion'],roster)
                        if kind=='single_ko':self.assertEqual(len(games),size-1)
                        else:
                            self.assertGreaterEqual(len(games),size-1)
                            self.assertLessEqual(len(games),2*size-1)
                            losses={p:0 for p in roster}
                            for m in games:
                                losses[m['player2_id'] if m['legs1']>m['legs2'] else m['player1_id']]+=1
                            for player in roster:
                                if player!=d['champion']:self.assertEqual(losses[player],2)
                            self.assertLess(losses[d['champion']],2)

    def test_refuses_corrupt_rounds(self):
        roster=[1,2,3,4]
        cases=[
            [game(1,2,1,1),game(1,3,1,2)], # double appearance
            [game(1,2,1,1),game(2,3,2,1)], # eliminated player
            [game(1,2,1,1,winner=2),game(3,4,1,2),game(2,3,2,1,winner=3),game(3,4,3,1)], # eliminated 4 returns
            [{**game(1,2,1,1), 'legs1':2,'legs2':2}],
            [{**game(1,2,1,1),'status':'running'}],
        ]
        for matches in cases:
            with self.subTest(matches=matches),self.assertRaises(BracketStateError):
                plan_next_ko_round('single_ko',roster,matches,[3,4] if len(matches)==1 else [])


if __name__=='__main__':unittest.main()

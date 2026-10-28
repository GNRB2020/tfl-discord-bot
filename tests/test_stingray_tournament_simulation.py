"""In-memory complete tournament and KO invariants. No Neon access."""
import unittest
from stingrays_v2.tournament_simulator import simulate


class TournamentSimulationTests(unittest.TestCase):
    def test_30_player_cup_with_best_placed(self):
        d = simulate({'players': 30, 'groups': 10, 'qualifiers': 1,
                      'wildcards': 6, 'seed': 91})
        self.assertEqual(d['preliminary']['matches'], 30)
        self.assertEqual(d['qualification']['direct'], 10)
        self.assertEqual(d['qualification']['additional'], 6)
        self.assertEqual(d['final']['participants'], 16)
        self.assertEqual(d['final']['matches'], 15)
        self.assertEqual(d['total_matches'], 45)
        self.assertEqual(d['writes'], 0)

    def test_100_players_10_groups(self):
        d = simulate({'players': 100, 'groups': 10, 'qualifiers': 2})
        self.assertEqual(d['preliminary']['matches'], 450)
        self.assertEqual(d['final']['participants'], 20)
        self.assertEqual(d['final']['matches'], 19)
        self.assertEqual(d['total_matches'], 469)

    def test_direct_ko_byes(self):
        for number in (3, 7, 9, 17, 64, 127):
            with self.subTest(players=number):
                d = simulate({'players': number, 'format': 'single_ko'})
                self.assertEqual(d['final']['matches'], number - 1)
                self.assertEqual(d['total_matches'], number - 1)
                self.assertEqual(d['writes'], 0)

    def test_double_ko_ends_without_eliminating_one_loss_players(self):
        for number in (2, 3, 7, 16, 32, 65, 128):
            with self.subTest(players=number):
                d = simulate({'players': number, 'format': 'double_ko', 'seed': number})
                self.assertGreaterEqual(d['final']['matches'], number - 1)
                self.assertLessEqual(d['final']['matches'], 2 * number - 1)
                self.assertLess(d['final']['rounds'], 31)
                self.assertTrue(d['final']['champion'])

    def test_grouped_double_ko(self):
        d = simulate({'players': 64, 'groups': 8, 'qualifiers': 2,
                      'follow_format': 'double_ko'})
        self.assertEqual(d['final']['participants'], 16)
        self.assertGreaterEqual(d['final']['matches'], 15)

    def test_reproducible(self):
        a = {'players': 36, 'groups': 6, 'qualifiers': 2, 'seed': 2026}
        self.assertEqual(simulate(a), simulate(a))
        self.assertNotEqual(simulate(a)['final']['champion'],
                            simulate({**a, 'seed': 2027})['final']['champion'])

    def test_invalid_configuration(self):
        for params in ({'players': 1}, {'players': 129},
                       {'players': 12, 'groups': 10},
                       {'players': 10, 'groups': 2, 'qualifiers': 8},
                       {'players': 8, 'groups': 2, 'wildcards': 100},
                       {'players': 30, 'best_of': 6},
                       {'players': 8, 'format': 'invalid'},
                       {'players': 8, 'follow_format': 'round_robin'},
                       {'players': 8, 'seed': -1}):
            with self.subTest(spec=params), self.assertRaises(ValueError):
                simulate(params)

    def test_ranking_tie_needs_manual_choice(self):
        found = False
        for seed in range(30):
            d = simulate({'players': 30, 'groups': 10, 'qualifiers': 1,
                          'wildcards': 6, 'seed': seed})
            if d['qualification']['cutoff_tie']:
                found = True
                self.assertIn('Adminentscheidung', d['qualification']['note'])
                break
        self.assertTrue(found)

    def test_all_group_matches_have_two_distinct_participants(self):
        for n in (6, 15, 48, 100, 128):
            groups = min(n // 2, 12)
            d = simulate({'players': n, 'groups': groups, 'qualifiers': 1})
            self.assertEqual(d['preliminary']['groups'], groups)
            self.assertTrue(d['final']['champion'])
            self.assertEqual(d['writes'], 0)


if __name__ == '__main__':
    unittest.main()

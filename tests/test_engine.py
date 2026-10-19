import unittest
from dart_engine import Rules, Match, possible_checkout_darts

class EngineTests(unittest.TestCase):
    def test_checkouts(self):
        self.assertEqual(possible_checkout_darts(170), [3])
        self.assertEqual(possible_checkout_darts(40), [1, 2, 3])
        self.assertEqual(possible_checkout_darts(159), [])
    def test_best_of_six_draw(self):
        m = Match(Rules(start_score=40, max_legs=6), ('A', 'B'))
        for i in range(6):
            winner = i % 2
            if m.current != winner:
                m.submit(m.current, 0)
            m.submit(winner, 40, darts=1, checkout=True)
        self.assertTrue(m.done)
        self.assertEqual(m.legs, [3, 3])
    def test_sets(self):
        m = Match(Rules(start_score=40, mode='sets', best_of_sets=3, best_of_legs_per_set=3), ('A','B'))
        for _ in range(4):
            if m.current != 0: m.submit(1, 0)
            m.submit(0, 40, darts=1, checkout=True)
        self.assertTrue(m.done)
        self.assertEqual(m.sets, [2,0])
    def test_invalid(self):
        m = Match(Rules(start_score=501), ('A','B'))
        with self.assertRaises(ValueError): m.submit(1, 60)
        with self.assertRaises(ValueError): m.submit(0, 181)

if __name__ == '__main__': unittest.main()

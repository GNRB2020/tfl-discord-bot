import unittest
from stingrays_v2.rules import elo_change,round_robin,rank_rows,mode_rules,bracket_pairs
from stingrays_v2.security import hash_password,verify_password
class CompetitionTests(unittest.TestCase):
 def test_elo(self):
  self.assertEqual(elo_change(1000,1000,1)[0],32)
  self.assertEqual(elo_change(1000,1000,0)[0],-32)
  self.assertEqual(elo_change(1000,1000,.5)[0],0)
 def test_robin(self):
  for n in range(2,16):
   fixtures=round_robin(range(n));self.assertEqual(len(fixtures),n*(n-1)//2)
   self.assertEqual(len({frozenset((a,b)) for _,a,b in fixtures}),len(fixtures))
   self.assertEqual(len(round_robin(range(n),True)),2*len(fixtures))
 def test_vm(self):
  self.assertEqual(mode_rules('vm','groups')['max_legs'],5)
  self.assertEqual(mode_rules('vm','knockout')['best_of_sets'],3)
  self.assertEqual(mode_rules('vm','knockout',True)['best_of_sets'],5)
 def test_bracket(self):
  pairs=bracket_pairs(list(range(13)));self.assertEqual(len(pairs),8)
  self.assertEqual(sum(x is None or y is None for x,y in pairs),3)
 def test_rank(self):
  r=rank_rows([{'player1_id':1,'player2_id':2,'status':'finished','legs1':4,'legs2':0}], [1,2]);self.assertEqual(r[0]['player_id'],1)
 def test_hash(self):
  h=hash_password('verysecure-passphrase');self.assertTrue(verify_password('verysecure-passphrase',h));self.assertFalse(verify_password('wrong',h))
if __name__=='__main__':unittest.main()

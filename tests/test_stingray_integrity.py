"""Integrity checks for live scores and K.O. release safety."""
import unittest
from uuid import uuid4
from aiohttp import web
from stingrays_v2.live_stats import live_averages
from stingrays_v2.api import _validate_released_bracket_roster


class LiveScorerTests(unittest.TestCase):
    def test_bust_consumes_darts_without_scored_points(self):
        visits=[{'player':0,'score':100,'darts':3},
                {'player':0,'score':60,'darts':3,'bust':True},
                {'player':1,'score':140,'darts':3},
                {'player':1,'score':50,'darts':2}]
        self.assertEqual(live_averages(visits),[50,114])

    def test_empty_invalid_visits_are_not_fabricated(self):
        self.assertEqual(live_averages([]),[None,None])
        self.assertEqual(live_averages([{'player':8,'score':180,'darts':3},
            {'player':0,'score':100,'darts':0},
            {'player':1,'score':'invalid','darts':3}]),[None,None])


class BracketReleaseTests(unittest.TestCase):
    def ids(self,n):return [uuid4() for _ in range(n)]

    def test_release_allows_bye_if_roster_complete(self):
        a,b,c=self.ids(3)
        rows=[{'player1_id':a,'player2_id':b}]
        self.assertIsNone(_validate_released_bracket_roster(rows,
             {'participants':[str(a),str(b),str(c)],'bye_players':[str(c)]}))

    def test_release_rejects_missing_bye(self):
        a,b,c=self.ids(3)
        with self.assertRaises(web.HTTPConflict):
            _validate_released_bracket_roster([{'player1_id':a,'player2_id':b}],
                    {'participants':[str(a),str(b),str(c)]})

    def test_release_rejects_duplicate_and_roster_swap(self):
        a,b,c,d=self.ids(4)
        with self.assertRaises(web.HTTPConflict):
            _validate_released_bracket_roster([{'player1_id':a,'player2_id':b},
                {'player1_id':a,'player2_id':c}],
                {'participants':[str(a),str(b),str(c),str(d)]})
        with self.assertRaises(web.HTTPConflict):
            _validate_released_bracket_roster([{'player1_id':a,'player2_id':b},
                {'player1_id':c,'player2_id':uuid4()}],
                {'participants':[str(a),str(b),str(c),str(d)]})

    def test_no_match_or_empty_roster_cannot_be_approved(self):
        with self.assertRaises(web.HTTPConflict):
            _validate_released_bracket_roster([],{'participants':[]})

if __name__=='__main__':unittest.main()

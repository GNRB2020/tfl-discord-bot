"""Regression: a successfully scored match must never be reported as unsaved
because a downstream phase needs manual qualification or fails unexpectedly.
"""
import unittest
from unittest.mock import patch,AsyncMock
from aiohttp import web
from stingrays_v2.advancement_guard import advance_with_feedback

class AdvancementFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_success(self):
        with patch('stingrays_v2.tournament_automation.progress',new_callable=AsyncMock) as p:
            status=await advance_with_feedback(None,'comp')
            self.assertEqual(status,{'status':'ok'})
            p.assert_awaited_once()

    async def test_qualification_tie_requires_admin_not_restart(self):
        with patch('stingrays_v2.tournament_automation.progress',new_callable=AsyncMock,
                   side_effect=web.HTTPConflict(text='Zwei Spieler gleichplatziert')):
            status=await advance_with_feedback(None,'comp')
            self.assertEqual(status['status'],'attention')
            self.assertIn('gleichplatziert',status['message'])

    async def test_unexpected_db_failure_is_visible_and_logged(self):
        with patch('stingrays_v2.tournament_automation.progress',new_callable=AsyncMock,
                   side_effect=RuntimeError('private connection details')):
            with patch('stingrays_v2.advancement_guard.log.exception') as logger:
                status=await advance_with_feedback(None,'comp')
            self.assertEqual(status['status'],'error')
            self.assertIn('incident',status)
            self.assertNotIn('private connection details',status['message'])
            logger.assert_called_once()

if __name__=='__main__':unittest.main()

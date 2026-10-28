"""Verify tournament-center browser workflow offline, without a Neon connection."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / 'stingrays_v2'

DASH = {'profile': {}, 'viewed_player_id': None, 'ladder': [],
        'recent_totals': {'wins': 0, 'draws': 0, 'losses': 0},
        'competitions': [], 'own_open': [], 'recent': []}
BOARD = [{'id': i, 'label': f'Board {i}', 'enabled': True,
          'match_id': None, 'competition_id': None, 'competition': None,
          'player1': None, 'player2': None} for i in range(1, 23)]
CENTER = {'boards': BOARD, 'unassigned': [], 'ready': [
            {'match_id': 'm-1', 'competition_id': 'c-1', 'competition': 'Test-Cup',
             'phase': 'Vorrunde', 'player1': 'Alpha', 'player2': 'Beta'}],
          'counts': {'running': 0, 'open_total': 1, 'active_competitions': 1},
          'board_count': 22, 'free_boards': 22}
SIM = {'players': 30, 'seed': 42, 'total_matches': 45, 'writes': 0,
       'preliminary': {'groups': 10, 'matches': 30},
       'qualification': {'direct': 10, 'additional': 6, 'cutoff_tie': False},
       'final': {'matches': 15, 'rounds': 4, 'byes': 0,
                 'champion': 'Spieler 001', 'same_group_first_round': 0},
       'checks': ['Keine Datenbankänderung']}


def run():
    for width in (1366, 390):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH') or None,
                                        args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': width, 'height': 900})
            js_errors = []
            page.on('pageerror', lambda error: js_errors.append(str(error)))

            mocks = {'me': {'role': 'admin', 'id': 'a-1', 'username': 'Testadmin',
                            'must_change_password': False},
                     'dashboard': DASH, 'players': [], 'live-games': [],
                     'tournament-center': CENTER,
                     'admin/tournament-simulation': SIM}
            page.goto('about:blank')
            page.set_content((ROOT / 'index.html').read_text(), wait_until='domcontentloaded')
            page.evaluate("""(mocks) => {
                window.__apiCalls = [];
                window.fetch = async (url, opts = {}) => {
                  const key = String(url).split('/dart/v2/api/')[1]?.split('?')[0] || '';
                  window.__apiCalls.push([(opts.method || 'GET'), key]);
                  return new Response(JSON.stringify(mocks[key] || {}),
                                      {status:200,headers:{'Content-Type':'application/json'}});
                };
            }""", mocks)
            page.add_style_tag(content=(ROOT / 'style.css').read_text())
            page.add_script_tag(content=(ROOT / 'training_minigames.js').read_text())
            page.add_script_tag(content=(ROOT / 'app.js').read_text())
            page.locator('#dashboard').wait_for(state='visible', timeout=8000)
            page.locator('nav [data-view="boards"]').evaluate('(button) => button.click()')
            page.locator('.tournament-center').wait_for(timeout=8000)
            assert page.locator('.center-board').count() == 22, '22 boards not rendered'
            assert page.get_by_text('Test-Cup').count() >= 1
            assert page.get_by_text('Alpha – Beta').count() >= 1
            if width == 390:
                assert page.locator('.simulation-form').count() == 1
            page.locator('.simulation-form input[name="players"]').fill('30')
            page.locator('.simulation-form input[name="groups"]').fill('10')
            page.locator('.simulation-form input[name="qualifiers"]').fill('1')
            page.locator('.simulation-form input[name="wildcards"]').fill('6')
            page.locator('.simulation-form button[type="submit"]').click()
            page.get_by_text('Simulation erfolgreich').wait_for(timeout=8000)
            assert ['POST', 'admin/tournament-simulation'] in page.evaluate('window.__apiCalls')
            assert not js_errors, (width, js_errors)
            browser.close()


if __name__ == '__main__':
    run()
    print('Tournament center smoke test passed: desktop and mobile')

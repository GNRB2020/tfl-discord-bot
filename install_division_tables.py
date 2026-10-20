"""Einmalig im Bot-Repository ausführen: python install_division_tables.py"""
from pathlib import Path

bot = Path(__file__).with_name('bot.py')
if not bot.exists():
    raise SystemExit('FEHLER: bot.py fehlt. Script neben bot.py ablegen.')
s = bot.read_text(encoding='utf-8')
if 'from division_tables import division_table_loop' not in s:
    anchor = 'from sheets_connection import get_season_spreadsheet, get_season_worksheet'
    if anchor not in s:
        raise SystemExit('FEHLER: Erwarteter Import aus sheets_connection fehlt. Keine Änderungen.')
    s = s.replace(anchor, anchor + '\nfrom division_tables import division_table_loop', 1)
if '_division_tables_started = False' not in s:
    anchor = '_cache_task_started = False'
    if anchor not in s:
        raise SystemExit('FEHLER: on_ready Initialisierung fehlt. Keine Änderungen.')
    s = s.replace(anchor, anchor + '\n_division_tables_started = False', 1)
original = 'global _client_synced_once, _cache_task_started'
modified = 'global _client_synced_once, _cache_task_started, _division_tables_started'
if original in s:
    s = s.replace(original, modified, 1)
if 'asyncio.create_task(division_table_loop(client, WB))' not in s:
    anchor = '    print("🤖 Bot bereit")'
    if anchor not in s:
        raise SystemExit('FEHLER: on_ready Ende nicht gefunden. Keine Änderungen.')
    insertion = '''    if not _division_tables_started and SHEETS_ENABLED and WB is not None:
        asyncio.create_task(division_table_loop(client, WB))
        _division_tables_started = True
        print("[TABELLEN] Auto-Update alle 15 Minuten gestartet")

'''
    s = s.replace(anchor, insertion + anchor, 1)
compile(s, str(bot), 'exec')
backup = bot.with_suffix('.py.bak')
if not backup.exists():
    backup.write_text(bot.read_text(encoding='utf-8'), encoding='utf-8')
bot.write_text(s, encoding='utf-8')
print('OK: bot.py aktualisiert. Backup: bot.py.bak')

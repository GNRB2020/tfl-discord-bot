"""TFL-Tabellen: sechs Divisionen und zwei Coop-Gruppen, Update alle 15 Minuten."""
import asyncio
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import discord
from sheet_guard import get_all_values_cached

LOG = logging.getLogger(__name__)
CHANNEL_ID = 1562124923441254450
INTERVAL = 900
MARKER = 'TFL-TABELLE-DIV-'
COOP_GROUPS = ('Coop_A', 'Coop_B')
COOP_MARKER = 'TFL-TABELLE-COOP-'


def calculate(rows):
    players = {}
    for row in rows[1:]:
        home = row[3].strip() if len(row) > 3 else ''
        result = row[4].strip() if len(row) > 4 else ''
        away = row[5].strip() if len(row) > 5 else ''
        if not home or not away or home.casefold() == away.casefold():
            continue
        for name in (home, away):
            k = name.casefold()
            if k not in players:
                players[k] = dict(name=name, sp=0, s=0, u=0, n=0, won=0, lost=0, pts=0)
        match = re.fullmatch(r'\s*([012])\s*[:\-]\s*([012])\s*', result)
        if not match:
            continue
        a, b = map(int, match.groups())
        if a + b != 2:
            continue
        p, q = players[home.casefold()], players[away.casefold()]
        for record, scored, conceded in ((p, a, b), (q, b, a)):
            record['sp'] += 1
            record['won'] += scored
            record['lost'] += conceded
            record['pts'] += scored
            if scored > conceded: record['s'] += 1
            elif scored == conceded: record['u'] += 1
            else: record['n'] += 1
    return sorted(players.values(), key=lambda p: (-p['pts'], -(p['won']-p['lost']), -p['won'], p['name'].casefold()))


def render(division, rows):
    standings = calculate(rows)
    header = 'Pl  Spieler               Sp S U N  Diff Pkt'
    lines = [header, '-' * len(header)]
    for idx, p in enumerate(standings, 1):
        name = p['name'][:20]
        diff = p['won'] - p['lost']
        lines.append(f"{idx:>2}  {name:<20} {p['sp']:>2} {p['s']:>1} {p['u']:>1} {p['n']:>1} {diff:>+5} {p['pts']:>3}")
    if not standings:
        lines.append('Keine Spieler gefunden.')
    now = datetime.now(ZoneInfo('Europe/Berlin')).strftime('%d.%m.%Y %H:%M')
    return discord.Embed(
        title=f'Division {division} | Tabelle',
        description='```\n' + '\n'.join(lines) + '\n```',
        color=discord.Color.blurple(),
    ).set_footer(text=f'{MARKER}{division} | Stand: {now} Uhr | Aktualisierung alle 15 Minuten')


def calculate_coop(rows):
    """Coop-Wertung: Siege 2, Remis 1, Niederlagen 0; Kader steht in Spalte N."""
    teams = {}
    def add(name):
        name = name.strip()
        if name and name.casefold() not in ('team', 'teamname', 'heim', 'gast', 'heimteam', 'gastteam', 'coop-gruppe a', 'coop-gruppe b'):
            teams.setdefault(name.casefold(), dict(name=name, sp=0, s=0, u=0, n=0, won=0, lost=0, pts=0))
    for row in rows[1:]:
        if len(row) > 13:
            add(row[13])
    for row in rows[1:]:
        home = row[3].strip() if len(row) > 3 else ''
        away = row[5].strip() if len(row) > 5 else ''
        result = row[4].strip() if len(row) > 4 else ''
        if not home or not away or home.casefold() == away.casefold():
            continue
        add(home)
        add(away)
        match = re.fullmatch(r'\s*([012])\s*[:\-]\s*([012])\s*', result)
        if not match:
            continue
        a, b = map(int, match.groups())
        if a + b != 2:
            continue
        for rec, scored, conceded in ((teams[home.casefold()], a, b), (teams[away.casefold()], b, a)):
            rec['sp'] += 1
            rec['won'] += scored
            rec['lost'] += conceded
            if scored > conceded:
                rec['s'] += 1
                rec['pts'] += 2
            elif scored == conceded:
                rec['u'] += 1
                rec['pts'] += 1
            else:
                rec['n'] += 1
    return sorted(teams.values(), key=lambda x: (-x['pts'], -(x['won']-x['lost']), -x['won'], -x['s'], x['name'].casefold()))


def render_coop(group, rows):
    standings = calculate_coop(rows)
    header = 'Pl  Team                 Sp S U N  Diff Pkt'
    lines = [header, '-' * len(header)]
    for i, r in enumerate(standings, 1):
        lines.append(f"{i:>2}  {r['name'][:20]:<20} {r['sp']:>2} {r['s']:>1} {r['u']:>1} {r['n']:>1} {r['won']-r['lost']:>+5} {r['pts']:>3}")
    if not standings:
        lines.append('Keine Teams gefunden.')
    now = datetime.now(ZoneInfo('Europe/Berlin')).strftime('%d.%m.%Y %H:%M')
    return discord.Embed(
        title=f'Coop League | Gruppe {group[-1]} | Tabelle',
        description='```\n' + '\n'.join(lines) + '\n```',
        color=discord.Color.blurple(),
    ).set_footer(text=f'{COOP_MARKER}{group} | Stand: {now} Uhr | Aktualisierung alle 15 Minuten')


async def find_coop_message(channel, bot_id, group):
    marker = f'{COOP_MARKER}{group} |'
    async for msg in channel.history(limit=250):
        if msg.author.id == bot_id and any(
            emb.footer and emb.footer.text and emb.footer.text.startswith(marker)
            for emb in msg.embeds
        ):
            return msg
    return None


async def find_message(channel, bot_id, division):
    marker = f'{MARKER}{division} |'
    async for msg in channel.history(limit=250):
        if msg.author.id == bot_id and any(
            emb.footer and emb.footer.text and emb.footer.text.startswith(marker)
            for emb in msg.embeds
        ):
            return msg
    return None



# TFL_WEB_STANDINGS_EXPORT_V1
import os
import json
import urllib.request

def publish_web_standings(tables):
    base = os.getenv('TFL_API_URL', '').rstrip('/')
    token = os.getenv('TFL_WEB_TOKEN', '')
    if not base or not token or not base.startswith('https://'):
        LOG.warning('TFL Website-Export deaktiviert: TFL_API_URL / TFL_WEB_TOKEN fehlen')
        return
    try:
        raw = json.dumps({'tables': tables}, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(base + '/api/update/web/standings', data=raw,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            LOG.info('TFL Website-Snapshot übertragen: %s', response.status)
    except Exception:
        LOG.exception('TFL Website-Snapshot konnte nicht übertragen werden')


NEWS_CHANNEL_IDS = (1544630487002259476, 1515987400097009694, 1275077454712668320)
async def publish_tfl_news(client):
    """Read-only Discord history, limited to 3 channels, published alongside standings."""
    import urllib.request
    import json
    import os
    base=os.getenv('TFL_API_URL','').rstrip('/')
    token=os.getenv('TFL_WEB_TOKEN','')
    if not base.startswith('https://') or not token:
        return
    items=[]
    for channel_id in NEWS_CHANNEL_IDS:
        try:
            channel=client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            async for msg in channel.history(limit=12):
                if not msg.content and not msg.embeds: continue
                body=msg.content or (msg.embeds[0].description or msg.embeds[0].title or '')
                title=(msg.embeds[0].title if msg.embeds and msg.embeds[0].title else '') or (body.splitlines()[0] if body else 'TFL News')
                items.append({'id':str(msg.id),'channel':channel.name,'title':title[:150],
                    'content':body[:2800],'date':msg.created_at.isoformat(),
                    'url':msg.jump_url})
        except Exception:
            LOG.exception('News-Kanal %s konnte nicht gelesen werden',channel_id)
    if not items: return
    unique={v['id']:v for v in items}
    sorted_items=sorted(unique.values(),key=lambda v:v['date'],reverse=True)[:36]
    def send():
        data=json.dumps({'items':sorted_items},ensure_ascii=False).encode('utf-8')
        req=urllib.request.Request(base+'/api/update/web/news',data=data,
           headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
        with urllib.request.urlopen(req,timeout=10) as resp:
            LOG.info('TFL News übertragen: %s (Einträge %s)',resp.status,len(sorted_items))
    try: await asyncio.to_thread(send)
    except Exception: LOG.exception('TFL News konnten nicht übertragen werden')



def build_coop_web_items(group, rows):
    """Use same B:H columns as the player Coop UI, no second sheet read."""
    items=[]
    for row in rows[1:]:
        home=(row[3] if len(row)>3 else '').strip()
        away=(row[5] if len(row)>5 else '').strip()
        if not home or not away or home.lower() in ('heim','heimteam'): continue
        score=(row[4] if len(row)>4 else '').strip()
        is_finished=bool(re.fullmatch(r'\s*[012]\s*[:\-]\s*[012]\s*',score)) and sum(int(x) for x in re.findall(r'\d',score))==2
        items.append({'group':group,'round':'Gruppenphase','home':home,'away':away,'score':score if is_finished else '',
                      'date':(row[1] if len(row)>1 else '').strip(),
                      'mode':(row[2] if len(row)>2 else '').strip(),
                      'link':(row[6] if len(row)>6 else '').strip(),
                      'status':'finished' if is_finished else 'open'})
    return items


def build_cup_web_items():
    """Read same Cup worksheet as schedule.py (gid=47251903), from sheet_guard cache."""
    import schedule
    ws=schedule.get_cup_worksheet()
    rows=get_all_values_cached(lambda:ws,sheet_name=schedule.get_schedule_sheet_cache_name(ws),ttl_seconds=840)
    items=[]
    for row in rows[1:]:
        rnd=schedule.normalize_text(row[0] if len(row)>0 else '')
        home=schedule.normalize_text(row[1] if len(row)>1 else '')
        score=schedule.normalize_text(row[2] if len(row)>2 else '')
        away=schedule.normalize_text(row[3] if len(row)>3 else '')
        when=schedule.normalize_text(row[4] if len(row)>4 else '')
        if not home or not away: continue
        mode=schedule.get_mode_from_round(rnd)
        # Cup results may be written as 1:0 / 2:1 or 1-0 / 2-1.
        # The legacy schedule.is_finished_result() only accepts hyphens.
        canonical = re.sub(r'\s+', '', score).replace('：', ':').replace(':', '-')
        finished=bool(schedule.is_finished_result(canonical,mode))
        items.append({'round':schedule.get_round_label(rnd),'mode':mode or '',
            'home':home,'away':away,'score':score if finished else '',
            'date':when,'link':'','status':'finished' if finished else 'open'})
    return items


def publish_web_competitions(data):
    base=os.getenv('TFL_API_URL','').rstrip('/')
    token=os.getenv('TFL_WEB_TOKEN','')
    if not base.startswith('https://') or not token: return
    try:
        raw=json.dumps({'competitions':data},ensure_ascii=False).encode('utf-8')
        req=urllib.request.Request(base+'/api/update/web/competitions',data=raw,
           headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
        with urllib.request.urlopen(req,timeout=12) as resp:
            LOG.info('TFL Cup/Coop-Webdaten übertragen: %s',resp.status)
    except Exception:
        LOG.exception('TFL Cup/Coop-Webdaten konnten nicht übertragen werden')



def _table_message_key(message):
    """Identify previously published table embeds by their persistent footer markers."""
    for embed in getattr(message, 'embeds', []) or []:
        footer = getattr(getattr(embed, 'footer', None), 'text', '') or ''
        if footer.startswith(MARKER):
            number = footer[len(MARKER):].split(' |', 1)[0].strip()
            if number in {'1', '2', '3', '4', '5', '6'}:
                return f'division-{number}'
        if footer.startswith(COOP_MARKER):
            group = footer[len(COOP_MARKER):].split(' |', 1)[0].strip()
            if group in COOP_GROUPS:
                return f'coop-{group[-1].lower()}'
    return None


async def _load_existing_table_messages(channel, bot_id):
    """One channel-history pass for all eight tables instead of eight separate passes."""
    existing = {}
    async for message in channel.history(limit=250):
        if getattr(getattr(message, 'author', None), 'id', None) != bot_id:
            continue
        key = _table_message_key(message)
        if key:
            existing.setdefault(key, message)  # newest matching post wins
    return existing


def _same_table_content(current, expected):
    """Ignore changing footer timestamps; compare the actual table content."""
    try:
        current_payload = current.to_dict()
        expected_payload = expected.to_dict()
        current_payload.pop('footer', None)
        expected_payload.pop('footer', None)
        return current_payload == expected_payload
    except (AttributeError, TypeError, ValueError):
        return False


async def _publish_table_if_changed(channel, existing, key, embed):
    """Return True only after a real Discord write."""
    message = existing.get(key)
    if message is not None:
        old_embeds = getattr(message, 'embeds', []) or []
        if len(old_embeds) == 1 and _same_table_content(old_embeds[0], embed):
            return False
        await message.edit(embed=embed)
    else:
        existing[key] = await channel.send(embed=embed)
    # Smooth legitimate bursts (e.g. new season / first bot start).
    await asyncio.sleep(1.0)
    return True


async def refresh(client, workbook):
    web_competitions = {}
    tables_for_web = {}
    now_web = datetime.now(ZoneInfo('Europe/Berlin')).strftime('%d.%m.%Y %H:%M')
    channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
    try:
        existing_tables = await _load_existing_table_messages(channel, client.user.id)
    except Exception:
        LOG.exception('Discord-Tabellen: Bestehende Nachrichten konnten nicht geladen werden')
        existing_tables = None  # never risk creating duplicates after an API error
    writes = 0
    unchanged = 0
    for div in range(1, 7):
        try:
            rows = await asyncio.to_thread(get_all_values_cached, lambda d=div: workbook.worksheet(f'{d}.DIV'), sheet_name=f'{div}.DIV', ttl_seconds=840)
            tables_for_web[f'division-{div}'] = {'title': f'Division {div}', 'items': calculate(rows), 'updated_at': now_web}
            embed = render(div, rows)
            if existing_tables is not None:
                if await _publish_table_if_changed(channel, existing_tables, f'division-{div}', embed):
                    writes += 1
                else:
                    unchanged += 1
        except Exception:
            LOG.exception('Fehler bei Division %s', div)
    for group in COOP_GROUPS:
        try:
            rows = await asyncio.to_thread(get_all_values_cached, lambda g=group: workbook.worksheet(g), sheet_name=group, ttl_seconds=840)
            tables_for_web[f'coop-{group[-1].lower()}'] = {'title': f'Coop League – Gruppe {group[-1]}', 'items': calculate_coop(rows), 'updated_at': now_web}
            web_competitions[f'coop-{group[-1].lower()}'] = {'items':build_coop_web_items(group, rows), 'updated_at':now_web}
            embed = render_coop(group, rows)
            if existing_tables is not None:
                if await _publish_table_if_changed(channel, existing_tables, f'coop-{group[-1].lower()}', embed):
                    writes += 1
                else:
                    unchanged += 1
        except Exception:
            LOG.exception('Fehler bei Coop-Gruppe %s', group)
    LOG.info('[TABELLEN] Discord: %d aktualisiert, %d unverändert', writes, unchanged)
    if tables_for_web:
        await asyncio.to_thread(publish_web_standings, tables_for_web)
    try:
        cup_rows=await asyncio.to_thread(build_cup_web_items)
        web_competitions['cup']={'items':cup_rows,'updated_at':now_web}
    except Exception:
        LOG.exception('TFL Cup-Webdaten konnten nicht gelesen werden')
    if web_competitions:
        await asyncio.to_thread(publish_web_competitions,web_competitions)
    await publish_tfl_news(client)


async def division_table_loop(client, workbook):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await refresh(client, workbook)
        except Exception:
            LOG.exception('Tabellenaktualisierung fehlgeschlagen')
        await asyncio.sleep(INTERVAL)

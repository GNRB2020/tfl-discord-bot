"""TFL-Tabellen: sechs feste Discord-Nachrichten, Update alle 15 Minuten."""
import asyncio
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import discord

LOG = logging.getLogger(__name__)
CHANNEL_ID = 1562124923441254450
INTERVAL = 900
MARKER = 'TFL-TABELLE-DIV-'


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


async def find_message(channel, bot_id, division):
    marker = f'{MARKER}{division} |'
    async for msg in channel.history(limit=250):
        if msg.author.id == bot_id and any(
            emb.footer and emb.footer.text and emb.footer.text.startswith(marker)
            for emb in msg.embeds
        ):
            return msg
    return None


async def refresh(client, workbook):
    channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
    for div in range(1, 7):
        try:
            rows = await asyncio.to_thread(workbook.worksheet(f'{div}.DIV').get_all_values)
            embed = render(div, rows)
            msg = await find_message(channel, client.user.id, div)
            if msg:
                await msg.edit(embed=embed)
            else:
                await channel.send(embed=embed)
        except Exception:
            LOG.exception('Fehler bei Division %s', div)


async def division_table_loop(client, workbook):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await refresh(client, workbook)
        except Exception:
            LOG.exception('Tabellenaktualisierung fehlgeschlagen')
        await asyncio.sleep(INTERVAL)

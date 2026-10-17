"""Coop League: Terminverwaltung und KO-Phase (getrennt von der Einzel-League).

Sheet Coop_KO nutzt A:I: Runde, Spiel, Datum, Modus, Heimteam,
Ergebnis, Gastteam, Link, Reporter. Bereits belegte Brackets werden nie überschrieben.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import uuid
from datetime import datetime, timedelta

import discord
import pytz
from gspread.exceptions import WorksheetNotFound
from sheet_guard import sheet_write_call
from sheets_connection import get_season_spreadsheet

TZ = pytz.timezone('Europe/Berlin')
LOCK = threading.RLock()
KO_SHEET = 'Coop_KO'
KO_CONFIG = 'CoopKOConfig'
REQUESTS = 'CoopTerminAenderungen'
KO_COLUMNS = ['Runde', 'Spiel', 'Datum', 'Modus', 'Heimteam', 'Ergebnis', 'Gastteam', 'Link', 'Reporter']
REQ_COLUMNS = ['ID', 'Gruppe', 'Spielzeile', 'Heim', 'Gast', 'Antragstellerteam', 'Aktion', 'Neuer Termin', 'Status', 'Zeitpunkt']


def player():
    import player as p
    return p


def cell(row, index):
    return str(row[index] or '').strip() if 0 <= index < len(row) else ''


def norm(x):
    return player().normalize_name(x)


def sheet(name):
    return get_season_spreadsheet().worksheet(name)


def ensure_sheet(name, headers, rows=500):
    book = get_season_spreadsheet()
    try:
        ws = book.worksheet(name)
    except WorksheetNotFound:
        ws = book.add_worksheet(title=name, rows=rows, cols=len(headers))
    if ws.col_count < len(headers):
        ws.add_cols(len(headers) - ws.col_count)
    head = ws.row_values(1)
    if not any(head):
        ws.update(f'A1:{chr(64+len(headers))}1', [headers])
    elif [cell(head,i) for i in range(len(headers))] != headers:
        raise ValueError(f'{name}: unerwartete Spaltenüberschriften; nichts überschrieben.')
    return ws


def config():
    ws = ensure_sheet(KO_CONFIG, ['Schlüssel', 'Wert'], 20)
    pairs = {cell(r,0).lower(): cell(r,1) for r in ws.get('A:B')[1:]}
    try:
        number = int(pairs.get('qualifikanten je gruppe', '2'))
    except ValueError:
        number = 2
    return number


def set_config(number):
    if number not in (1,2,4,8,16):
        raise ValueError('Möglich sind 1, 2, 4, 8 oder 16 qualifizierte Teams pro Gruppe.')
    with LOCK:
        ws = ensure_sheet(KO_CONFIG, ['Schlüssel','Wert'], 20)
        rows = ws.get('A:B')
        for n,row in enumerate(rows[1:],2):
            if cell(row,0).lower() == 'qualifikanten je gruppe':
                ws.update(f'B{n}', [[str(number)]])
                return
        ws.update(f'A{len(rows)+1}:B{len(rows)+1}', [['Qualifikanten je Gruppe', str(number)]])


def group_ranking(name):
    p = player()
    rows = p._coop_group_rows(name, True)
    names = list(p._coop_group_roster(rows).values())
    games = list(p._coop_group_matches(name, rows))
    if not names or not games:
        raise ValueError(f'{name}: Kader oder Spielplan fehlt.')
    if any(p._is_open_result_value(m['result']) for m in games):
        raise ValueError(f'{name}: Es sind noch Begegnungen offen.')
    return p._build_coop_table(rows, names, '')


def make_bracket():
    """Seeding A1-Bn, B1-An; zwei Gruppen, KO für 2/4/8/... Teams."""
    with LOCK:
        amount = config()
        a, b = group_ranking('Coop_A'), group_ranking('Coop_B')
        if len(a)<amount or len(b)<amount:
            raise ValueError('Zu wenige Teams für die konfigurierte Qualifikation.')
        ws = sheet(KO_SHEET)  # Ein bestehendes benanntes KO-Sheet wird vorausgesetzt.
        content = ws.get('A:I')
        if any(any(cell(r,c) for c in range(9)) for r in content[1:]):
            raise ValueError('Coop_KO enthält bereits Bracketdaten ab Zeile 2. Kein Überschreiben.')
        if content and any(content[0]) and [cell(content[0],i) for i in range(9)] != KO_COLUMNS:
            raise ValueError('Coop_KO: Die Spalten A:I sind anders belegt. Bitte das Bracketlayout zuerst klären.')
        size=amount*2
        round_label={2:'Finale',4:'Halbfinale',8:'Viertelfinale',16:'Achtelfinale',32:'Sechzehntelfinale'}
        names_a=[x['name'] for x in a[:amount]]
        names_b=[x['name'] for x in b[:amount]]
        # Über Kreuz: beide Gruppensieger können erst im Finale zusammentreffen.
        paired=[]
        for i in range(amount):
            paired.append((names_a[i],names_b[amount-1-i]))
        rows=[]; n=size
        while n>=2:
            label=round_label.get(n,f'Runde der letzten {n}')
            for ix in range(n//2):
                home, away=paired[ix] if n==size else ('','')
                rows.append([label,str(ix+1),'','',home,'vs',away,'',''])
            n//=2
        if not content:
            ws.update('A1:I1',[KO_COLUMNS])
        ws.update(f'A2:I{len(rows)+1}', rows)
        return len(rows), amount


def bracket():
    ws=sheet(KO_SHEET)
    rows=ws.get('A:I')
    if not rows or [cell(rows[0],i) for i in range(9)]!=KO_COLUMNS:
        return []
    out=[]
    for index,row in enumerate(rows[1:],2):
        if cell(row,0):
            out.append({'row':index,'round':cell(row,0),'game':cell(row,1),
                'date':cell(row,2),'mode':cell(row,3),'home':cell(row,4),
                'result':cell(row,5),'away':cell(row,6),'link':cell(row,7)})
    return out


def submit_ko_result(member, rownum, home, away, score, link):
    if score not in ('1:0','0:1'):
        raise ValueError('KO-Spiele benötigen einen Sieger (1:0 oder 0:1).')
    if not link.lower().startswith('https://'):
        raise ValueError('Bitte einen gültigen HTTPS-Racetime-Link eintragen.')
    identity=player()._coop_team_identity(member)
    team=norm(identity['team_name'])
    with LOCK:
        matches=bracket()
        match=next((m for m in matches if m['row']==rownum),None)
        if match is None or norm(match['home'])!=norm(home) or norm(match['away'])!=norm(away):
            raise ValueError('Begegnung nicht mehr aktuell.')
        if team not in (norm(home),norm(away)):
            raise PermissionError('Dein Team spielt nicht in dieser Begegnung.')
        if not player()._is_open_result_value(match['result']):
            raise ValueError('Ergebnis ist bereits eingetragen.')
        winner=home if score=='1:0' else away
        # Bracket-Fortschreibung erst prüfen, dann speichern.
        round_games=[x for x in matches if x['round']==match['round']]
        round_index=next(i for i,x in enumerate(round_games) if x['row']==rownum)
        round_order=list(dict.fromkeys(m['round'] for m in matches))
        round_pos=round_order.index(match['round'])
        nxt=None
        if round_pos+1<len(round_order):
            later=[m for m in matches if m['round']==round_order[round_pos+1]]
            if round_index//2>=len(later):
                raise ValueError('Folgerunde fehlt.')
            nxt=later[round_index//2]
            target='E' if round_index%2==0 else 'G'
            prior=nxt['home'] if target=='E' else nxt['away']
            if prior and norm(prior)!=norm(winner):
                raise ValueError('Folgerunde ist bereits anders belegt. Admin muss prüfen.')
        ws=sheet(KO_SHEET)
        changes=[{'range':f'F{rownum}', 'values':[[score]]},
                 {'range':f'H{rownum}:I{rownum}', 'values':[[link,member.display_name]]}]
        if nxt:
            changes.append({'range':f'{target}{nxt["row"]}', 'values':[[winner]]})
        ws.batch_update(changes)
        return match,winner


def scheduled_for(member):
    identity=player()._coop_team_identity(member)
    group,team=identity['group'],identity['team_name']
    rows=player()._coop_group_rows(group,True)
    return group,team,[m for m in player()._coop_group_matches(group,rows)
        if norm(team) in (norm(m['home']),norm(m['away']))
        and m['date_text'] and player()._is_open_result_value(m['result'])]


def create_change(member, match, operation, date):
    if operation not in ('verschieben','absagen'):
        raise ValueError('Ungültige Aktion')
    identity=player()._coop_team_identity(member)
    group,team=identity['group'],identity['team_name']
    with LOCK:
        current=scheduled_for(member)[2]
        found=next((m for m in current if m['row']==match['row'] and
            norm(m['home'])==norm(match['home']) and norm(m['away'])==norm(match['away'])),None)
        if found is None:
            raise ValueError('Termin nicht mehr aktuell.')
        if operation=='verschieben':
            parsed=TZ.localize(datetime.strptime(date,'%d.%m.%Y %H:%M'))
            if parsed<=datetime.now(TZ):
                raise ValueError('Neuer Termin muss in der Zukunft liegen.')
            from coop_term_offers import _busy
            if _busy(group,match['home'],parsed,match['row']) or _busy(group,match['away'],parsed,match['row']):
                raise ValueError('Ein Team hat zu diesem Zeitpunkt bereits eine Begegnung.')
        ws=ensure_sheet(REQUESTS,REQ_COLUMNS)
        records=ws.get('A:J')
        if any(cell(r,1)==group and cell(r,2)==str(match['row']) and cell(r,8)=='offen' for r in records[1:]):
            raise ValueError('Für das Spiel ist bereits eine offene Änderungsanfrage vorhanden.')
        code=uuid.uuid4().hex[:12]
        row=[code,group,str(match['row']),match['home'],match['away'],team,operation,date,'offen',datetime.now(TZ).strftime('%d.%m.%Y %H:%M')]
        ws.update(f'A{len(records)+1}:J{len(records)+1}',[row])
        return code, match['away'] if norm(team)==norm(match['home']) else match['home']


def pending_changes(member):
    data=player()._coop_team_identity(member)
    ws=ensure_sheet(REQUESTS,REQ_COLUMNS)
    rows=ws.get('A:J')
    return [(i,r) for i,r in enumerate(rows[1:],2) if cell(r,8)=='offen' and
        cell(r,1)==data['group'] and norm(data['team_name']) in (norm(cell(r,3)),norm(cell(r,4)))
        and norm(data['team_name'])!=norm(cell(r,5))]


def respond_change(member, code, accept):
    data=player()._coop_team_identity(member)
    with LOCK:
        records=pending_changes(member)
        target=next(((n,r) for n,r in records if cell(r,0)==code),None)
        if target is None:
            raise PermissionError('Keine offene Anfrage für dein Team.')
        n,row=target; group=cell(row,1); rnum=int(cell(row,2))
        live=player()._coop_group_rows(group,True)
        current=next((m for m in player()._coop_group_matches(group,live) if m['row']==rnum),None)
        if not current or norm(current['home'])!=norm(cell(row,3)) or norm(current['away'])!=norm(cell(row,4)) or not current['date_text'] or not player()._is_open_result_value(current['result']):
            raise ValueError('Das Spiel wurde inzwischen verändert.')
        changes=[]
        if accept:
            action=cell(row,6)
            if action=='verschieben':
                parsed=TZ.localize(datetime.strptime(cell(row,7),'%d.%m.%Y %H:%M'))
                if parsed<=datetime.now(TZ):
                    raise ValueError('Termin liegt in der Vergangenheit.')
                from coop_term_offers import _busy
                if _busy(group,current['home'],parsed,rnum) or _busy(group,current['away'],parsed,rnum):
                    raise ValueError('Terminkollision.')
                changes.append({'range':f'B{rnum}','values':[[cell(row,7)]]})
            elif action=='absagen':
                changes.extend([{'range':f'B{rnum}:C{rnum}','values':[['','']]},
                                {'range':f'G{rnum}','values':[['']] }])
            else:
                raise ValueError('Unbekannte Aktion')
        if changes:
            player()._get_coop_group_ws(group).batch_update(changes)
        ensure_sheet(REQUESTS,REQ_COLUMNS).update(f'I{n}',[['angenommen' if accept else 'abgelehnt']])
        return row, current['link'], current['date_text']


async def update_discord_event(guild, link, operation, new_date):
    """Versucht das bestehende Event mitzupflegen; meldet statt zu schweigen."""
    if not guild or not link:
        return None
    match=re.search(r'(?:discord\.com|discordapp\.com)/events/\d+/(\d+)',link)
    if not match:
        return None
    try:
        event=await guild.fetch_scheduled_event(int(match.group(1)))
        if operation=='absagen':
            await event.delete()
            return 'Discord-Event gelöscht.'
        instant=TZ.localize(datetime.strptime(new_date,'%d.%m.%Y %H:%M'))
        old_length=(event.end_time-event.start_time) if event.end_time else timedelta(hours=3)
        await event.edit(start_time=instant,end_time=instant+old_length)
        return 'Discord-Event verschoben.'
    except (discord.HTTPException, ValueError) as exc:
        return f'Discord-Event muss manuell aktualisiert werden: {exc}'


async def notify_team(guild,group,team,message):
    if not guild:
        return 0
    members=await player()._coop_offer_members(guild,group,team)
    count=0
    for member in members:
        try:
            await member.send(message)
            count+=1
        except discord.HTTPException:
            pass
    return count


class ChangeModal(discord.ui.Modal, title='Coop-Termin verwalten'):
    date=discord.ui.TextInput(label='Neuer Termin (TT.MM.JJJJ HH:MM)', required=False, max_length=24)
    def __init__(self,match,action):
        super().__init__(); self.match=match; self.action=action
    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            raw=str(self.date.value or '').strip()
            if self.action=='verschieben' and not raw:
                raise ValueError('Bitte neuen Termin eingeben.')
            code,opponent=await asyncio.to_thread(create_change,interaction.user,self.match,self.action,raw)
            identity=await asyncio.to_thread(player()._coop_team_identity,interaction.user)
            sent=await notify_team(interaction.guild,identity['group'],opponent,
                f'Coop-Terminänderung für **{self.match["home"]} vs. {self.match["away"]}**: **{self.action}**'
                + (f' auf {raw}' if raw else '') + '. Bitte über /player → Coop-Menü → Terminanfragen prüfen antworten.')
            await interaction.followup.send(f'Anfrage `{code}` gespeichert. {sent} gegnerische Runner per DM informiert.',ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f'Terminänderung nicht möglich: {exc}',ephemeral=True)


class ChangeMatchSelect(discord.ui.Select):
    def __init__(self,matches):
        self.matches={str(i):m for i,m in enumerate(matches[:25])}
        super().__init__(placeholder='Terminiertes Spiel wählen',options=[discord.SelectOption(label=f'{m["home"]} vs. {m["away"]}'[:100],description=m['date_text'][:100],value=str(i)) for i,m in enumerate(matches[:25])])
    async def callback(self,interaction):
        await interaction.response.send_message('Was soll mit diesem Termin geschehen?',view=ChangeActionView(self.matches[self.values[0]]),ephemeral=True)


class ChangeActionView(discord.ui.View):
    def __init__(self,match):
        super().__init__(timeout=600);self.match=match
    @discord.ui.button(label='Verschieben',style=discord.ButtonStyle.primary)
    async def move(self,interaction,button):
        await interaction.response.send_modal(ChangeModal(self.match,'verschieben'))
    @discord.ui.button(label='Absagen',style=discord.ButtonStyle.danger)
    async def cancel(self,interaction,button):
        await interaction.response.send_modal(ChangeModal(self.match,'absagen'))


class ChangeDecisionButton(discord.ui.Button):
    def __init__(self,code,accept):
        super().__init__(label='Annehmen' if accept else 'Ablehnen',style=discord.ButtonStyle.success if accept else discord.ButtonStyle.danger)
        self.code=code;self.accept=accept
    async def callback(self,interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            row, event_link, old_date=await asyncio.to_thread(respond_change,interaction.user,self.code,self.accept)
            event_info=(await update_discord_event(interaction.guild,event_link,cell(row,6),cell(row,7))) if self.accept else None
            response='Terminanfrage '+('angenommen' if self.accept else 'abgelehnt')+'.'
            if event_info:
                response+='\n'+event_info
            await interaction.followup.send(response,ephemeral=True)
            for team in (cell(row,3),cell(row,4)):
                await notify_team(interaction.guild,cell(row,1),team,
                    f'Coop-Terminänderung **{cell(row,3)} vs. {cell(row,4)}** wurde '+('angenommen' if self.accept else 'abgelehnt')+'.')
        except Exception as exc:
            await interaction.followup.send(f'Änderung fehlgeschlagen: {exc}',ephemeral=True)


class ChangeDecisionView(discord.ui.View):
    def __init__(self,code):
        super().__init__(timeout=600)
        self.add_item(ChangeDecisionButton(code,True))
        self.add_item(ChangeDecisionButton(code,False))


class ChangePendingSelect(discord.ui.Select):
    def __init__(self,requests):
        self.requests={str(i):r for i,(_,r) in enumerate(requests[:25])}
        super().__init__(placeholder='Anfrage auswählen',options=[discord.SelectOption(label=f'{cell(r,3)} vs. {cell(r,4)}'[:100],description=(cell(r,6)+' '+cell(r,7))[:100],value=str(i)) for i,r in enumerate(requests[:25])])
    async def callback(self,interaction):
        row=self.requests[self.values[0]]
        await interaction.response.send_message(f'{cell(row,3)} vs. {cell(row,4)}: {cell(row,6)} {cell(row,7)}',view=ChangeDecisionView(cell(row,0)),ephemeral=True)


async def manage_schedule(interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        group,team,matches=await asyncio.to_thread(scheduled_for,interaction.user)
        if not matches:
            await interaction.followup.send('Keine terminierten offenen Coop-Spiele.',ephemeral=True);return
        view=discord.ui.View(timeout=600)
        view.add_item(ChangeMatchSelect(matches))
        await interaction.followup.send('Welchen Coop-Termin möchtest du bearbeiten?',view=view,ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f'Terminverwaltung fehlgeschlagen: {exc}',ephemeral=True)


async def review_changes(interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        requests=await asyncio.to_thread(pending_changes,interaction.user)
        if not requests:
            await interaction.followup.send('Keine offenen Terminanfragen.',ephemeral=True);return
        view=discord.ui.View(timeout=600);view.add_item(ChangePendingSelect(requests))
        await interaction.followup.send('Terminanfragen deines Teams:',view=view,ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f'Terminanfragen konnten nicht geladen werden: {exc}',ephemeral=True)


class KOResultLinkModal(discord.ui.Modal,title='Coop KO-Ergebnis'):
    link=discord.ui.TextInput(label='Racetime-Link',required=True,max_length=300)
    def __init__(self,match,score):
        super().__init__();self.match=match;self.score=score
    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            match,winner=await asyncio.to_thread(submit_ko_result,interaction.user,self.match['row'],self.match['home'],self.match['away'],self.score,str(self.link.value).strip())
            await interaction.followup.send(f'KO-Ergebnis gespeichert: **{match["home"]} {self.score} {match["away"]}**. Sieger: **{winner}**.',ephemeral=True)
            if interaction.guild:
                await player().send_result_post(
                    interaction.guild,
                    f'[Coop_KO {match["round"]}] {datetime.now(TZ).strftime("%d.%m.%Y %H:%M")}\n'
                    f'{match["home"]} vs {match["away"]} → {self.score}\n'
                    f'Modus: Coop KO\n'
                    f'Raceroom: {self.link.value}'
                )
        except Exception as exc:
            await interaction.followup.send(f'KO-Ergebnismeldung fehlgeschlagen: {exc}',ephemeral=True)


class KOResultScoreView(discord.ui.View):
    def __init__(self,match):
        super().__init__(timeout=600);self.match=match
    @discord.ui.button(label='Heimteam gewinnt',style=discord.ButtonStyle.success)
    async def home(self,interaction,button):
        await interaction.response.send_modal(KOResultLinkModal(self.match,'1:0'))
    @discord.ui.button(label='Gastteam gewinnt',style=discord.ButtonStyle.primary)
    async def away(self,interaction,button):
        await interaction.response.send_modal(KOResultLinkModal(self.match,'0:1'))


class KOResultSelect(discord.ui.Select):
    def __init__(self,matches):
        self.matches={str(i):m for i,m in enumerate(matches[:25])}
        super().__init__(placeholder='KO-Spiel auswählen',options=[discord.SelectOption(label=f'{m["home"]} vs. {m["away"]}'[:100],description=m['round'][:100],value=str(i)) for i,m in enumerate(matches[:25])])
    async def callback(self,interaction):
        m=self.matches[self.values[0]]
        await interaction.response.send_message(f'{m["round"]}: {m["home"]} vs. {m["away"]}',view=KOResultScoreView(m),ephemeral=True)


async def ko_report(interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        data=await asyncio.to_thread(player()._coop_team_identity,interaction.user)
        team=norm(data['team_name'])
        matches=[m for m in await asyncio.to_thread(bracket) if m['home'] and m['away'] and player()._is_open_result_value(m['result']) and team in (norm(m['home']),norm(m['away']))]
        if not matches:
            await interaction.followup.send('Keine offenen KO-Spiele für dein Team.',ephemeral=True);return
        view=discord.ui.View(timeout=600);view.add_item(KOResultSelect(matches))
        await interaction.followup.send('Wähle das KO-Spiel:',view=view,ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f'KO-Spiele konnten nicht geladen werden: {exc}',ephemeral=True)


async def ko_overview(interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        games=await asyncio.to_thread(bracket)
        if not games:
            await interaction.followup.send('Noch kein Coop-KO-Bracket erzeugt.',ephemeral=True);return
        lines=[f'**{m["round"]}** · {m["home"] or "TBD"} {m["result"]} {m["away"] or "TBD"}' for m in games]
        await interaction.followup.send('\n'.join(lines)[:1900],ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f'KO-Bracket nicht verfügbar: {exc}',ephemeral=True)


class KOConfigModal(discord.ui.Modal,title='Coop-KO Qualifikation'):
    number=discord.ui.TextInput(label='Qualifikanten je Gruppe (1, 2, 4, 8, 16)',placeholder='2',required=True,max_length=2)
    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            amount=int(str(self.number.value).strip())
            await asyncio.to_thread(set_config,amount)
            await interaction.followup.send(f'Coop-KO: **{amount} Teams je Gruppe**, insgesamt {amount*2} qualifiziert.',ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f'Qualifikation konnte nicht gespeichert werden: {exc}',ephemeral=True)


class KOCreateConfirm(discord.ui.View):
    def __init__(self,owner_id):
        super().__init__(timeout=180);self.owner_id=owner_id
    @discord.ui.button(label='Bracket unwiderruflich erstellen',style=discord.ButtonStyle.danger)
    async def confirm(self,interaction,button):
        if interaction.user.id!=self.owner_id or not player().has_admin_role(interaction.user):
            await interaction.response.send_message('Nur Admins dürfen das Bracket erstellen.',ephemeral=True);return
        await interaction.response.defer(ephemeral=True)
        try:
            count,amount=await asyncio.to_thread(make_bracket)
            await interaction.followup.send(f'Coop-KO erstellt: {count} Spiele, {amount} Qualifikanten je Gruppe.',ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f'Bracket nicht erstellt: {exc}',ephemeral=True)


class KOAdminView(discord.ui.View):
    def __init__(self,owner_id):
        super().__init__(timeout=900);self.owner_id=owner_id
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id or not player().has_admin_role(interaction.user):
            await interaction.response.send_message('Nur Admins.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Qualifikanten einstellen',style=discord.ButtonStyle.primary)
    async def amount(self,interaction,button):
        await interaction.response.send_modal(KOConfigModal())
    @discord.ui.button(label='Bracket erstellen',style=discord.ButtonStyle.danger)
    async def create(self,interaction,button):
        amount=await asyncio.to_thread(config)
        await interaction.response.send_message(f'Bestätigen: **{amount} Teams je Gruppe**, insgesamt {2*amount}. Es wird **nur in ein leeres Coop_KO** geschrieben.',view=KOCreateConfirm(interaction.user.id),ephemeral=True)


async def ko_admin(interaction):
    if not player().has_admin_role(interaction.user):
        await interaction.response.send_message('Nur Admins.',ephemeral=True);return
    amount=await asyncio.to_thread(config)
    await interaction.response.send_message(f'Coop-KO Administration: aktuell **{amount} Qualifikanten je Gruppe**.',view=KOAdminView(interaction.user.id),ephemeral=True)

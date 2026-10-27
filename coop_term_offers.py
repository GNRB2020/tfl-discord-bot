"""Coop-Terminbörse nach dem Vorbild der Divisions-Terminbörse.

Ausschließlich Coop_A / Coop_B. Keine Änderungen an der Einzel-League.
Öffentliche Angebote enthalten bis zu drei freie Termine und keinen festen Gegner.
Beim Anklicken werden freie Begegnungen geprüft, danach wählt ein Runner des
Heimteams den Modus. Persistente Google-Sheets-Daten überstehen Bot-Neustarts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta

import discord
import pytz
from gspread.exceptions import WorksheetNotFound

from sheet_guard import sheet_write_call
from sheets_connection import get_season_spreadsheet

LOG = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Berlin")
CHANNEL_ID = int(os.getenv("TFL_COOP_TERMINBOERSE_CHANNEL_ID", "1544986965202567188"))
CHANNEL_B_ID = int(os.getenv("TFL_COOP_TERMINBOERSE_B_CHANNEL_ID", "1563809712728973342"))


def channel_for_group(group):
    return CHANNEL_B_ID if group == "Coop_B" else CHANNEL_ID
STORE_SHEET = "CoopTerminboerseV3"
MODES = ("AD Boots", "Crosskeys", "Duality", "Logical Enemizer", "Influkeys", "Pilot Spoiler")
HEADERS = ["ID", "Gruppe", "Anbieterteam", "Anbieter ID", "Termin", "Status", "Kanal ID", "Nachricht ID", "Heimteam", "Gastteam", "Matchzeile", "Modus", "Annehmendes Team", "Modus-Deadline", "Event", "Aktualisiert"]
_LOCK = threading.RLock()
_STATUSES = {"offen", "moduswahl", "gebucht", "abgelaufen", "zurückgezogen"}


def _player():
    import player
    return player


def _norm(value):
    return _player().normalize_name(str(value or ""))


def _cell(row, index):
    return str(row[index]).strip() if index < len(row) else ""


def _now():
    return datetime.now(TZ)


def _parse(value):
    try:
        naive = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")
        result = TZ.localize(naive, is_dst=None)
    except (ValueError, pytz.exceptions.AmbiguousTimeError, pytz.exceptions.NonExistentTimeError):
        raise ValueError("Datum bitte als TT.MM.JJJJ HH:MM eingeben (gültige Berliner Ortszeit).")
    if result <= _now():
        raise ValueError("Der Termin liegt nicht in der Zukunft.")
    return result


def _ws():
    wb = get_season_spreadsheet()
    try:
        ws = wb.worksheet(STORE_SHEET)
    except WorksheetNotFound:
        ws = wb.add_worksheet(title=STORE_SHEET, rows=1000, cols=len(HEADERS))
    if ws.col_count < len(HEADERS):
        ws.add_cols(len(HEADERS) - ws.col_count)
    first = ws.row_values(1)
    if not any(first):
        ws.update("A1:P1", [HEADERS])
    elif first[:len(HEADERS)] != HEADERS:
        raise RuntimeError(f"{STORE_SHEET}: Spaltenüberschriften weichen ab. Keine Änderung vorgenommen.")
    return ws


def _all():
    return _ws().get("A:P")


def _load(identifier):
    rows = _all()
    for i, row in enumerate(rows[1:], 2):
        if _cell(row, 0) == identifier:
            return i, row
    raise ValueError("Dieses Coop-Terminangebot existiert nicht mehr.")


def _update(rowno, data):
    ws = _ws()
    ws.update(f"A{rowno}:P{rowno}", [data], value_input_option="RAW")


def _save(rowno, row):
    values = [_cell(row, i) for i in range(16)]
    values[15] = _now().strftime("%d.%m.%Y %H:%M:%S")
    _update(rowno, values)


def _matches(group, team):
    p = _player()
    rows = p._coop_group_rows(group, True)
    return [m for m in p._coop_group_matches(group, rows)
            if _norm(team) in {_norm(m["home"]), _norm(m["away"])}]


def _identity(member):
    p = _player()
    data = p._coop_team_identity(member)
    if data.get("group") not in ("Coop_A", "Coop_B") or not data.get("team_name"):
        raise PermissionError("Keinem Coop-Team zugeordnet.")
    return data["group"], data["team_name"]


def _team_members(group, team):
    p = _player()
    return p._coop_ids_for_team(group, team)


def _interaction_guild(interaction):
    """Resolve the TFL guild also for modal/select interactions answered via DM.

    DM interactions have _interaction_guild(interaction) == None, even if they originate
    from a guild-based scheduling flow. Guild ID takes precedence.
    """
    if interaction.guild is not None:
        return interaction.guild
    client = interaction.client
    raw_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    if raw_id.isdigit():
        guild = client.get_guild(int(raw_id))
        if guild is not None:
            return guild
    channel = client.get_channel(CHANNEL_ID)
    guild = getattr(channel, "guild", None)
    if guild is not None:
        return guild
    if len(client.guilds) == 1:
        return client.guilds[0]
    return None


def _coop_multistream(group, home, away):
    """Build the four-channel multistre.am link from team roster and Runner mapping."""
    from urllib.parse import quote
    import coop

    mapping = coop.get_runner_mapping()
    channels = []
    missing = []
    for team in (home, away):
        _row, first, second, _ban = _player()._coop_team_members(group, team)
        for racer in (first, second):
            if not racer:
                missing.append(f"{team}: Racer nicht eingetragen")
                continue
            twitch = (mapping.get(_norm(racer)) or "").strip().lstrip("@").strip("/")
            if twitch.lower().startswith(("http://", "https://")):
                from urllib.parse import urlparse
                twitch = urlparse(twitch).path.strip("/").split("/")[0]
            if not twitch or not __import__("re").fullmatch(r"[A-Za-z0-9_]{4,25}", twitch):
                missing.append(f"{team}: {racer}")
            else:
                channels.append(quote(twitch, safe=""))
    if missing:
        return "", missing
    return "https://multistre.am/" + "/".join(channels) + "/layout12/", []


async def _notify(guild, group, teams, content):
    """Jeden Spieler höchstens einmal informieren; DM-Fehler sind nicht fatal."""
    if guild is None:
        return 0
    p = _player()
    seen = set()
    total = 0
    for team in teams:
        members = await p._coop_offer_members(guild, group, team)
        for member in members:
            if member.id in seen:
                continue
            seen.add(member.id)
            try:
                await member.send(content)
                total += 1
            except (discord.Forbidden, discord.HTTPException):
                pass
    return total


def _busy(group, team, instant, exclude_row=0):
    """Keine zweite Begegnung eines Teams zur selben Uhrzeit; gruppenübergreifend."""
    p = _player()
    for section in p.COOP_GROUP_SHEETS:
        rows = p._coop_group_rows(section, True)
        for match in p._coop_group_matches(section, rows):
            if section == group and match["row"] == exclude_row:
                continue
            if _norm(team) not in {_norm(match["home"]), _norm(match["away"])}:
                continue
            value = str(match.get("date_text") or "").strip()
            parsed = p.parse_sheet_datetime(value) if value else None
            if parsed is not None and parsed == instant:
                return True
    return False


def _match_candidates(group, origin, destination, instant):
    p = _player()
    rows = p._coop_group_rows(group, True)
    available = []
    for m in p._coop_group_matches(group, rows):
        if {_norm(m["home"]), _norm(m["away"])} != {_norm(origin), _norm(destination)}:
            continue
        if not p._is_open_result_value(m["result"]) or m["date_text"]:
            continue
        if _busy(group, m["home"], instant, m["row"]) or _busy(group, m["away"], instant, m["row"]):
            continue
        available.append(m)
    return available


def _create(group, team, actor, times):
    if len(times) < 1 or len(times) > 3 or len(times) != len(set(times)):
        raise ValueError("Bitte 1 bis 3 unterschiedliche Termine eingeben.")
    if not any(_player()._is_open_result_value(m["result"]) and not m["date_text"] for m in _matches(group, team)):
        raise ValueError("Dein Team hat keine freie Begegnung mehr.")
    with _LOCK:
        ws = _ws()
        allrows = ws.get("A:P")
        targets = []
        next_row = max(2, len(allrows) + 1)
        for when in times:
            if _busy(group, team, when):
                raise ValueError(f"Für {when.strftime('%d.%m.%Y %H:%M')} ist dein Team bereits verplant.")
            offer_id = uuid.uuid4().hex[:12]
            values = [offer_id, group, team, str(actor), when.strftime("%d.%m.%Y %H:%M"), "offen", "", "", "", "", "", "", "", "", "", _now().strftime("%d.%m.%Y %H:%M:%S")]
            targets.append((next_row, values))
            next_row += 1
        # Ein Google-Sheets-Schreibaufruf für alle angebotenen Termine.
        sheet_write_call(lambda: ws.batch_update([{"range": f"A{i}:P{i}", "values": [v]} for i, v in targets]))
        return [(i, v[0]) for i, v in targets]


def _take(offer_id, group, team, actor, match_row, expected_home, expected_away):
    with _LOCK:
        rowno, row = _load(offer_id)
        if _cell(row, 5) != "offen":
            raise ValueError("Termin ist bereits vergeben oder zurückgezogen.")
        if group != _cell(row, 1) or _norm(team) == _norm(_cell(row, 2)):
            raise PermissionError("Ein anderer Coop-Gegner muss das Angebot annehmen.")
        instant = _parse(_cell(row, 4))
        matches = _match_candidates(group, _cell(row, 2), team, instant)
        match = next((m for m in matches if m["row"] == match_row and _norm(m["home"]) == _norm(expected_home) and _norm(m["away"]) == _norm(expected_away)), None)
        if match is None:
            raise ValueError("Zwischen diesen Teams ist diese Begegnung nicht mehr frei.")
        # Zwei öffentliche Angebote dürfen nicht parallel dieselbe Begegnung
        # für die Moduswahl blockieren.
        for another in _all()[1:]:
            if (_cell(another, 0) != offer_id and _cell(another, 1) == group
                    and _cell(another, 5) == "moduswahl"
                    and _cell(another, 10) == str(match_row)):
                deadline = _cell(another, 13)
                if deadline:
                    try:
                        expires = TZ.localize(datetime.strptime(deadline, "%d.%m.%Y %H:%M"))
                        if expires > _now():
                            raise ValueError("Diese Begegnung wartet bereits auf eine andere Modusbestätigung.")
                    except ValueError as error:
                        if "wartet bereits" in str(error):
                            raise
        row = list(row) + [""] * (16 - len(row))
        row[5] = "moduswahl"
        row[8], row[9], row[10] = match["home"], match["away"], str(match["row"])
        row[12] = team
        row[13] = (_now() + timedelta(hours=24)).strftime("%d.%m.%Y %H:%M")
        _save(rowno, row)
        return match, instant


def _allowed_modes(group, home, away):
    _, _, _, h_ban = _player()._coop_team_members(group, home)
    _, _, _, a_ban = _player()._coop_team_members(group, away)
    banned = {_norm(h_ban), _norm(a_ban)} - {""}
    return [m for m in MODES if _norm(m) not in banned]


def _book(offer_id, group, team, mode):
    with _LOCK:
        rowno, row = _load(offer_id)
        if _cell(row, 5) != "moduswahl":
            raise ValueError("Keine offene Modusbestätigung vorhanden.")
        if group != _cell(row, 1) or _norm(team) != _norm(_cell(row, 8)):
            raise PermissionError("Den Modus darf nur das Heimteam festlegen.")
        expires = TZ.localize(datetime.strptime(_cell(row, 13), "%d.%m.%Y %H:%M"))
        if _now() > expires:
            values = list(row) + [""] * (16 - len(row))
            values[5] = "abgelaufen"
            _save(rowno, values)
            raise ValueError("Die 24 Stunden für die Moduswahl sind abgelaufen.")
        if mode not in _allowed_modes(group, _cell(row, 8), _cell(row, 9)):
            raise ValueError("Der Modus ist für eines der Teams gestrichen.")
        p = _player()
        instant = _parse(_cell(row, 4))
        matchrow = int(_cell(row, 10))
        choices = _match_candidates(group, _cell(row, 8), _cell(row, 9), instant)
        if not any(m["row"] == matchrow for m in choices):
            raise ValueError("Begegnung ist inzwischen nicht mehr frei.")
        ws = p._get_coop_group_ws(group)
        sheet_write_call(lambda: ws.batch_update([
            {"range": f"B{matchrow}:C{matchrow}", "values": [[_cell(row, 4), mode]]},
            {"range": f"H{matchrow}", "values": [[f"Coop-Terminbörse {_cell(row, 0)}"]]},
        ]), invalidate_prefixes=p._coop_league_invalidation(ws))
        values = list(row) + [""] * (16 - len(row))
        values[5], values[11] = "gebucht", mode
        _save(rowno, values)
        return values


def _cancel(offer_id, group, team):
    with _LOCK:
        rowno, row = _load(offer_id)
        if group != _cell(row, 1) or _norm(team) != _norm(_cell(row, 2)):
            raise PermissionError("Nur das anbietende Team darf zurückziehen.")
        if _cell(row, 5) != "offen":
            raise ValueError("Das Angebot ist bereits in Bearbeitung oder beendet.")
        values = list(row) + [""] * (16 - len(row))
        values[5] = "zurückgezogen"
        _save(rowno, values)
        return values


def _cancel_pending(offer_id, group, team):
    with _LOCK:
        rowno, row = _load(offer_id)
        if _cell(row, 5) != "moduswahl":
            return
        if group != _cell(row, 1) or _norm(team) not in {_norm(_cell(row, 2)), _norm(_cell(row, 12))}:
            raise PermissionError("Nicht am Angebot beteiligt.")
        values = list(row) + [""] * (16 - len(row))
        values[5] = "offen"
        for index in (8, 9, 10, 11, 12, 13):
            values[index] = ""
        _save(rowno, values)


def _offer_content(rows):
    group, team = _cell(rows[0], 1), _cell(rows[0], 2)
    labels = [f"**{_cell(row,4)} Uhr**" for row in rows]
    return (f"**Coop-Terminbörse · {group}**\n**{team} bietet Race-Termine an**\n"
            + "\n".join(f"• {t}" for t in labels)
            + "\nAndere Teams dieser Gruppe können einen der Termine auswählen. "
              "Vor der Buchung werden freie Begegnungen, Teamtermine und Streichmodi geprüft.")


# =========================================================
# DIREKTE COOP-SPIELPLANUNG (ohne öffentliche Terminbörse)
# =========================================================

def _direct_matches(group, team):
    p = _player()
    return [m for m in _matches(group, team)
            if p._is_open_result_value(m["result"]) and not m["date_text"]]


def _direct_propose(group, team, member_id, match, when):
    p = _player()
    if _norm(team) not in {_norm(match["home"]), _norm(match["away"])}:
        raise PermissionError("Dein Team ist nicht beteiligt.")
    if _busy(group, match["home"], when) or _busy(group, match["away"], when):
        raise ValueError("Ein Team hat zu diesem Zeitpunkt bereits ein Spiel.")
    with _LOCK:
        live = _match_candidates(group, match["home"], match["away"], when)
        if not any(x["row"] == match["row"] for x in live):
            raise ValueError("Diese Begegnung ist nicht mehr frei.")
        for row in _all()[1:]:
            if (_cell(row, 1) == group and _cell(row, 10) == str(match["row"])
                    and _cell(row, 5) in {"direkt", "moduswahl"}):
                raise ValueError("Für diese Begegnung existiert bereits eine offene Terminanfrage.")
        identifier = uuid.uuid4().hex[:12]
        values = [identifier, group, team, str(member_id), when.strftime("%d.%m.%Y %H:%M"),
                  "direkt", "", "", match["home"], match["away"], str(match["row"]),
                  "", "", "", "", _now().strftime("%d.%m.%Y %H:%M:%S")]
        ws = _ws()
        existing = ws.get("A:P")
        rowno = max(2, len(existing) + 1)
        _update(rowno, values)
        return identifier


def _direct_decide(identifier, group, team, accept):
    with _LOCK:
        rowno, original = _load(identifier)
        if _cell(original, 5) != "direkt":
            raise ValueError("Diese Terminanfrage ist nicht mehr offen.")
        proposer = _cell(original, 2)
        if group != _cell(original, 1) or _norm(team) == _norm(proposer):
            raise PermissionError("Nur das gegnerische Team darf diese Anfrage beantworten.")
        if _norm(team) not in {_norm(_cell(original, 8)), _norm(_cell(original, 9))}:
            raise PermissionError("Dein Team ist an dieser Begegnung nicht beteiligt.")
        if not accept:
            values = list(original) + [""] * (16 - len(original))
            values[5] = "zurückgezogen"
            _save(rowno, values)
            return None
        when = _parse(_cell(original, 4))
        matches = _match_candidates(group, proposer, team, when)
        match = next((x for x in matches if x["row"] == int(_cell(original, 10))), None)
        if match is None:
            raise ValueError("Die Begegnung ist nicht mehr frei oder der Termin kollidiert.")
        values = list(original) + [""] * (16 - len(original))
        values[5] = "offen"
        _save(rowno, values)
        try:
            # Dieselbe atomare Reservierung wie bei der öffentlichen Coop-Terminbörse.
            _take(identifier, group, team, 0, match["row"], match["home"], match["away"])
        except Exception:
            _save(rowno, original)
            raise
        return match


class DirectDecisionView(discord.ui.View):
    def __init__(self, identifier):
        super().__init__(timeout=None)
        self.identifier = identifier
        yes = discord.ui.Button(label="Termin annehmen", style=discord.ButtonStyle.success,
                                custom_id=f"tfl:coop:direct:yes:{identifier}")
        no = discord.ui.Button(label="Termin ablehnen", style=discord.ButtonStyle.danger,
                               custom_id=f"tfl:coop:direct:no:{identifier}")
        yes.callback = self.accept
        no.callback = self.reject
        self.add_item(yes)
        self.add_item(no)

    async def accept(self, interaction):
        await self._decide(interaction, True)

    async def reject(self, interaction):
        await self._decide(interaction, False)

    async def _decide(self, interaction, yes):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            group, team = await asyncio.to_thread(_identity, interaction.user)
            result = await asyncio.to_thread(_direct_decide, self.identifier, group, team, yes)
            _, row = await asyncio.to_thread(_load, self.identifier)
            proposer = _cell(row, 2)
            home, away = _cell(row, 8), _cell(row, 9)
            if not yes:
                await _notify(_interaction_guild(interaction), group, (proposer, team),
                              f"Coop-Terminanfrage **{home} vs. {away}** am {_cell(row, 4)} Uhr wurde abgelehnt.")
                await interaction.followup.send("Terminanfrage abgelehnt.", ephemeral=True)
                return
            modes = await asyncio.to_thread(_allowed_modes, group, home, away)
            if not modes:
                await asyncio.to_thread(_cancel_pending, self.identifier, group, team)
                raise ValueError("Kein zulässiger Coop-Modus vorhanden.")
            await _notify(_interaction_guild(interaction), group, (home, away),
                          f"Coop-Termin **{home} vs. {away}** am {_cell(row, 4)} Uhr ist angefragt und angenommen. "
                          "Das Heimteam muss innerhalb von 24 Stunden den Modus wählen. "
                          "Bitte `/player` → Coop-Menü → Offene Moduswahl öffnen.")
            home_members = await _player()._coop_offer_members(_interaction_guild(interaction), group, home) if _interaction_guild(interaction) else []
            for member in home_members:
                try:
                    await member.send(f"**Coop-Moduswahl:** {home} vs. {away} · {_cell(row, 4)} Uhr",
                                      view=ModeView(member.id, group, home, self.identifier, modes))
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await interaction.followup.send("Terminanfrage angenommen. Das Heimteam wurde zur Moduswahl aufgefordert.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Terminanfrage konnte nicht bearbeitet werden: {exc}", ephemeral=True)


class DirectDateModal(discord.ui.Modal, title="Coop-Spiel direkt eintragen"):
    when = discord.ui.TextInput(label="Termin (TT.MM.JJJJ HH:MM)", placeholder="25.10.2026 20:00",
                                required=True, max_length=30)

    def __init__(self, group, team, match):
        super().__init__()
        self.group, self.team, self.match = group, team, match

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            instant = _parse(str(self.when.value))
            identifier = await asyncio.to_thread(_direct_propose, self.group, self.team,
                                                 interaction.user.id, self.match, instant)
            opponent = (self.match["away"] if _norm(self.match["home"]) == _norm(self.team)
                        else self.match["home"])
            message = (f"**Direkte Coop-Terminanfrage**\n"
                       f"**{self.match['home']} vs. {self.match['away']}** · {self.group}\n"
                       f"**{instant.strftime('%d.%m.%Y %H:%M')} Uhr**\n"
                       "Ein Runner des gegnerischen Teams kann den Termin bestätigen oder ablehnen. "
                       "Danach wählt das Heimteam den Modus.")
            count = 0
            members = await _player()._coop_offer_members(_interaction_guild(interaction), self.group, opponent) if _interaction_guild(interaction) else []
            for member in members:
                try:
                    await member.send(message, view=DirectDecisionView(identifier))
                    count += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass
            if not count:
                # Ein Angebot ohne erreichbaren Gegner darf nicht als erfolgreich gelten.
                with _LOCK:
                    rowno, row = _load(identifier)
                    vals = list(row) + [""] * (16 - len(row))
                    vals[5] = "zurückgezogen"
                    _save(rowno, vals)
                raise ValueError("Kein Gegner konnte per DM erreicht werden. Anfrage verworfen.")
            await _notify(_interaction_guild(interaction), self.group, (self.team,),
                          f"Du hast **{self.match['home']} vs. {self.match['away']}** für "
                          f"{instant.strftime('%d.%m.%Y %H:%M')} Uhr vorgeschlagen. "
                          f"{count} gegnerische Runner haben eine DM erhalten.")
            await interaction.followup.send(f"Terminanfrage versendet. **{count}** Gegner-DM(s). "
                                            "Es wird noch nichts ins Spielplan-Sheet eingetragen.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Direkte Coop-Spielplanung fehlgeschlagen: {exc}", ephemeral=True)


class DirectMatchSelect(discord.ui.Select):
    def __init__(self, group, team, matches):
        self.group, self.team = group, team
        self.matches = {str(m["row"]): m for m in matches[:25]}
        super().__init__(placeholder="Offene Begegnung wählen", options=[
            discord.SelectOption(label=f"{m['home']} vs. {m['away']}"[:100], value=str(m["row"]))
            for m in matches[:25]])

    async def callback(self, interaction):
        try:
            group, team = await asyncio.to_thread(_identity, interaction.user)
            if group != self.group or _norm(team) != _norm(self.team):
                raise PermissionError("Nicht dein Team.")
            match = self.matches[self.values[0]]
            await interaction.response.send_modal(DirectDateModal(group, team, match))
        except Exception as exc:
            if not interaction.response.is_done():
                await interaction.response.send_message(str(exc), ephemeral=True)


async def direct_plan(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        group, team = await asyncio.to_thread(_identity, interaction.user)
        matches = await asyncio.to_thread(_direct_matches, group, team)
        if not matches:
            await interaction.followup.send("Keine freie Coop-Begegnung ohne Termin vorhanden.", ephemeral=True)
            return
        view = discord.ui.View(timeout=300)
        view.add_item(DirectMatchSelect(group, team, matches))
        await interaction.followup.send("Wähle die Begegnung, die du direkt terminieren möchtest:", view=view, ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Direkte Spielplanung nicht verfügbar: {exc}", ephemeral=True)


class OfferSlotButton(discord.ui.Button):
    def __init__(self, row):
        self.offer_id = _cell(row, 0)
        self.when = _cell(row, 4)
        state = _cell(row, 5)
        super().__init__(label=self.when[:75], style=discord.ButtonStyle.primary if state == "offen" else discord.ButtonStyle.secondary,
                         custom_id=f"tfl:coop:v3:slot:{self.offer_id}", disabled=state != "offen")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            group, team = await asyncio.to_thread(_identity, interaction.user)
            rowno, offer = await asyncio.to_thread(_load, self.offer_id)
            if _cell(offer, 5) != "offen":
                raise ValueError("Dieser Termin ist nicht mehr verfügbar.")
            if group != _cell(offer, 1) or _norm(team) == _norm(_cell(offer, 2)):
                raise PermissionError("Annahme nur durch ein anderes Team derselben Gruppe.")
            instant = _parse(_cell(offer, 4))
            matches = await asyncio.to_thread(_match_candidates, group, _cell(offer, 2), team, instant)
            if not matches:
                raise ValueError("Zwischen euren Teams gibt es keine freie Begegnung oder einen Terminkonflikt.")
            await interaction.followup.send("Welche freie Begegnung soll terminiert werden?", view=MatchSelectView(interaction.user.id, self.offer_id, matches), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Termin kann nicht gewählt werden: {exc}", ephemeral=True)


class PublicOfferView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=None)
        for row in rows:
            self.add_item(OfferSlotButton(row))


class MatchSelect(discord.ui.Select):
    def __init__(self, owner, offer_id, matches):
        self.owner, self.offer_id = owner, offer_id
        self.matches = {str(m["row"]): m for m in matches}
        options = [discord.SelectOption(label=f"{m['home']} vs. {m['away']}"[:100], value=str(m["row"])) for m in matches[:25]]
        super().__init__(placeholder="Heim-/Gast-Begegnung wählen", options=options)

    async def callback(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("Nicht deine Auswahl.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            group, team = await asyncio.to_thread(_identity, interaction.user)
            m = self.matches[self.values[0]]
            match, instant = await asyncio.to_thread(_take, self.offer_id, group, team, interaction.user.id, m["row"], m["home"], m["away"])
            _rowno, data = await asyncio.to_thread(_load, self.offer_id)
            await _refresh_post(interaction.client, data)
            modes = await asyncio.to_thread(_allowed_modes, group, match["home"], match["away"])
            home_members = await _player()._coop_offer_members(_interaction_guild(interaction), group, match["home"]) if _interaction_guild(interaction) else []
            home_dms = 0
            for member in home_members:
                try:
                    await member.send(
                        f"**Coop-Terminbörse: {match['home']} vs. {match['away']}**\n"
                        f"{instant.strftime('%d.%m.%Y %H:%M')} Uhr vorgemerkt.\n"
                        "**Dein Heimteam muss den Modus innerhalb von 24 Stunden bestätigen.**\n"
                        "Falls die Auswahl hier nicht mehr funktioniert: `/player` → Coop-Menü → Offene Moduswahl.",
                        view=ModeView(member.id, group, match["home"], self.offer_id, modes) if modes else None,
                    )
                    home_dms += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass
            away_team = match["away"]
            away_dms = await _notify(_interaction_guild(interaction), group, (away_team,),
                                    f"**Coop-Terminbörse: {match['home']} vs. {match['away']}**\n"
                                    f"{instant.strftime('%d.%m.%Y %H:%M')} Uhr vorgemerkt. "
                                    f"Das Heimteam {match['home']} muss den Modus noch bestätigen.")
            await interaction.followup.send(
                f"Termin vorgemerkt: **{match['home']} vs. {match['away']}**. "
                f"Benachrichtigungen: {home_dms} Heimteam-DMs mit Moduswahl, {away_dms} Gastteam-DMs.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Begegnung nicht reserviert: {exc}", ephemeral=True)


class MatchSelectView(discord.ui.View):
    def __init__(self, owner, offer_id, matches):
        super().__init__(timeout=300)
        self.add_item(MatchSelect(owner, offer_id, matches))


class OfferModal(discord.ui.Modal, title="Coop: Race-Termine anbieten"):
    first = discord.ui.TextInput(label="Termin 1", placeholder="TT.MM.JJJJ HH:MM", max_length=30)
    second = discord.ui.TextInput(label="Termin 2 (optional)", required=False, max_length=30)
    third = discord.ui.TextInput(label="Termin 3 (optional)", required=False, max_length=30)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            group, team = await asyncio.to_thread(_identity, interaction.user)
            dates = [str(v).strip() for v in (self.first.value, self.second.value, self.third.value) if str(v).strip()]
            instants = [_parse(v) for v in dates]
            created = await asyncio.to_thread(_create, group, team, interaction.user.id, instants)
            try:
                target_channel_id = channel_for_group(group)
                guild = _interaction_guild(interaction)
                channel = guild.get_channel(target_channel_id) if guild else None
                if channel is None:
                    channel = await interaction.client.fetch_channel(target_channel_id)
                if not hasattr(channel, "send"):
                    raise RuntimeError("Terminbörsen-Kanal ist kein Textkanal.")
                rows = [(await asyncio.to_thread(_load, identifier))[1] for _, identifier in created]
                msg = await channel.send(_offer_content(rows), view=PublicOfferView(rows))
                await asyncio.to_thread(_attach_message, created, msg.channel.id, msg.id)
                await interaction.followup.send(f"**{len(created)} Termine** in <#{target_channel_id}> veröffentlicht: {msg.jump_url}", ephemeral=True)
            except Exception as exc:
                await asyncio.to_thread(_mark_failed, created)
                raise RuntimeError(f"Terminbörse konnte nicht in <#{target_channel_id}> veröffentlicht werden: {exc}")
        except Exception as exc:
            await interaction.followup.send(f"Coop-Terminangebot fehlgeschlagen: {exc}", ephemeral=True)


def _attach_message(created, channel_id, message_id):
    with _LOCK:
        for _, identifier in created:
            rowno, row = _load(identifier)
            values = list(row) + [""] * (16 - len(row))
            values[6], values[7] = str(channel_id), str(message_id)
            _save(rowno, values)


def _mark_failed(created):
    with _LOCK:
        for _, identifier in created:
            rowno, row = _load(identifier)
            values = list(row) + [""] * (16 - len(row))
            values[5] = "zurückgezogen"
            _save(rowno, values)


async def _refresh_post(client, row):
    if not _cell(row, 6).isdigit() or not _cell(row, 7).isdigit():
        return
    try:
        channel = client.get_channel(int(_cell(row, 6))) or await client.fetch_channel(int(_cell(row, 6)))
        message = await channel.fetch_message(int(_cell(row, 7)))
        rows = await asyncio.to_thread(_all)
        siblings = [r for r in rows[1:] if _cell(r, 6) == _cell(row, 6) and _cell(r, 7) == _cell(row, 7)]
        await message.edit(content=_offer_content(siblings), view=PublicOfferView(siblings))
    except (discord.HTTPException, AttributeError) as exc:
        LOG.warning("Coop-Beitrag konnte nicht aktualisiert werden: %s", exc)


class ModeSelect(discord.ui.Select):
    def __init__(self, owner, group, team, offer_id, modes):
        self.owner, self.group, self.team, self.offer_id = owner, group, team, offer_id
        super().__init__(placeholder="Modus des Heimteams wählen", options=[discord.SelectOption(label=m, value=m) for m in modes])

    async def callback(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("Nicht deine Modusauswahl.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            group, team = await asyncio.to_thread(_identity, interaction.user)
            row = await asyncio.to_thread(_book, self.offer_id, group, team, self.values[0])
            await _refresh_post(interaction.client, row)
            event_url = ""
            multistream_url = ""
            event_error = ""
            try:
                multistream_url, missing = await asyncio.to_thread(
                    _coop_multistream, group, _cell(row, 8), _cell(row, 9)
                )
                if missing:
                    LOG.warning("Coop-Multistream unvollständig: %s", ", ".join(missing))
            except Exception as exc:
                LOG.exception("Coop-Multistream konnte nicht erzeugt werden: %s", exc)
                missing = ["Runner-Zuordnung konnte nicht gelesen werden"]
            try:
                import matchcenter
                when = TZ.localize(datetime.strptime(_cell(row, 4), "%d.%m.%Y %H:%M"))
                guild = _interaction_guild(interaction)
                if guild is None:
                    raise RuntimeError("TFL-Server nicht gefunden: DISCORD_GUILD_ID und Bot-Serverzuordnung prüfen.")
                # External events require a location; show the stream URL when available.
                location = multistream_url or "TFL Discord / Racetime"
                description = f"{group} · Modus: {_cell(row, 11)}"
                if multistream_url:
                    description += f"\nMultistream: {multistream_url}"
                event = await matchcenter.create_scheduled_event(
                    guild, f"Coop {_cell(row, 8)} vs. {_cell(row, 9)}",
                    location, when, when + timedelta(minutes=180), description
                )
                event_url = str(event.url)
                ws = _player()._get_coop_group_ws(group)
                sheet_write_call(
                    lambda: ws.update_acell(f"G{int(_cell(row, 10))}", event_url),
                    invalidate_prefixes=_player()._coop_league_invalidation(ws)
                )
            except Exception as exc:
                event_error = str(exc)
                LOG.exception("Coop-Event nicht erstellt: %s", exc)
            notice = (f"**Coop-Spiel terminiert!** {_cell(row, 8)} vs. {_cell(row, 9)}\n"
                      f"{_cell(row, 4)} Uhr · **{self.values[0]}**")
            if multistream_url:
                notice += f"\nMultistream: {multistream_url}"
            elif missing:
                notice += "\nMultistream fehlt: " + ", ".join(missing)
            notice += f"\nDiscord-Event: {event_url}" if event_url else "\nDiscord-Event konnte nicht angelegt werden."
            await _notify(_interaction_guild(interaction), group, (_cell(row, 8), _cell(row, 9)), notice)
            result = (f"**Termin bestätigt:** {_cell(row, 8)} vs. {_cell(row, 9)} · "
                      f"{_cell(row, 4)} · {self.values[0]}")
            if multistream_url:
                result += f"\nMultistream: {multistream_url}"
            elif missing:
                result += "\nFehlende Twitch-Zuordnung: " + ", ".join(missing)
            if event_url:
                result += f"\nDiscord-Event: {event_url}"
            else:
                result += f"\n⚠️ Discord-Event fehlgeschlagen: {event_error}"
            await interaction.followup.send(result[:1900], ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Modusbestätigung fehlgeschlagen: {exc}", ephemeral=True)


class ModeView(discord.ui.View):
    def __init__(self, owner, group, team, offer_id, modes):
        super().__init__(timeout=86400)
        self.add_item(ModeSelect(owner, group, team, offer_id, modes))


class ManageSelect(discord.ui.Select):
    def __init__(self, owner, entries):
        self.owner = owner
        self.entries = {str(i): (rowno, row) for i, (rowno, row) in enumerate(entries[:25])}
        options = [discord.SelectOption(label=f"{_cell(row, 4)} · {_cell(row, 5)}"[:100], value=key)
                   for key, (rowno, row) in self.entries.items()]
        super().__init__(placeholder="Eigenes Terminangebot wählen", options=options)

    async def callback(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("Nicht dein Menü.", ephemeral=True)
            return
        group, team = await asyncio.to_thread(_identity, interaction.user)
        _, row = self.entries[self.values[0]]
        try:
            changed = await asyncio.to_thread(_cancel, _cell(row, 0), group, team)
            await _refresh_post(interaction.client, changed)
            await interaction.response.send_message("Terminangebot zurückgezogen.", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


async def offer(interaction):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Nur auf dem TFL-Discord möglich.", ephemeral=True)
        return
    await interaction.response.send_modal(OfferModal())


async def manage(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        group, team = await asyncio.to_thread(_identity, interaction.user)
        values = await asyncio.to_thread(_all)
        own = [(i, row) for i, row in enumerate(values[1:], 2)
               if _cell(row, 1) == group and _norm(_cell(row, 2)) == _norm(team) and _cell(row, 5) == "offen"]
        if not own:
            await interaction.followup.send("Keine eigenen offenen Coop-Terminangebote.", ephemeral=True)
        else:
            view = discord.ui.View(timeout=300)
            view.add_item(ManageSelect(interaction.user.id, own))
            await interaction.followup.send("Eigenen Termin zurückziehen:", view=view, ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Angebotsverwaltung nicht verfügbar: {exc}", ephemeral=True)


async def incoming(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        group, team = await asyncio.to_thread(_identity, interaction.user)
        values = await asyncio.to_thread(_all)
        pending = [r for r in values[1:] if _cell(r, 1) == group and _cell(r, 5) == "moduswahl" and _norm(_cell(r, 8)) == _norm(team)
                   and _cell(r, 13) and TZ.localize(datetime.strptime(_cell(r, 13), "%d.%m.%Y %H:%M")) > _now()]
        if not pending:
            await interaction.followup.send("Keine ausstehende Modusauswahl für dein Heimteam.", ephemeral=True)
            return
        view = discord.ui.View(timeout=300)
        opts = [discord.SelectOption(label=f"{_cell(r, 9)} · {_cell(r, 4)}"[:100], value=_cell(r, 0)) for r in pending[:25]]
        picker = PendingSelect(interaction.user.id, opts)
        view.add_item(picker)
        await interaction.followup.send("Wähle die Heimspiel-Modusbestätigung:", view=view, ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Modusauswahl nicht verfügbar: {exc}", ephemeral=True)


class PendingSelect(discord.ui.Select):
    def __init__(self, owner, options):
        self.owner = owner
        super().__init__(placeholder="Offene Heimspiel-Moduswahl", options=options)

    async def callback(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("Nicht deine Auswahl.", ephemeral=True)
            return
        group, team = await asyncio.to_thread(_identity, interaction.user)
        try:
            _, row = await asyncio.to_thread(_load, self.values[0])
            if _norm(team) != _norm(_cell(row, 8)) or group != _cell(row, 1):
                raise PermissionError("Nur das Heimteam kann den Modus wählen.")
            modes = await asyncio.to_thread(_allowed_modes, group, _cell(row, 8), _cell(row, 9))
            if not modes:
                raise ValueError("Kein zulässiger Modus vorhanden.")
            await interaction.response.send_message(
                f"**{_cell(row, 8)} vs. {_cell(row, 9)}** · {_cell(row, 4)} Uhr\nBitte Modus auswählen:",
                view=ModeView(interaction.user.id, group, team, _cell(row, 0), modes), ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


def _expire_old_pending():
    with _LOCK:
        rows = _all()
        for index, row in enumerate(rows[1:], 2):
            if _cell(row, 5) != "moduswahl" or not _cell(row, 13):
                continue
            try:
                end = TZ.localize(datetime.strptime(_cell(row, 13), "%d.%m.%Y %H:%M"))
            except ValueError:
                continue
            if end < _now():
                values = list(row) + [""] * (16 - len(row))
                values[5] = "abgelaufen"
                _save(index, values)


async def restore(bot):
    """Öffentliche Buttons nach Neustart wiederherstellen."""
    try:
        await asyncio.to_thread(_expire_old_pending)
        rows = await asyncio.to_thread(_all)
        for row in rows[1:]:
            if _cell(row, 5) == "direkt" and _cell(row, 0):
                bot.add_view(DirectDecisionView(_cell(row, 0)))
        grouped = {}
        for row in rows[1:]:
            if _cell(row, 7).isdigit():
                grouped.setdefault(int(_cell(row, 7)), []).append(row)
        total = 0
        for message_id, family in grouped.items():
            if any(_cell(row, 5) == "offen" for row in family):
                bot.add_view(PublicOfferView(family), message_id=message_id)
                total += 1
        LOG.info("%s Coop-Terminbörsen-Beiträge wiederhergestellt", total)
    except Exception as exc:
        LOG.exception("Coop-Terminbörse konnte nicht wiederhergestellt werden: %s", exc)

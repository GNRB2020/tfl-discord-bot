import os
import asyncio
import re
from datetime import datetime as dt

import discord
import gspread
from discord import app_commands
from discord.ext import commands
from oauth2client.service_account import ServiceAccountCredentials

from matchcenter import (
    write_league_result,
    league_result_post_text,
    send_result_post,
    now_berlin_str,
)

# =========================================================
# KONFIG
# =========================================================

GUILD_ID = 1275076189173579846
LOG_CHANNEL_ID = 1494265084208222208
ADMIN_ROLE_NAME = "Admin"

QUALI_SHEET_NAME = "Quali"
START_ROW = 4
RUN_STALE_SECONDS = 15 * 60

# Quali:
# B = Runner
# D = Quali1 Async?/VoD/DNF
# E = Quali1 Zeit
# F = Quali2 Async?/VoD/DNF
# G = Quali2 Zeit
# D2 = Seed Quali 1
# F2 = Seed Quali 2

# Async:
# B = Player1
# D = VoD1
# E = Time1
# F = Player2
# G = VoD2
# H = Time2
# I = Seed
# J = Art
# K = Source Row Index
# L = Division
# M = Mode

TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")

CREDS_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json").strip()
SPREADSHEET_ID = "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8"
ASYNC_SPREADSHEET_ID = "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8"
ASYNC_WORKSHEET_GID = 539808866

# Teilnahmeberechtigung Quali
SIGNUP_SPREADSHEET_ID = "1pZxg1_DUtbO4dZvX95ZrIqEZnkMc1MjmE7z5SEsMHQU"
SIGNUP_WORKSHEET_GID = 463142264
NOT_ELIGIBLE_TEXT = (
    "Du bist für die Qualifikation nicht teilnahmeberechtigt! "
    "Nimm gerne an den Liveraces zur Quali (ohne Wertung) teil."
)

# =========================================================
# HILFSFUNKTIONEN
# =========================================================


def normalize_name(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def get_runner_name(interaction: discord.Interaction) -> str:
    if isinstance(interaction.user, discord.Member):
        return interaction.user.display_name.strip()
    return interaction.user.name.strip()


def format_seconds_to_hms(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def parse_hms_to_seconds(value: str) -> int:
    h, m, s = map(int, value.split(":"))
    return h * 3600 + m * 60 + s


def normalize_hms(value: str) -> str:
    value = value.strip()
    if not TIME_RE.match(value):
        raise ValueError("Zeitformat muss HH:MM:SS sein.")
    total = parse_hms_to_seconds(value)
    return format_seconds_to_hms(total)


def is_filled(value) -> bool:
    return str(value).strip() != ""


def safe_cell(values, idx: int) -> str:
    if idx < len(values):
        return str(values[idx]).strip()
    return ""


def safe_time_to_seconds(value: str):
    value = str(value).strip()
    if not value or not TIME_RE.match(value):
        return None
    try:
        return parse_hms_to_seconds(value)
    except Exception:
        return None


def find_member_by_runner_name(
    guild: discord.Guild | None,
    runner_name: str,
) -> discord.Member | None:
    if guild is None:
        return None

    target = normalize_name(runner_name)
    for member in guild.members:
        for candidate in [member.display_name, getattr(member, "global_name", None), member.name]:
            if normalize_name(candidate or "") == target:
                return member
    return None


async def try_send_dm(member: discord.Member | discord.User | None, text: str):
    if member is None:
        return
    try:
        await member.send(text)
    except Exception:
        pass


# =========================================================
# GOOGLE SHEETS
# =========================================================


def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    return gspread.authorize(creds)


def get_quali_worksheet():
    client = get_gspread_client()
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.worksheet(QUALI_SHEET_NAME)


def get_async_worksheet():
    client = get_gspread_client()
    spreadsheet = client.open_by_key(ASYNC_SPREADSHEET_ID)
    for ws in spreadsheet.worksheets():
        if ws.id == ASYNC_WORKSHEET_GID:
            return ws
    raise RuntimeError(f"Worksheet mit gid/id {ASYNC_WORKSHEET_GID} nicht gefunden.")


def get_signup_worksheet():
    client = get_gspread_client()
    sheet = client.open_by_key(SIGNUP_SPREADSHEET_ID)
    for ws in sheet.worksheets():
        if ws.id == SIGNUP_WORKSHEET_GID:
            return ws
    raise RuntimeError(f"Worksheet mit gid/id {SIGNUP_WORKSHEET_GID} nicht gefunden.")


def is_runner_quali_eligible(runner_name: str) -> bool:
    ws = get_signup_worksheet()
    rows = ws.get_all_values()
    target = normalize_name(runner_name)

    for row in rows:
        name_in_a = safe_cell(row, 0)   # A
        allowed_in_i = safe_cell(row, 8)  # I
        if not name_in_a:
            continue
        if normalize_name(name_in_a) == target:
            return allowed_in_i.lower() == "ja"
    return False


def get_quali_seed(ws, quali_number: int) -> str:
    if quali_number == 1:
        seed = ws.acell("D2").value
    elif quali_number == 2:
        seed = ws.acell("F2").value
    else:
        raise ValueError("Ungültige Quali-Nummer.")

    seed = (seed or "").strip()
    if not seed:
        raise ValueError(f"Kein Seed für Quali {quali_number} im Sheet hinterlegt.")
    return seed


def find_existing_runner_row(ws, runner_name: str):
    all_values = ws.get_all_values()
    for row_idx in range(START_ROW, len(all_values) + 1):
        row = all_values[row_idx - 1]
        name_in_b = safe_cell(row, 1)  # B
        if name_in_b.lower() == runner_name.lower():
            return row_idx
    return None


def find_first_free_row(ws):
    all_values = ws.get_all_values()
    row_idx = START_ROW
    while True:
        if row_idx > len(all_values):
            return row_idx
        row = all_values[row_idx - 1]
        name_in_b = safe_cell(row, 1)  # B
        if not name_in_b:
            return row_idx
        row_idx += 1


def get_or_create_runner_row(ws, runner_name: str):
    existing = find_existing_runner_row(ws, runner_name)
    if existing is not None:
        return existing
    free_row = find_first_free_row(ws)
    ws.update(f"B{free_row}", [[runner_name]])
    return free_row


def read_runner_status(ws, runner_name: str) -> dict:
    row_idx = find_existing_runner_row(ws, runner_name)
    if row_idx is None:
        return {
            "row": None,
            "q1_done": False,
            "q2_done": False,
            "q1_async": "",
            "q1_time": "",
            "q2_async": "",
            "q2_time": "",
        }

    row = ws.row_values(row_idx)
    q1_async = safe_cell(row, 3)  # D
    q1_time = safe_cell(row, 4)   # E
    q2_async = safe_cell(row, 5)  # F
    q2_time = safe_cell(row, 6)   # G

    return {
        "row": row_idx,
        "q1_done": is_filled(q1_async),
        "q2_done": is_filled(q2_async),
        "q1_async": q1_async,
        "q1_time": q1_time,
        "q2_async": q2_async,
        "q2_time": q2_time,
    }


def write_quali_result(ws, runner_name: str, quali_number: int, async_value: str, race_time: str):
    row_idx = get_or_create_runner_row(ws, runner_name)

    if quali_number == 1:
        ws.update(f"D{row_idx}:E{row_idx}", [[async_value, race_time]])
    elif quali_number == 2:
        ws.update(f"F{row_idx}:G{row_idx}", [[async_value, race_time]])
    else:
        raise ValueError("Ungültige Quali-Nummer.")

    return row_idx


def get_quali_results(ws, quali_number: int):
    all_values = ws.get_all_values()
    results = []

    for row_idx in range(START_ROW, len(all_values) + 1):
        row = all_values[row_idx - 1]
        runner_name = safe_cell(row, 1)  # B
        if not runner_name:
            continue

        if quali_number == 1:
            async_value = safe_cell(row, 3)  # D
            time_value = safe_cell(row, 4)   # E
        elif quali_number == 2:
            async_value = safe_cell(row, 5)  # F
            time_value = safe_cell(row, 6)   # G
        else:
            raise ValueError("Ungültige Quali-Nummer.")

        seconds = safe_time_to_seconds(time_value)
        if is_filled(async_value) and seconds is not None:
            results.append((runner_name, seconds))

    results.sort(key=lambda item: (item[1], item[0].lower()))
    return results


def get_quali_stats_for_runner(ws, runner_name: str, quali_number: int):
    results = get_quali_results(ws, quali_number)
    total_played = len(results)
    rank = None
    for idx, (name, _) in enumerate(results, start=1):
        if name.lower() == runner_name.lower():
            rank = idx
            break
    return total_played, rank


def get_overall_results(ws):
    all_values = ws.get_all_values()
    results = []

    for row_idx in range(START_ROW, len(all_values) + 1):
        row = all_values[row_idx - 1]
        runner_name = safe_cell(row, 1)  # B
        if not runner_name:
            continue

        q1_async = safe_cell(row, 3)  # D
        q1_time = safe_cell(row, 4)   # E
        q2_async = safe_cell(row, 5)  # F
        q2_time = safe_cell(row, 6)   # G

        q1_seconds = safe_time_to_seconds(q1_time)
        q2_seconds = safe_time_to_seconds(q2_time)

        if is_filled(q1_async) and is_filled(q2_async) and q1_seconds is not None and q2_seconds is not None:
            results.append((runner_name, q1_seconds + q2_seconds))

    results.sort(key=lambda item: (item[1], item[0].lower()))
    return results


def get_overall_stats_for_runner(ws, runner_name: str):
    results = get_overall_results(ws)
    total_completed = len(results)
    rank = None
    for idx, (name, _) in enumerate(results, start=1):
        if name.lower() == runner_name.lower():
            rank = idx
            break
    return total_completed, rank


def get_async_open_entries_for_runner(ws, runner_name: str):
    rows = ws.get_all_values()
    target = runner_name.strip().lower()
    entries = []

    for row_idx, row in enumerate(rows[1:], start=2):
        p1 = safe_cell(row, 1)    # B
        vod1 = safe_cell(row, 3)  # D
        time1 = safe_cell(row, 4) # E
        p2 = safe_cell(row, 5)    # F
        vod2 = safe_cell(row, 6)  # G
        time2 = safe_cell(row, 7) # H
        seed = safe_cell(row, 8)  # I
        art = safe_cell(row, 9)   # J
        source_row = safe_cell(row, 10) # K
        div = safe_cell(row, 11)  # L
        mode = safe_cell(row, 12) # M

        if not seed:
            continue

        side = None
        if p1.lower() == target and not vod1 and not time1:
            side = 1
        elif p2.lower() == target and not vod2 and not time2:
            side = 2

        if side is None:
            continue

        entries.append({
            "sheet_row": row_idx,
            "player1": p1,
            "player2": p2,
            "seed": seed,
            "art": art,
            "source_row_index": int(source_row) if source_row.isdigit() else None,
            "division": div,
            "mode": mode,
            "side": side,
        })

    return entries


def write_async_runner_result(ws, sheet_row: int, side: int, vod_link: str, final_time: str):
    if side == 1:
        ws.update(f"D{sheet_row}:E{sheet_row}", [[vod_link, final_time]])
    elif side == 2:
        ws.update(f"G{sheet_row}:H{sheet_row}", [[vod_link, final_time]])
    else:
        raise ValueError("Ungültige Seite.")


def read_async_entry(ws, sheet_row: int) -> dict:
    row = ws.row_values(sheet_row)
    return {
        "player1": safe_cell(row, 1),   # B
        "vod1": safe_cell(row, 3),      # D
        "time1": safe_cell(row, 4),     # E
        "player2": safe_cell(row, 5),   # F
        "vod2": safe_cell(row, 6),      # G
        "time2": safe_cell(row, 7),     # H
        "seed": safe_cell(row, 8),      # I
        "art": safe_cell(row, 9),       # J
        "source_row_index": safe_cell(row, 10),  # K
        "division": safe_cell(row, 11), # L
        "mode": safe_cell(row, 12),     # M
    }


def build_league_async_result(time1: str, time2: str) -> str:
    sec1 = parse_hms_to_seconds(time1)
    sec2 = parse_hms_to_seconds(time2)
    diff = abs(sec1 - sec2)

    if diff < 5:
        return "1:1"
    if sec1 < sec2:
        return "2:0"
    return "0:2"


# =========================================================
# AKTIVE RUNS IM SPEICHER
# =========================================================


class QualiRunState:
    def __init__(self, user_id: int, runner_name: str, quali_number: int, seed_url: str):
        self.user_id = user_id
        self.runner_name = runner_name
        self.quali_number = quali_number
        self.seed_url = seed_url

        self.created_at = dt.utcnow()
        self.seed_shown_at: dt | None = None
        self.started_at: dt | None = None
        self.finished_at: dt | None = None
        self.locked_final_time: str | None = None

        self.finished = False
        self.cancelled = False

        self.message: discord.Message | None = None
        self.timeout_task: asyncio.Task | None = None

    def measured_time(self) -> str:
        if not self.started_at:
            return "00:00:00"
        seconds = int((dt.utcnow() - self.started_at).total_seconds())
        if seconds < 0:
            seconds = 0
        return format_seconds_to_hms(seconds)

    def is_stale(self) -> bool:
        if self.started_at is None:
            return (dt.utcnow() - self.created_at).total_seconds() > RUN_STALE_SECONDS
        return False


class AsyncRaceState:
    def __init__(self, user_id: int, runner_name: str, entry: dict):
        self.user_id = user_id
        self.runner_name = runner_name
        self.entry = entry

        self.created_at = dt.utcnow()
        self.seed_shown_at: dt | None = None
        self.started_at: dt | None = None
        self.finished_at: dt | None = None
        self.locked_final_time: str | None = None

        self.finished = False
        self.cancelled = False

        self.message: discord.Message | None = None

    def measured_time(self) -> str:
        if not self.started_at:
            return "00:00:00"
        seconds = int((dt.utcnow() - self.started_at).total_seconds())
        if seconds < 0:
            seconds = 0
        return format_seconds_to_hms(seconds)


# =========================================================
# MODALS
# =========================================================


class QualiSubmitModal(discord.ui.Modal):
    def __init__(self, cog, state: QualiRunState, forfeit: bool = False):
        super().__init__(title=f"Quali {state.quali_number} Ergebnis")
        self.cog = cog
        self.state = state
        self.forfeit = forfeit

        if not forfeit:
            shown_time = state.locked_final_time or "Unbekannt"
            self.time_info = discord.ui.TextInput(
                label="Erreichte Zeit",
                default=shown_time,
                required=True,
            )
            self.add_item(self.time_info)

        self.vod_input = discord.ui.TextInput(
            label="VoD-Link" if not forfeit else "Kommentar (optional)",
            placeholder="https://..." if not forfeit else "Optional",
            required=not forfeit,
        )
        self.add_item(self.vod_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            if self.state.cancelled:
                await interaction.followup.send("Diese Quali wurde bereits abgebrochen.", ephemeral=True)
                return

            runner_name = self.state.runner_name
            ws = await asyncio.to_thread(get_quali_worksheet)

            if self.forfeit:
                async_value = "DNF"
                final_time = "03:00:00"
            else:
                vod_link = str(self.vod_input.value).strip()
                if not vod_link:
                    await interaction.followup.send("VoD-Link ist Pflicht.", ephemeral=True)
                    return

                if not self.state.locked_final_time:
                    await interaction.followup.send(
                        "Die Zielzeit konnte nicht eindeutig gespeichert werden. Bitte erneut versuchen.",
                        ephemeral=True,
                    )
                    return

                async_value = vod_link
                final_time = self.state.locked_final_time

            status = await asyncio.to_thread(read_runner_status, ws, runner_name)

            if self.state.quali_number == 1 and status["q1_done"]:
                await interaction.followup.send("Quali 1 ist für dich bereits eingetragen.", ephemeral=True)
                return

            if self.state.quali_number == 2 and status["q2_done"]:
                await interaction.followup.send("Quali 2 ist für dich bereits eingetragen.", ephemeral=True)
                return

            await asyncio.to_thread(
                write_quali_result,
                ws,
                runner_name,
                self.state.quali_number,
                async_value,
                final_time,
            )

            total_played, rank = await asyncio.to_thread(
                get_quali_stats_for_runner,
                ws,
                runner_name,
                self.state.quali_number,
            )

            self.state.finished = True
            self.state.finished_at = dt.utcnow()
            self.cog.stop_state_tasks(self.state)
            self.cog.active_runs.pop(self.state.user_id, None)

            await self.cog.send_quali_log(runner_name, self.state.quali_number, final_time)

            rank_text = f"Platz {rank}/{total_played}" if rank else f"{total_played} Ergebnisse"
            text = (
                f"Quali {self.state.quali_number} gespeichert.\n"
                f"Zeit: **{final_time}**\n"
                f"Aktueller Stand: **{rank_text}**"
            )
            await interaction.followup.send(text, ephemeral=True)

            if self.state.message:
                try:
                    await self.state.message.edit(
                        content=f"**Quali abgeschlossen**\nZeit: **{final_time}**",
                        view=None,
                    )
                except Exception:
                    pass

        except Exception as e:
            await interaction.followup.send(f"Fehler beim Speichern: {e}", ephemeral=True)


class AsyncSubmitModal(discord.ui.Modal):
    def __init__(self, cog, state: AsyncRaceState):
        super().__init__(title="Async Ergebnis")
        self.cog = cog
        self.state = state

        self.vod_input = discord.ui.TextInput(
            label="VoD-Link",
            placeholder="https://...",
            required=True,
        )
        self.add_item(self.vod_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            ws = await asyncio.to_thread(get_async_worksheet)

            vod_link = str(self.vod_input.value).strip()
            if not vod_link:
                await interaction.edit_original_response(content="VoD-Link ist Pflicht.")
                return

            final_time = self.state.locked_final_time
            if not final_time:
                await interaction.edit_original_response(content="Keine Zielzeit vorhanden.")
                return

            await asyncio.to_thread(
                write_async_runner_result,
                ws,
                self.state.entry["sheet_row"],
                self.state.entry["side"],
                vod_link,
                final_time,
            )

            updated = await asyncio.to_thread(
                read_async_entry,
                ws,
                self.state.entry["sheet_row"],
            )

            self.state.finished = True
            self.state.finished_at = dt.utcnow()

            both_done = bool(updated["time1"] and updated["time2"])
            result_info = ""

            if both_done:
                provisional = None
                if updated["art"].lower() == "league" and updated["time1"] and updated["time2"]:
                    provisional = build_league_async_result(updated["time1"], updated["time2"])
                    result_info = f"\n\nVorläufiges Ergebnis: **{provisional}**"

                await self.cog.notify_async_review_ready(
                    interaction,
                    self.state.entry["sheet_row"],
                    updated,
                    provisional,
                )
                result_info += "\nOrga-Prüfung wurde angefordert."
            else:
                result_info = "\nDer andere Spieler muss noch fertig werden."

            await interaction.edit_original_response(
                content=(
                    "Async-Ergebnis gespeichert.\n"
                    f"Spiel: **{updated['player1']} vs. {updated['player2']}**\n"
                    f"Zeit: **{final_time}**{result_info}"
                )
            )

            if self.state.message:
                try:
                    await self.state.message.edit(
                        content=(
                            f"**Async abgeschlossen**\n"
                            f"Spiel: **{updated['player1']} vs. {updated['player2']}**\n"
                            f"Zeit: **{final_time}**"
                        ),
                        view=None,
                    )
                except Exception:
                    pass

        except Exception as e:
            await interaction.edit_original_response(content=f"Fehler beim Speichern: {e}")


class AsyncRejectModal(discord.ui.Modal, title="Async ablehnen"):
    def __init__(self, cog, sheet_row: int):
        super().__init__()
        self.cog = cog
        self.sheet_row = sheet_row

        self.reason_input = discord.ui.TextInput(
            label="Grund",
            style=discord.TextStyle.paragraph,
            placeholder="Ablehnungsgrund",
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason = str(self.reason_input.value).strip()

        try:
            await self.cog.reject_async_result(interaction, self.sheet_row, reason)
            await interaction.edit_original_response(content="Async wurde abgelehnt.")
        except Exception as e:
            await interaction.edit_original_response(content=f"Fehler beim Ablehnen: {e}")


# =========================================================
# QUALI VIEWS
# =========================================================


class QualiSelectView(discord.ui.View):
    def __init__(self, cog, runner_name: str, q1_disabled: bool, q2_disabled: bool):
        super().__init__(timeout=300)
        self.cog = cog
        self.runner_name = runner_name

        self.q1_button.disabled = q1_disabled
        self.q2_button.disabled = q2_disabled

    @discord.ui.button(label="Quali 1", style=discord.ButtonStyle.primary)
    async def q1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_quali_seed(interaction, self.runner_name, 1)

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary)
    async def q2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_quali_seed(interaction, self.runner_name, 2)

   

class QualiSeedView(discord.ui.View):
    def __init__(self, cog, state: QualiRunState):
        super().__init__(timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Seed öffnen", style=discord.ButtonStyle.primary)
    async def reveal_seed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.reveal_quali_seed(interaction, self.state)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_quali(interaction, self.state)


class QualiStartView(discord.ui.View):
    def __init__(self, cog, state: QualiRunState):
        super().__init__(timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.start_quali_run(interaction, self.state)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_quali(interaction, self.state)


class QualiRunningView(discord.ui.View):
    def __init__(self, cog, state: QualiRunState):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.success)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.finish_quali(interaction, self.state)

    @discord.ui.button(label="DNF", style=discord.ButtonStyle.danger)
    async def dnf_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QualiSubmitModal(self.cog, self.state, forfeit=True))


# =========================================================
# ASYNC VIEWS
# =========================================================


class AsyncEntrySelect(discord.ui.Select):
    def __init__(self, cog, entries: list[dict]):
        self.cog = cog
        self.entries = entries

        options = []
        for entry in entries[:25]:
            label = f"{entry['player1']} vs. {entry['player2']}"
            description = f"{entry['art']} | {entry['division']} | {entry['mode']}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    description=description[:100],
                    value=str(entry["sheet_row"]),
                )
            )

        super().__init__(
            placeholder="Offenes Async auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        sheet_row = int(self.values[0])
        entry = next((e for e in self.entries if e["sheet_row"] == sheet_row), None)

        if entry is None:
            await interaction.response.send_message("Async nicht gefunden.", ephemeral=True)
            return

        await self.cog.open_async_entry(interaction, entry)


class AsyncSelectView(discord.ui.View):
    def __init__(self, cog, entries: list[dict]):
        super().__init__(timeout=300)
        self.add_item(AsyncEntrySelect(cog, entries))


class AsyncSeedView(discord.ui.View):
    def __init__(self, cog, state: AsyncRaceState):
        super().__init__(timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Seed öffnen", style=discord.ButtonStyle.primary)
    async def reveal_seed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.reveal_async_seed(interaction, self.state)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_async(interaction, self.state)


class AsyncStartView(discord.ui.View):
    def __init__(self, cog, state: AsyncRaceState):
        super().__init__(timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.start_async_race(interaction, self.state)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_async(interaction, self.state)


class AsyncRunningView(discord.ui.View):
    def __init__(self, cog, state: AsyncRaceState):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.success)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.finish_async(interaction, self.state)


class AsyncAdminReviewView(discord.ui.View):
    def __init__(self, cog, sheet_row: int):
        super().__init__(timeout=86400)
        self.cog = cog
        self.sheet_row = sheet_row

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.cog.is_admin_user(interaction):
            await interaction.response.send_message("Dafür brauchst du Admin-Rechte.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AsyncRejectModal(self.cog, self.sheet_row))

    @discord.ui.button(label="Eintragen", style=discord.ButtonStyle.success)
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        try:
            result_text = await self.cog.approve_async_result(interaction, self.sheet_row)
            await interaction.edit_original_response(content=f"Async wurde eingetragen: **{result_text}**")
        except Exception as e:
            await interaction.edit_original_response(content=f"Fehler beim Eintragen: {e}")


# =========================================================
# HELFER FÜR PLAYER.PY
# =========================================================


async def open_quali_from_player(interaction: discord.Interaction):
    cog = interaction.client.get_cog("QualiCog")
    if cog is None or not isinstance(cog, QualiCog):
        await interaction.response.send_message("Qualifikation ist aktuell nicht verfügbar.", ephemeral=True)
        return
    await cog.start_quali_flow(interaction, edit_existing=True)


async def open_async_play_from_player(interaction: discord.Interaction):
    cog = interaction.client.get_cog("QualiCog")
    if cog is None or not isinstance(cog, QualiCog):
        await interaction.response.send_message("Async spielen ist aktuell nicht verfügbar.", ephemeral=True)
        return
    await cog.start_async_flow(interaction, edit_existing=True)


# =========================================================
# COG
# =========================================================


class QualiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_runs: dict[int, QualiRunState] = {}
        self.active_asyncs: dict[int, AsyncRaceState] = {}

    def is_admin_user(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        return any(role.name == ADMIN_ROLE_NAME for role in interaction.user.roles)

    def stop_state_tasks(self, state: QualiRunState):
        if state.timeout_task and not state.timeout_task.done():
            state.timeout_task.cancel()
        state.timeout_task = None

    async def send_quali_log(self, runner_name: str, quali_number: int, final_time: str):
        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                return

        try:
            await channel.send(
                f"**{runner_name}** hat **Qualifikation {quali_number}** "
                f"mit einer Zeit von **{final_time}** beendet."
            )
        except Exception:
            pass

    def cleanup_stale_run(self, user_id: int):
        active = self.active_runs.get(user_id)
        if active and not active.finished and active.is_stale():
            self.stop_state_tasks(active)
            self.active_runs.pop(user_id, None)

    async def start_quali_flow(self, interaction: discord.Interaction, edit_existing: bool = False):
        if not edit_existing:
            await interaction.response.defer(ephemeral=True)
        else:
            await interaction.response.defer()

        try:
            self.cleanup_stale_run(interaction.user.id)
            runner_name = get_runner_name(interaction)

            is_eligible = await asyncio.to_thread(is_runner_quali_eligible, runner_name)
            if not is_eligible:
                if edit_existing:
                    await interaction.edit_original_response(content=NOT_ELIGIBLE_TEXT, view=None)
                else:
                    await interaction.followup.send(NOT_ELIGIBLE_TEXT, ephemeral=True)
                return

            ws = await asyncio.to_thread(get_quali_worksheet)
            status = await asyncio.to_thread(read_runner_status, ws, runner_name)

            active = self.active_runs.get(interaction.user.id)
            if active and not active.finished:
                text = f"Du hast bereits eine laufende Quali {active.quali_number}. Nutze **/qualireset**."
                if edit_existing:
                    await interaction.edit_original_response(content=text, view=None)
                else:
                    await interaction.followup.send(text, ephemeral=True)
                return

            view = QualiSelectView(
                cog=self,
                runner_name=runner_name,
                q1_disabled=status["q1_done"],
                q2_disabled=status["q2_done"],
            )

            text = (
                f"**Qualifikationsauswahl für {runner_name}**\n\n"
                f"Quali 1: {'bereits gespielt' if status['q1_done'] else 'offen'}\n"
                f"Quali 2: {'bereits gespielt' if status['q2_done'] else 'offen'}\n\n"
                f"**Wichtig:** Nach dem Klick auf **Start** läuft deine Zeit, "
                f"aber es wird kein Live-Timer im Discord angezeigt.\n"
                f"Zum Abschluss musst du dein Ergebnis mit VoD-Link einreichen."
            )

            if edit_existing:
                await interaction.edit_original_response(content=text, view=view)
            else:
                await interaction.followup.send(text, view=view, ephemeral=True)

        except Exception as e:
            if edit_existing:
                await interaction.edit_original_response(content=f"Fehler: {e}", view=None)
            else:
                await interaction.followup.send(f"Fehler: {e}", ephemeral=True)

    async def open_quali_seed(self, interaction: discord.Interaction, runner_name: str, quali_number: int):
        try:
            if interaction.user.id in self.active_runs and not self.active_runs[interaction.user.id].finished:
                await interaction.response.send_message("Du hast bereits eine laufende Quali.", ephemeral=True)
                return

            ws = await asyncio.to_thread(get_quali_worksheet)
            seed_url = await asyncio.to_thread(get_quali_seed, ws, quali_number)

            state = QualiRunState(interaction.user.id, runner_name, quali_number, seed_url)
            self.active_runs[interaction.user.id] = state

            text = (
                f"**Quali {quali_number}**\n\n"
                f"Mit Klick auf **Seed öffnen** siehst du den Seed.\n"
                f"Danach musst du **Start** drücken, damit deine Zeit beginnt."
            )
            view = QualiSeedView(self, state)
            await interaction.response.edit_message(content=text, view=view)
            state.message = await interaction.original_response()

        except Exception as e:
            await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)

    async def reveal_quali_seed(self, interaction: discord.Interaction, state: QualiRunState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        state.seed_shown_at = dt.utcnow()
        content = (
            f"**Quali {state.quali_number} Seed**\n\n"
            f"Seed-Link: {state.seed_url}\n\n"
            f"Drücke **Start**, wenn du wirklich bereit bist.\n"
            f"Es gibt keinen Live-Timer im Discord."
        )
        view = QualiStartView(self, state)
        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

    async def start_quali_run(self, interaction: discord.Interaction, state: QualiRunState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        if state.started_at is not None:
            await interaction.response.send_message("Diese Quali läuft bereits.", ephemeral=True)
            return

        state.started_at = dt.utcnow()
        content = (
            f"**Quali {state.quali_number} läuft**\n\n"
            f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n\n"
            f"Drücke am Ende **Finish** oder **DNF**.\n"
            f"Es gibt keinen Live-Timer im Discord."
        )
        view = QualiRunningView(self, state)
        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

    async def finish_quali(self, interaction: discord.Interaction, state: QualiRunState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        if state.started_at is None:
            await interaction.response.send_message("Diese Quali wurde noch nicht gestartet.", ephemeral=True)
            return

        state.finished_at = dt.utcnow()
        state.locked_final_time = state.measured_time()
        await interaction.response.send_modal(QualiSubmitModal(self, state, forfeit=False))

    async def cancel_quali(self, interaction: discord.Interaction, state: QualiRunState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        state.cancelled = True
        self.stop_state_tasks(state)
        self.active_runs.pop(state.user_id, None)

        await interaction.response.edit_message(
            content="Quali abgebrochen.",
            view=None,
        )

    async def send_quali_stand(self, interaction: discord.Interaction, quali_number: int):
        try:
            ws = await asyncio.to_thread(get_quali_worksheet)
            results = await asyncio.to_thread(get_quali_results, ws, quali_number)

            if not results:
                text = f"Für Quali {quali_number} liegen noch keine Ergebnisse vor."
            else:
                lines = [f"**Stand Quali {quali_number}**"]
                for idx, (name, secs) in enumerate(results[:20], start=1):
                    lines.append(f"{idx}. {name} — {format_seconds_to_hms(secs)}")
                text = "\n".join(lines)

            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)

        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Fehler: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)

    async def send_overall_stand(self, interaction: discord.Interaction):
        try:
            ws = await asyncio.to_thread(get_quali_worksheet)
            results = await asyncio.to_thread(get_overall_results, ws)

            if not results:
                text = "Es liegen noch keine Gesamtwertungen vor."
            else:
                lines = ["**Gesamtstand**"]
                for idx, (name, secs) in enumerate(results[:20], start=1):
                    lines.append(f"{idx}. {name} — {format_seconds_to_hms(secs)}")
                text = "\n".join(lines)

            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)

        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Fehler: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)

    async def start_async_flow(self, interaction: discord.Interaction, edit_existing: bool = False):
        if not edit_existing:
            await interaction.response.defer(ephemeral=True)
        else:
            await interaction.response.defer()

        try:
            runner_name = get_runner_name(interaction)

            active = self.active_asyncs.get(interaction.user.id)
            if active and not active.finished:
                text = "Du hast bereits ein laufendes Async."
                if edit_existing:
                    await interaction.edit_original_response(content=text, view=None)
                else:
                    await interaction.followup.send(text, ephemeral=True)
                return

            ws = await asyncio.to_thread(get_async_worksheet)
            entries = await asyncio.to_thread(get_async_open_entries_for_runner, ws, runner_name)

            if not entries:
                text = "Keine offenen Asyncs für dich gefunden."
                if edit_existing:
                    await interaction.edit_original_response(content=text, view=None)
                else:
                    await interaction.followup.send(text, ephemeral=True)
                return

            text = (
                f"**Offene Asyncs für {runner_name}**\n\n"
                f"Wähle ein Async aus. Nach dem Klick auf **Start** läuft deine Zeit, "
                f"aber es wird kein Live-Timer im Discord angezeigt."
            )
            view = AsyncSelectView(self, entries)

            if edit_existing:
                await interaction.edit_original_response(content=text, view=view)
            else:
                await interaction.followup.send(text, view=view, ephemeral=True)

        except Exception as e:
            if edit_existing:
                await interaction.edit_original_response(content=f"Fehler: {e}", view=None)
            else:
                await interaction.followup.send(f"Fehler: {e}", ephemeral=True)

    async def open_async_entry(self, interaction: discord.Interaction, entry: dict):
        runner_name = get_runner_name(interaction)
        state = AsyncRaceState(interaction.user.id, runner_name, entry)
        self.active_asyncs[interaction.user.id] = state

        text = (
            f"**Async Race**\n\n"
            f"Spiel: **{entry['player1']} vs. {entry['player2']}**\n"
            f"Art: **{entry['art']}**\n"
            f"Division: **{entry['division']}**\n"
            f"Modus: **{entry['mode']}**\n\n"
            f"Mit Klick auf **Seed öffnen** erhältst du den Async-Seed.\n"
            f"Danach startet deine Zeit erst mit **Start**."
        )
        view = AsyncSeedView(self, state)
        await interaction.response.edit_message(content=text, view=view)
        state.message = await interaction.original_response()

    async def reveal_async_seed(self, interaction: discord.Interaction, state: AsyncRaceState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht dein Async.", ephemeral=True)
            return

        state.seed_shown_at = dt.utcnow()
        content = (
            f"**Async Seed geöffnet**\n\n"
            f"Spiel: **{state.entry['player1']} vs. {state.entry['player2']}**\n"
            f"Seed-Link: {state.entry['seed']}\n\n"
            f"Drücke **Start**, wenn du wirklich bereit bist.\n"
            f"Während des Runs gibt es keinen Live-Timer im Discord."
        )
        view = AsyncStartView(self, state)
        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

    async def start_async_race(self, interaction: discord.Interaction, state: AsyncRaceState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht dein Async.", ephemeral=True)
            return

        if state.started_at is not None:
            await interaction.response.send_message("Dieses Async läuft bereits.", ephemeral=True)
            return

        state.started_at = dt.utcnow()
        content = (
            f"**Async läuft**\n\n"
            f"Spiel: **{state.entry['player1']} vs. {state.entry['player2']}**\n"
            f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n\n"
            f"Drücke am Ende **Finish**.\n"
            f"Es gibt keinen Live-Timer im Discord."
        )
        view = AsyncRunningView(self, state)
        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

    async def finish_async(self, interaction: discord.Interaction, state: AsyncRaceState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht dein Async.", ephemeral=True)
            return

        if state.started_at is None:
            await interaction.response.send_message("Dieses Async wurde noch nicht gestartet.", ephemeral=True)
            return

        state.finished_at = dt.utcnow()
        state.locked_final_time = state.measured_time()
        await interaction.response.send_modal(AsyncSubmitModal(self, state))

    async def cancel_async(self, interaction: discord.Interaction, state: AsyncRaceState):
        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht dein Async.", ephemeral=True)
            return

        state.cancelled = True
        self.active_asyncs.pop(state.user_id, None)
        await interaction.response.edit_message(content="Async abgebrochen.", view=None)

    async def notify_async_review_ready(
        self,
        interaction: discord.Interaction,
        sheet_row: int,
        updated: dict,
        provisional_result: str | None,
    ):
        guild = interaction.guild

        player1 = updated["player1"]
        player2 = updated["player2"]
        time1 = updated["time1"] or "-"
        time2 = updated["time2"] or "-"
        vod1 = updated["vod1"] or "-"
        vod2 = updated["vod2"] or "-"
        art = updated["art"] or "-"
        division = updated["division"] or "-"
        mode = updated["mode"] or "-"

        dm_text = (
            f"Dein Async ist vollständig.\n\n"
            f"Spiel: **{player1} vs. {player2}**\n"
            f"Zeiten: **{player1}: {time1}** | **{player2}: {time2}**\n"
            f"Vorläufiges Ergebnis: **{provisional_result or '-'}**\n"
            f"Hinweis: Das Ergebnis wird noch von der Orga geprüft."
        )

        member1 = find_member_by_runner_name(guild, player1)
        member2 = find_member_by_runner_name(guild, player2)

        await try_send_dm(member1, dm_text)
        await try_send_dm(member2, dm_text)

        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                channel = None

        if channel is None:
            return

        review_text = (
            f"**Async zur Orga-Prüfung**\n\n"
            f"Spiel: **{player1} vs. {player2}**\n"
            f"Art: **{art}**\n"
            f"Division: **{division}**\n"
            f"Modus: **{mode}**\n"
            f"Zeiten: **{player1}: {time1}** | **{player2}: {time2}**\n"
            f"Vorläufiges Ergebnis: **{provisional_result or '-'}**\n"
            f"VoD {player1}: {vod1}\n"
            f"VoD {player2}: {vod2}"
        )

        await channel.send(review_text, view=AsyncAdminReviewView(self, sheet_row))

    async def approve_async_result(self, interaction: discord.Interaction, sheet_row: int) -> str:
        ws = await asyncio.to_thread(get_async_worksheet)
        updated = await asyncio.to_thread(read_async_entry, ws, sheet_row)

        if not updated["time1"] or not updated["time2"]:
            raise RuntimeError("Es liegen noch nicht beide Zeiten vor.")

        if updated["art"].lower() != "league":
            raise RuntimeError("Automatisches Eintragen ist aktuell nur für League umgesetzt.")

        if not updated["source_row_index"].isdigit():
            raise RuntimeError("Original-Zeile im Div-Sheet fehlt.")

        if not updated["division"]:
            raise RuntimeError("Division fehlt im Async-Sheet.")

        result_text = build_league_async_result(updated["time1"], updated["time2"])
        timestamp = now_berlin_str()
        source_row_index = int(updated["source_row_index"])
        mode = updated["mode"] or "Async"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            write_league_result,
            source_row_index,
            mode,
            result_text,
            "Async",
            "Async",
            timestamp,
            updated["division"],
        )

        if interaction.guild is not None:
            post_text = league_result_post_text(
                updated["division"],
                timestamp,
                updated["player1"],
                updated["player2"],
                result_text,
                mode,
                "Async",
            )
            await send_result_post(interaction.guild, post_text)

        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    content=(interaction.message.content or "") + f"\n\n✅ Eingetragen: **{result_text}**",
                    view=None,
                )
            except Exception:
                pass

        return result_text

    async def reject_async_result(self, interaction: discord.Interaction, sheet_row: int, reason: str):
        ws = await asyncio.to_thread(get_async_worksheet)
        updated = await asyncio.to_thread(read_async_entry, ws, sheet_row)

        guild = interaction.guild
        dm_text = (
            f"Dein Async wurde von der Orga abgelehnt.\n\n"
            f"Spiel: **{updated['player1']} vs. {updated['player2']}**\n"
            f"Grund: {reason}"
        )

        member1 = find_member_by_runner_name(guild, updated["player1"])
        member2 = find_member_by_runner_name(guild, updated["player2"])

        await try_send_dm(member1, dm_text)
        await try_send_dm(member2, dm_text)

        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    content=(interaction.message.content or "") + f"\n\n❌ Abgelehnt: {reason}",
                    view=None,
                )
            except Exception:
                pass

    @app_commands.command(name="quali", description="Qualifikation starten")
    async def quali_cmd(self, interaction: discord.Interaction):
        await self.start_quali_flow(interaction, edit_existing=False)

    @app_commands.command(name="qualireset", description="Laufende Quali zurücksetzen")
    async def qualireset_cmd(self, interaction: discord.Interaction):
        active = self.active_runs.pop(interaction.user.id, None)
        if active:
            active.cancelled = True
            self.stop_state_tasks(active)
            await interaction.response.send_message("Deine laufende Quali wurde zurückgesetzt.", ephemeral=True)
            return
        await interaction.response.send_message("Du hast aktuell keine laufende Quali.", ephemeral=True)

    @app_commands.command(name="asyncplay", description="Offenes Async spielen")
    async def asyncplay_cmd(self, interaction: discord.Interaction):
        await self.start_async_flow(interaction, edit_existing=False)


async def setup(bot):
    await bot.add_cog(QualiCog(bot))

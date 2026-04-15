import os
import asyncio
import re
import gspread
from datetime import datetime as dt, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# KONFIG
# =========================================================

GUILD_ID = 1275076189173579846
QUALI_SHEET_NAME = "Quali"
START_ROW = 4
RUN_STALE_SECONDS = 15 * 60  # 15 Minuten

# B = Runner
# D = Quali1 Async?/VoD/DNF
# E = Quali1 Zeit
# F = Quali2 Async?/VoD/DNF
# G = Quali2 Zeit
# D2 = Seed Quali 1
# F2 = Seed Quali 2

TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")

CREDS_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json").strip()
SPREADSHEET_ID = "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8"


# =========================================================
# HILFSFUNKTIONEN
# =========================================================

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


# =========================================================
# GOOGLE SHEETS
# =========================================================

def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    return gspread.authorize(creds)


def get_quali_worksheet():
    client = get_gspread_client()
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.worksheet(QUALI_SHEET_NAME)


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

    q1_async = safe_cell(row, 3)   # D
    q1_time = safe_cell(row, 4)    # E
    q2_async = safe_cell(row, 5)   # F
    q2_time = safe_cell(row, 6)    # G

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


# =========================================================
# MODAL
# =========================================================

class QualiSubmitModal(discord.ui.Modal):
    def __init__(self, cog, state: QualiRunState, forfeit: bool = False):
        super().__init__(title=f"Quali {state.quali_number} Ergebnis")
        self.cog = cog
        self.state = state
        self.forfeit = forfeit

        self.vod_input = discord.ui.TextInput(
            label="VoD-Link" if not forfeit else "Kommentar (optional)",
            placeholder="https://..." if not forfeit else "Optional",
            required=not forfeit
        )

        self.add_item(self.vod_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            if self.state.cancelled:
                await interaction.followup.send(
                    "Diese Quali wurde bereits abgebrochen.",
                    ephemeral=True
                )
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
                        ephemeral=True
                    )
                    return

                async_value = vod_link
                final_time = self.state.locked_final_time

            status = await asyncio.to_thread(read_runner_status, ws, runner_name)

            if self.state.quali_number == 1 and status["q1_done"]:
                await interaction.followup.send(
                    "Quali 1 ist für dich bereits eingetragen.",
                    ephemeral=True
                )
                return

            if self.state.quali_number == 2 and status["q2_done"]:
                await interaction.followup.send(
                    "Quali 2 ist für dich bereits eingetragen.",
                    ephemeral=True
                )
                return

            row_idx = await asyncio.to_thread(
                write_quali_result,
                ws,
                runner_name,
                self.state.quali_number,
                async_value,
                final_time
            )

            total_played, rank = await asyncio.to_thread(
                get_quali_stats_for_runner,
                ws,
                runner_name,
                self.state.quali_number
            )

            self.state.finished = True
            self.state.finished_at = dt.utcnow()
            self.cog.stop_state_tasks(self.state)
            self.cog.active_runs.pop(self.state.user_id, None)

            place_text = f"Platz: **{rank}/{total_played}**" if rank is not None else "Platz aktuell nicht verfügbar."

            await interaction.followup.send(
                f"Ergebnis gespeichert.\n"
                f"Runner: **{runner_name}**\n"
                f"Quali: **{self.state.quali_number}**\n"
                f"Zeile: **{row_idx}**\n"
                f"Eintrag: **{async_value}**\n"
                f"Zeit: **{final_time}**\n"
                f"Bereits gespielt: **{total_played}**\n"
                f"{place_text}",
                ephemeral=True
            )

            if self.state.message:
                try:
                    await self.state.message.edit(
                        content=(
                            f"**Quali {self.state.quali_number} abgeschlossen**\n"
                            f"Eintrag: **{async_value}**\n"
                            f"Zeit: **{final_time}**\n"
                            f"Bereits gespielt: **{total_played}**\n"
                            f"{place_text}"
                        ),
                        view=None
                    )
                except Exception:
                    pass

        except Exception as e:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"Fehler beim Speichern: {e}",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"Fehler beim Speichern: {e}",
                        ephemeral=True
                    )
            except Exception:
                pass


# =========================================================
# VIEWS
# =========================================================

class QualiSelectView(discord.ui.View):
    def __init__(self, cog, runner_name: str, q1_disabled: bool, q2_disabled: bool):
        super().__init__(timeout=300)
        self.cog = cog
        self.runner_name = runner_name

        self.quali1_button.disabled = q1_disabled
        self.quali2_button.disabled = q2_disabled

    @discord.ui.button(label="Quali 1", style=discord.ButtonStyle.primary, custom_id="quali_select_1")
    async def quali1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_quali_info(interaction, quali_number=1)

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary, custom_id="quali_select_2")
    async def quali2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_quali_info(interaction, quali_number=2)


class QualiSeedView(discord.ui.View):
    def __init__(self, cog, state: QualiRunState):
        super().__init__(timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Seed öffnen", style=discord.ButtonStyle.success, custom_id="quali_seed_1")
    async def seed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.reveal_seed(interaction, self.state)


class QualiStartView(discord.ui.View):
    def __init__(self, cog, state: QualiRunState):
        super().__init__(timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, custom_id="quali_start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.start_race(interaction, self.state)


class QualiRunningView(discord.ui.View):
    def __init__(self, cog, state: QualiRunState):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.success, custom_id="quali_finish")
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state.finished:
            await interaction.response.send_message("Diese Quali ist bereits abgeschlossen.", ephemeral=True)
            return

        if self.state.cancelled:
            await interaction.response.send_message("Diese Quali wurde bereits abgebrochen.", ephemeral=True)
            return

        self.state.locked_final_time = self.state.measured_time()
        self.cog.stop_state_tasks(self.state)

        modal = QualiSubmitModal(self.cog, self.state, forfeit=False)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, custom_id="quali_forfeit")
    async def forfeit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state.finished:
            await interaction.response.send_message("Diese Quali ist bereits abgeschlossen.", ephemeral=True)
            return

        if self.state.cancelled:
            await interaction.response.send_message("Diese Quali wurde bereits abgebrochen.", ephemeral=True)
            return

        self.state.locked_final_time = "03:00:00"
        self.cog.stop_state_tasks(self.state)

        modal = QualiSubmitModal(self.cog, self.state, forfeit=True)
        await interaction.response.send_modal(modal)


class QualiStandView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Stand Quali 1", style=discord.ButtonStyle.primary, custom_id="quali_stand_q1")
    async def stand_q1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_quali_stand(interaction, 1)

    @discord.ui.button(label="Stand Quali 2", style=discord.ButtonStyle.primary, custom_id="quali_stand_q2")
    async def stand_q2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_quali_stand(interaction, 2)

    @discord.ui.button(label="Gesamtstand", style=discord.ButtonStyle.secondary, custom_id="quali_stand_total")
    async def stand_total_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_overall_stand(interaction)


# =========================================================
# COG
# =========================================================

class QualiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_runs: dict[int, QualiRunState] = {}

    def cleanup_stale_run(self, user_id: int):
        active = self.active_runs.get(user_id)
        if active and not active.finished and active.is_stale():
            self.stop_state_tasks(active)
            self.active_runs.pop(user_id, None)

    @app_commands.command(
        name="quali",
        description="Startet die Qualifikationsauswahl."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def quali(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            self.cleanup_stale_run(interaction.user.id)

            runner_name = get_runner_name(interaction)
            ws = await asyncio.to_thread(get_quali_worksheet)
            status = await asyncio.to_thread(read_runner_status, ws, runner_name)

            active = self.active_runs.get(interaction.user.id)
            if active and not active.finished:
                await interaction.followup.send(
                    f"Du hast bereits eine laufende Quali {active.quali_number}. Nutze **/qualireset**.",
                    ephemeral=True
                )
                return

            view = QualiSelectView(
                cog=self,
                runner_name=runner_name,
                q1_disabled=status["q1_done"],
                q2_disabled=status["q2_done"]
            )

            text = (
                f"**Qualifikationsauswahl für {runner_name}**\n\n"
                f"Quali 1: {'bereits gespielt' if status['q1_done'] else 'offen'}\n"
                f"Quali 2: {'bereits gespielt' if status['q2_done'] else 'offen'}\n\n"
                f"**Wichtig:** Nach dem Klick auf **Start** läuft deine Zeit, aber es wird kein Live-Timer im Discord angezeigt.\n"
                f"Nutze für dich selbst einen eigenen Timer oder orientiere dich an deiner Aufnahme."
            )

            await interaction.followup.send(text, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler bei /quali: {e}",
                ephemeral=True
            )

    @app_commands.command(
        name="qualistand",
        description="Zeigt deinen aktuellen Stand in Quali 1, Quali 2 oder Gesamt."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def qualistand(self, interaction: discord.Interaction):
        view = QualiStandView(self)
        await interaction.response.send_message(
            "**Welchen Stand möchtest du sehen?**",
            view=view,
            ephemeral=True
        )

    @app_commands.command(
        name="qualireset",
        description="Setzt eine hängende Quali zurück."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def qualireset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        state = self.active_runs.pop(interaction.user.id, None)

        if not state:
            await interaction.followup.send("Keine aktive Quali gefunden.", ephemeral=True)
            return

        state.cancelled = True
        state.finished = True
        self.stop_state_tasks(state)

        if state.message:
            try:
                await state.message.edit(
                    content="**Quali abgebrochen und zurückgesetzt.**",
                    view=None
                )
            except Exception:
                pass

        await interaction.followup.send("Quali wurde zurückgesetzt.", ephemeral=True)

    @qualireset.error
    async def qualireset_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.errors.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Diesen Command dürfen nur Admins ausführen.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Diesen Command dürfen nur Admins ausführen.",
                    ephemeral=True
                )
            return

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Fehler bei /qualireset: {error}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Fehler bei /qualireset: {error}",
                ephemeral=True
            )

    async def send_quali_stand(self, interaction: discord.Interaction, quali_number: int):
        await interaction.response.defer(ephemeral=True)

        try:
            runner_name = get_runner_name(interaction)
            ws = await asyncio.to_thread(get_quali_worksheet)
            total_played, rank = await asyncio.to_thread(
                get_quali_stats_for_runner,
                ws,
                runner_name,
                quali_number
            )

            if rank is None:
                text = (
                    f"**Stand Quali {quali_number}**\n\n"
                    f"Bereits gespielt: **{total_played}**\n"
                    f"Du hast Quali {quali_number} aktuell noch nicht abgeschlossen."
                )
            else:
                text = (
                    f"**Stand Quali {quali_number}**\n\n"
                    f"Bereits gespielt: **{total_played}**\n"
                    f"Dein aktueller Platz: **{rank}/{total_played}**"
                )

            await interaction.followup.send(text, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler bei Stand Quali {quali_number}: {e}",
                ephemeral=True
            )

    async def send_overall_stand(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            runner_name = get_runner_name(interaction)
            ws = await asyncio.to_thread(get_quali_worksheet)
            total_completed, rank = await asyncio.to_thread(
                get_overall_stats_for_runner,
                ws,
                runner_name
            )

            if rank is None:
                text = (
                    f"**Gesamtstand**\n\n"
                    f"Beide Qualis abgeschlossen: **{total_completed}**\n"
                    f"Du bist aktuell noch nicht im Gesamtstand, weil dir mindestens eine Quali fehlt."
                )
            else:
                text = (
                    f"**Gesamtstand**\n\n"
                    f"Beide Qualis abgeschlossen: **{total_completed}**\n"
                    f"Dein aktueller Platz: **{rank}/{total_completed}**"
                )

            await interaction.followup.send(text, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Gesamtstand: {e}",
                ephemeral=True
            )

    async def open_quali_info(self, interaction: discord.Interaction, quali_number: int):
        await interaction.response.defer(ephemeral=True)

        try:
            self.cleanup_stale_run(interaction.user.id)

            runner_name = get_runner_name(interaction)
            ws = await asyncio.to_thread(get_quali_worksheet)
            status = await asyncio.to_thread(read_runner_status, ws, runner_name)

            if quali_number == 1 and status["q1_done"]:
                await interaction.followup.send("Quali 1 ist für dich bereits eingetragen.", ephemeral=True)
                return

            if quali_number == 2 and status["q2_done"]:
                await interaction.followup.send("Quali 2 ist für dich bereits eingetragen.", ephemeral=True)
                return

            active = self.active_runs.get(interaction.user.id)
            if active and not active.finished:
                await interaction.followup.send(
                    f"Du hast bereits eine laufende Quali {active.quali_number}. Nutze **/qualireset**.",
                    ephemeral=True
                )
                return

            seed_url = await asyncio.to_thread(get_quali_seed, ws, quali_number)

            state = QualiRunState(
                user_id=interaction.user.id,
                runner_name=runner_name,
                quali_number=quali_number,
                seed_url=seed_url
            )
            self.active_runs[interaction.user.id] = state

            hint_text = (
                f"**Quali {quali_number}**\n\n"
                f"Mit Klick auf **Seed öffnen** erhältst du den Link zum Quali-Seed.\n"
                f"Innerhalb von **5 Minuten** nach dem Öffnen musst du starten. Bei Überschreiten erhältst du "
                f"ein FF und **03:00:00** als Ergebnis.\n\n"
                f"**Wichtig:** Nach dem Klick auf **Start** läuft deine Zeit, aber Discord zeigt keinen Live-Timer an.\n"
                f"Drücke also erst auf **Start**, wenn du wirklich bereit bist.\n\n"
                f"Achte bei deiner Aufnahme darauf, dass dein Timer durchgehend zu sehen ist und lasse den Endscreen "
                f"bis zum Ende durchlaufen."
            )

            view = QualiSeedView(self, state)

            await interaction.followup.send(hint_text, view=view, ephemeral=True)
            state.message = await interaction.original_response()

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Öffnen der Quali: {e}",
                ephemeral=True
            )

    async def reveal_seed(self, interaction: discord.Interaction, state: QualiRunState):
        if state.finished:
            await interaction.response.send_message("Diese Quali ist bereits abgeschlossen.", ephemeral=True)
            return

        if state.cancelled:
            await interaction.response.send_message("Diese Quali wurde bereits abgebrochen.", ephemeral=True)
            return

        if state.seed_shown_at is not None:
            await interaction.response.send_message("Der Seed wurde bereits geöffnet.", ephemeral=True)
            return

        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        state.seed_shown_at = dt.utcnow()
        deadline = state.seed_shown_at + timedelta(minutes=5)

        content = (
            f"**Quali {state.quali_number} – Seed geöffnet**\n\n"
            f"Seed-Link: {state.seed_url}\n\n"
            f"Du musst innerhalb von **5 Minuten** starten.\n"
            f"Startfenster endet um: <t:{int(deadline.timestamp())}:T>\n"
            f"Noch verbleibend: <t:{int(deadline.timestamp())}:R>\n\n"
            f"**Hinweis:** Nach dem Klick auf **Start** läuft deine Zeit ohne Live-Anzeige im Discord weiter."
        )

        view = QualiStartView(self, state)

        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

        state.timeout_task = asyncio.create_task(self.seed_start_timeout(state))

    async def start_race(self, interaction: discord.Interaction, state: QualiRunState):
        if state.finished:
            await interaction.response.send_message("Diese Quali ist bereits abgeschlossen.", ephemeral=True)
            return

        if state.cancelled:
            await interaction.response.send_message("Diese Quali wurde bereits abgebrochen.", ephemeral=True)
            return

        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        if state.seed_shown_at is None:
            await interaction.response.send_message("Du musst zuerst den Seed öffnen.", ephemeral=True)
            return

        if state.started_at is not None:
            await interaction.response.send_message("Das Race wurde bereits gestartet.", ephemeral=True)
            return

        limit = state.seed_shown_at + timedelta(minutes=5)
        if dt.utcnow() > limit:
            await interaction.response.send_message(
                "Das Startfenster ist bereits abgelaufen. Du erhältst ein FF.",
                ephemeral=True
            )
            return

        state.started_at = dt.utcnow()
        state.locked_final_time = None

        if state.timeout_task:
            state.timeout_task.cancel()
            state.timeout_task = None

        content = (
            f"**Quali {state.quali_number} läuft**\n\n"
            f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n"
            f"Deine Zeit läuft jetzt.\n\n"
            f"**Wichtig:** Discord zeigt keinen Live-Timer an.\n"
            f"Nutze deinen eigenen Timer bzw. deine Aufnahme als Referenz.\n\n"
            f"Drücke am Ende **Finish** oder **Forfeit**."
        )

        view = QualiRunningView(self, state)

        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

    async def seed_start_timeout(self, state: QualiRunState):
        try:
            await asyncio.sleep(300)

            if state.finished or state.cancelled or state.started_at is not None:
                return

            ws = await asyncio.to_thread(get_quali_worksheet)
            status = await asyncio.to_thread(read_runner_status, ws, state.runner_name)

            if state.quali_number == 1 and status["q1_done"]:
                self.active_runs.pop(state.user_id, None)
                return

            if state.quali_number == 2 and status["q2_done"]:
                self.active_runs.pop(state.user_id, None)
                return

            await asyncio.to_thread(
                write_quali_result,
                ws,
                state.runner_name,
                state.quali_number,
                "DNF",
                "03:00:00"
            )

            total_played, rank = await asyncio.to_thread(
                get_quali_stats_for_runner,
                ws,
                state.runner_name,
                state.quali_number
            )

            state.finished = True
            state.finished_at = dt.utcnow()
            state.locked_final_time = "03:00:00"
            self.stop_state_tasks(state)
            self.active_runs.pop(state.user_id, None)

            place_text = f"Platz: **{rank}/{total_played}**" if rank is not None else "Platz aktuell nicht verfügbar."

            if state.message:
                try:
                    await state.message.edit(
                        content=(
                            f"**Quali {state.quali_number} beendet**\n"
                            f"Startfenster überschritten.\n"
                            f"Ergebnis: **DNF / 03:00:00**\n"
                            f"Bereits gespielt: **{total_played}**\n"
                            f"{place_text}"
                        ),
                        view=None
                    )
                except Exception:
                    pass

        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def stop_state_tasks(self, state: QualiRunState):
        task = state.timeout_task
        if task and not task.done():
            task.cancel()
        state.timeout_task = None


# =========================================================
# SETUP
# =========================================================

async def setup(bot):
    await bot.add_cog(QualiCog(bot))

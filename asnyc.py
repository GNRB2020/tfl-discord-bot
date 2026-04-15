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
        self.update_task: asyncio.Task | None = None
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

            self.state.finished = True
            self.state.finished_at = dt.utcnow()
            self.cog.stop_state_tasks(self.state)
            self.cog.active_runs.pop(self.state.user_id, None)

            await interaction.followup.send(
                f"Ergebnis gespeichert.\n"
                f"Runner: **{runner_name}**\n"
                f"Quali: **{self.state.quali_number}**\n"
                f"Zeile: **{row_idx}**\n"
                f"Eintrag: **{async_value}**\n"
                f"Zeit: **{final_time}**",
                ephemeral=True
            )

            if self.state.message:
                try:
                    await self.state.message.edit(
                        content=(
                            f"**Quali {self.state.quali_number} abgeschlossen**\n"
                            f"Eintrag: **{async_value}**\n"
                            f"Zeit: **{final_time}**"
                        ),
                        view=None
                    )
                except Exception as e:
                    print(f"[QualiSubmitModal.message.edit] Fehler: {e}")

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
            except Exception as inner_e:
                print(f"[QualiSubmitModal.on_submit] Folgefehler: {inner_e}")


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
                f"Quali 2: {'bereits gespielt' if status['q2_done'] else 'offen'}"
            )

            await interaction.followup.send(text, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler bei /quali: {e}",
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
            except Exception as e:
                print(f"[qualireset.message.edit] Fehler: {e}")

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
                f"Mit Klick auf **Seed öffnen** erhältst du den Link zum Quali-Seed und ein Timer, "
                f"der von 5 Minuten runterzählt erscheint. Innerhalb dieser 5 Minuten musst du den Seed starten. "
                f"Bei Überschreiten dieser Zeit erhältst du ein FF und **03:00:00** als Ergebnis für das Race.\n\n"
                f"Drücke also erst auf **Seed öffnen**, wenn du wirklich bereit bist.\n\n"
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
            f"Noch verbleibend: <t:{int(deadline.timestamp())}:R>"
        )

        view = QualiStartView(self, state)

        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

        state.update_task = asyncio.create_task(self.seed_countdown_updater(state))
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

        if state.update_task:
            state.update_task.cancel()
            state.update_task = None

        content = (
            f"**Quali {state.quali_number} läuft**\n\n"
            f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n"
            f"Laufzeit: **00:00:00**\n\n"
            f"Drücke **Finish** oder **Forfeit**."
        )

        view = QualiRunningView(self, state)

        await interaction.response.edit_message(content=content, view=view)
        state.message = await interaction.original_response()

        state.update_task = asyncio.create_task(self.race_timer_updater(state))

    async def seed_countdown_updater(self, state: QualiRunState):
        try:
            while (
                not state.finished
                and not state.cancelled
                and state.seed_shown_at
                and state.started_at is None
                and state.message
            ):
                deadline = state.seed_shown_at + timedelta(minutes=5)
                remaining = int((deadline - dt.utcnow()).total_seconds())
                if remaining < 0:
                    remaining = 0

                content = (
                    f"**Quali {state.quali_number} – Seed geöffnet**\n\n"
                    f"Seed-Link: {state.seed_url}\n\n"
                    f"Startfenster endet um: <t:{int(deadline.timestamp())}:T>\n"
                    f"Verbleibend: **{format_seconds_to_hms(remaining)}**"
                )

                await state.message.edit(content=content)
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[seed_countdown_updater] Fehler: {e}")

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

            state.finished = True
            state.finished_at = dt.utcnow()
            state.locked_final_time = "03:00:00"
            self.stop_state_tasks(state)
            self.active_runs.pop(state.user_id, None)

            if state.message:
                try:
                    await state.message.edit(
                        content=(
                            f"**Quali {state.quali_number} beendet**\n"
                            f"Startfenster überschritten.\n"
                            f"Ergebnis: **DNF / 03:00:00**"
                        ),
                        view=None
                    )
                except Exception as e:
                    print(f"[seed_start_timeout.message.edit] Fehler: {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[seed_start_timeout] Fehler: {e}")

    async def race_timer_updater(self, state: QualiRunState):
        try:
            while not state.finished and not state.cancelled and state.started_at and state.message:
                runtime = state.measured_time()

                content = (
                    f"**Quali {state.quali_number} läuft**\n\n"
                    f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n"
                    f"Laufzeit: **{runtime}**\n\n"
                    f"Drücke **Finish** oder **Forfeit**."
                )

                await state.message.edit(content=content)
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[race_timer_updater] Fehler: {e}")

    def stop_state_tasks(self, state: QualiRunState):
        for task in (state.update_task, state.timeout_task):
            if task and not task.done():
                task.cancel()
        state.update_task = None
        state.timeout_task = None


# =========================================================
# SETUP
# =========================================================

async def setup(bot):
    await bot.add_cog(QualiCog(bot))

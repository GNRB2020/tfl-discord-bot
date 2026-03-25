import asyncio
import re
from datetime import datetime as dt, timedelta

import discord
from discord import app_commands
from discord.ext import commands

# =========================================================
# KONFIG
# =========================================================

GUILD_ID = 1275076189173579846  
QUALI1_SEED_URL = "https://dein-link-fuer-quali-1-seed"
QUALI2_SEED_URL = "https://dein-link-fuer-quali-2-seed"
QUALI_SHEET_NAME = "Quali"  # Name des Tabellenblatts, falls benötigt

# Spalten:
# B = Discordname
# D = Quali1 VoD
# E = Quali1 Zeit
# F = Quali2 VoD
# G = Quali2 Zeit
START_ROW = 4

TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")


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
# SHEET-HILFSFUNKTIONEN
# =========================================================

def get_quali_worksheet():
    """
    Passe diese Funktion an deinen vorhandenen Sheet-Code an.
    Falls du schon get_worksheet() hast und das richtige Blatt zurückkommt,
    ersetze den Inhalt einfach durch:
        return get_worksheet()
    """
    ws = get_worksheet()  # bestehende Funktion aus deinem Bot
    # Wenn dein get_worksheet() bereits das richtige Blatt liefert, reicht das.
    return ws


def find_existing_runner_row(ws, runner_name: str):
    """
    Sucht ab Zeile 4 in Spalte B nach dem Runner.
    """
    all_values = ws.get_all_values()

    for row_idx in range(START_ROW, len(all_values) + 1):
        row = all_values[row_idx - 1]
        name_in_b = safe_cell(row, 1)  # B
        if name_in_b.lower() == runner_name.lower():
            return row_idx

    return None


def find_first_free_row(ws):
    """
    Erste freie Zeile ab START_ROW in Spalte B.
    """
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
    """
    Liefert Status für Quali 1 und Quali 2.
    completed = Zeit oder VoD vorhanden
    """
    row_idx = find_existing_runner_row(ws, runner_name)
    if row_idx is None:
        return {
            "row": None,
            "q1_done": False,
            "q2_done": False,
            "q1_vod": "",
            "q1_time": "",
            "q2_vod": "",
            "q2_time": "",
        }

    row = ws.row_values(row_idx)

    q1_vod = safe_cell(row, 3)   # D
    q1_time = safe_cell(row, 4)  # E
    q2_vod = safe_cell(row, 5)   # F
    q2_time = safe_cell(row, 6)  # G

    return {
        "row": row_idx,
        "q1_done": is_filled(q1_vod) or is_filled(q1_time),
        "q2_done": is_filled(q2_vod) or is_filled(q2_time),
        "q1_vod": q1_vod,
        "q1_time": q1_time,
        "q2_vod": q2_vod,
        "q2_time": q2_time,
    }


def write_quali_result(ws, runner_name: str, quali_number: int, vod_link: str, race_time: str):
    row_idx = get_or_create_runner_row(ws, runner_name)

    if quali_number == 1:
        ws.update(f"D{row_idx}:E{row_idx}", [[vod_link, race_time]])
    elif quali_number == 2:
        ws.update(f"F{row_idx}:G{row_idx}", [[vod_link, race_time]])
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

        self.seed_shown_at: dt | None = None
        self.started_at: dt | None = None
        self.finished = False

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


# =========================================================
# MODAL
# =========================================================

class QualiSubmitModal(discord.ui.Modal):
    def __init__(self, cog, state: QualiRunState, forced_time: str | None = None, forfeit: bool = False):
        super().__init__(title=f"Quali {state.quali_number} Ergebnis")
        self.cog = cog
        self.state = state
        self.forfeit = forfeit

        computed = forced_time if forced_time else state.measured_time()

        self.time_input = discord.ui.TextInput(
            label="Deine Zeit (HH:MM:SS)",
            placeholder="z. B. 00:37:12",
            required=True,
            default=computed,
            max_length=8
        )
        self.vod_input = discord.ui.TextInput(
            label="VoD-Link",
            placeholder="https://...",
            required=True
        )

        self.add_item(self.time_input)
        self.add_item(self.vod_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            runner_name = self.state.runner_name
            ws = get_quali_worksheet()

            vod_link = str(self.vod_input.value).strip()

            if self.forfeit:
                final_time = "03:00:00"
            else:
                entered_time = normalize_hms(str(self.time_input.value))
                computed_time = self.state.measured_time()

                # Hier bewusst: gemessene Zeit ist maßgeblich.
                # Das Pflichtfeld "Zeit" bleibt trotzdem erhalten.
                # Wenn du stattdessen die eingetragene Zeit schreiben willst:
                # final_time = entered_time
                final_time = computed_time

            status = read_runner_status(ws, runner_name)

            if self.state.quali_number == 1 and status["q1_done"]:
                await interaction.response.send_message(
                    "Quali 1 ist für dich bereits eingetragen.",
                    ephemeral=True
                )
                return

            if self.state.quali_number == 2 and status["q2_done"]:
                await interaction.response.send_message(
                    "Quali 2 ist für dich bereits eingetragen.",
                    ephemeral=True
                )
                return

            row_idx = write_quali_result(
                ws=ws,
                runner_name=runner_name,
                quali_number=self.state.quali_number,
                vod_link=vod_link,
                race_time=final_time
            )

            self.state.finished = True
            self.cog.stop_state_tasks(self.state)
            self.cog.active_runs.pop(self.state.user_id, None)

            await interaction.response.send_message(
                f"Ergebnis gespeichert.\n"
                f"Runner: **{runner_name}**\n"
                f"Quali: **{self.state.quali_number}**\n"
                f"Zeile: **{row_idx}**\n"
                f"Zeit: **{final_time}**",
                ephemeral=True
            )

            if self.state.message:
                try:
                    await self.state.message.edit(
                        content=(
                            f"**Quali {self.state.quali_number} abgeschlossen**\n"
                            f"Zeit: **{final_time}**\n"
                            f"VoD: {vod_link}"
                        ),
                        view=None
                    )
                except Exception:
                    pass

        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Speichern: {e}",
                ephemeral=True
            )


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

    @discord.ui.button(label="Seed 1", style=discord.ButtonStyle.success, custom_id="quali_seed_1")
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

        self.cog.stop_state_tasks(self.state)
        modal = QualiSubmitModal(self.cog, self.state, forfeit=False)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, custom_id="quali_forfeit")
    async def forfeit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state.finished:
            await interaction.response.send_message("Diese Quali ist bereits abgeschlossen.", ephemeral=True)
            return

        self.cog.stop_state_tasks(self.state)
        modal = QualiSubmitModal(self.cog, self.state, forced_time="03:00:00", forfeit=True)
        await interaction.response.send_modal(modal)


# =========================================================
# COG
# =========================================================

class QualiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_runs: dict[int, QualiRunState] = {}

    # -----------------------------------------------------
    # Slash Command
    # -----------------------------------------------------
    @app_commands.command(
        name="quali",
        description="Startet die Qualifikationsauswahl."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def quali(self, interaction: discord.Interaction):
        try:
            runner_name = get_runner_name(interaction)
            ws = get_quali_worksheet()
            status = read_runner_status(ws, runner_name)

            active = self.active_runs.get(interaction.user.id)
            if active and not active.finished:
                await interaction.response.send_message(
                    f"Du hast bereits eine laufende Quali {active.quali_number}.",
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

            await interaction.response.send_message(text, view=view, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"Fehler bei /quali: {e}",
                ephemeral=True
            )

    # -----------------------------------------------------
    # Flow
    # -----------------------------------------------------
    async def open_quali_info(self, interaction: discord.Interaction, quali_number: int):
        runner_name = get_runner_name(interaction)
        ws = get_quali_worksheet()
        status = read_runner_status(ws, runner_name)

        if quali_number == 1 and status["q1_done"]:
            await interaction.response.send_message("Quali 1 ist für dich bereits eingetragen.", ephemeral=True)
            return

        if quali_number == 2 and status["q2_done"]:
            await interaction.response.send_message("Quali 2 ist für dich bereits eingetragen.", ephemeral=True)
            return

        active = self.active_runs.get(interaction.user.id)
        if active and not active.finished:
            await interaction.response.send_message(
                f"Du hast bereits eine laufende Quali {active.quali_number}.",
                ephemeral=True
            )
            return

        seed_url = QUALI1_SEED_URL if quali_number == 1 else QUALI2_SEED_URL
        state = QualiRunState(
            user_id=interaction.user.id,
            runner_name=runner_name,
            quali_number=quali_number,
            seed_url=seed_url
        )
        self.active_runs[interaction.user.id] = state

        hint_text = (
            f"**Quali {quali_number}**\n\n"
            f"Mit Klick auf **Seed** erhältst du den Link zum ersten Quali-Seed und ein Timer, "
            f"der von 5 Minuten runterzählt erscheint. Innerhalb dieser 5 Minuten musst du den Seed starten. "
            f"Bei Überschreiten dieser Zeit erhältst du ein FF und **03:00:00** als Ergebnis für das Race.\n\n"
            f"Drücke also erst auf **Seed**, wenn du wirklich bereit bist.\n\n"
            f"Achte bei deiner Aufnahme darauf, dass dein Timer durchgehend zu sehen ist und lasse den Endscreen "
            f"bis zum Ende durchlaufen."
        )

        view = QualiSeedView(self, state)

        await interaction.response.send_message(hint_text, view=view, ephemeral=True)
        state.message = await interaction.original_response()

    async def reveal_seed(self, interaction: discord.Interaction, state: QualiRunState):
        if state.finished:
            await interaction.response.send_message("Diese Quali ist bereits abgeschlossen.", ephemeral=True)
            return

        if state.seed_shown_at is not None:
            await interaction.response.send_message("Der Seed wurde bereits geöffnet.", ephemeral=True)
            return

        if interaction.user.id != state.user_id:
            await interaction.response.send_message("Das ist nicht deine Quali.", ephemeral=True)
            return

        state.seed_shown_at = dt.utcnow()

        content = (
            f"**Quali {state.quali_number} – Seed geöffnet**\n\n"
            f"Seed-Link: {state.seed_url}\n\n"
            f"Du musst innerhalb von **5 Minuten** starten.\n"
            f"Startfenster endet um: <t:{int((state.seed_shown_at + timedelta(minutes=5)).timestamp())}:T>\n"
            f"Noch verbleibend: <t:{int((state.seed_shown_at + timedelta(minutes=5)).timestamp())}:R>"
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

    # -----------------------------------------------------
    # Timer / Auto-FF
    # -----------------------------------------------------
    async def seed_countdown_updater(self, state: QualiRunState):
        try:
            while not state.finished and state.seed_shown_at and state.started_at is None and state.message:
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

                await state.message.edit(content=content, view=QualiStartView(self, state))
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def seed_start_timeout(self, state: QualiRunState):
        try:
            await asyncio.sleep(300)

            if state.finished or state.started_at is not None:
                return

            ws = get_quali_worksheet()
            status = read_runner_status(ws, state.runner_name)

            if state.quali_number == 1 and status["q1_done"]:
                self.active_runs.pop(state.user_id, None)
                return

            if state.quali_number == 2 and status["q2_done"]:
                self.active_runs.pop(state.user_id, None)
                return

            write_quali_result(
                ws=ws,
                runner_name=state.runner_name,
                quali_number=state.quali_number,
                vod_link="TIMEOUT - kein VOD",
                race_time="03:00:00"
            )

            state.finished = True
            self.stop_state_tasks(state)
            self.active_runs.pop(state.user_id, None)

            if state.message:
                try:
                    await state.message.edit(
                        content=(
                            f"**Quali {state.quali_number} beendet**\n"
                            f"Startfenster überschritten.\n"
                            f"Ergebnis: **FF / 03:00:00**"
                        ),
                        view=None
                    )
                except Exception:
                    pass

        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def race_timer_updater(self, state: QualiRunState):
        try:
            while not state.finished and state.started_at and state.message:
                runtime = state.measured_time()

                content = (
                    f"**Quali {state.quali_number} läuft**\n\n"
                    f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n"
                    f"Laufzeit: **{runtime}**\n\n"
                    f"Drücke **Finish** oder **Forfeit**."
                )

                await state.message.edit(content=content, view=QualiRunningView(self, state))
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

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

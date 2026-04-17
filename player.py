import os
import re
import asyncio
import gspread
import discord
from datetime import datetime as dt, timedelta
from discord import app_commands
from discord.ext import commands
from oauth2client.service_account import ServiceAccountCredentials

from signup import (
    get_signup_status_text_for_member,
    get_league_signup_text,
    get_cup_signup_text,
)

from asnyc import (
    get_quali_worksheet,
    get_quali_stats_for_runner,
    get_overall_stats_for_runner,
)

from restinfo import (
    list_rest_players,
    format_restprogramm_text,
    get_open_restprogramm_text_for_name_candidates,
)

from streichinfo import (
    format_streichungen_text,
    get_own_division_streich_text,
)

from plan import (
    PlanMenuView,
    get_member_name_candidates,
    normalize_name,
)

from asyncplan import (
    collect_requestable_matches_for_member,
    AsyncRequestMatchListView,
)

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
TFL_ROLE_ID = int(os.getenv("TFL_ROLE_ID", "0"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "1275077562984435853"))

LOG_CHANNEL_ID = 1494265084208222208
ASYNC_WORKSHEET_GID = 539808866
TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")

CREDS_FILE = (
    os.getenv("GOOGLE_CREDENTIALS_FILE")
    or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    or "credentials.json"
).strip()
SPREADSHEET_ID = "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8"
ASYNC_START_TIMEOUT_SECONDS = 5 * 60


# =========================================================
# Hilfsfunktionen
# =========================================================
def has_admin_role(member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if ADMIN_ROLE_ID == 0:
        return False
    return any(r.id == ADMIN_ROLE_ID for r in member.roles)


def has_tfl_role(member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if TFL_ROLE_ID == 0:
        return False
    return any(r.id == TFL_ROLE_ID for r in member.roles)


async def build_quali_info_text(member: discord.Member, quali_number: int) -> str:
    runner_name = member.display_name.strip()
    ws = await asyncio.to_thread(get_quali_worksheet)
    total_played, rank = await asyncio.to_thread(
        get_quali_stats_for_runner,
        ws,
        runner_name,
        quali_number
    )

    if rank is None:
        return (
            f"**Stand Quali {quali_number}**\n\n"
            f"Bereits gespielt: **{total_played}**\n"
            f"Du hast Quali {quali_number} aktuell noch nicht abgeschlossen."
        )

    return (
        f"**Stand Quali {quali_number}**\n\n"
        f"Bereits gespielt: **{total_played}**\n"
        f"Dein aktueller Platz: **{rank}/{total_played}**"
    )


async def build_quali_overall_text(member: discord.Member) -> str:
    runner_name = member.display_name.strip()
    ws = await asyncio.to_thread(get_quali_worksheet)
    total_completed, rank = await asyncio.to_thread(
        get_overall_stats_for_runner,
        ws,
        runner_name
    )

    if rank is None:
        return (
            f"**Gesamtstand**\n\n"
            f"Beide Qualis abgeschlossen: **{total_completed}**\n"
            f"Du bist aktuell noch nicht im Gesamtstand, weil dir mindestens eine Quali fehlt."
        )

    return (
        f"**Gesamtstand**\n\n"
        f"Beide Qualis abgeschlossen: **{total_completed}**\n"
        f"Dein aktueller Platz: **{rank}/{total_completed}**"
    )


def format_seconds_to_hms(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def parse_hms_to_seconds(value: str) -> int:
    h, m, s = map(int, value.split(":"))
    return h * 3600 + m * 60 + s


def safe_cell(values, idx: int) -> str:
    if idx < len(values):
        return str(values[idx]).strip()
    return ""


def is_filled(value) -> bool:
    return str(value).strip() != ""


def safe_time_to_seconds(value: str):
    value = str(value).strip()
    if not value or not TIME_RE.match(value):
        return None
    try:
        return parse_hms_to_seconds(value)
    except Exception:
        return None


def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    return gspread.authorize(creds)


def get_async_worksheet():
    client = get_gspread_client()
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.get_worksheet_by_id(ASYNC_WORKSHEET_GID)


def collect_playable_async_matches_for_member(name_candidates: list[str]) -> list[dict]:
    ws = get_async_worksheet()
    rows = ws.get_all_values()
    targets = {normalize_name(x) for x in name_candidates if x}
    out = []

    for row_idx, row in enumerate(rows, start=1):
        if row_idx == 1:
            continue

        player1 = safe_cell(row, 1)   # B
        vod1 = safe_cell(row, 3)      # D
        time1 = safe_cell(row, 4)     # E
        player2 = safe_cell(row, 5)   # F
        vod2 = safe_cell(row, 6)      # G
        time2 = safe_cell(row, 7)     # H
        seed_url = safe_cell(row, 8)  # I

        if not player1 or not player2 or not seed_url:
            continue

        p1_match = normalize_name(player1) in targets
        p2_match = normalize_name(player2) in targets

        if not p1_match and not p2_match:
            continue

        if p1_match:
            already_played = is_filled(vod1) or is_filled(time1)
            requester_side = 1
        else:
            already_played = is_filled(vod2) or is_filled(time2)
            requester_side = 2

        if already_played:
            continue

        out.append({
            "row_index": row_idx,
            "player1": player1,
            "player2": player2,
            "vod1": vod1,
            "time1": time1,
            "vod2": vod2,
            "time2": time2,
            "seed_url": seed_url,
            "requester_side": requester_side,
            "label": f"{player1} vs. {player2}",
        })

    return out[:25]


def read_async_match_by_row(row_idx: int) -> dict:
    ws = get_async_worksheet()
    row = ws.row_values(row_idx)

    return {
        "row_index": row_idx,
        "player1": safe_cell(row, 1),   # B
        "vod1": safe_cell(row, 3),      # D
        "time1": safe_cell(row, 4),     # E
        "player2": safe_cell(row, 5),   # F
        "vod2": safe_cell(row, 6),      # G
        "time2": safe_cell(row, 7),     # H
        "seed_url": safe_cell(row, 8),  # I
    }


def write_async_result(row_idx: int, side: int, vod_value: str, race_time: str):
    ws = get_async_worksheet()

    if side == 1:
        ws.update(f"D{row_idx}:E{row_idx}", [[vod_value, race_time]])
    elif side == 2:
        ws.update(f"G{row_idx}:H{row_idx}", [[vod_value, race_time]])
    else:
        raise ValueError("Ungültige Seite.")

    return read_async_match_by_row(row_idx)


def get_async_side_state(match_data: dict, side: int) -> tuple[str, str]:
    if side == 1:
        return match_data["vod1"], match_data["time1"]
    return match_data["vod2"], match_data["time2"]


def get_async_opponent_side(side: int) -> int:
    return 2 if side == 1 else 1


# =========================================================
# Basis-View
# =========================================================
class PlayerBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Dieses Menü gehört nicht dir.",
                ephemeral=True
            )
            return False
        return True


# =========================================================
# Allgemeine Detailansicht mit Zurück
# =========================================================
class PlaceholderView(PlayerBaseView):
    def __init__(self, owner_id: int, back_view: discord.ui.View, back_content: str):
        super().__init__(owner_id)
        self.back_view = back_view
        self.back_content = back_content

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.back_content,
            view=self.back_view
        )


# =========================================================
# Ergebnis melden
# =========================================================
class ResultMenuView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.invoke_named_app_command(interaction, "result")

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.invoke_named_app_command(interaction, "cupresult")

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Async-Races State
# =========================================================
class AsyncRunState:
    def __init__(
        self,
        user_id: int,
        row_index: int,
        requester_side: int,
        player1: str,
        player2: str,
        seed_url: str,
    ):
        self.user_id = user_id
        self.row_index = row_index
        self.requester_side = requester_side
        self.player1 = player1
        self.player2 = player2
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

    @property
    def requester_name(self) -> str:
        return self.player1 if self.requester_side == 1 else self.player2

    @property
    def opponent_name(self) -> str:
        return self.player2 if self.requester_side == 1 else self.player1

    def measured_time(self) -> str:
        if not self.started_at:
            return "00:00:00"
        seconds = int((dt.utcnow() - self.started_at).total_seconds())
        if seconds < 0:
            seconds = 0
        return format_seconds_to_hms(seconds)


# =========================================================
# Async spielen
# =========================================================
class AsyncPlaySelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        self.matches = {str(i): m for i, m in enumerate(matches)}

        options = [
            discord.SelectOption(label=m["label"][:100], value=str(i))
            for i, m in enumerate(matches[:25])
        ]

        super().__init__(
            placeholder="Async-Spiel auswählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AsyncPlaySelectView):
            return

        view.selected_match = self.matches[self.values[0]]

        await interaction.response.edit_message(
            content=(
                "**Spielermenü → Async-Races → Async spielen**\n"
                f"Ausgewählt: **{view.selected_match['player1']} vs. {view.selected_match['player2']}**\n\n"
                "Bestätige mit **Spielen**."
            ),
            view=view
        )


class AsyncPlaySelectView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog", matches: list[dict]):
        super().__init__(owner_id, timeout=300)
        self.cog = cog
        self.matches = matches
        self.selected_match: dict | None = None
        self.add_item(AsyncPlaySelect(matches))

    @discord.ui.button(label="Spielen", style=discord.ButtonStyle.success, row=1)
    async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_match:
            await interaction.response.send_message("Bitte zuerst ein Async-Spiel auswählen.", ephemeral=True)
            return

        active = self.cog.active_async_runs.get(interaction.user.id)
        if active and not active.finished:
            await interaction.response.send_message(
                "Du hast bereits ein laufendes Async.",
                ephemeral=True
            )
            return

        state = AsyncRunState(
            user_id=interaction.user.id,
            row_index=self.selected_match["row_index"],
            requester_side=self.selected_match["requester_side"],
            player1=self.selected_match["player1"],
            player2=self.selected_match["player2"],
            seed_url=self.selected_match["seed_url"],
        )
        self.cog.active_async_runs[interaction.user.id] = state

        hint_text = (
            f"**Async spielen**\n\n"
            f"Spiel: **{state.player1} vs. {state.player2}**\n\n"
            f"Wenn du auf **Zum Seed** klickst, hast du **5 Minuten** Zeit zum Starten.\n"
            f"Bereite dein Setup also vor, bevor du zum Seed gehst."
        )

        view = AsyncSeedView(owner_id=interaction.user.id, cog=self.cog, state=state)

        await interaction.response.edit_message(content=hint_text, view=view)
        state.message = await interaction.original_response()

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Async-Races**\nWähle einen Bereich:",
            view=AsyncRacesView(owner_id=interaction.user.id, cog=self.cog)
        )


class AsyncSeedView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog", state: AsyncRunState):
        super().__init__(owner_id, timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Zum Seed", style=discord.ButtonStyle.primary, row=0)
    async def seed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.state

        if state.finished:
            await interaction.response.send_message("Dieses Async wurde bereits abgeschlossen.", ephemeral=True)
            return

        if state.cancelled:
            await interaction.response.send_message("Dieses Async wurde bereits abgebrochen.", ephemeral=True)
            return

        if state.seed_shown_at is not None:
            await interaction.response.send_message("Der Seed wurde bereits geöffnet.", ephemeral=True)
            return

        state.seed_shown_at = dt.utcnow()
        deadline = state.seed_shown_at + timedelta(seconds=ASYNC_START_TIMEOUT_SECONDS)

        content = (
            f"**Async spielen – Seed geöffnet**\n\n"
            f"Spiel: **{state.player1} vs. {state.player2}**\n"
            f"Seed-Link: {state.seed_url}\n\n"
            f"Du musst innerhalb von **5 Minuten** starten.\n"
            f"Startfenster endet um: <t:{int(deadline.timestamp())}:T>\n"
            f"Noch verbleibend: <t:{int(deadline.timestamp())}:R>"
        )

        await interaction.response.edit_message(
            content=content,
            view=AsyncStartView(owner_id=interaction.user.id, cog=self.cog, state=state)
        )
        state.message = await interaction.original_response()
        state.timeout_task = asyncio.create_task(self.cog.async_seed_start_timeout(state))


class AsyncStartView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog", state: AsyncRunState):
        super().__init__(owner_id, timeout=300)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, row=0)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.state

        if state.finished:
            await interaction.response.send_message("Dieses Async wurde bereits abgeschlossen.", ephemeral=True)
            return

        if state.seed_shown_at is None:
            await interaction.response.send_message("Du musst zuerst den Seed öffnen.", ephemeral=True)
            return

        limit = state.seed_shown_at + timedelta(seconds=ASYNC_START_TIMEOUT_SECONDS)
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

        await interaction.response.edit_message(
            content=(
                f"**Async läuft**\n\n"
                f"Spiel: **{state.player1} vs. {state.player2}**\n"
                f"Gestartet um: <t:{int(state.started_at.timestamp())}:T>\n\n"
                f"Drücke am Ende **Finish** oder **Forfeit**."
            ),
            view=AsyncRunningView(owner_id=interaction.user.id, cog=self.cog, state=state)
        )
        state.message = await interaction.original_response()


class AsyncSubmitModal(discord.ui.Modal):
    def __init__(self, cog: "PlayerCog", state: AsyncRunState, forfeit: bool = False):
        title = f"Async-Ergebnis · {state.locked_final_time or '00:00:00'}"
        super().__init__(title=title)
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
        await interaction.response.defer(ephemeral=True)

        state = self.state

        if self.forfeit:
            vod_value = "FF"
            final_time = "03:00:00"
        else:
            vod_value = str(self.vod_input.value).strip()
            if not vod_value:
                await interaction.followup.send("VoD-Link ist Pflicht.", ephemeral=True)
                return

            if not state.locked_final_time:
                await interaction.followup.send("Die Zielzeit konnte nicht gespeichert werden.", ephemeral=True)
                return

            final_time = state.locked_final_time

        match_after_write = await asyncio.to_thread(
            write_async_result,
            state.row_index,
            state.requester_side,
            vod_value,
            final_time
        )

        state.finished = True
        state.finished_at = dt.utcnow()
        self.cog.stop_async_state_tasks(state)
        self.cog.active_async_runs.pop(state.user_id, None)

        await self.cog.handle_async_finish(
            interaction=interaction,
            state=state,
            match_data=match_after_write,
            final_time=final_time,
            vod_value=vod_value
        )

        await interaction.followup.send(
            f"Ergebnis gespeichert.\n"
            f"Spiel: **{state.player1} vs. {state.player2}**\n"
            f"Zeit: **{final_time}**\n"
            f"VoD: **{vod_value}**",
            ephemeral=True
        )


class AsyncRunningView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog", state: AsyncRunState):
        super().__init__(owner_id, timeout=None)
        self.cog = cog
        self.state = state

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.success, row=0)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.locked_final_time = self.state.measured_time()
        self.cog.stop_async_state_tasks(self.state)
        await interaction.response.send_modal(AsyncSubmitModal(self.cog, self.state, forfeit=False))

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, row=0)
    async def forfeit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.locked_final_time = "03:00:00"
        self.cog.stop_async_state_tasks(self.state)
        await interaction.response.send_modal(AsyncSubmitModal(self.cog, self.state, forfeit=True))


class AsyncRejectModal(discord.ui.Modal, title="Ergebnis ablehnen"):
    reason = discord.ui.TextInput(
        label="Ablehnungsgrund",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    def __init__(self, cog: "PlayerCog", match_data: dict):
        super().__init__()
        self.cog = cog
        self.match_data = match_data

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "Nur die Spielleitung darf Ergebnisse ablehnen.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        await self.cog.notify_async_rejection(
            interaction.guild,
            self.match_data,
            str(self.reason).strip()
        )

        await interaction.followup.send("Ablehnungsgrund wurde an beide Runner verschickt.", ephemeral=True)


class AsyncResultReviewView(discord.ui.View):
    def __init__(self, cog: "PlayerCog", match_data: dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_data = match_data

    @discord.ui.button(label="Ergebnis bestätigen", style=discord.ButtonStyle.success, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "Nur die Spielleitung darf Ergebnisse bestätigen.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self.cog.confirm_async_result(interaction, self.match_data)
        await interaction.followup.send("Async-Ergebnis bestätigt.", ephemeral=True)

    @discord.ui.button(label="Ergebnis ablehnen", style=discord.ButtonStyle.danger, row=0)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "Nur die Spielleitung darf Ergebnisse ablehnen.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(AsyncRejectModal(self.cog, self.match_data))


# =========================================================
# Async-Races
# =========================================================
class AsyncRacesView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Async beantragen", style=discord.ButtonStyle.primary, row=0)
    async def async_request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            matches = await asyncio.to_thread(
                collect_requestable_matches_for_member,
                get_member_name_candidates(member),
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Laden der Spiele für Async: {e}",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=AsyncRacesView(owner_id=interaction.user.id, cog=self.cog),
                    back_content="**Spielermenü → Async-Races**\nWähle einen Bereich:",
                ),
            )
            return

        if not matches:
            await interaction.edit_original_response(
                content="**Spielermenü → Async-Races → Async beantragen**\nKeine offenen League- oder Cup-Spiele für dich gefunden.",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=AsyncRacesView(owner_id=interaction.user.id, cog=self.cog),
                    back_content="**Spielermenü → Async-Races**\nWähle einen Bereich:",
                ),
            )
            return

        await interaction.edit_original_response(
            content="**Spielermenü → Async-Races → Async beantragen**\nWähle ein Spiel:",
            view=AsyncRequestMatchListView(
                owner_id=interaction.user.id,
                matches=matches,
                requester_member=member,
            ),
        )

    @discord.ui.button(label="Async spielen", style=discord.ButtonStyle.success, row=0)
    async def async_play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.async_play_menu(interaction)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Hauptmenü
# =========================================================
class PlayerMenuView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Info", style=discord.ButtonStyle.secondary, row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Spiel planen", style=discord.ButtonStyle.primary, row=0)
    async def plan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spiel planen**\nWähle einen Bereich:",
            view=PlanMenuView(owner_id=interaction.user.id, player_cog=self.cog)
        )

    @discord.ui.button(label="Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Ergebnis melden**\nWähle einen Bereich:",
            view=ResultMenuView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.secondary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Qualifikation**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=PlayerMenuView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Async-Races", style=discord.ButtonStyle.primary, row=1)
    async def async_races_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Async-Races**\nWähle einen Bereich:",
            view=AsyncRacesView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Saisonmeldung", style=discord.ButtonStyle.secondary, row=2)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Saisonmeldung**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=PlayerMenuView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Einstellungen", style=discord.ButtonStyle.secondary, row=2)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Einstellungen**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=PlayerMenuView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )


# =========================================================
# Info-Menü
# =========================================================
class InfoMenuView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Meldestatus", style=discord.ButtonStyle.primary, row=0)
    async def meldestatus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Meldestatus**\nWähle einen Bereich:",
            view=MeldestatusView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.primary, row=0)
    async def qualifikation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Qualifikation**\nWähle einen Bereich:",
            view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Restprogramm", style=discord.ButtonStyle.primary, row=1)
    async def restprogramm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm**\nWähle einen Bereich:",
            view=RestprogrammView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Streichmodus", style=discord.ButtonStyle.primary, row=1)
    async def streichmodus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus**\nWähle einen Bereich:",
            view=StreichmodusView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Ergebnisse/Tabelle", style=discord.ButtonStyle.primary, row=2)
    async def ergebnisse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle**\nWähle eine Liga oder den Cup:",
            view=ErgebnisseTabelleView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Meldestatus
# =========================================================
class MeldestatusView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Meiner", style=discord.ButtonStyle.primary, row=0)
    async def meiner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = get_signup_status_text_for_member(member)
            except Exception as e:
                text = f"Fehler beim Abrufen deines Eintrags: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → Meiner**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = get_league_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der League-Anmeldungen: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → League**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = get_cup_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der Cup-Anmeldungen: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → Cup**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Info -> Qualifikation
# =========================================================
class InfoQualifikationView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Quali 1", style=discord.ButtonStyle.primary, row=0)
    async def quali1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                await interaction.response.defer()
                text = await build_quali_info_text(member, 1)
                await interaction.edit_original_response(
                    content=f"**Info → Qualifikation → Quali 1**\n{text}",
                    view=PlaceholderView(
                        owner_id=interaction.user.id,
                        back_view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog),
                        back_content="**Info → Qualifikation**\nWähle einen Bereich:"
                    )
                )
                return
            except Exception as e:
                text = f"Fehler bei Quali 1: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Qualifikation → Quali 1**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary, row=0)
    async def quali2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                await interaction.response.defer()
                text = await build_quali_info_text(member, 2)
                await interaction.edit_original_response(
                    content=f"**Info → Qualifikation → Quali 2**\n{text}",
                    view=PlaceholderView(
                        owner_id=interaction.user.id,
                        back_view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog),
                        back_content="**Info → Qualifikation**\nWähle einen Bereich:"
                    )
                )
                return
            except Exception as e:
                text = f"Fehler bei Quali 2: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Qualifikation → Quali 2**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Gesamt", style=discord.ButtonStyle.primary, row=0)
    async def gesamt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                await interaction.response.defer()
                text = await build_quali_overall_text(member)
                await interaction.edit_original_response(
                    content=f"**Info → Qualifikation → Gesamt**\n{text}",
                    view=PlaceholderView(
                        owner_id=interaction.user.id,
                        back_view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog),
                        back_content="**Info → Qualifikation**\nWähle einen Bereich:"
                    )
                )
                return
            except Exception as e:
                text = f"Fehler beim Gesamtstand: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Qualifikation → Gesamt**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Restprogramm - Andere
# =========================================================
class RestOtherPlayerSelect(discord.ui.Select):
    def __init__(self, division: str, players: list[str], owner_id: int, cog: "PlayerCog"):
        self.division = division
        self.owner_id = owner_id
        self.cog = cog

        options = [discord.SelectOption(label=p, value=p) for p in players[:25]]

        super().__init__(
            placeholder="Spieler wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        player = self.values[0]

        await interaction.response.defer()

        try:
            text = await asyncio.to_thread(format_restprogramm_text, self.division, player)
        except Exception as e:
            text = f"Fehler beim Ermitteln des Restprogramms: {e}"

        await interaction.edit_original_response(
            content=text,
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestOtherDivisionView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Restprogramm → Andere**\nWähle eine Division:"
            )
        )


class RestOtherPlayerView(PlayerBaseView):
    def __init__(self, owner_id: int, division: str, players: list[str], cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog
        self.add_item(RestOtherPlayerSelect(division, players, owner_id, cog))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            view=RestOtherDivisionView(owner_id=interaction.user.id, cog=self.cog)
        )


class RestOtherDivisionSelect(discord.ui.Select):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        self.owner_id = owner_id
        self.cog = cog
        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]
        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        await interaction.response.defer()

        try:
            players = await asyncio.to_thread(list_rest_players, div_number)
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Laden der Spieler für Division {div_number}: {e}",
                view=RestOtherDivisionView(owner_id=interaction.user.id, cog=self.cog)
            )
            return

        if not players:
            await interaction.edit_original_response(
                content=f"Keine Spieler in Division {div_number} für das Restprogramm gefunden.",
                view=RestOtherDivisionView(owner_id=interaction.user.id, cog=self.cog)
            )
            return

        await interaction.edit_original_response(
            content=f"**Info → Restprogramm → Andere**\nDivision {div_number} gewählt. Bitte Spieler wählen:",
            view=RestOtherPlayerView(
                owner_id=interaction.user.id,
                division=div_number,
                players=players,
                cog=self.cog
            )
        )


class RestOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog
        self.add_item(RestOtherDivisionSelect(owner_id, cog))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm**\nWähle einen Bereich:",
            view=RestprogrammView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Restprogramm
# =========================================================
class RestprogrammView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Eigenes", style=discord.ButtonStyle.primary, row=0)
    async def eigenes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                name_candidates = [
                    member.display_name,
                    getattr(member, "global_name", None),
                    member.name,
                ]
                text = await asyncio.to_thread(
                    get_open_restprogramm_text_for_name_candidates,
                    name_candidates
                )
            except Exception as e:
                text = f"Fehler beim Abrufen deines Restprogramms: {e}"

        await interaction.edit_original_response(
            content=f"**Info → Restprogramm → Eigenes**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestprogrammView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Restprogramm**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Andere", style=discord.ButtonStyle.primary, row=0)
    async def andere_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            view=RestOtherDivisionView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Streichmodus - Andere Divisionen
# =========================================================
class StreichOtherDivisionSelect(discord.ui.Select):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        self.owner_id = owner_id
        self.cog = cog
        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]
        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        await interaction.response.defer()

        try:
            text = await asyncio.to_thread(format_streichungen_text, div_number)
        except Exception as e:
            text = f"❌ Fehler beim Lesen der Streichungen aus Division {div_number}: {e}"

        await interaction.edit_original_response(
            content=text,
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichOtherDivisionView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Streichmodus → Andere Divisionen**\nWähle eine Division:"
            )
        )


class StreichOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog
        self.add_item(StreichOtherDivisionSelect(owner_id, cog))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus**\nWähle einen Bereich:",
            view=StreichmodusView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Streichmodus
# =========================================================
class StreichmodusView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

    @discord.ui.button(label="Eigene Division", style=discord.ButtonStyle.primary, row=0)
    async def eigene_division_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                name_candidates = [
                    member.display_name,
                    getattr(member, "global_name", None),
                    member.name,
                ]
                text = await asyncio.to_thread(
                    get_own_division_streich_text,
                    name_candidates
                )
            except Exception as e:
                text = f"Fehler beim Abrufen des Streichmodus: {e}"

        await interaction.edit_original_response(
            content=f"**Info → Streichmodus → Eigene Division**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichmodusView(owner_id=interaction.user.id, cog=self.cog),
                back_content="**Info → Streichmodus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Andere Divisionen", style=discord.ButtonStyle.primary, row=0)
    async def andere_divisionen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus → Andere Divisionen**\nWähle eine Division:",
            view=StreichOtherDivisionView(owner_id=interaction.user.id, cog=self.cog)
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Ergebnisse / Tabelle mit Browser-Links
# =========================================================
class ErgebnisseTabelleView(PlayerBaseView):
    def __init__(self, owner_id: int, cog: "PlayerCog"):
        super().__init__(owner_id)
        self.cog = cog

        self.add_item(discord.ui.Button(
            label="1. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division",
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="2. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division-2",
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="3. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division",
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="4. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-2",
            row=1
        ))
        self.add_item(discord.ui.Button(
            label="5. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-3",
            row=1
        ))
        self.add_item(discord.ui.Button(
            label="6. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-4",
            row=1
        ))
        self.add_item(discord.ui.Button(
            label="Cup",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/cup",
            row=2
        ))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id, cog=self.cog)
        )


# =========================================================
# Cog
# =========================================================
class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_async_runs: dict[int, AsyncRunState] = {}

    def _get_app_command(self, name: str):
        guild_obj = discord.Object(id=GUILD_ID)

        cmd = self.bot.tree.get_command(name, guild=guild_obj)
        if cmd is not None:
            return cmd

        return self.bot.tree.get_command(name)

    async def invoke_named_app_command(self, interaction: discord.Interaction, command_name: str):
        cmd = self._get_app_command(command_name)
        if cmd is None:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Command `/{command_name}` wurde nicht gefunden.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Command `/{command_name}` wurde nicht gefunden.",
                    ephemeral=True
                )
            return

        try:
            binding = getattr(cmd, "binding", None)

            if binding is not None:
                await cmd.callback(binding, interaction)
            else:
                await cmd.callback(interaction)

        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Fehler beim Öffnen von `/{command_name}`: {e}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Fehler beim Öffnen von `/{command_name}`: {e}",
                    ephemeral=True
                )

    def stop_async_state_tasks(self, state: AsyncRunState):
        task = state.timeout_task
        if task and not task.done():
            task.cancel()
        state.timeout_task = None

    async def resolve_member_by_name(self, guild: discord.Guild | None, name: str):
        if guild is None:
            return None

        target = normalize_name(name)

        for member in guild.members:
            candidates = [
                member.display_name,
                getattr(member, "global_name", None),
                member.name,
            ]
            if any(normalize_name(c or "") == target for c in candidates if c):
                return member

        return None

    async def async_play_menu(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            matches = await asyncio.to_thread(
                collect_playable_async_matches_for_member,
                get_member_name_candidates(member),
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Laden der Asyncs: {e}",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=AsyncRacesView(owner_id=interaction.user.id, cog=self),
                    back_content="**Spielermenü → Async-Races**\nWähle einen Bereich:"
                )
            )
            return

        if not matches:
            await interaction.edit_original_response(
                content="**Spielermenü → Async-Races → Async spielen**\nKeine genehmigten Asyncs für dich vorhanden.",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=AsyncRacesView(owner_id=interaction.user.id, cog=self),
                    back_content="**Spielermenü → Async-Races**\nWähle einen Bereich:"
                )
            )
            return

        await interaction.edit_original_response(
            content="**Spielermenü → Async-Races → Async spielen**\nWähle ein Spiel:",
            view=AsyncPlaySelectView(owner_id=interaction.user.id, cog=self, matches=matches)
        )

    async def async_seed_start_timeout(self, state: AsyncRunState):
        try:
            await asyncio.sleep(ASYNC_START_TIMEOUT_SECONDS)

            if state.finished or state.cancelled or state.started_at is not None:
                return

            match_after_write = await asyncio.to_thread(
                write_async_result,
                state.row_index,
                state.requester_side,
                "FF",
                "03:00:00"
            )

            state.finished = True
            state.finished_at = dt.utcnow()
            state.locked_final_time = "03:00:00"
            self.stop_async_state_tasks(state)
            self.active_async_runs.pop(state.user_id, None)

            await self.post_async_log_and_notifications(
                guild=None,
                match_data=match_after_write,
                finisher_name=state.requester_name,
                final_time="03:00:00",
                first_finish_hint=False
            )

            if state.message:
                try:
                    await state.message.edit(
                        content=(
                            f"**Async beendet**\n"
                            f"Spiel: **{state.player1} vs. {state.player2}**\n"
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

    async def handle_async_finish(
        self,
        interaction: discord.Interaction,
        state: AsyncRunState,
        match_data: dict,
        final_time: str,
        vod_value: str,
    ):
        other_side = get_async_opponent_side(state.requester_side)
        other_vod, other_time = get_async_side_state(match_data, other_side)
        other_pending = (not is_filled(other_vod)) and (not is_filled(other_time))
        first_finish_hint = other_pending

        if state.message:
            try:
                await state.message.edit(
                    content=(
                        f"**Async abgeschlossen**\n"
                        f"Spiel: **{state.player1} vs. {state.player2}**\n"
                        f"Zeit: **{final_time}**\n"
                        f"VoD: **{vod_value}**"
                    ),
                    view=None
                )
            except Exception:
                pass

        await self.post_async_log_and_notifications(
            guild=interaction.guild,
            match_data=match_data,
            finisher_name=state.requester_name,
            final_time=final_time,
            first_finish_hint=first_finish_hint
        )

        if not other_pending:
            await self.send_async_both_finished_dm(interaction.guild, match_data)

    async def post_async_log_and_notifications(
        self,
        guild: discord.Guild | None,
        match_data: dict,
        finisher_name: str,
        final_time: str,
        first_finish_hint: bool,
    ):
        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                channel = None

        player1 = match_data["player1"]
        player2 = match_data["player2"]
        vod1 = match_data["vod1"]
        time1 = match_data["time1"]
        vod2 = match_data["vod2"]
        time2 = match_data["time2"]

        both_done = is_filled(vod1) and is_filled(time1) and is_filled(vod2) and is_filled(time2)

        if channel:
            if both_done:
                await channel.send(
                    content=(
                        f"**{finisher_name}** hat den Async vom Spiel zwischen **{player1}** und **{player2}** "
                        f"mit einer Zeit von **{final_time}** beendet.\n"
                        f"Beide Runner sind fertig.\n"
                        f"**{player1}: {time1}**\n"
                        f"**{player2}: {time2}**"
                    ),
                    view=AsyncResultReviewView(self, match_data)
                )
            else:
                other_player = player2 if normalize_name(finisher_name) == normalize_name(player1) else player1
                await channel.send(
                    f"**{finisher_name}** hat den Async vom Spiel zwischen **{player1}** und **{player2}** "
                    f"mit einer Zeit von **{final_time}** beendet.\n"
                    f"**{other_player}** muss den Seed noch spielen."
                )

        opponent_name = player2 if normalize_name(finisher_name) == normalize_name(player1) else player1
        opponent_member = await self.resolve_member_by_name(guild, opponent_name)

        if opponent_member:
            msg = f"Dein Gegner **{finisher_name}** hat den Async für **{player1} vs. {player2}** beendet."
            if first_finish_hint:
                msg += "\nDu kannst den Seed jetzt auch im Stream spielen."
            try:
                await opponent_member.send(msg)
            except Exception:
                pass

    async def send_async_both_finished_dm(self, guild: discord.Guild | None, match_data: dict):
        player1_member = await self.resolve_member_by_name(guild, match_data["player1"])
        player2_member = await self.resolve_member_by_name(guild, match_data["player2"])

        text = (
            f"Der Async für **{match_data['player1']} vs. {match_data['player2']}** wurde von beiden Runnern abgeschlossen.\n\n"
            f"{match_data['player1']}: **{match_data['time1']}**\n"
            f"{match_data['player2']}: **{match_data['time2']}**\n\n"
            f"Dies ist nur ein vorläufiges Ergebnis und muss noch von der Spielleitung geprüft und bestätigt werden."
        )

        for member in [player1_member, player2_member]:
            if member:
                try:
                    await member.send(text)
                except Exception:
                    pass

    async def notify_async_rejection(self, guild: discord.Guild | None, match_data: dict, reason: str):
        members = [
            await self.resolve_member_by_name(guild, match_data["player1"]),
            await self.resolve_member_by_name(guild, match_data["player2"]),
        ]

        text = (
            f"Das Ergebnis für den Async **{match_data['player1']} vs. {match_data['player2']}** wurde abgelehnt.\n\n"
            f"Grund:\n{reason}"
        )

        for member in members:
            if member:
                try:
                    await member.send(text)
                except Exception:
                    pass

    async def confirm_async_result(self, interaction: discord.Interaction, match_data: dict):
        p1_seconds = safe_time_to_seconds(match_data["time1"])
        p2_seconds = safe_time_to_seconds(match_data["time2"])

        if p1_seconds is None or p2_seconds is None:
            await interaction.followup.send("Es liegen nicht für beide Runner gültige Zeiten vor.", ephemeral=True)
            return

        diff = abs(p1_seconds - p2_seconds)

        if diff <= 5:
            ergebnis = "1:1"
        elif p1_seconds < p2_seconds:
            ergebnis = "2:0"
        else:
            ergebnis = "0:2"

        channel = self.bot.get_channel(RESULTS_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(RESULTS_CHANNEL_ID)
            except Exception:
                channel = None

        if channel is None:
            await interaction.followup.send("Ergebnischannel nicht gefunden.", ephemeral=True)
            return

        now_str = dt.now().strftime("%d.%m.%Y %H:%M")
        out_lines = [
            f"**[Async]** {now_str}",
            f"**{match_data['player1']}** vs **{match_data['player2']}** → **{ergebnis}**",
            "Modus: Async",
            "Raceroom: Async Race",
        ]
        await channel.send("\n".join(out_lines))

    @app_commands.command(name="player", description="Öffnet das Spielermenü")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def player(self, interaction: discord.Interaction):
        view = PlayerMenuView(owner_id=interaction.user.id, cog=self)
        await interaction.response.send_message(
            "**Spielermenü**\nWähle einen Bereich:",
            view=view,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))

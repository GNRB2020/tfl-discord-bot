
import os
import asyncio
import re
from datetime import datetime as dt, timedelta

import discord
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from matchcenter import (
    get_div_ws_from_label,
    _cell,
    DIV_COL_LEFT,
    DIV_COL_MARKER,
    DIV_COL_RIGHT,
    get_runner_modes,
)
from schedule import load_open_matches as load_open_cup_matches

ADMIN_LOG_CHANNEL_ID = 1494265084208222208
ASYNC_SPREADSHEET_ID = "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8"
ASYNC_WORKSHEET_GID = 539808866
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")


def get_gspread_client() -> gspread.Client:
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    return gspread.authorize(creds)


def get_async_worksheet():
    client = get_gspread_client()
    spreadsheet = client.open_by_key(ASYNC_SPREADSHEET_ID)
    for ws in spreadsheet.worksheets():
        if ws.id == ASYNC_WORKSHEET_GID:
            return ws
    raise RuntimeError(f"Worksheet mit gid/id {ASYNC_WORKSHEET_GID} nicht gefunden.")


def append_async_row(home_player: str, guest_player: str, seed_link: str, mode: str = "") -> int:
    ws = get_async_worksheet()
    col_a = ws.col_values(1)
    row_index = 2
    while row_index <= len(col_a):
        if not (col_a[row_index - 1] or "").strip():
            break
        row_index += 1
    timestamp = dt.now().strftime("%d.%m.%Y %H:%M")
    ws.update(f"A{row_index}", [[timestamp]])
    ws.update(f"B{row_index}", [[home_player]])
    ws.update(f"F{row_index}", [[guest_player]])
    ws.update(f"I{row_index}", [[seed_link]])
    if mode:
        ws.update(f"M{row_index}", [[mode]])
    return row_index


def normalize_name(value: str) -> str:
    return ((value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", ""))


def format_seconds_to_hms(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def collect_requestable_matches_for_member(name_candidates: list[str]) -> list[dict]:
    targets = {normalize_name(x) for x in name_candidates if x}
    out = []
    for division_label in [f"Div {i}" for i in range(1, 7)]:
        ws = get_div_ws_from_label(division_label)
        rows = ws.get_all_values()
        for idx, row in enumerate(rows, start=1):
            if idx == 1:
                continue
            p1 = _cell(row, DIV_COL_LEFT - 1)
            marker = _cell(row, DIV_COL_MARKER - 1)
            p2 = _cell(row, DIV_COL_RIGHT - 1)
            if not p1 or not p2 or marker.lower() != "vs":
                continue
            if normalize_name(p1) not in targets and normalize_name(p2) not in targets:
                continue
            out.append({"kind": "league", "label": f"League | {division_label} | {p1} vs. {p2}", "division": division_label, "row_index": idx, "player1": p1, "player2": p2})
    for match in load_open_cup_matches():
        p1, p2 = match["player1"], match["player2"]
        if normalize_name(p1) not in targets and normalize_name(p2) not in targets:
            continue
        out.append({"kind": "cup", "label": f"Cup | {match['round']} | {p1} vs. {p2}", "round": match["round"], "row_index": match["row"], "player1": p1, "player2": p2})
    return out[:25]


def find_member_by_sheet_name(guild: discord.Guild, player_name: str) -> discord.Member | None:
    target = normalize_name(player_name)
    for member in guild.members:
        for cand in [member.display_name, getattr(member, "global_name", None), member.name]:
            if normalize_name(cand) == target:
                return member
    return None


def get_requester_vs_opponent(match_data: dict, requester_member: discord.Member) -> tuple[str, str]:
    requester_names = {normalize_name(requester_member.display_name), normalize_name(getattr(requester_member, "global_name", None)), normalize_name(requester_member.name)}
    p1, p2 = match_data["player1"], match_data["player2"]
    if normalize_name(p1) in requester_names:
        return p1, p2
    if normalize_name(p2) in requester_names:
        return p2, p1
    return p1, p2


def find_open_async_entries_for_name_candidates(name_candidates: list[str]) -> list[dict]:
    targets = {normalize_name(x) for x in name_candidates if x}
    ws = get_async_worksheet()
    rows = ws.get_all_values()
    results = []
    for idx, row in enumerate(rows[1:], start=2):
        p1 = _cell(row, 1)
        vod1 = _cell(row, 3)
        time1 = _cell(row, 4)
        p2 = _cell(row, 5)
        vod2 = _cell(row, 6)
        time2 = _cell(row, 7)
        seed = _cell(row, 8)
        art = _cell(row, 9)
        div = _cell(row, 11)
        mode = _cell(row, 12)
        if not seed or not p1 or not p2:
            continue
        n1, n2 = normalize_name(p1), normalize_name(p2)
        if n1 in targets and not vod1 and not time1:
            results.append({"row_index": idx, "side": 1, "player1": p1, "player2": p2, "seed": seed, "mode": mode or "Unbekannt", "art": art or "async", "div": div})
        elif n2 in targets and not vod2 and not time2:
            results.append({"row_index": idx, "side": 2, "player1": p1, "player2": p2, "seed": seed, "mode": mode or "Unbekannt", "art": art or "async", "div": div})
    return results[:25]


def write_async_result(row_index: int, side: int, vod_or_dnf: str, race_time: str):
    ws = get_async_worksheet()
    if side == 1:
        ws.update(f"D{row_index}:E{row_index}", [[vod_or_dnf, race_time]])
    else:
        ws.update(f"G{row_index}:H{row_index}", [[vod_or_dnf, race_time]])


def get_back_view(back_target: str, owner_id: int):
    if back_target == "plan":
        from plan import PlanMenuView
        return "**Spiel planen**\nWähle einen Bereich:", PlanMenuView(owner_id=owner_id)
    from player import AsyncMenuView
    return "**Spielermenü → Async**\nWähle einen Bereich:", AsyncMenuView(owner_id=owner_id)


class AsyncBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 1800):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Dieses Fenster gehört nicht dir.", ephemeral=True)
            return False
        return True


class AsyncRequestMatchSelect(discord.ui.Select):
    def __init__(self, matches: list[dict], requester_member: discord.Member):
        self.matches = {str(i): m for i, m in enumerate(matches)}
        self.requester_member = requester_member
        options = [discord.SelectOption(label=m["label"][:100], value=str(i)) for i, m in enumerate(matches[:25])]
        super().__init__(placeholder="Spiel auswählen …", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        match_data = self.matches[self.values[0]]
        await interaction.response.defer()
        try:
            modes = await asyncio.to_thread(get_runner_modes)
        except Exception:
            modes = ["Standard"]
        view = AsyncRequestModeView(owner_id=interaction.user.id, requester_member=self.requester_member, match_data=match_data, modes=modes, back_target=getattr(self.view, "back_target", "player"))
        await interaction.edit_original_response(content="**Async beantragen**\nWähle den Spielmodus:", view=view)


class AsyncRequestMatchListView(AsyncBaseView):
    def __init__(self, owner_id: int, matches: list[dict], requester_member: discord.Member, back_target: str):
        super().__init__(owner_id)
        self.back_target = back_target
        self.add_item(AsyncRequestMatchSelect(matches, requester_member))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        content, view = get_back_view(self.back_target, interaction.user.id)
        await interaction.response.edit_message(content=content, view=view)


class AsyncModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str]):
        options = [discord.SelectOption(label=m[:100], value=m) for m in modes[:25]]
        super().__init__(placeholder="Spielmodus wählen …", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AsyncRequestModeView):
            return
        view.selected_mode = self.values[0]
        await interaction.response.edit_message(content=view.render_text(), view=view)


class AsyncRequestModeView(AsyncBaseView):
    def __init__(self, owner_id: int, requester_member: discord.Member, match_data: dict, modes: list[str], back_target: str):
        super().__init__(owner_id, timeout=3600)
        self.requester_member = requester_member
        self.match_data = match_data
        self.selected_mode = None
        self.back_target = back_target
        self.add_item(AsyncModeSelect(modes))

    def render_text(self) -> str:
        lines = ["**Async beantragen**", f"**Spiel:** {self.match_data['label']}"]
        if self.selected_mode:
            lines.append(f"**Spielmodus:** {self.selected_mode}")
        return "\n".join(lines)

    @discord.ui.button(label="Beantragen", style=discord.ButtonStyle.success, row=1)
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_mode:
            await interaction.response.send_message("Bitte zuerst einen Spielmodus wählen.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("Das funktioniert nur auf dem Server.", ephemeral=True)
            return
        requester_name, opponent_name = get_requester_vs_opponent(self.match_data, self.requester_member)
        opponent_member = find_member_by_sheet_name(interaction.guild, opponent_name)
        if opponent_member is None:
            await interaction.response.send_message(f"Gegner `{opponent_name}` konnte auf dem Server nicht gefunden werden.", ephemeral=True)
            return
        if opponent_member.id == self.requester_member.id:
            await interaction.response.send_message("⚠️ Testmodus erkannt. Antragsteller und Gegner sind identisch. Es wird keine DM verschickt.", ephemeral=True)
            return
        await interaction.response.defer()
        request_data = {"match_kind": self.match_data["kind"], "match_label": self.match_data["label"], "division": self.match_data.get("division"), "round": self.match_data.get("round"), "player1": self.match_data["player1"], "player2": self.match_data["player2"], "requester_id": self.requester_member.id, "requester_name": requester_name, "opponent_id": opponent_member.id, "opponent_name": opponent_name, "selected_mode": self.selected_mode}
        dm_text = (f"**Async-Anfrage**\nSpiel: {request_data['player1']} vs. {request_data['player2']}\nBereich: {request_data['match_kind'].capitalize()}\nSpielmodus: {request_data['selected_mode']}\n\n{requester_name} beantragt ein Async für dieses Spiel.")
        try:
            await opponent_member.send(dm_text, view=OpponentConsentView(request_data))
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ DM an den Gegner konnte nicht gesendet werden: {e}", view=self)
            return
        await interaction.edit_original_response(content=f"✅ Async-Anfrage wurde an **{opponent_name}** per DM geschickt.\nSpielmodus: **{self.selected_mode}**", view=AsyncDoneView(owner_id=interaction.user.id, back_target=self.back_target))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        content, view = get_back_view(self.back_target, interaction.user.id)
        await interaction.response.edit_message(content=content, view=view)


class AsyncDoneView(AsyncBaseView):
    def __init__(self, owner_id: int, back_target: str):
        super().__init__(owner_id)
        self.back_target = back_target

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        content, view = get_back_view(self.back_target, interaction.user.id)
        await interaction.response.edit_message(content=content, view=view)


class OpponentConsentView(discord.ui.View):
    def __init__(self, request_data: dict):
        super().__init__(timeout=86400)
        self.request_data = request_data

    @discord.ui.button(label="Zustimmen", style=discord.ButtonStyle.success)
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.request_data["opponent_id"]:
            await interaction.response.send_message("Diese Anfrage ist nicht für dich.", ephemeral=True)
            return
        await interaction.response.defer()
        channel = interaction.client.get_channel(ADMIN_LOG_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await interaction.edit_original_response(content="❌ Admin-Log-Channel wurde nicht gefunden.", view=None)
            return
        content = (f"**Async beantragt**\nFür das Spiel **{self.request_data['player1']} vs. {self.request_data['player2']}**\nwird ein Async mit dem Spielmodus **{self.request_data['selected_mode']}** beantragt.\n\nBeantragt von: <@{self.request_data['requester_id']}>\nZugestimmt von: <@{self.request_data['opponent_id']}>")
        await channel.send(content, view=AdminDecisionView(self.request_data))
        await interaction.edit_original_response(content="✅ Du hast dem Async zugestimmt. Die Admins wurden informiert.", view=None)


class DenyReasonModal(discord.ui.Modal, title="Async ablehnen"):
    reason = discord.ui.TextInput(label="Ablehnungsgrund", placeholder="Grund eingeben …", required=True, style=discord.TextStyle.paragraph, max_length=1000)
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    async def on_submit(self, interaction: discord.Interaction):
        data = self.parent_view.request_data
        requester = await interaction.client.fetch_user(data["requester_id"])
        opponent = await interaction.client.fetch_user(data["opponent_id"])
        reason = str(self.reason).strip()
        dm_text = f"❌ Async wurde abgelehnt.\nSpiel: {data['player1']} vs. {data['player2']}\nSpielmodus: {data['selected_mode']}\nAblehnungsgrund: {reason}"
        for user in [requester, opponent]:
            try:
                await user.send(dm_text)
            except Exception:
                pass
        await interaction.response.edit_message(content=f"{interaction.message.content}\n\n**Status:** Abgelehnt\n**Grund:** {reason}", view=None)


class SeedLinkModal(discord.ui.Modal, title="Seed setzen"):
    seed_link = discord.ui.TextInput(label="Seed-Link", placeholder="https://...", required=True, style=discord.TextStyle.paragraph, max_length=1000)
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    async def on_submit(self, interaction: discord.Interaction):
        data = self.parent_view.request_data
        seed = str(self.seed_link).strip()
        await interaction.response.defer()
        try:
            row_index = await asyncio.to_thread(append_async_row, data["player1"], data["player2"], seed, data["selected_mode"])
        except Exception as e:
            await interaction.edit_original_response(content=f"{interaction.message.content}\n\n❌ Fehler beim Schreiben ins Async-Sheet: {e}", view=None)
            return
        requester = await interaction.client.fetch_user(data["requester_id"])
        opponent = await interaction.client.fetch_user(data["opponent_id"])
        dm_text = f"✅ Dem Async wurde zugestimmt.\nDer **{data['selected_mode']}**-Seed wurde eurem Async Race hinterlegt."
        for user in [requester, opponent]:
            try:
                await user.send(dm_text)
            except Exception:
                pass
        await interaction.edit_original_response(content=f"{interaction.message.content}\n\n**Status:** Zugestimmt\n**Async-Sheet-Zeile:** {row_index}\n**Seed in Spalte I gespeichert**", view=None)


class AdminDecisionView(discord.ui.View):
    def __init__(self, request_data: dict):
        super().__init__(timeout=86400)
        self.request_data = request_data
    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyReasonModal(self))
    @discord.ui.button(label="Zustimmen", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SeedLinkModal(self))


class AsyncPlaySelect(discord.ui.Select):
    def __init__(self, entries: list[dict]):
        self.entries = {str(i): e for i, e in enumerate(entries)}
        options = [discord.SelectOption(label=f"{e['player1']} vs. {e['player2']}"[:100], description=f"{e['mode']} | Zeile {e['row_index']}"[:100], value=str(i)) for i, e in enumerate(entries)]
        super().__init__(placeholder="Async wählen …", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        entry = self.entries[self.values[0]]
        await interaction.response.edit_message(content=render_async_play_intro(entry), view=AsyncPlaySeedView(interaction.user.id, entry, getattr(self.view, 'back_target', 'player')))


class AsyncPlaySelectView(AsyncBaseView):
    def __init__(self, owner_id: int, entries: list[dict], back_target: str):
        super().__init__(owner_id)
        self.back_target = back_target
        self.add_item(AsyncPlaySelect(entries))
    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        content, view = get_back_view(self.back_target, interaction.user.id)
        await interaction.response.edit_message(content=content, view=view)


def render_async_play_intro(entry: dict) -> str:
    return (f"**Async spielen**\n\nSpiel: **{entry['player1']} vs. {entry['player2']}**\nModus: **{entry['mode']}**\nSeed hinterlegt.\n\nÖffne zuerst den Seed und starte dann dein Race.")


class AsyncRunState:
    def __init__(self, entry: dict, user_id: int, back_target: str):
        self.entry = entry
        self.user_id = user_id
        self.back_target = back_target
        self.seed_shown_at = None
        self.started_at = None
        self.locked_final_time = None

    def measured_time(self):
        if not self.started_at:
            return "00:00:00"
        return format_seconds_to_hms(int((dt.utcnow() - self.started_at).total_seconds()))


class AsyncPlaySeedView(AsyncBaseView):
    def __init__(self, owner_id: int, entry: dict, back_target: str):
        super().__init__(owner_id)
        self.state = AsyncRunState(entry, owner_id, back_target)

    @discord.ui.button(label="Seed öffnen", style=discord.ButtonStyle.primary, row=0)
    async def seed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.seed_shown_at = dt.utcnow()
        await interaction.response.edit_message(content=(f"**Async spielen**\n\nSpiel: **{self.state.entry['player1']} vs. {self.state.entry['player2']}**\nModus: **{self.state.entry['mode']}**\nSeed: {self.state.entry['seed']}\n\nDrücke jetzt **Start**, wenn du wirklich bereit bist."), view=AsyncPlayStartView(interaction.user.id, self.state))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        content, view = get_back_view(self.state.back_target, interaction.user.id)
        await interaction.response.edit_message(content=content, view=view)


class AsyncPlayStartView(AsyncBaseView):
    def __init__(self, owner_id: int, state: AsyncRunState):
        super().__init__(owner_id)
        self.state = state

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, row=0)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.started_at = dt.utcnow()
        await interaction.response.edit_message(content=(f"**Async läuft**\n\nSpiel: **{self.state.entry['player1']} vs. {self.state.entry['player2']}**\nModus: **{self.state.entry['mode']}**\n\nDeine Zeit läuft jetzt. Drücke am Ende **Finish** oder **Forfeit**."), view=AsyncPlayRunningView(interaction.user.id, self.state))


class AsyncSubmitModal(discord.ui.Modal):
    vod_input = discord.ui.TextInput(label="VoD-Link", placeholder="https://...", required=True)
    def __init__(self, state: AsyncRunState, forfeit: bool = False):
        super().__init__(title="Async-Ergebnis")
        self.state = state
        self.forfeit = forfeit
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vod = "DNF" if self.forfeit else str(self.vod_input).strip()
        race_time = "03:00:00" if self.forfeit else (self.state.locked_final_time or self.state.measured_time())
        try:
            await asyncio.to_thread(write_async_result, self.state.entry['row_index'], self.state.entry['side'], vod, race_time)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Fehler beim Speichern des Async-Ergebnisses: {e}", view=None)
            return
        await interaction.edit_original_response(content=(f"**Async abgeschlossen**\n\nSpiel: **{self.state.entry['player1']} vs. {self.state.entry['player2']}**\nModus: **{self.state.entry['mode']}**\nZeit: **{race_time}**"), view=AsyncDoneView(owner_id=interaction.user.id, back_target=self.state.back_target))


class AsyncPlayRunningView(AsyncBaseView):
    def __init__(self, owner_id: int, state: AsyncRunState):
        super().__init__(owner_id, timeout=7200)
        self.state = state
    @discord.ui.button(label="Finish", style=discord.ButtonStyle.success, row=0)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.locked_final_time = self.state.measured_time()
        await interaction.response.send_modal(AsyncSubmitModal(self.state, forfeit=False))
    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, row=0)
    async def forfeit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.locked_final_time = "03:00:00"
        await interaction.response.send_modal(AsyncSubmitModal(self.state, forfeit=True))


async def open_async_request_from_player(interaction: discord.Interaction, back_target: str = "player"):
    member = interaction.user
    await interaction.response.defer()
    if not isinstance(member, discord.Member):
        await interaction.edit_original_response(content="Nur auf dem Server verfügbar.", view=None)
        return
    name_candidates = [member.display_name, getattr(member, "global_name", None), member.name]
    try:
        matches = await asyncio.to_thread(collect_requestable_matches_for_member, name_candidates)
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Fehler beim Laden der beantragbaren Spiele: {e}", view=None)
        return
    if not matches:
        await interaction.edit_original_response(content="Für dich wurden aktuell keine offenen League- oder Cup-Spiele gefunden.", view=AsyncDoneView(owner_id=interaction.user.id, back_target=back_target))
        return
    await interaction.edit_original_response(content="**Async beantragen**\nWähle das Spiel aus:", view=AsyncRequestMatchListView(owner_id=interaction.user.id, matches=matches, requester_member=member, back_target=back_target))


async def open_async_play_from_player(interaction: discord.Interaction, back_target: str = "player"):
    member = interaction.user
    await interaction.response.defer()
    if not isinstance(member, discord.Member):
        await interaction.edit_original_response(content="Nur auf dem Server verfügbar.", view=None)
        return
    name_candidates = [member.display_name, getattr(member, "global_name", None), member.name]
    try:
        entries = await asyncio.to_thread(find_open_async_entries_for_name_candidates, name_candidates)
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Fehler beim Laden deiner Asyncs: {e}", view=None)
        return
    if not entries:
        await interaction.edit_original_response(content="Für dich wurde aktuell kein offenes Async mit hinterlegtem Seed gefunden.", view=AsyncDoneView(owner_id=interaction.user.id, back_target=back_target))
        return
    if len(entries) == 1:
        await interaction.edit_original_response(content=render_async_play_intro(entries[0]), view=AsyncPlaySeedView(interaction.user.id, entries[0], back_target))
        return
    await interaction.edit_original_response(content="**Async spielen**\nWähle dein Async aus:", view=AsyncPlaySelectView(owner_id=interaction.user.id, entries=entries, back_target=back_target))

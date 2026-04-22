import os
import asyncio
from datetime import datetime

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


def menu_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=0x00FFCC,
    )


# =========================================================
# GOOGLE SHEETS
# =========================================================
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


def append_async_row(
    home_player: str,
    guest_player: str,
    seed_link: str,
    art: str,
    source_row_index: int,
    division: str,
    mode: str,
) -> int:
    ws = get_async_worksheet()
    col_a = ws.col_values(1)

    row_index = 1
    while row_index <= len(col_a):
        if not (col_a[row_index - 1] or "").strip():
            break
        row_index += 1

    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    reqs = [
        {"range": f"A{row_index}:A{row_index}", "values": [[timestamp]]},
        {"range": f"B{row_index}:B{row_index}", "values": [[home_player]]},
        {"range": f"F{row_index}:F{row_index}", "values": [[guest_player]]},
        {"range": f"I{row_index}:I{row_index}", "values": [[seed_link]]},
        {"range": f"J{row_index}:J{row_index}", "values": [[art]]},
        {"range": f"K{row_index}:K{row_index}", "values": [[str(source_row_index)]]},
        {"range": f"L{row_index}:L{row_index}", "values": [[division]]},
        {"range": f"M{row_index}:M{row_index}", "values": [[mode]]},
    ]
    ws.batch_update(reqs)
    return row_index


# =========================================================
# HELFER
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


def collect_requestable_matches_for_member(name_candidates: list[str]) -> list[dict]:
    targets = {normalize_name(x) for x in name_candidates if x}
    out: list[dict] = []

    for division_label in [f"Div {i}" for i in range(1, 7)]:
        ws = get_div_ws_from_label(division_label)
        rows = ws.get_all_values()

        for idx, row in enumerate(rows, start=1):
            if idx == 1:
                continue

            p1 = _cell(row, DIV_COL_LEFT - 1)
            marker = _cell(row, DIV_COL_MARKER - 1)
            p2 = _cell(row, DIV_COL_RIGHT - 1)

            if not p1 or not p2:
                continue
            if marker.lower() != "vs":
                continue

            if normalize_name(p1) not in targets and normalize_name(p2) not in targets:
                continue

            out.append(
                {
                    "kind": "league",
                    "label": f"League | {division_label} | {p1} vs. {p2}",
                    "division": division_label,
                    "row_index": idx,
                    "player1": p1,
                    "player2": p2,
                }
            )

    cup_matches = load_open_cup_matches()
    for match in cup_matches:
        p1 = match["player1"]
        p2 = match["player2"]

        if normalize_name(p1) not in targets and normalize_name(p2) not in targets:
            continue

        out.append(
            {
                "kind": "cup",
                "label": f"Cup | {match['round']} | {p1} vs. {p2}",
                "round": match["round"],
                "row_index": match["row"],
                "player1": p1,
                "player2": p2,
            }
        )

    return out[:25]


def find_member_by_sheet_name(guild: discord.Guild, player_name: str) -> discord.Member | None:
    target = normalize_name(player_name)

    for member in guild.members:
        candidates = [
            member.display_name,
            getattr(member, "global_name", None),
            member.name,
        ]
        for cand in candidates:
            if normalize_name(cand) == target:
                return member
    return None


def get_requester_vs_opponent(match_data: dict, requester_member: discord.Member) -> tuple[str, str]:
    requester_names = {
        normalize_name(requester_member.display_name),
        normalize_name(getattr(requester_member, "global_name", None)),
        normalize_name(requester_member.name),
    }

    p1 = match_data["player1"]
    p2 = match_data["player2"]

    if normalize_name(p1) in requester_names:
        return p1, p2
    if normalize_name(p2) in requester_names:
        return p2, p1

    return p1, p2


# =========================================================
# BASIS
# =========================================================
class AsyncBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 1800):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Dieses Fenster gehört nicht dir.",
                ephemeral=True,
            )
            return False
        return True


# =========================================================
# MATCH AUSWAHL
# =========================================================
class AsyncRequestMatchSelect(discord.ui.Select):
    def __init__(self, matches: list[dict], requester_member: discord.Member):
        self.matches = {str(i): m for i, m in enumerate(matches)}
        self.requester_member = requester_member

        options = [
            discord.SelectOption(label=m["label"][:100], value=str(i))
            for i, m in enumerate(matches[:25])
        ]

        super().__init__(
            placeholder="Spiel auswählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        match_data = self.matches[self.values[0]]

        await interaction.response.defer()

        try:
            modes = await asyncio.to_thread(get_runner_modes)
        except Exception:
            modes = ["Standard"]

        view = AsyncRequestModeView(
            owner_id=interaction.user.id,
            requester_member=self.requester_member,
            match_data=match_data,
            modes=modes,
        )

        await interaction.edit_original_response(
            embed=view.render_embed(),
            view=view,
            content=None,
        )


class AsyncRequestMatchListView(AsyncBaseView):
    def __init__(self, owner_id: int, matches: list[dict], requester_member: discord.Member):
        super().__init__(owner_id)
        self.add_item(AsyncRequestMatchSelect(matches, requester_member))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import AsyncMenuView

        await interaction.response.edit_message(
            embed=menu_embed("⚡ Async", "Wähle einen Bereich."),
            view=AsyncMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# MODUS AUSWAHL
# =========================================================
class AsyncModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str]):
        options = [discord.SelectOption(label=m[:100], value=m) for m in modes[:25]]
        super().__init__(
            placeholder="Spielmodus wählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AsyncRequestModeView):
            return

        view.selected_mode = self.values[0]
        await interaction.response.edit_message(
            embed=view.render_embed(),
            view=view,
            content=None,
        )


class AsyncRequestModeView(AsyncBaseView):
    def __init__(self, owner_id: int, requester_member: discord.Member, match_data: dict, modes: list[str]):
        super().__init__(owner_id, timeout=3600)
        self.requester_member = requester_member
        self.match_data = match_data
        self.selected_mode: str | None = None
        self.add_item(AsyncModeSelect(modes))

    def render_embed(self) -> discord.Embed:
        lines = [f"**Spiel:** {self.match_data['label']}"]
        lines.append(f"**Spielmodus:** {self.selected_mode or '-'}")
        return menu_embed("⚡ Async → Beantragen", "\n".join(lines))

    @discord.ui.button(label="Beantragen", style=discord.ButtonStyle.success, row=1)
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_mode:
            await interaction.response.send_message(
                "Bitte zuerst einen Spielmodus wählen.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Das funktioniert nur auf dem Server.",
                ephemeral=True,
            )
            return

        requester_name, opponent_name = get_requester_vs_opponent(self.match_data, self.requester_member)
        opponent_member = find_member_by_sheet_name(interaction.guild, opponent_name)

        if opponent_member is None:
            await interaction.response.send_message(
                f"Gegner `{opponent_name}` konnte auf dem Server nicht gefunden werden.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        request_data = {
            "match_kind": self.match_data["kind"],
            "match_label": self.match_data["label"],
            "division": self.match_data.get("division"),
            "round": self.match_data.get("round"),
            "source_row_index": self.match_data["row_index"],
            "player1": self.match_data["player1"],
            "player2": self.match_data["player2"],
            "requester_id": self.requester_member.id,
            "requester_name": requester_name,
            "opponent_id": opponent_member.id,
            "opponent_name": opponent_name,
            "selected_mode": self.selected_mode,
        }

        dm_text = (
            f"**Async-Anfrage**\n"
            f"Spiel: {request_data['player1']} vs. {request_data['player2']}\n"
            f"Bereich: {request_data['match_kind'].capitalize()}\n"
            f"Spielmodus: {request_data['selected_mode']}\n\n"
            f"{requester_name} beantragt ein Async für dieses Spiel."
        )

        try:
            await opponent_member.send(
                embed=menu_embed("⚡ Async-Anfrage", dm_text),
                view=OpponentConsentView(request_data),
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚡ Async → Beantragen",
                    f"DM an den Gegner konnte nicht gesendet werden: {e}",
                ),
                view=self,
                content=None,
            )
            return

        await interaction.edit_original_response(
            embed=menu_embed(
                "⚡ Async → Beantragen",
                (
                    f"Anfrage wurde an **{opponent_name}** per DM geschickt.\n"
                    f"**Spielmodus:** {self.selected_mode}"
                ),
            ),
            view=AsyncRequestDoneView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import AsyncMenuView

        await interaction.response.edit_message(
            embed=menu_embed("⚡ Async", "Wähle einen Bereich."),
            view=AsyncMenuView(owner_id=interaction.user.id),
            content=None,
        )


class AsyncRequestDoneView(AsyncBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import AsyncMenuView

        await interaction.response.edit_message(
            embed=menu_embed("⚡ Async", "Wähle einen Bereich."),
            view=AsyncMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# GEGNER STIMMT ZU
# =========================================================
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
            await interaction.edit_original_response(
                embed=menu_embed("⚡ Async-Anfrage", "Admin-Log-Channel wurde nicht gefunden."),
                view=None,
                content=None,
            )
            return

        content = (
            f"Für das Spiel **{self.request_data['player1']} vs. {self.request_data['player2']}**\n"
            f"wird ein Async mit dem Spielmodus **{self.request_data['selected_mode']}** beantragt.\n\n"
            f"Beantragt von: <@{self.request_data['requester_id']}>\n"
            f"Zugestimmt von: <@{self.request_data['opponent_id']}>"
        )

        await channel.send(
            embed=menu_embed("⚡ Async beantragt", content),
            view=AdminDecisionView(self.request_data),
        )

        await interaction.edit_original_response(
            embed=menu_embed(
                "⚡ Async-Anfrage",
                "Du hast dem Async zugestimmt. Die Admins wurden informiert.",
            ),
            view=None,
            content=None,
        )


# =========================================================
# ADMIN ENTSCHEIDUNG
# =========================================================
class DenyReasonModal(discord.ui.Modal, title="Async ablehnen"):
    reason = discord.ui.TextInput(
        label="Ablehnungsgrund",
        placeholder="Grund eingeben …",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, parent_view: "AdminDecisionView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        data = self.parent_view.request_data
        requester = await interaction.client.fetch_user(data["requester_id"])
        opponent = await interaction.client.fetch_user(data["opponent_id"])
        reason = str(self.reason).strip()

        dm_text = (
            f"Async wurde abgelehnt.\n"
            f"Spiel: {data['player1']} vs. {data['player2']}\n"
            f"Spielmodus: {data['selected_mode']}\n"
            f"Ablehnungsgrund: {reason}"
        )

        for user in [requester, opponent]:
            try:
                await user.send(embed=menu_embed("⚡ Async abgelehnt", dm_text))
            except Exception:
                pass

        await interaction.response.edit_message(
            embed=menu_embed(
                "⚡ Async beantragt",
                (
                    f"Für das Spiel **{data['player1']} vs. {data['player2']}**\n"
                    f"wurde der Async **abgelehnt**.\n\n"
                    f"**Grund:** {reason}"
                ),
            ),
            view=None,
            content=None,
        )


class SeedLinkModal(discord.ui.Modal, title="Seed setzen"):
    seed_link = discord.ui.TextInput(
        label="Seed-Link",
        placeholder="https://...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, parent_view: "AdminDecisionView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        data = self.parent_view.request_data
        seed = str(self.seed_link).strip()

        await interaction.response.defer()

        try:
            row_index = await asyncio.to_thread(
                append_async_row,
                data["player1"],
                data["player2"],
                seed,
                data["match_kind"],
                data["source_row_index"],
                data["division"] or "",
                data["selected_mode"],
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚡ Async beantragt",
                    f"Fehler beim Schreiben ins Async-Sheet: {e}",
                ),
                view=None,
                content=None,
            )
            return

        requester = await interaction.client.fetch_user(data["requester_id"])
        opponent = await interaction.client.fetch_user(data["opponent_id"])

        dm_text = (
            "Dem Async wurde zugestimmt.\n"
            f"Der **{data['selected_mode']}**-Seed wurde eurem Async Race hinterlegt."
        )

        for user in [requester, opponent]:
            try:
                await user.send(embed=menu_embed("⚡ Async bestätigt", dm_text))
            except Exception:
                pass

        await interaction.edit_original_response(
            embed=menu_embed(
                "⚡ Async beantragt",
                (
                    f"Für das Spiel **{data['player1']} vs. {data['player2']}**\n"
                    f"wurde der Async **zugestimmt**.\n\n"
                    f"**Sheet-Zeile:** {row_index}\n"
                    f"**Seed gesetzt:** hinterlegt"
                ),
            ),
            view=None,
            content=None,
        )


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


# =========================================================
# ÖFFNER FÜR PLAYER / PLAN
# =========================================================
async def open_async_request_from_player(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        name_candidates = [
            member.display_name,
            getattr(member, "global_name", None),
            member.name,
        ]
        matches = await asyncio.to_thread(
            collect_requestable_matches_for_member,
            name_candidates,
        )
    except Exception as e:
        await interaction.edit_original_response(
            embed=menu_embed("⚡ Async → Beantragen", f"Fehler beim Laden der Spiele: {e}"),
            view=AsyncRequestDoneView(owner_id=interaction.user.id),
            content=None,
        )
        return

    if not matches:
        await interaction.edit_original_response(
            embed=menu_embed(
                "⚡ Async → Beantragen",
                "Für dich wurden keine offenen League- oder Cup-Spiele gefunden.",
            ),
            view=AsyncRequestDoneView(owner_id=interaction.user.id),
            content=None,
        )
        return

    await interaction.edit_original_response(
        embed=menu_embed("⚡ Async → Beantragen", "Wähle ein Spiel."),
        view=AsyncRequestMatchListView(
            owner_id=interaction.user.id,
            matches=matches,
            requester_member=member,
        ),
        content=None,
    )

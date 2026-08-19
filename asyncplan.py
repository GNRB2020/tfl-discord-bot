import os
import asyncio
from datetime import datetime

import discord
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from sheet_guard import (
    col_values_cached,
    get_all_values_cached,
    sheet_write_call,
)

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
ADMIN_ROLE_NAME = "admin"
ASYNC_SPREADSHEET_ID = "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8"
ASYNC_WORKSHEET_GID = 539808866

CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

ASYNCPLAN_PERFORMANCE_VERSION = "asyncplan-admin-request-v2"
print(f"[ASYNCPLAN] geladen: {ASYNCPLAN_PERFORMANCE_VERSION}")
ASYNCPLAN_SHEET_CACHE_TTL_SECONDS = int(os.getenv("ASYNCPLAN_SHEET_CACHE_TTL_SECONDS", "90"))
ASYNCPLAN_ASYNC_COL_CACHE_TTL_SECONDS = int(os.getenv("ASYNCPLAN_ASYNC_COL_CACHE_TTL_SECONDS", "30"))

_GSPREAD_CLIENT_CACHE = None
_SPREADSHEET_CACHE = None
_ASYNC_WORKSHEET_CACHE = None


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
    global _GSPREAD_CLIENT_CACHE

    if _GSPREAD_CLIENT_CACHE is not None:
        return _GSPREAD_CLIENT_CACHE

    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    _GSPREAD_CLIENT_CACHE = gspread.authorize(creds)
    return _GSPREAD_CLIENT_CACHE


def get_async_spreadsheet():
    global _SPREADSHEET_CACHE

    if _SPREADSHEET_CACHE is not None:
        return _SPREADSHEET_CACHE

    client = get_gspread_client()
    _SPREADSHEET_CACHE = client.open_by_key(ASYNC_SPREADSHEET_ID)
    return _SPREADSHEET_CACHE


def get_async_worksheet():
    global _ASYNC_WORKSHEET_CACHE

    if _ASYNC_WORKSHEET_CACHE is not None:
        return _ASYNC_WORKSHEET_CACHE

    spreadsheet = get_async_spreadsheet()
    for ws in spreadsheet.worksheets():
        if int(ws.id) == int(ASYNC_WORKSHEET_GID):
            _ASYNC_WORKSHEET_CACHE = ws
            return _ASYNC_WORKSHEET_CACHE

    raise RuntimeError(f"Worksheet mit gid/id {ASYNC_WORKSHEET_GID} nicht gefunden.")


def sheet_cache_name(ws, fallback: str = "AsyncPlan") -> str:
    return getattr(ws, "title", fallback)


def invalidate_prefixes_for_ws(ws, fallback: str = "AsyncPlan") -> list[str]:
    name = sheet_cache_name(ws, fallback)
    return [
        f"records:{name}",
        f"values:{name}",
        f"row:{name}:",
        f"col:{name}:",
        f"cell:{name}:",
    ]


def get_cached_sheet_values(ws, fallback: str = "AsyncPlan", ttl_seconds: int = ASYNCPLAN_SHEET_CACHE_TTL_SECONDS):
    return get_all_values_cached(
        lambda: ws,
        sheet_name=sheet_cache_name(ws, fallback),
        ttl_seconds=ttl_seconds,
    )


def append_async_row(
    home_player: str,
    guest_player: str,
    seed_link: str,
    art: str,
    source_row_index: int,
    division: str,
    mode: str,
) -> int:
    """
    Async-Sheet:
    A = Timestamp
    B = Player1
    D = VoD1
    E = Time1
    F = Player2
    G = VoD2
    H = Time2
    I = Seed
    J = Art
    K = Source Row Index
    L = Division
    M = Mode
    """
    ws = get_async_worksheet()
    col_a = col_values_cached(
        lambda: ws,
        sheet_name=sheet_cache_name(ws, "Async"),
        col=1,
        ttl_seconds=ASYNCPLAN_ASYNC_COL_CACHE_TTL_SECONDS,
    )
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
    sheet_write_call(
        lambda: ws.batch_update(reqs),
        invalidate_prefixes=invalidate_prefixes_for_ws(ws, "Async"),
    )
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


def is_admin_member(member: discord.Member) -> bool:
    return any(role.name.casefold() == ADMIN_ROLE_NAME.casefold() for role in member.roles)


def get_admin_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.find(
        lambda role: role.name.casefold() == ADMIN_ROLE_NAME.casefold(),
        guild.roles,
    )


def collect_requestable_matches(name_candidates: list[str] | None = None) -> list[dict]:
    """
    Ohne name_candidates: alle offenen League-/Cup-Spiele (Admin).
    Mit name_candidates: nur Spiele des jeweiligen Spielers.
    """
    targets = None
    if name_candidates is not None:
        targets = {normalize_name(x) for x in name_candidates if x}

    out: list[dict] = []

    # League
    for division_label in [f"Div {i}" for i in range(1, 7)]:
        ws = get_div_ws_from_label(division_label)
        rows = get_cached_sheet_values(ws, division_label)

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
            if targets is not None:
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

    # Cup
    cup_matches = load_open_cup_matches()
    for match in cup_matches:
        p1 = match["player1"]
        p2 = match["player2"]

        if targets is not None:
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

    return out


def collect_requestable_matches_for_member(name_candidates: list[str]) -> list[dict]:
    return collect_requestable_matches(name_candidates)


def collect_all_requestable_matches() -> list[dict]:
    return collect_requestable_matches(None)


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


def member_matches_sheet_name(member: discord.Member, player_name: str) -> bool:
    target = normalize_name(player_name)
    candidates = [
        member.display_name,
        getattr(member, "global_name", None),
        member.name,
    ]
    return any(normalize_name(cand) == target for cand in candidates if cand)


async def fetch_users(client: discord.Client, user_ids: list[int]) -> list[discord.User]:
    users: list[discord.User] = []
    seen: set[int] = set()

    for user_id in user_ids:
        if user_id in seen:
            continue
        seen.add(user_id)
        try:
            users.append(await client.fetch_user(user_id))
        except Exception:
            pass

    return users


async def send_admin_decision_request(client: discord.Client, request_data: dict) -> bool:
    if request_data.get("admin_log_sent"):
        return True

    channel = client.get_channel(ADMIN_LOG_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return False

    # Vor dem await setzen, damit zwei fast zeitgleiche Zustimmungen
    # nicht zwei Admin-Meldungen erzeugen.
    request_data["admin_log_sent"] = True

    admin_role = get_admin_role(channel.guild)
    mention = admin_role.mention if admin_role is not None else "@admin"

    approved_ids = list(dict.fromkeys(request_data.get("approved_consent_ids", [])))
    approved_mentions = ", ".join(f"<@{user_id}>" for user_id in approved_ids) or "-"

    requester_line = f"<@{request_data['requester_id']}>"
    if request_data.get("initiated_by_admin"):
        requester_line += " (Admin)"

    content = (
        f"Für das Spiel **{request_data['player1']} vs. {request_data['player2']}**\n"
        f"wird ein Async mit dem Spielmodus **{request_data['selected_mode']}** beantragt.\n\n"
        f"Beantragt von: {requester_line}\n"
        f"Zugestimmt von: {approved_mentions}"
    )

    try:
        await channel.send(
            content=mention,
            embed=menu_embed("⚡ Async beantragt", content),
            view=AdminDecisionView(request_data),
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )
    except Exception:
        request_data["admin_log_sent"] = False
        raise

    return True


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
    def __init__(
        self,
        matches: list[dict],
        requester_member: discord.Member,
        initiated_by_admin: bool,
    ):
        self.matches = {str(i): m for i, m in enumerate(matches)}
        self.requester_member = requester_member
        self.initiated_by_admin = initiated_by_admin

        options = [
            discord.SelectOption(label=m["label"][:100], value=str(i))
            for i, m in enumerate(matches)
        ]

        super().__init__(
            placeholder="Spiel auswählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
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
            initiated_by_admin=self.initiated_by_admin,
        )

        await interaction.edit_original_response(
            embed=view.render_embed(),
            view=view,
            content=None,
        )


class AsyncRequestMatchListView(AsyncBaseView):
    PAGE_SIZE = 25

    def __init__(
        self,
        owner_id: int,
        matches: list[dict],
        requester_member: discord.Member,
        initiated_by_admin: bool = False,
        page: int = 0,
    ):
        super().__init__(owner_id)
        self.matches = matches
        self.requester_member = requester_member
        self.initiated_by_admin = initiated_by_admin
        self.max_page = max(0, (len(matches) - 1) // self.PAGE_SIZE)
        self.page = max(0, min(page, self.max_page))

        start = self.page * self.PAGE_SIZE
        page_matches = matches[start:start + self.PAGE_SIZE]

        self.add_item(
            AsyncRequestMatchSelect(
                page_matches,
                requester_member,
                initiated_by_admin,
            )
        )

        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= self.max_page

    def render_embed(self) -> discord.Embed:
        admin_text = "Admin-Modus: alle offenen Spiele." if self.initiated_by_admin else "Wähle eines deiner offenen Spiele."
        return menu_embed(
            "⚡ Async → Beantragen",
            f"{admin_text}\nSeite **{self.page + 1}/{self.max_page + 1}**",
        )

    @discord.ui.button(label="◀ Seite", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AsyncRequestMatchListView(
            owner_id=self.owner_id,
            matches=self.matches,
            requester_member=self.requester_member,
            initiated_by_admin=self.initiated_by_admin,
            page=self.page - 1,
        )
        await interaction.response.edit_message(
            embed=view.render_embed(),
            view=view,
            content=None,
        )

    @discord.ui.button(label="Seite ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AsyncRequestMatchListView(
            owner_id=self.owner_id,
            matches=self.matches,
            requester_member=self.requester_member,
            initiated_by_admin=self.initiated_by_admin,
            page=self.page + 1,
        )
        await interaction.response.edit_message(
            embed=view.render_embed(),
            view=view,
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
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
    def __init__(
        self,
        owner_id: int,
        requester_member: discord.Member,
        match_data: dict,
        modes: list[str],
        initiated_by_admin: bool = False,
    ):
        super().__init__(owner_id, timeout=3600)
        self.requester_member = requester_member
        self.match_data = match_data
        self.initiated_by_admin = initiated_by_admin
        self.selected_mode: str | None = None
        self.add_item(AsyncModeSelect(modes))

    def render_embed(self) -> discord.Embed:
        lines = [f"**Spiel:** {self.match_data['label']}"]
        lines.append(f"**Spielmodus:** {self.selected_mode or '-'}")
        if self.initiated_by_admin:
            lines.append("**Admin-Antrag:** Beide Spieler müssen zustimmen.")
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

        player1_name = self.match_data["player1"]
        player2_name = self.match_data["player2"]
        player1_member = find_member_by_sheet_name(interaction.guild, player1_name)
        player2_member = find_member_by_sheet_name(interaction.guild, player2_name)

        missing = []
        if player1_member is None:
            missing.append(player1_name)
        if player2_member is None:
            missing.append(player2_name)

        if missing:
            await interaction.response.send_message(
                "Folgende Spieler konnten auf dem Server nicht gefunden werden: " + ", ".join(f"`{name}`" for name in missing),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        participant_ids = [player1_member.id, player2_member.id]

        if self.initiated_by_admin:
            required_consent_ids = participant_ids.copy()
            approved_consent_ids: list[int] = []
        else:
            # Beim normalen Spielerantrag gilt der Antrag des Spielers selbst
            # bereits als eigene Zustimmung. Nur der Gegner muss bestätigen.
            if self.requester_member.id not in participant_ids:
                await interaction.edit_original_response(
                    embed=menu_embed(
                        "⚡ Async → Beantragen",
                        "Du bist keinem der beiden Spieler dieses Matches zugeordnet.",
                    ),
                    view=self,
                    content=None,
                )
                return

            required_consent_ids = [
                user_id for user_id in participant_ids
                if user_id != self.requester_member.id
            ]
            approved_consent_ids = [self.requester_member.id]

        request_data = {
            "match_kind": self.match_data["kind"],
            "match_label": self.match_data["label"],
            "division": self.match_data.get("division"),
            "round": self.match_data.get("round"),
            "source_row_index": self.match_data["row_index"],
            "player1": player1_name,
            "player2": player2_name,
            "player1_id": player1_member.id,
            "player2_id": player2_member.id,
            "requester_id": self.requester_member.id,
            "selected_mode": self.selected_mode,
            "initiated_by_admin": self.initiated_by_admin,
            "required_consent_ids": required_consent_ids,
            "approved_consent_ids": approved_consent_ids,
            "admin_log_sent": False,
        }

        target_members = [
            member
            for member in (player1_member, player2_member)
            if member.id in required_consent_ids
        ]

        sent_to: list[str] = []
        failed_to: list[str] = []

        for target_member in target_members:
            dm_text = (
                f"**Async-Anfrage**\n"
                f"Spiel: {player1_name} vs. {player2_name}\n"
                f"Bereich: {request_data['match_kind'].capitalize()}\n"
                f"Spielmodus: {request_data['selected_mode']}\n\n"
            )

            if self.initiated_by_admin:
                dm_text += f"<@{self.requester_member.id}> hat als Admin einen Async für dieses Spiel beantragt."
            else:
                dm_text += f"<@{self.requester_member.id}> beantragt ein Async für dieses Spiel."

            try:
                await target_member.send(
                    embed=menu_embed("⚡ Async-Anfrage", dm_text),
                    view=PlayerConsentView(request_data, target_member.id),
                )
                sent_to.append(target_member.display_name)
            except Exception:
                failed_to.append(target_member.display_name)

        if failed_to:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚡ Async → Beantragen",
                    (
                        "Die Anfrage konnte nicht an alle benötigten Spieler gesendet werden.\n\n"
                        f"Gesendet an: {', '.join(sent_to) or '-'}\n"
                        f"Fehlgeschlagen: {', '.join(failed_to)}"
                    ),
                ),
                view=AsyncRequestDoneView(owner_id=interaction.user.id),
                content=None,
            )
            return

        await interaction.edit_original_response(
            embed=menu_embed(
                "⚡ Async → Beantragen",
                (
                    f"Async-Anfrage verschickt.\n"
                    f"**Spiel:** {player1_name} vs. {player2_name}\n"
                    f"**Spielmodus:** {self.selected_mode}\n"
                    f"**Zustimmung erforderlich von:** {', '.join(sent_to)}"
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
# SPIELER STIMMEN ZU
# =========================================================

class PlayerConsentView(discord.ui.View):
    def __init__(self, request_data: dict, target_player_id: int):
        # Kein 24h-Timeout mehr. Die View bleibt aktiv, solange der Botprozess läuft.
        super().__init__(timeout=None)
        self.request_data = request_data
        self.target_player_id = target_player_id

    @discord.ui.button(label="Zustimmen", style=discord.ButtonStyle.success)
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_player_id:
            await interaction.response.send_message(
                "Diese Anfrage ist nicht für dich.",
                ephemeral=True,
            )
            return

        approved_ids = self.request_data.setdefault("approved_consent_ids", [])
        if interaction.user.id in approved_ids:
            await interaction.response.send_message(
                "Du hast dieser Async-Anfrage bereits zugestimmt.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        approved_ids.append(interaction.user.id)

        required_ids = set(self.request_data.get("required_consent_ids", []))
        current_approved_ids = set(self.request_data.get("approved_consent_ids", []))
        all_confirmed = required_ids.issubset(current_approved_ids)

        if all_confirmed:
            try:
                sent = await send_admin_decision_request(interaction.client, self.request_data)
            except Exception as exc:
                self.request_data["admin_log_sent"] = False
                await interaction.edit_original_response(
                    embed=menu_embed(
                        "⚡ Async-Anfrage",
                        f"Zustimmung gespeichert, aber die Admin-Meldung konnte nicht gesendet werden: {exc}",
                    ),
                    view=None,
                    content=None,
                )
                return

            if not sent:
                await interaction.edit_original_response(
                    embed=menu_embed(
                        "⚡ Async-Anfrage",
                        "Du hast zugestimmt, aber der Admin-Log-Channel wurde nicht gefunden.",
                    ),
                    view=None,
                    content=None,
                )
                return

            text = "Du hast dem Async zugestimmt. Alle benötigten Spieler haben bestätigt. Die Admins wurden informiert."
        else:
            remaining_ids = required_ids - current_approved_ids
            remaining_mentions = ", ".join(f"<@{user_id}>" for user_id in remaining_ids)
            text = (
                "Du hast dem Async zugestimmt.\n"
                f"Es fehlt noch die Zustimmung von: {remaining_mentions}"
            )

        await interaction.edit_original_response(
            embed=menu_embed("⚡ Async-Anfrage", text),
            view=None,
            content=None,
        )


# Alias für mögliche ältere Imports innerhalb des Projekts.
OpponentConsentView = PlayerConsentView


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
        reason = str(self.reason).strip()

        dm_text = (
            f"Async wurde abgelehnt.\n"
            f"Spiel: {data['player1']} vs. {data['player2']}\n"
            f"Spielmodus: {data['selected_mode']}\n"
            f"Ablehnungsgrund: {reason}"
        )

        player_ids = [data["player1_id"], data["player2_id"]]
        users = await fetch_users(interaction.client, player_ids)
        for user in users:
            try:
                await user.send(embed=menu_embed("⚡ Async abgelehnt", dm_text))
            except Exception:
                pass

        await interaction.response.edit_message(
            content=None,
            embed=menu_embed(
                "⚡ Async beantragt",
                (
                    f"Für das Spiel **{data['player1']} vs. {data['player2']}**\n"
                    f"wurde der Async **abgelehnt**.\n\n"
                    f"**Grund:** {reason}"
                ),
            ),
            view=None,
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
                int(data["source_row_index"]),
                data.get("division") or "",
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

        dm_text = (
            f"Dem Async wurde zugestimmt.\n"
            f"Spiel: {data['player1']} vs. {data['player2']}\n"
            f"Spielmodus: {data['selected_mode']}\n"
            f"Seed: hinterlegt"
        )

        player_ids = [data["player1_id"], data["player2_id"]]
        users = await fetch_users(interaction.client, player_ids)
        for user in users:
            try:
                await user.send(embed=menu_embed("⚡ Async bestätigt", dm_text))
            except Exception:
                pass

        await interaction.edit_original_response(
            content=None,
            embed=menu_embed(
                "⚡ Async beantragt",
                (
                    f"Für das Spiel **{data['player1']} vs. {data['player2']}**\n"
                    f"wurde dem Async **zugestimmt**.\n\n"
                    f"**Sheet-Zeile:** {row_index}\n"
                    f"**Seed gesetzt:** hinterlegt"
                ),
            ),
            view=None,
        )


class AdminDecisionView(discord.ui.View):
    def __init__(self, request_data: dict):
        # Kein 24h-Timeout mehr.
        super().__init__(timeout=None)
        self.request_data = request_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_admin_member(member):
            await interaction.response.send_message(
                "Nur Mitglieder mit der Rolle @admin können diesen Antrag bearbeiten.",
                ephemeral=True,
            )
            return False
        return True

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

    initiated_by_admin = is_admin_member(member)

    await interaction.response.defer()
    try:
        if initiated_by_admin:
            matches = await asyncio.to_thread(collect_all_requestable_matches)
        else:
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
        text = (
            "Es wurden keine offenen League- oder Cup-Spiele gefunden."
            if initiated_by_admin
            else "Für dich wurden keine offenen League- oder Cup-Spiele gefunden."
        )
        await interaction.edit_original_response(
            embed=menu_embed("⚡ Async → Beantragen", text),
            view=AsyncRequestDoneView(owner_id=interaction.user.id),
            content=None,
        )
        return

    view = AsyncRequestMatchListView(
        owner_id=interaction.user.id,
        matches=matches,
        requester_member=member,
        initiated_by_admin=initiated_by_admin,
    )

    await interaction.edit_original_response(
        embed=view.render_embed(),
        view=view,
        content=None,
    )

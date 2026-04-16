import os
import asyncio
from datetime import timedelta

import discord

from matchcenter import (
    get_div_ws_from_label,
    _cell,
    DIV_COL_LEFT,
    DIV_COL_MARKER,
    DIV_COL_RIGHT,
    get_runner_modes,
    build_multistream_url,
    parse_berlin_datetime,
    create_scheduled_event,
)

from schedule import (
    load_open_matches as load_open_cup_matches,
    CupTerminModal,
)

from asyncplan import (
    collect_requestable_matches_for_member,
    AsyncRequestMatchListView,
)

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))


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


def get_member_name_candidates(member: discord.Member) -> list[str]:
    return [
        member.display_name,
        getattr(member, "global_name", None),
        member.name,
    ]


def collect_open_league_matches_for_member(name_candidates: list[str]) -> list[dict]:
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

            if not p1 or not p2:
                continue
            if marker.lower() != "vs":
                continue

            if normalize_name(p1) not in targets and normalize_name(p2) not in targets:
                continue

            out.append(
                {
                    "kind": "league",
                    "division": division_label,
                    "row_index": idx,
                    "player1": p1,
                    "player2": p2,
                    "label": f"{division_label} | {p1} vs. {p2}",
                }
            )

    return out[:25]


def collect_open_cup_matches_for_member(name_candidates: list[str]) -> list[dict]:
    targets = {normalize_name(x) for x in name_candidates if x}
    matches = load_open_cup_matches()

    out = []
    for match in matches:
        p1 = match["player1"]
        p2 = match["player2"]

        if normalize_name(p1) not in targets and normalize_name(p2) not in targets:
            continue

        out.append(
            {
                "kind": "cup",
                "row_index": match["row"],
                "round": match["round"],
                "mode": match["mode"],
                "player1": p1,
                "player2": p2,
                "result": match["result"],
                "date_value": match["date_value"],
                "label": f"{match['round']} | {p1} vs. {p2}",
                "raw_match": match,
            }
        )

    return out[:25]


# =========================================================
# BASIS
# =========================================================
class PlanBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Dieses Menü gehört nicht dir.",
                ephemeral=True,
            )
            return False
        return True


class PlanPlaceholderView(PlanBaseView):
    def __init__(self, owner_id: int, back_view: discord.ui.View, back_content: str):
        super().__init__(owner_id)
        self.back_view = back_view
        self.back_content = back_content

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.back_content,
            view=self.back_view,
        )


# =========================================================
# DATE/TIME MODAL LEAGUE
# =========================================================
class LeaguePlanDateTimeModal(discord.ui.Modal, title="Datum und Uhrzeit"):
    date_input = discord.ui.TextInput(
        label="Datum",
        placeholder="26.03.2026",
        required=True,
        max_length=10,
    )

    time_input = discord.ui.TextInput(
        label="Uhrzeit",
        placeholder="20:30",
        required=True,
        max_length=5,
    )

    def __init__(self, parent_view: "LeaguePlanDetailView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        date_str = str(self.date_input).strip()
        time_str = str(self.time_input).strip()

        try:
            parse_berlin_datetime(date_str, time_str)
        except ValueError:
            await interaction.response.send_message(
                "Ungültiges Format. Datum: TT.MM.JJJJ und Uhrzeit: HH:MM",
                ephemeral=True,
            )
            return

        self.parent_view.date_str = date_str
        self.parent_view.time_str = time_str

        await interaction.response.edit_message(
            content=self.parent_view.render_text(),
            view=self.parent_view,
        )


# =========================================================
# LEAGUE
# =========================================================
class LeaguePlanMatchSelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        self.matches = {str(i): m for i, m in enumerate(matches)}

        options = [
            discord.SelectOption(label=m["label"][:100], value=str(i))
            for i, m in enumerate(matches[:25])
        ]

        super().__init__(
            placeholder="League-Spiel auswählen …",
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

        view = LeaguePlanDetailView(
            owner_id=interaction.user.id,
            match_data=match_data,
            modes=modes,
        )

        await interaction.edit_original_response(
            content=view.render_text(),
            view=view,
        )


class LeaguePlanListView(PlanBaseView):
    def __init__(self, owner_id: int, matches: list[dict]):
        super().__init__(owner_id)
        self.add_item(LeaguePlanMatchSelect(matches))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spiel planen**\nWähle einen Bereich:",
            view=PlanMenuView(owner_id=interaction.user.id),
        )


class LeagueModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str]):
        options = [discord.SelectOption(label=m[:100], value=m) for m in modes[:25]]
        super().__init__(
            placeholder="Modus wählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, LeaguePlanDetailView):
            return

        view.selected_mode = self.values[0]
        await interaction.response.edit_message(
            content=view.render_text(),
            view=view,
        )


class LeaguePlanDetailView(PlanBaseView):
    def __init__(self, owner_id: int, match_data: dict, modes: list[str]):
        super().__init__(owner_id, timeout=600)
        self.match_data = match_data
        self.selected_mode: str | None = None
        self.date_str: str | None = None
        self.time_str: str | None = None

        self.add_item(LeagueModeSelect(modes))

    def render_text(self) -> str:
        lines = [
            "**Spiel planen → League**",
            f"**Spiel:** {self.match_data['label']}",
            f"**Spieler 1:** {self.match_data['player1']}",
            f"**Spieler 2:** {self.match_data['player2']}",
        ]

        if self.selected_mode:
            lines.append(f"**Modus:** {self.selected_mode}")
        if self.date_str:
            lines.append(f"**Datum:** {self.date_str}")
        if self.time_str:
            lines.append(f"**Uhrzeit:** {self.time_str}")

        return "\n".join(lines)

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=1)
    async def datetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LeaguePlanDateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=1)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_mode or not self.date_str or not self.time_str:
            await interaction.response.send_message(
                "Es fehlen noch Angaben.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Der Befehl funktioniert nur auf dem Server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            start_dt = parse_berlin_datetime(self.date_str, self.time_str)
            end_dt = start_dt + timedelta(hours=2)
            location = build_multistream_url(
                self.match_data["player1"],
                self.match_data["player2"],
            )
            title = (
                f"{self.match_data['division']} | "
                f"{self.match_data['player1']} vs. {self.match_data['player2']} | "
                f"{self.selected_mode}"
            )

            await create_scheduled_event(
                interaction.guild,
                title,
                location,
                start_dt,
                end_dt,
                (
                    f"League-Match in {self.match_data['division']} zwischen "
                    f"{self.match_data['player1']} und {self.match_data['player2']}."
                ),
            )

            await interaction.edit_original_response(
                content=f"✅ Event erstellt:\n**{title}**",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Event konnte nicht erstellt werden: {e}",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spiel planen → League**\nWähle ein Spiel:",
            view=PlanMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# CUP
# =========================================================
class CupPlanMatchSelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        self.matches = {str(i): m for i, m in enumerate(matches)}

        options = [
            discord.SelectOption(label=m["label"][:100], value=str(i))
            for i, m in enumerate(matches[:25])
        ]

        super().__init__(
            placeholder="Cup-Spiel auswählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        match_data = self.matches[self.values[0]]["raw_match"]
        await interaction.response.send_modal(CupTerminModal(match_data))


class CupPlanListView(PlanBaseView):
    def __init__(self, owner_id: int, matches: list[dict]):
        super().__init__(owner_id)
        self.add_item(CupPlanMatchSelect(matches))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spiel planen**\nWähle einen Bereich:",
            view=PlanMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# PLAN MENU
# =========================================================
class PlanMenuView(PlanBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            matches = await asyncio.to_thread(
                collect_open_league_matches_for_member,
                get_member_name_candidates(member),
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Laden der League-Spiele: {e}",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
            return

        if not matches:
            await interaction.edit_original_response(
                content="**Spiel planen → League**\nKeine offenen League-Spiele für dich gefunden.",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
            return

        await interaction.edit_original_response(
            content="**Spiel planen → League**\nWähle ein Spiel:",
            view=LeaguePlanListView(owner_id=interaction.user.id, matches=matches),
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            matches = await asyncio.to_thread(
                collect_open_cup_matches_for_member,
                get_member_name_candidates(member),
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Laden der Cup-Spiele: {e}",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
            return

        if not matches:
            await interaction.edit_original_response(
                content="**Spiel planen → Cup**\nKeine offenen Cup-Spiele für dich gefunden.",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
            return

        await interaction.edit_original_response(
            content="**Spiel planen → Cup**\nWähle ein Spiel:",
            view=CupPlanListView(owner_id=interaction.user.id, matches=matches),
        )

    @discord.ui.button(label="Async beantragen", style=discord.ButtonStyle.secondary, row=1)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
            return

        if not matches:
            await interaction.edit_original_response(
                content="**Spiel planen → Async beantragen**\nKeine offenen League- oder Cup-Spiele für dich gefunden.",
                view=PlanPlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=PlanMenuView(owner_id=interaction.user.id),
                    back_content="**Spiel planen**\nWähle einen Bereich:",
                ),
            )
            return

        await interaction.edit_original_response(
            content="**Spiel planen → Async beantragen**\nWähle ein Spiel:",
            view=AsyncRequestMatchListView(
                owner_id=interaction.user.id,
                matches=matches,
                requester_member=member,
            ),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import PlayerMenuView

        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id),
        )

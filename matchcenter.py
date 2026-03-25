import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple


# =========================================================
# KONFIG / HILFSFUNKTIONEN
# =========================================================

GUILD_ID = 123456789012345678  # TODO
EVENT_CHANNEL_ID = 123456789012345678  # TODO: Kanal für Discord-Events / Terminposts
LEAGUE_RESULT_CHANNEL_ID = 123456789012345678  # TODO
CUP_RESULT_CHANNEL_ID = 123456789012345678  # TODO

CUP_ROUNDS = [
    "Vorrunde",
    "Last 32",
    "Last 16",
    "Quarterfinals",
    "Semifinals",
    "Finals",
]

DIVISIONS = [
    "Div 1",
    "Div 2",
    "Div 3",
    "Div 4",
    "Div 5",
    "Div 6",
]


def parse_matchup(match_text: str) -> Tuple[str, str]:
    parts = [p.strip() for p in match_text.split("vs.")]
    if len(parts) != 2:
        return match_text.strip(), ""
    return parts[0], parts[1]


def normalize_result(winner_value: str) -> str:
    mapping = {
        "spieler1": "2:0",
        "spieler2": "0:2",
        "remis": "1:1",
    }
    return mapping.get(winner_value, "")


def normalize_cup_result(winner_value: str) -> str:
    mapping = {
        "spieler1": "1:0",
        "spieler2": "0:1",
    }
    return mapping.get(winner_value, "")


def parse_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")


# =========================================================
# TODO: SHEETS / DATENANBINDUNG
# Diese Funktionen musst du an dein bestehendes Sheets-Setup hängen
# =========================================================

def get_runner_modes() -> List[str]:
    """
    Lädt Sheet 'Runner', Spalte N.
    Doppelte / leere Werte entfernen.
    """
    # TODO: Aus Google Sheet lesen
    return [
        "Classic",
        "All Dungeons",
        "Open",
        "Inverted",
        "Mystery",
    ]


def get_division_players(division: str) -> List[str]:
    """
    Liefert Spieler einer Division.
    """
    # TODO: Aus deiner League-Tabelle lesen
    demo = {
        "Div 1": ["crackerito", "RoterAlarm", "Blackirave", "NTapple"],
        "Div 2": ["Spieler A", "Spieler B", "Spieler C"],
        "Div 3": ["Spieler D", "Spieler E"],
        "Div 4": ["Spieler F", "Spieler G"],
        "Div 5": ["Spieler H", "Spieler I"],
        "Div 6": ["Spieler J", "Spieler K"],
    }
    return demo.get(division, [])


def get_league_home_matches(division: str, home_player: str) -> List[str]:
    """
    Liefert alle Spiele, in denen home_player Heimrecht hat.
    Rückgabeformat: 'Spieler1 vs. Spieler2'
    """
    # TODO: Aus Divisionstabelle lesen
    demo = {
        ("Div 1", "crackerito"): [
            "crackerito vs. RoterAlarm",
            "crackerito vs. Blackirave",
        ],
        ("Div 1", "RoterAlarm"): [
            "RoterAlarm vs. NTapple",
        ],
    }
    return demo.get((division, home_player), [])


def get_cup_matches() -> List[str]:
    """
    Alle Spiele aus 'TFL Cup', in denen in Spalte C 'vs' vorkommt.
    """
    # TODO: Aus TFL Cup lesen
    return [
        "Spieler A vs. Spieler B",
        "Spieler C vs. Spieler D",
        "Spieler E vs. Spieler F",
    ]


def get_multistream_link(player1: str, player2: str) -> str:
    """
    Multistream-Link aus Mapping beider Spieler.
    """
    # TODO: echtes Mapping verwenden
    mapping = {
        "crackerito": "https://twitch.tv/crackerito",
        "RoterAlarm": "https://twitch.tv/roteralarm",
        "Blackirave": "https://twitch.tv/blackirave",
        "NTapple": "https://twitch.tv/ntapple",
        "Spieler A": "https://twitch.tv/spieler_a",
        "Spieler B": "https://twitch.tv/spieler_b",
    }

    p1 = mapping.get(player1)
    p2 = mapping.get(player2)

    if p1 and p2:
        # TODO: echte Multistream-Logik
        return f"{p1} | {p2}"
    return p1 or p2 or "Kein Multistream-Link gefunden"


def write_league_result(
    division: str,
    match_text: str,
    mode: str,
    result: str,
    racetime_link: str,
    entered_by: str,
    timestamp: str,
) -> bool:
    """
    Schreibe in passende Zeile der Divisionstabelle:
    B = Zeitstempel
    C = Modus
    E = Ergebnis
    G = Racetime
    H = Discordname
    """
    # TODO: konkrete Sheets-Logik
    print("[LEAGUE WRITE]", division, match_text, mode, result, racetime_link, entered_by, timestamp)
    return True


def write_cup_result(
    round_name: str,
    match_text: str,
    result: str,
    racetime_link: str,
    entered_meta: str,
) -> bool:
    """
    C = Ergebnis
    E = Racetime
    F = Eingebender + Zeitstempel
    """
    # TODO: konkrete Sheets-Logik
    print("[CUP WRITE]", round_name, match_text, result, racetime_link, entered_meta)
    return True


# =========================================================
# DISCORD EVENT / POSTS
# =========================================================

async def create_discord_scheduled_event(
    guild: discord.Guild,
    title: str,
    location: str,
    start_dt: datetime,
    end_dt: datetime,
    description: Optional[str] = None,
) -> Optional[discord.ScheduledEvent]:
    try:
        event = await guild.create_scheduled_event(
            name=title,
            description=description or "",
            start_time=start_dt,
            end_time=end_dt,
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
            location=location,
        )
        return event
    except Exception as e:
        print(f"Fehler beim Erstellen des Events: {e}")
        return None


async def send_result_message(channel: discord.TextChannel, text: str) -> None:
    try:
        await channel.send(text)
    except Exception as e:
        print(f"Fehler beim Senden der Ergebnismeldung: {e}")


# =========================================================
# STATE
# =========================================================

class MatchCenterState:
    def __init__(self):
        self.kind: Optional[str] = None  # term_league / term_cup / result_league / result_cup

        self.division: Optional[str] = None
        self.home_player: Optional[str] = None
        self.match_text: Optional[str] = None
        self.mode: Optional[str] = None

        self.cup_round: Optional[str] = None

        self.winner: Optional[str] = None
        self.racetime_link: Optional[str] = None

        self.date_str: Optional[str] = None
        self.time_str: Optional[str] = None

    def reset(self):
        self.__init__()


# =========================================================
# MODALS
# =========================================================

class DateTimeModal(discord.ui.Modal, title="Datum und Uhrzeit eingeben"):
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

    def __init__(self, parent_view: "BaseFlowView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.state.date_str = str(self.date_input).strip()
        self.parent_view.state.time_str = str(self.time_input).strip()

        try:
            parse_datetime(self.parent_view.state.date_str, self.parent_view.state.time_str)
        except ValueError:
            await interaction.response.send_message(
                "Ungültiges Format. Datum: TT.MM.JJJJ und Uhrzeit: HH:MM",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=self.parent_view.render_summary(),
            view=self.parent_view
        )


class RacetimeModal(discord.ui.Modal, title="Racetime-Link eingeben"):
    racetime_input = discord.ui.TextInput(
        label="Racetime-Link",
        placeholder="https://racetime.gg/...",
        required=True,
        style=discord.TextStyle.short,
        max_length=200,
    )

    def __init__(self, parent_view: "BaseFlowView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.state.racetime_link = str(self.racetime_input).strip()
        await interaction.response.edit_message(
            content=self.parent_view.render_summary(),
            view=self.parent_view
        )


# =========================================================
# BASIS-VIEW
# =========================================================

class BaseFlowView(discord.ui.View):
    def __init__(self, cog: "MatchCenterCog", author_id: int, timeout: int = 900):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.state = MatchCenterState()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Dieses Fenster gehört nicht dir.",
                ephemeral=True
            )
            return False
        return True

    def render_summary(self) -> str:
        s = self.state
        lines = ["## Matchcenter"]

        if s.kind:
            lines.append(f"**Typ:** {s.kind}")

        if s.division:
            lines.append(f"**Division:** {s.division}")
        if s.home_player:
            lines.append(f"**Heimrecht:** {s.home_player}")
        if s.cup_round:
            lines.append(f"**Runde:** {s.cup_round}")
        if s.match_text:
            lines.append(f"**Spiel:** {s.match_text}")
        if s.mode:
            lines.append(f"**Modus:** {s.mode}")
        if s.winner:
            lines.append(f"**Gewinner:** {s.winner}")
        if s.date_str:
            lines.append(f"**Datum:** {s.date_str}")
        if s.time_str:
            lines.append(f"**Uhrzeit:** {s.time_str}")
        if s.racetime_link:
            lines.append(f"**Racetime:** {s.racetime_link}")

        return "\n".join(lines)


# =========================================================
# START-VIEW
# =========================================================

class MatchCenterStartView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)

    @discord.ui.button(label="Termin League", style=discord.ButtonStyle.primary, row=0)
    async def termin_league(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LeagueScheduleView(self.cog, self.author_id)
        view.state.kind = "Termin League"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )

    @discord.ui.button(label="Termin Cup", style=discord.ButtonStyle.primary, row=0)
    async def termin_cup(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CupScheduleView(self.cog, self.author_id)
        view.state.kind = "Termin Cup"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )

    @discord.ui.button(label="Ergebnis League", style=discord.ButtonStyle.success, row=1)
    async def result_league(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LeagueResultView(self.cog, self.author_id)
        view.state.kind = "Ergebnis League"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )

    @discord.ui.button(label="Ergebnis Cup", style=discord.ButtonStyle.success, row=1)
    async def result_cup(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CupResultView(self.cog, self.author_id)
        view.state.kind = "Ergebnis Cup"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


# =========================================================
# LEAGUE TERMIN
# =========================================================

class DivisionSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=d, value=d) for d in DIVISIONS]
        super().__init__(
            placeholder="Welche Division?",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: LeagueScheduleView = self.view  # type: ignore
        view.state.division = self.values[0]
        view.refresh_dynamic_items()
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class HomePlayerSelect(discord.ui.Select):
    def __init__(self, players: List[str]):
        options = [discord.SelectOption(label=p, value=p) for p in players[:25]]
        super().__init__(
            placeholder="Wer hat Heimrecht?",
            options=options,
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: LeagueScheduleView = self.view  # type: ignore
        view.state.home_player = self.values[0]
        view.refresh_dynamic_items()
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class MatchSelect(discord.ui.Select):
    def __init__(self, matches: List[str], row: int = 2):
        options = [discord.SelectOption(label=m[:100], value=m) for m in matches[:25]]
        super().__init__(
            placeholder="Spiel auswählen",
            options=options,
            min_values=1,
            max_values=1,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view  # type: ignore
        view.state.match_text = self.values[0]
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class ModeSelect(discord.ui.Select):
    def __init__(self, modes: List[str], row: int = 3):
        options = [discord.SelectOption(label=m[:100], value=m) for m in modes[:25]]
        super().__init__(
            placeholder="Welcher Modus?",
            options=options,
            min_values=1,
            max_values=1,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view  # type: ignore
        view.state.mode = self.values[0]
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class LeagueScheduleView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(DivisionSelect())
        self.add_item(ModeSelect(get_runner_modes(), row=3))

    def refresh_dynamic_items(self):
        # vorhandene dynamische Elemente entfernen
        to_remove = []
        for item in self.children:
            if isinstance(item, (HomePlayerSelect, MatchSelect)):
                to_remove.append(item)
        for item in to_remove:
            self.remove_item(item)

        if self.state.division:
            players = get_division_players(self.state.division)
            if players:
                self.add_item(HomePlayerSelect(players))

        if self.state.division and self.state.home_player:
            matches = get_league_home_matches(self.state.division, self.state.home_player)
            if matches:
                self.add_item(MatchSelect(matches, row=2))

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=4)
    async def datetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=4)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.division, s.home_player, s.match_text, s.mode, s.date_str, s.time_str]):
            await interaction.response.send_message(
                "Es fehlen noch Angaben.",
                ephemeral=True
            )
            return

        player1, player2 = parse_matchup(s.match_text)
        location = get_multistream_link(player1, player2)

        try:
            start_dt = parse_datetime(s.date_str, s.time_str)
            end_dt = start_dt + timedelta(hours=2)
        except ValueError:
            await interaction.response.send_message(
                "Datum/Uhrzeit ungültig.",
                ephemeral=True
            )
            return

        title = f"{s.division} | {player1} vs. {player2} | {s.mode}"

        event = await create_discord_scheduled_event(
            guild=interaction.guild,
            title=title,
            location=location,
            start_dt=start_dt,
            end_dt=end_dt,
            description="League-Match aus dem Matchcenter"
        )

        if event:
            await interaction.response.send_message(
                f"Event erstellt: **{title}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Event konnte nicht erstellt werden.",
                ephemeral=True
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=4)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## Matchcenter",
            view=view
        )


# =========================================================
# CUP TERMIN
# =========================================================

class CupRoundSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=r, value=r) for r in CUP_ROUNDS]
        super().__init__(
            placeholder="Welche Runde?",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view  # type: ignore
        view.state.cup_round = self.values[0]
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class CupScheduleView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(CupRoundSelect())
        self.add_item(MatchSelect(get_cup_matches(), row=1))
        self.add_item(ModeSelect(get_runner_modes(), row=2))

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=3)
    async def datetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=3)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.cup_round, s.match_text, s.mode, s.date_str, s.time_str]):
            await interaction.response.send_message(
                "Es fehlen noch Angaben.",
                ephemeral=True
            )
            return

        player1, player2 = parse_matchup(s.match_text)
        location = get_multistream_link(player1, player2)

        try:
            start_dt = parse_datetime(s.date_str, s.time_str)
            end_dt = start_dt + timedelta(hours=2)
        except ValueError:
            await interaction.response.send_message(
                "Datum/Uhrzeit ungültig.",
                ephemeral=True
            )
            return

        title = f"TFL Cup {s.cup_round} | {player1} vs. {player2} | {s.mode}"

        event = await create_discord_scheduled_event(
            guild=interaction.guild,
            title=title,
            location=location,
            start_dt=start_dt,
            end_dt=end_dt,
            description="Cup-Match aus dem Matchcenter"
        )

        if event:
            await interaction.response.send_message(
                f"Event erstellt: **{title}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Event konnte nicht erstellt werden.",
                ephemeral=True
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## Matchcenter",
            view=view
        )


# =========================================================
# LEAGUE ERGEBNIS
# =========================================================

class WinnerLeagueSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1", value="spieler1"),
            discord.SelectOption(label="Spieler 2", value="spieler2"),
            discord.SelectOption(label="Remis", value="remis"),
        ]
        super().__init__(
            placeholder="Wer hat gewonnen?",
            options=options,
            min_values=1,
            max_values=1,
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view  # type: ignore
        view.state.winner = self.values[0]
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class LeagueResultView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(DivisionSelect())
        self.add_item(ModeSelect(get_runner_modes(), row=3))
        self.add_item(WinnerLeagueSelect())

    def refresh_dynamic_items(self):
        to_remove = []
        for item in self.children:
            if isinstance(item, (HomePlayerSelect, MatchSelect)):
                to_remove.append(item)
        for item in to_remove:
            self.remove_item(item)

        if self.state.division:
            players = get_division_players(self.state.division)
            if players:
                self.add_item(HomePlayerSelect(players))

        if self.state.division and self.state.home_player:
            matches = get_league_home_matches(self.state.division, self.state.home_player)
            if matches:
                self.add_item(MatchSelect(matches, row=2))

    @discord.ui.button(label="Racetime-Link", style=discord.ButtonStyle.secondary, row=5)
    async def racetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RacetimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=5)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.division, s.home_player, s.match_text, s.mode, s.winner, s.racetime_link]):
            await interaction.response.send_message(
                "Es fehlen noch Angaben.",
                ephemeral=True
            )
            return

        result = normalize_result(s.winner)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        entered_by = interaction.user.display_name

        ok = write_league_result(
            division=s.division,
            match_text=s.match_text,
            mode=s.mode,
            result=result,
            racetime_link=s.racetime_link,
            entered_by=entered_by,
            timestamp=timestamp,
        )

        if not ok:
            await interaction.response.send_message(
                "Ergebnis konnte nicht ins Sheet geschrieben werden.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(LEAGUE_RESULT_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            player1, player2 = parse_matchup(s.match_text)
            text = (
                f"[TFL League] {timestamp}\n"
                f"{s.division}\n"
                f"{player1} vs. {player2} -> {result}\n"
                f"Modus: {s.mode}\n"
                f"Racetime: {s.racetime_link}\n"
                f"Eingetragen von: {entered_by}"
            )
            await send_result_message(channel, text)

        await interaction.response.send_message(
            "League-Ergebnis eingetragen.",
            ephemeral=True
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=5)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## Matchcenter",
            view=view
        )


# =========================================================
# CUP ERGEBNIS
# =========================================================

class WinnerCupSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1", value="spieler1"),
            discord.SelectOption(label="Spieler 2", value="spieler2"),
        ]
        super().__init__(
            placeholder="Wer hat gewonnen?",
            options=options,
            min_values=1,
            max_values=1,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view  # type: ignore
        view.state.winner = self.values[0]
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class CupResultView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(CupRoundSelect())
        self.add_item(MatchSelect(get_cup_matches(), row=1))
        self.add_item(WinnerCupSelect())

    @discord.ui.button(label="Racetime-Link", style=discord.ButtonStyle.secondary, row=3)
    async def racetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RacetimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=3)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.cup_round, s.match_text, s.winner, s.racetime_link]):
            await interaction.response.send_message(
                "Es fehlen noch Angaben.",
                ephemeral=True
            )
            return

        # Hinweis nur als Guard / Info
        if s.cup_round in ["Semifinals", "Finals"]:
            # Best of 3 Hinweis. Speicherung bleibt hier wie von dir gewünscht 1:0 / 0:1.
            pass

        result = normalize_cup_result(s.winner)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        entered_meta = f"{interaction.user.display_name} | {timestamp}"

        ok = write_cup_result(
            round_name=s.cup_round,
            match_text=s.match_text,
            result=result,
            racetime_link=s.racetime_link,
            entered_meta=entered_meta,
        )

        if not ok:
            await interaction.response.send_message(
                "Cup-Ergebnis konnte nicht ins Sheet geschrieben werden.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(CUP_RESULT_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            player1, player2 = parse_matchup(s.match_text)
            text = (
                f"[TFL Cup] {timestamp}\n"
                f"Runde: {s.cup_round}\n"
                f"{player1} vs. {player2} -> {result}\n"
                f"Racetime: {s.racetime_link}\n"
                f"Eingetragen von: {interaction.user.display_name}"
            )
            await send_result_message(channel, text)

        await interaction.response.send_message(
            "Cup-Ergebnis eingetragen.",
            ephemeral=True
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## Matchcenter",
            view=view
        )


# =========================================================
# COG
# =========================================================

class MatchCenterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="matchcenter", description="Öffnet das TFL Matchcenter.")
    async def matchcenter(self, interaction: discord.Interaction):
        view = MatchCenterStartView(self, interaction.user.id)
        await interaction.response.send_message(
            "## Matchcenter",
            view=view,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCenterCog(bot))

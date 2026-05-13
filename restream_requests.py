import asyncio
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime as dt, timedelta, time

import discord
import pytz
from discord import app_commands
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

BERLIN_TZ = pytz.timezone("Europe/Berlin")

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

# Zielkanal: tägliche kompakte Liste der Spiele, die für Restreams auswählbar sind
RESTREAMABLE_CHANNEL_ID = int(os.getenv("RESTREAMABLE_CHANNEL_ID", "1405291916387422228"))

# Zielkanal: finale Restream-Ankündigungen
# Wichtig: NICHT RESTREAM_CHANNEL_ID als Fallback nutzen, weil diese Variable in bot.py ggf. anders belegt ist.
RESTREAMS_CHANNEL_ID = int(os.getenv("RESTREAMS_CHANNEL_ID", "1277949546650931241"))

ZSRDE_RESTREAM_URL = os.getenv(
    "ZSRDE_RESTREAM_URL",
    os.getenv("ZSR_RESTREAM_URL", "https://www.twitch.tv/ZeldaSpeedRunsDE"),
)

DRR_RESTREAM_URL = os.getenv(
    "DRR_RESTREAM_URL",
    "https://www.twitch.tv/DeutscheRandoRestreams",
)

RESTREAM_TARGETS = {
    "ZSRDE": ZSRDE_RESTREAM_URL,
    "DRR": DRR_RESTREAM_URL,
    "Privat": "",
}

EVENT_TITLE_FILTERS = (
    "Div 1",
    "Div 2",
    "Div 3",
    "Div 4",
    "Div 5",
    "Div 6",
    "TFL Cup",
)


# =========================================================
# STATE
# =========================================================

@dataclass
class RestreamRequest:
    request_id: str
    guild_id: int
    event_id: int
    event_title: str
    event_start_text: str
    area: str
    player1: str
    player2: str
    mode: str
    requester_id: int
    requester_name: str
    target: str
    link: str
    commentator: str
    co_commentator: str
    tracker: str
    approvals: dict[int, bool] = field(default_factory=dict)
    player_member_ids: list[int] = field(default_factory=list)
    declined: bool = False
    finalized: bool = False


REQUESTS: dict[str, RestreamRequest] = {}


# =========================================================
# HELFER
# =========================================================

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_lookup(value: str) -> str:
    value = clean_text(value).lower()
    return re.sub(r"[^a-z0-9äöüß]", "", value)


def short_text(value: str, limit: int) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def format_event_start(start_time) -> str:
    if not start_time:
        return "unbekannter Termin"

    try:
        if start_time.tzinfo is None:
            start_time = pytz.utc.localize(start_time)
        local = start_time.astimezone(BERLIN_TZ)
        return local.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(start_time)


def format_event_start_long(start_time) -> str:
    if not start_time:
        return "unbekannter Termin"

    try:
        if start_time.tzinfo is None:
            start_time = pytz.utc.localize(start_time)
        local = start_time.astimezone(BERLIN_TZ)
        return local.strftime("%d.%m.%Y um %H:%M Uhr")
    except Exception:
        return str(start_time)


def parse_event_title(event: discord.ScheduledEvent) -> dict:
    """
    Erkennt mehrere Titelvarianten:

    Standard:
    Div 1 | Spieler1 vs. Spieler2 | Modus
    TFL Cup | Spieler1 vs. Spieler2 | Runde

    Bereits aktualisierte Restream-Events:
    RESTREAM ZSRDE | Div 1 | Spieler1 vs. Spieler2 | Modus

    Fallback:
    sucht den Teil mit "vs" und nimmt davor Bereich, danach Modus.
    """
    title = clean_text(event.name)
    parts = [clean_text(p) for p in title.split("|") if clean_text(p)]

    # Falls Event bereits als Restream markiert ist:
    # RESTREAM ZSRDE | Div X | Spieler1 vs. Spieler2 | Modus
    if parts and parts[0].upper().startswith("RESTREAM "):
        parts = parts[1:]

    area = ""
    match = ""
    mode = ""

    # Robust: Teil mit vs suchen
    match_index = None
    for i, part in enumerate(parts):
        normalized = part.replace(" vs. ", " vs ").replace(" VS ", " vs ")
        if " vs " in normalized:
            match_index = i
            break

    if match_index is not None:
        match = parts[match_index]
        area = parts[match_index - 1] if match_index > 0 else ""
        mode = parts[match_index + 1] if match_index + 1 < len(parts) else ""
    elif len(parts) >= 3:
        area = parts[0]
        match = parts[1]
        mode = parts[2]
    elif len(parts) == 2:
        area = parts[0]
        match = parts[1]
        mode = ""
    else:
        area = ""
        match = title
        mode = ""

    match_clean = match.replace(" vs. ", " vs ").replace(" VS ", " vs ")
    if " vs " in match_clean:
        player1, player2 = [clean_text(x) for x in match_clean.split(" vs ", 1)]
    else:
        player1, player2 = "", ""

    if area == "TFL Cup" and mode:
        mode_text = f"Cup / {mode}"
    else:
        mode_text = mode or "unbekannter Modus"

    return {
        "title": title,
        "area": area,
        "match": match,
        "player1": player1,
        "player2": player2,
        "mode": mode_text,
    }


def event_is_tfl_match(event: discord.ScheduledEvent) -> bool:
    title = clean_text(event.name)

    if title.startswith("RESTREAM "):
        return False

    return any(token in title for token in EVENT_TITLE_FILTERS)


def get_event_location(event: discord.ScheduledEvent) -> str:
    try:
        if getattr(event, "entity_metadata", None):
            location = getattr(event.entity_metadata, "location", None)
            if location:
                return location

        location = getattr(event, "location", None)
        if location:
            return location
    except Exception:
        pass

    return ""


async def fetch_all_scheduled_events(guild: discord.Guild) -> list[discord.ScheduledEvent]:
    try:
        events = await guild.fetch_scheduled_events(with_counts=False)
    except TypeError:
        events = await guild.fetch_scheduled_events()
    except Exception:
        events = list(getattr(guild, "scheduled_events", []) or [])

    return list(events or [])


async def find_member_by_player_name(guild: discord.Guild, player_name: str) -> discord.Member | None:
    target = normalize_lookup(player_name)

    if not target:
        return None

    # Erst Cache durchsuchen
    for member in guild.members:
        candidates = [
            member.display_name,
            member.name,
            getattr(member, "global_name", None),
        ]

        for candidate in candidates:
            if normalize_lookup(candidate or "") == target:
                return member

    # Fallback: Discord-Suche
    try:
        found = await guild.query_members(query=player_name, limit=10)
        for member in found:
            candidates = [
                member.display_name,
                member.name,
                getattr(member, "global_name", None),
            ]

            for candidate in candidates:
                if normalize_lookup(candidate or "") == target:
                    return member
    except Exception:
        pass

    return None


async def get_scheduled_event_by_id(guild: discord.Guild, event_id: int) -> discord.ScheduledEvent | None:
    events = await fetch_all_scheduled_events(guild)

    for event in events:
        if int(event.id) == int(event_id):
            return event

    return None


async def send_dm_safe(member: discord.Member | discord.User, content: str, view: discord.ui.View | None = None) -> bool:
    try:
        await member.send(content, view=view)
        return True
    except discord.Forbidden:
        print(f"⚠️ DM blockiert/deaktiviert bei {getattr(member, 'display_name', member)}")
    except Exception as e:
        print(f"⚠️ Fehler beim DM-Versand an {getattr(member, 'display_name', member)}: {e}")

    return False


def build_restream_post(req: RestreamRequest) -> str:
    team_parts = []

    if req.commentator:
        team_parts.append(f"🎙️ {req.commentator}")
    if req.co_commentator:
        team_parts.append(f"🎙️ {req.co_commentator}")
    if req.tracker:
        team_parts.append(f"🧭 {req.tracker}")

    team_text = " · ".join(team_parts) if team_parts else "Team folgt"

    return (
        "📺 **RESTREAM-ANKÜNDIGUNG**\n"
        f"**{req.area} · {req.player1} vs. {req.player2}**\n"
        f"🕒 {req.event_start_text} · 🎮 {req.mode}\n"
        f"📡 **{req.target}:** {req.link}\n"
        f"👥 {team_text}\n"
        "Interview nach dem Race: optional."
    )


def build_dm_request_text(req: RestreamRequest) -> str:
    return (
        f"**{req.area}: {req.player1} vs. {req.player2}**, {req.mode} am "
        f"**{req.event_start_text}** wurde von **{req.requester_name}** "
        f"für einen Restream auf {req.link} ausgewählt.\n\n"
        "Ein anschließendes Interview ist immer optional.\n\n"
        "Bitte bestätigen oder ablehnen."
    )


async def notify_requester(bot: commands.Bot, req: RestreamRequest, content: str, view: discord.ui.View | None = None):
    requester = bot.get_user(req.requester_id)

    if requester is None:
        try:
            requester = await bot.fetch_user(req.requester_id)
        except Exception:
            requester = None

    if requester:
        await send_dm_safe(requester, content, view=view)


async def finalize_restream(bot: commands.Bot, guild: discord.Guild, req: RestreamRequest):
    if req.finalized:
        return

    restream_channel = guild.get_channel(RESTREAMS_CHANNEL_ID)

    if restream_channel is None:
        try:
            restream_channel = await guild.fetch_channel(RESTREAMS_CHANNEL_ID)
        except Exception:
            restream_channel = None

    if restream_channel is None or not hasattr(restream_channel, "send"):
        raise RuntimeError(f"Ankündigungs-Kanal nicht gefunden oder nicht beschreibbar: {RESTREAMS_CHANNEL_ID}")

    await restream_channel.send(build_restream_post(req))
    print(f"✅ Restream-Ankündigung gesendet in Kanal {RESTREAMS_CHANNEL_ID}")

    event = await get_scheduled_event_by_id(guild, req.event_id)

    if event is not None:
        old_name = event.name

        if old_name.startswith("RESTREAM "):
            new_name = old_name
        else:
            new_name = f"RESTREAM {req.target} | {old_name}"

        old_description = event.description or ""
        restream_block = (
            "\n\n"
            "📺 Restream\n"
            f"Ziel: {req.target}\n"
            f"Link: {req.link}\n"
            f"Kommentator: {req.commentator or '-'}\n"
            f"Co-Kommentator: {req.co_commentator or '-'}\n"
            f"Tracker: {req.tracker or '-'}\n"
            "Interview: optional"
        )

        if "📺 Restream" not in old_description:
            new_description = old_description + restream_block
        else:
            new_description = old_description

        try:
            await event.edit(
                name=new_name[:100],
                description=new_description[:1000],
                location=req.link,
            )
        except TypeError:
            await event.edit(
                name=new_name[:100],
                description=new_description[:1000],
            )
            print("⚠️ Event-Ort konnte nicht editiert werden: discord.py unterstützt location hier nicht.")
        except Exception as e:
            print(f"⚠️ Event konnte nicht vollständig aktualisiert werden: {e}")

    req.finalized = True


# =========================================================
# VIEWS
# =========================================================

class RestreamEventSelect(discord.ui.Select):
    def __init__(self, events: list[discord.ScheduledEvent]):
        options = []

        for event in events[:25]:
            parsed = parse_event_title(event)
            label = short_text(f"{format_event_start(event.start_time)} | {parsed['area'] or '-'} | {parsed['match'] or event.name}", 100)
            description = short_text(f"{parsed['mode']}", 100)

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(event.id),
                    description=description,
                )
            )

        super().__init__(
            placeholder="Spiel für Restream-Anfrage auswählen …",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="tfl_restream_event_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        event_id = int(self.values[0])

        await interaction.followup.send(
            "Wähle das Restream-Ziel.",
            view=RestreamTargetView(event_id),
            ephemeral=True,
        )


class RestreamEventSelectView(discord.ui.View):
    def __init__(self, events: list[discord.ScheduledEvent]):
        super().__init__(timeout=86400)
        self.add_item(RestreamEventSelect(events))


class RestreamTargetSelect(discord.ui.Select):
    def __init__(self, event_id: int):
        self.event_id = int(event_id)

        options = [
            discord.SelectOption(label="ZSRDE", value="ZSRDE"),
            discord.SelectOption(label="DRR", value="DRR"),
            discord.SelectOption(label="Privat", value="Privat"),
        ]

        super().__init__(
            placeholder="Restream-Ziel wählen …",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"tfl_restream_target_{self.event_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        default_link = RESTREAM_TARGETS.get(target, "")

        await interaction.response.send_modal(
            RestreamRequestModal(
                event_id=self.event_id,
                target=target,
                default_link=default_link,
            )
        )


class RestreamTargetView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=300)
        self.add_item(RestreamTargetSelect(event_id))


class RestreamRequestModal(discord.ui.Modal):
    def __init__(self, event_id: int, target: str, default_link: str):
        super().__init__(title="Restream anfragen")

        self.event_id = int(event_id)
        self.target = target

        self.link_input = discord.ui.TextInput(
            label="Restream-Link",
            default=default_link,
            placeholder="https://www.twitch.tv/...",
            required=True,
            max_length=300,
        )

        self.commentator_input = discord.ui.TextInput(
            label="Kommentator",
            placeholder="optional",
            required=False,
            max_length=100,
        )

        self.co_commentator_input = discord.ui.TextInput(
            label="Co-Kommentator",
            placeholder="optional",
            required=False,
            max_length=100,
        )

        self.tracker_input = discord.ui.TextInput(
            label="Tracker",
            placeholder="optional",
            required=False,
            max_length=100,
        )

        self.add_item(self.link_input)
        self.add_item(self.commentator_input)
        self.add_item(self.co_commentator_input)
        self.add_item(self.tracker_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        link = clean_text(str(self.link_input.value))

        if not link:
            await interaction.response.send_message("Restream-Link fehlt.", ephemeral=True)
            return

        if self.target in {"ZSRDE", "DRR"}:
            expected = RESTREAM_TARGETS.get(self.target, "")
            if expected and link != expected:
                link = expected

        await interaction.response.defer(ephemeral=True)

        event = await get_scheduled_event_by_id(interaction.guild, self.event_id)

        if event is None:
            await interaction.followup.send("Das Discord-Event wurde nicht gefunden.", ephemeral=True)
            return

        parsed = parse_event_title(event)

        if not parsed["player1"] or not parsed["player2"]:
            await interaction.followup.send(
                "Spieler konnten aus dem Event-Titel nicht erkannt werden. Erwartetes Format: `Spieler1 vs. Spieler2`.",
                ephemeral=True,
            )
            return

        p1_member = await find_member_by_player_name(interaction.guild, parsed["player1"])
        p2_member = await find_member_by_player_name(interaction.guild, parsed["player2"])

        missing = []
        if p1_member is None:
            missing.append(parsed["player1"])
        if p2_member is None:
            missing.append(parsed["player2"])

        if missing:
            await interaction.followup.send(
                "Folgende Spieler wurden auf dem Discord nicht gefunden:\n"
                + "\n".join(f"- {name}" for name in missing),
                ephemeral=True,
            )
            return

        request_id = uuid.uuid4().hex[:12]

        req = RestreamRequest(
            request_id=request_id,
            guild_id=int(interaction.guild.id),
            event_id=int(event.id),
            event_title=event.name,
            event_start_text=format_event_start_long(event.start_time),
            area=parsed["area"] or "TFL",
            player1=parsed["player1"],
            player2=parsed["player2"],
            mode=parsed["mode"],
            requester_id=interaction.user.id,
            requester_name=interaction.user.display_name,
            target=self.target,
            link=link,
            commentator=clean_text(str(self.commentator_input.value)),
            co_commentator=clean_text(str(self.co_commentator_input.value)),
            tracker=clean_text(str(self.tracker_input.value)),
            approvals={
                int(p1_member.id): False,
                int(p2_member.id): False,
            },
            player_member_ids=[int(p1_member.id), int(p2_member.id)],
        )

        REQUESTS[request_id] = req

        dm_text = build_dm_request_text(req)

        sent_1 = await send_dm_safe(p1_member, dm_text, view=PlayerApprovalView(request_id))
        sent_2 = await send_dm_safe(p2_member, dm_text, view=PlayerApprovalView(request_id))

        if not sent_1 or not sent_2:
            await interaction.followup.send(
                "Restream-Anfrage wurde erstellt, aber mindestens eine Spieler-DM konnte nicht zugestellt werden.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Restream-Anfrage wurde an beide Spieler per DM verschickt.",
            ephemeral=True,
        )


class PlayerApprovalView(discord.ui.View):
    def __init__(self, request_id: str):
        super().__init__(timeout=7 * 24 * 60 * 60)
        self.request_id = request_id

    @discord.ui.button(label="Bestätigen", style=discord.ButtonStyle.success, custom_id="tfl_restream_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        req = REQUESTS.get(self.request_id)

        if req is None:
            await interaction.response.send_message("Diese Anfrage ist nicht mehr aktiv.", ephemeral=True)
            return

        if req.declined:
            await interaction.response.send_message("Diese Anfrage wurde bereits abgelehnt.", ephemeral=True)
            return

        if req.finalized:
            await interaction.response.send_message("Diese Anfrage wurde bereits eingetragen.", ephemeral=True)
            return

        if interaction.user.id not in req.approvals:
            await interaction.response.send_message("Diese Anfrage gehört nicht zu dir.", ephemeral=True)
            return

        req.approvals[interaction.user.id] = True

        await interaction.response.edit_message(
            content="Du hast den Restream bestätigt.",
            view=None,
        )

        if all(req.approvals.values()):
            await notify_requester(
                interaction.client,
                req,
                (
                    "Beide Spieler haben dem Restream zugestimmt.\n\n"
                    f"**Bereich:** {req.area}\n"
                    f"**Spiel:** {req.player1} vs. {req.player2}\n"
                    f"**Modus:** {req.mode}\n"
                    f"**Termin:** {req.event_start_text}\n"
                    f"**Restream:** {req.target}\n"
                    f"**Link:** {req.link}\n\n"
                    "Klicke auf **Eintragen**, um den Restream zu veröffentlichen und das Discord-Event zu aktualisieren."
                ),
                view=RequesterFinalizeView(req.request_id),
            )

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger, custom_id="tfl_restream_decline")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        req = REQUESTS.get(self.request_id)

        if req is None:
            await interaction.response.send_message("Diese Anfrage ist nicht mehr aktiv.", ephemeral=True)
            return

        if interaction.user.id not in req.approvals:
            await interaction.response.send_message("Diese Anfrage gehört nicht zu dir.", ephemeral=True)
            return

        req.declined = True

        await interaction.response.edit_message(
            content="Du hast den Restream abgelehnt.",
            view=None,
        )

        await notify_requester(
            interaction.client,
            req,
            (
                "Die Restream-Anfrage wurde abgelehnt.\n\n"
                f"**Bereich:** {req.area}\n"
                f"**Spiel:** {req.player1} vs. {req.player2}\n"
                f"**Abgelehnt von:** {interaction.user.display_name}"
            ),
        )


class RequesterFinalizeView(discord.ui.View):
    def __init__(self, request_id: str):
        super().__init__(timeout=7 * 24 * 60 * 60)
        self.request_id = request_id

    @discord.ui.button(label="Eintragen", style=discord.ButtonStyle.success, custom_id="tfl_restream_finalize")
    async def finalize_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        req = REQUESTS.get(self.request_id)

        if req is None:
            await interaction.response.send_message("Diese Anfrage ist nicht mehr aktiv.", ephemeral=True)
            return

        if interaction.user.id != req.requester_id:
            await interaction.response.send_message("Nur der Anfrager kann diesen Restream eintragen.", ephemeral=True)
            return

        if req.declined:
            await interaction.response.send_message("Diese Anfrage wurde abgelehnt.", ephemeral=True)
            return

        if not all(req.approvals.values()):
            await interaction.response.send_message("Noch nicht beide Spieler haben zugestimmt.", ephemeral=True)
            return

        guild = interaction.client.get_guild(req.guild_id)

        if guild is None:
            try:
                guild = await interaction.client.fetch_guild(req.guild_id)
            except Exception:
                guild = None

        if guild is None and interaction.guild is not None:
            guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                f"Server nicht gefunden. Gespeicherte Guild-ID: {req.guild_id}",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await finalize_restream(interaction.client, guild, req)
            await interaction.edit_original_response(
                content=f"Restream wurde eingetragen, in <#{RESTREAMS_CHANNEL_ID}> gepostet und das Discord-Event wurde aktualisiert.",
                view=None,
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"Fehler beim Eintragen des Restreams: {e}",
                view=self,
            )


# =========================================================
# COG
# =========================================================

class RestreamRequestsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_task: asyncio.Task | None = None

    async def cog_load(self):
        self.daily_task = asyncio.create_task(self.daily_restreamable_loop())
        print("✅ restream_requests daily loop gestartet")

    async def cog_unload(self):
        if self.daily_task:
            self.daily_task.cancel()

    async def daily_restreamable_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            now = dt.now(BERLIN_TZ)
            target = BERLIN_TZ.localize(dt.combine(now.date(), time(4, 0)))

            if now >= target:
                target = target + timedelta(days=1)

            sleep_seconds = max(1, int((target - now).total_seconds()))
            await asyncio.sleep(sleep_seconds)

            try:
                await self.post_restreamable_events()
            except Exception as e:
                print(f"⚠️ Fehler beim täglichen Restreamable-Post: {e}")

    async def post_restreamable_events(self):
        guild = self.bot.get_guild(GUILD_ID)

        if guild is None:
            guilds = list(self.bot.guilds)
            guild = guilds[0] if guilds else None

        if guild is None:
            print("⚠️ Restreamable: Guild nicht gefunden")
            return

        channel = guild.get_channel(RESTREAMABLE_CHANNEL_ID)

        if channel is None:
            try:
                channel = await guild.fetch_channel(RESTREAMABLE_CHANNEL_ID)
            except Exception:
                channel = None

        if not isinstance(channel, discord.TextChannel):
            print("⚠️ Restreamable-Kanal nicht gefunden oder kein Textkanal")
            return

        # Alte Bot-Posts im Kanal entfernen, damit die tägliche Liste nicht doppelt wächst.
        try:
            async for msg in channel.history(limit=100):
                if self.bot.user and msg.author.id == self.bot.user.id:
                    await msg.delete()
        except Exception as e:
            print(f"⚠️ Alte Restreamable-Posts konnten nicht vollständig gelöscht werden: {e}")

        events = await fetch_all_scheduled_events(guild)
        events = [event for event in events if event_is_tfl_match(event)]
        events.sort(key=lambda e: e.start_time or dt.max)

        if not events:
            await channel.send("📺 **Restreamable Spiele**\nAktuell sind keine restreambaren TFL-Spiele als Discord-Event vorhanden.")
            return

        shown_events = events[:25]

        lines = [
            "📺 **Restreamable Spiele**",
            "",
            "Spiel unten im Dropdown auswählen.",
            "",
        ]

        for i, event in enumerate(shown_events, start=1):
            parsed = parse_event_title(event)
            match = parsed["match"] or event.name
            lines.append(
                f"`{i:02d}` {format_event_start(event.start_time)} · {parsed['area'] or '-'} · {match} · {parsed['mode']}"
            )

        if len(events) > 25:
            lines.append("")
            lines.append(f"⚠️ Es werden nur die ersten 25 von {len(events)} Events angezeigt. Discord erlaubt max. 25 Dropdown-Optionen.")

        await channel.send(
            "\n".join(lines),
            view=RestreamEventSelectView(shown_events),
        )

    @commands.command(name="restreamables")
    @commands.has_permissions(administrator=True)
    async def manual_restreamables(self, ctx: commands.Context):
        """
        Admin-Testbefehl:
        !restreamables

        Hinweis:
        Funktioniert nur, wenn Prefix-Commands und Message Content Intent aktiv sind.
        Der Slash-Command /restreamables ist zuverlässiger.
        """
        await self.post_restreamable_events()
        await ctx.reply("Restreamable-Spiele wurden neu gepostet.", mention_author=False)

    @app_commands.command(
        name="restreamables",
        description="Postet die restreambaren Spiele sofort neu.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    async def restreamables_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.post_restreamable_events()
            await interaction.followup.send(
                "Restreamable-Spiele wurden neu gepostet.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Posten der restreambaren Spiele: {e}",
                ephemeral=True,
            )

    @app_commands.command(
        name="restreampush",
        description="Postet einen Restream ohne Spieler-DMs direkt in #restreams und aktualisiert das Event.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        event_id="Discord-Event-ID des Spiels",
        ziel="Restream-Ziel",
        link="Restream-Link. Bei ZSRDE/DRR leer lassen möglich.",
        kommentator="Kommentator",
        co_kommentator="Co-Kommentator",
        tracker="Tracker",
    )
    @app_commands.choices(
        ziel=[
            app_commands.Choice(name="ZSRDE", value="ZSRDE"),
            app_commands.Choice(name="DRR", value="DRR"),
            app_commands.Choice(name="Privat", value="Privat"),
        ]
    )
    async def restreampush_slash(
        self,
        interaction: discord.Interaction,
        event_id: str,
        ziel: app_commands.Choice[str],
        link: str = "",
        kommentator: str = "",
        co_kommentator: str = "",
        tracker: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            guild = interaction.client.get_guild(GUILD_ID)

        if guild is None:
            await interaction.followup.send(
                "Server nicht gefunden. Bitte Command direkt auf dem TFL-Server ausführen.",
                ephemeral=True,
            )
            return

        try:
            clean_event_id = int(clean_text(event_id))
        except ValueError:
            await interaction.followup.send(
                "Event-ID ist ungültig. Bitte nur die numerische Discord-Event-ID eintragen.",
                ephemeral=True,
            )
            return

        event = await get_scheduled_event_by_id(guild, clean_event_id)
        if event is None:
            await interaction.followup.send(
                "Discord-Event wurde nicht gefunden. Prüfe die Event-ID.",
                ephemeral=True,
            )
            return

        target = ziel.value
        final_link = clean_text(link)

        if target in {"ZSRDE", "DRR"} and not final_link:
            final_link = RESTREAM_TARGETS.get(target, "")

        if not final_link:
            await interaction.followup.send(
                "Restream-Link fehlt. Bei Privat ist der Link Pflicht.",
                ephemeral=True,
            )
            return

        parsed = parse_event_title(event)

        if not parsed["player1"] or not parsed["player2"]:
            await interaction.followup.send(
                "Spieler konnten aus dem Event-Titel nicht erkannt werden. Erwartetes Format: `Bereich | Spieler1 vs. Spieler2 | Modus`.",
                ephemeral=True,
            )
            return

        req = RestreamRequest(
            request_id=f"manual-{uuid.uuid4().hex[:8]}",
            guild_id=int(guild.id),
            event_id=int(event.id),
            event_title=event.name,
            event_start_text=format_event_start_long(event.start_time),
            area=parsed["area"] or "TFL",
            player1=parsed["player1"],
            player2=parsed["player2"],
            mode=parsed["mode"],
            requester_id=interaction.user.id,
            requester_name=interaction.user.display_name,
            target=target,
            link=final_link,
            commentator=clean_text(kommentator),
            co_commentator=clean_text(co_kommentator),
            tracker=clean_text(tracker),
            approvals={},
            player_member_ids=[],
            declined=False,
            finalized=False,
        )

        try:
            await finalize_restream(interaction.client, guild, req)
            await interaction.followup.send(
                f"Restream wurde ohne Spieler-DMs in <#{RESTREAMS_CHANNEL_ID}> gepostet und das Discord-Event wurde aktualisiert.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Pushen des Restreams: {e}",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(RestreamRequestsCog(bot))

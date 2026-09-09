from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime as dt, timedelta

import discord
import pytz

import matchcenter
from sheet_guard import col_values_cached, row_values_cached, sheet_write_call
from sheets_connection import get_season_worksheet, get_season_worksheet_by_gid


BERLIN_TZ = pytz.timezone("Europe/Berlin")

DIVISION_CHANNELS = {
    1: 1344118033920168047,
    2: 1344118383859204146,
    3: 1344118470102614036,
    4: 1344118574943572100,
    5: 1389541046874148924,
    6: 1438136009085817023,
}

MODE_CONFIG_WORKSHEET_GID = 463142264
DIVISION_MODE_COLUMNS = {
    1: 11,  # K
    2: 12,  # L
    3: 13,  # M
    4: 14,  # N
    5: 15,  # O
    6: 16,  # P
}

PROFILE_CACHE_TTL = 60
MODE_CACHE_TTL = 300
RESERVATION_SECONDS = 10 * 60

# Laufzeit-Registry. Die Nachrichten bleiben solange interaktiv, wie der Bot läuft.
# Ein späterer Ausbau kann diese Offers in einem Sheet persistieren und beim Start
# wieder registrieren, ohne den eigentlichen Terminworkflow zu ändern.
_OFFER_VIEWS: dict[tuple[int, int], "TermOfferView"] = {}
_RESERVATIONS: dict[str, tuple[int, float]] = {}


def normalize_name(value: str | None) -> str:
    value = (value or "").lower().strip()
    return re.sub(r"[^a-z0-9äöüß]", "", value)


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _cell(row: list[str], idx0: int) -> str:
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


def _sheet_name(ws, fallback: str) -> str:
    return getattr(ws, "title", fallback)


def _invalidate_prefixes(ws, fallback: str) -> list[str]:
    title = _sheet_name(ws, fallback)
    return [
        f"records:{title}",
        f"values:{title}",
        f"row:{title}:",
        f"col:{title}:",
        f"cell:{title}:",
    ]


@dataclass(frozen=True)
class PlayerProfile:
    division: int
    player_name: str
    ban_1: str
    ban_2: str


@dataclass(frozen=True)
class MatchRow:
    row_index: int
    home: str
    away: str
    timestamp: str
    marker_or_result: str
    mode: str

    @property
    def is_open(self) -> bool:
        return self.marker_or_result.lower() == "vs"

    @property
    def is_available(self) -> bool:
        return self.is_open and not self.timestamp

    @property
    def is_scheduled(self) -> bool:
        return self.is_open and bool(self.timestamp)

    @property
    def is_played(self) -> bool:
        return bool(self.marker_or_result) and not self.is_open


@dataclass(frozen=True)
class OfferSlot:
    index: int
    when: dt

    @property
    def date_str(self) -> str:
        return self.when.strftime("%d.%m.%Y")

    @property
    def time_str(self) -> str:
        return self.when.strftime("%H:%M")

    @property
    def timestamp(self) -> str:
        return self.when.strftime("%d.%m.%Y %H:%M")

    @property
    def short_label(self) -> str:
        return self.when.strftime("%d.%m. · %H:%M")

    @property
    def long_label(self) -> str:
        weekdays = [
            "Montag", "Dienstag", "Mittwoch", "Donnerstag",
            "Freitag", "Samstag", "Sonntag",
        ]
        return f"{weekdays[self.when.weekday()]}, {self.when.strftime('%d.%m.%Y')} – {self.time_str} Uhr"


def _member_name_candidates(member: discord.Member) -> list[str]:
    return [
        member.display_name,
        getattr(member, "global_name", None),
        member.name,
        str(member),
    ]


def _find_profile_by_candidates(name_candidates: list[str]) -> PlayerProfile | None:
    targets = {normalize_name(v) for v in name_candidates if v}
    targets.discard("")

    if not targets:
        return None

    for division in range(1, 7):
        ws = get_season_worksheet(f"{division}.DIV")
        values = col_values_cached(
            lambda ws=ws: ws,
            sheet_name=_sheet_name(ws, f"{division}.DIV"),
            col=12,  # L = Spielername für Streichmodi
            ttl_seconds=PROFILE_CACHE_TTL,
        )

        for row_index, value in enumerate(values, start=1):
            if normalize_name(value) not in targets:
                continue

            row = row_values_cached(
                lambda ws=ws: ws,
                sheet_name=_sheet_name(ws, f"{division}.DIV"),
                row=row_index,
                ttl_seconds=PROFILE_CACHE_TTL,
            )

            canonical = _cell(row, 11) or clean_text(value)
            return PlayerProfile(
                division=division,
                player_name=canonical,
                ban_1=_cell(row, 12),  # M
                ban_2=_cell(row, 13),  # N
            )

    return None


def find_member_profile(member: discord.Member) -> PlayerProfile | None:
    return _find_profile_by_candidates(_member_name_candidates(member))


def find_profile_by_player_name(division: int, player_name: str) -> PlayerProfile | None:
    ws = get_season_worksheet(f"{division}.DIV")
    values = col_values_cached(
        lambda: ws,
        sheet_name=_sheet_name(ws, f"{division}.DIV"),
        col=12,
        ttl_seconds=PROFILE_CACHE_TTL,
    )
    target = normalize_name(player_name)

    for row_index, value in enumerate(values, start=1):
        if normalize_name(value) != target:
            continue

        row = row_values_cached(
            lambda: ws,
            sheet_name=_sheet_name(ws, f"{division}.DIV"),
            row=row_index,
            ttl_seconds=PROFILE_CACHE_TTL,
        )
        return PlayerProfile(
            division=division,
            player_name=_cell(row, 11) or player_name,
            ban_1=_cell(row, 12),
            ban_2=_cell(row, 13),
        )

    return None


def get_division_modes(division: int) -> list[str]:
    col = DIVISION_MODE_COLUMNS.get(int(division))
    if not col:
        return []

    ws = get_season_worksheet_by_gid(MODE_CONFIG_WORKSHEET_GID)
    values = col_values_cached(
        lambda: ws,
        sheet_name=_sheet_name(ws, "ModeConfig"),
        col=col,
        ttl_seconds=MODE_CACHE_TTL,
    )

    ignored = {
        "modus", "modis", "mode", "modes",
        f"{division}. division", f"division {division}", f"{division}.division",
    }
    out: list[str] = []
    seen: set[str] = set()

    for value in values:
        mode = clean_text(value)
        if not mode:
            continue
        key = mode.lower()
        if key in ignored or key in seen:
            continue
        seen.add(key)
        out.append(mode)

    return out[:25]


def _pair_matches(division: int, player_a: str, player_b: str) -> list[MatchRow]:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)

    a = normalize_name(player_a)
    b = normalize_name(player_b)
    out: list[MatchRow] = []

    for row_index, row in enumerate(rows, start=1):
        if row_index == 1:
            continue

        home = _cell(row, 3)   # D
        marker = _cell(row, 4) # E = "vs" oder Ergebnis
        away = _cell(row, 5)   # F
        if not home or not away:
            continue

        home_n = normalize_name(home)
        away_n = normalize_name(away)
        if {home_n, away_n} != {a, b}:
            continue

        out.append(
            MatchRow(
                row_index=row_index,
                home=home,
                away=away,
                timestamp=_cell(row, 1),  # B
                marker_or_result=marker,
                mode=_cell(row, 2),       # C
            )
        )

    return out


def get_pair_state(division: int, player_a: str, player_b: str) -> dict:
    matches = _pair_matches(division, player_a, player_b)
    return {
        "all": matches,
        "available": [m for m in matches if m.is_available],
        "scheduled": [m for m in matches if m.is_scheduled],
        "played": [m for m in matches if m.is_played],
    }


def player_has_schedule_at(division: int, player_name: str, timestamp: str, exclude_row: int | None = None) -> bool:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)
    target = normalize_name(player_name)
    wanted_ts = clean_text(timestamp)

    for row_index, row in enumerate(rows, start=1):
        if row_index == 1 or row_index == exclude_row:
            continue

        ts = clean_text(_cell(row, 1))
        marker = _cell(row, 4)
        if ts != wanted_ts or marker.lower() != "vs":
            continue

        home = normalize_name(_cell(row, 3))
        away = normalize_name(_cell(row, 5))
        if target in {home, away}:
            return True

    return False


def _parse_offer_datetime(value: str) -> dt:
    value = clean_text(value)
    parsed = dt.strptime(value, "%d.%m.%Y %H:%M")
    return BERLIN_TZ.localize(parsed)


def _cleanup_reservations() -> None:
    now = time.monotonic()
    expired = [key for key, (_, until) in _RESERVATIONS.items() if until <= now]
    for key in expired:
        _RESERVATIONS.pop(key, None)


def reserve_slot(key: str, user_id: int) -> bool:
    _cleanup_reservations()
    current = _RESERVATIONS.get(key)
    if current and current[0] != user_id:
        return False
    _RESERVATIONS[key] = (user_id, time.monotonic() + RESERVATION_SECONDS)
    return True


def release_slot(key: str, user_id: int | None = None) -> None:
    current = _RESERVATIONS.get(key)
    if not current:
        return
    if user_id is not None and current[0] != user_id:
        return
    _RESERVATIONS.pop(key, None)


def _validate_target_match(
    division: int,
    row_index: int,
    home: str,
    away: str,
    timestamp: str,
) -> None:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)

    if row_index < 1 or row_index > len(rows):
        raise RuntimeError("Die Begegnung wurde im Sheet nicht mehr gefunden.")

    row = rows[row_index - 1]
    sheet_home = _cell(row, 3)
    marker = _cell(row, 4)
    sheet_away = _cell(row, 5)
    current_timestamp = _cell(row, 1)

    if normalize_name(sheet_home) != normalize_name(home) or normalize_name(sheet_away) != normalize_name(away):
        raise RuntimeError("Die Begegnung im Sheet hat sich inzwischen geändert.")

    if marker.lower() != "vs":
        raise RuntimeError("Diese Begegnung wurde inzwischen bereits gespielt.")

    if current_timestamp:
        raise RuntimeError("Für diese Begegnung ist inzwischen bereits ein Termin eingetragen.")

    for player in (home, away):
        if player_has_schedule_at(division, player, timestamp, exclude_row=row_index):
            raise RuntimeError(
                f"{player} hat zu diesem Zeitpunkt inzwischen bereits ein anderes TFL-Spiel."
            )


def _rollback_league_schedule(division: int, row_index: int) -> None:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    sheet_name = _sheet_name(ws, f"{division}.DIV")
    reqs = [
        {"range": f"B{row_index}:C{row_index}", "values": [["", ""]]},
        {"range": f"G{row_index}:H{row_index}", "values": [["", ""]]},
    ]
    sheet_write_call(
        lambda: ws.batch_update(reqs),
        invalidate_prefixes=matchcenter.matchcenter_invalidate_prefixes(sheet_name),
    )


def _verify_league_schedule(
    division: int,
    row_index: int,
    home: str,
    away: str,
    mode: str,
    timestamp: str,
) -> None:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)
    if row_index < 1 or row_index > len(rows):
        raise RuntimeError("Der Spieleintrag konnte nach dem Schreiben nicht verifiziert werden.")

    row = rows[row_index - 1]
    checks = {
        "Datum/Uhrzeit": clean_text(_cell(row, 1)) == clean_text(timestamp),
        "Modus": clean_text(_cell(row, 2)) == clean_text(mode),
        "Heimspieler": normalize_name(_cell(row, 3)) == normalize_name(home),
        "Status": _cell(row, 4).lower() == "vs",
        "Gastspieler": normalize_name(_cell(row, 5)) == normalize_name(away),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError(
            "Der Sheet-Eintrag konnte nicht eindeutig bestätigt werden: " + ", ".join(failed)
        )


async def finalize_match_schedule(
    *,
    guild: discord.Guild,
    actor: discord.Member | discord.User,
    division: int,
    row_index: int,
    home: str,
    away: str,
    mode: str,
    slot: OfferSlot,
) -> dict:
    """
    Zentrale Transaktion der Terminbörse:
    1. Live-Prüfung des Match-Slots.
    2. Sheet schreiben.
    3. Sheet verifizieren.
    4. Erst danach Discord Scheduled Event erzeugen.
    5. Bei Discord-Fehler wird der Sheet-Termin zurückgerollt.
    6. Gegner per bestehender Matchcenter-DM informieren.
    """
    division_label = f"Div {division}"
    timestamp = slot.timestamp

    await asyncio.to_thread(
        _validate_target_match,
        division,
        row_index,
        home,
        away,
        timestamp,
    )

    multistream_url = await asyncio.to_thread(matchcenter.build_multistream_url, home, away)
    entered_by = f"Terminbörse: {actor.display_name}"

    await asyncio.to_thread(
        matchcenter.write_league_schedule,
        row_index,
        mode,
        multistream_url,
        entered_by,
        timestamp,
        division_label,
    )

    try:
        await asyncio.to_thread(
            _verify_league_schedule,
            division,
            row_index,
            home,
            away,
            mode,
            timestamp,
        )
    except Exception:
        await asyncio.to_thread(_rollback_league_schedule, division, row_index)
        raise

    start_dt = slot.when
    end_dt = start_dt + timedelta(hours=2)
    title = f"{division_label} | {home} vs. {away} | {mode}"
    description = f"Geplant über TFL Terminbörse von {actor.display_name}"

    try:
        event = await matchcenter.create_scheduled_event(
            guild,
            title,
            multistream_url,
            start_dt,
            end_dt,
            description,
        )
    except Exception as exc:
        try:
            await asyncio.to_thread(_rollback_league_schedule, division, row_index)
        except Exception as rollback_exc:
            raise RuntimeError(
                "Discord-Event konnte nicht erstellt werden und auch das automatische "
                f"Zurückrollen des Sheet-Eintrags ist fehlgeschlagen. Eventfehler: {exc}; "
                f"Rollbackfehler: {rollback_exc}"
            ) from exc
        raise RuntimeError(
            "Das Discord-Event konnte nicht erstellt werden. Der Sheet-Eintrag wurde "
            "deshalb automatisch zurückgenommen."
        ) from exc

    event_url = getattr(event, "url", "") or ""

    try:
        await matchcenter.send_schedule_dm_to_other_player(
            guild=guild,
            creator=actor,
            player1=home,
            player2=away,
            area="League",
            info=division_label,
            mode=mode,
            date_str=slot.date_str,
            time_str=slot.time_str,
            event_url=event_url or multistream_url,
        )
    except Exception as exc:
        # Der Termin ist an diesem Punkt korrekt in Sheet + Discord angelegt.
        # Ein DM-Problem darf den Termin nicht zerstören.
        print(f"⚠️ [TERMINBÖRSE] Termin steht, DM konnte nicht gesendet werden: {exc}")

    return {
        "event_url": event_url,
        "multistream_url": multistream_url,
        "timestamp": timestamp,
        "mode": mode,
        "home": home,
        "away": away,
    }


async def _get_division_channel(client: discord.Client, division: int):
    channel_id = DIVISION_CHANNELS.get(division)
    if not channel_id:
        return None

    channel = client.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        return await client.fetch_channel(channel_id)
    except Exception:
        return None


async def _send_mode_dm(
    *,
    interaction: discord.Interaction,
    division: int,
    match: MatchRow,
    slot: OfferSlot,
    reservation_key: str,
    offer_channel_id: int,
    offer_message_id: int,
    slot_index: int,
) -> bool:
    guild = interaction.guild
    if guild is None:
        release_slot(reservation_key, interaction.user.id)
        return False

    home_member = await matchcenter.find_member_by_player_name(guild, match.home)
    if home_member is None:
        release_slot(reservation_key, interaction.user.id)
        return False

    guest_profile = await asyncio.to_thread(
        find_profile_by_player_name,
        division,
        match.away,
    )
    ban_1 = guest_profile.ban_1 if guest_profile else ""
    ban_2 = guest_profile.ban_2 if guest_profile else ""

    modes = await asyncio.to_thread(get_division_modes, division)
    bans_normalized = {normalize_name(v) for v in (ban_1, ban_2) if v}
    allowed_modes = [m for m in modes if normalize_name(m) not in bans_normalized]

    if not allowed_modes:
        release_slot(reservation_key, interaction.user.id)
        return False

    view = ModeChoiceView(
        owner_id=home_member.id,
        division=division,
        match=match,
        slot=slot,
        allowed_modes=allowed_modes,
        ban_1=ban_1,
        ban_2=ban_2,
        reservation_key=reservation_key,
        reservation_owner_id=interaction.user.id,
        offer_channel_id=offer_channel_id,
        offer_message_id=offer_message_id,
        slot_index=slot_index,
    )

    try:
        await home_member.send(view.render_text(), view=view)
        return True
    except Exception as exc:
        print(f"⚠️ [TERMINBÖRSE] Modus-DM an {match.home} fehlgeschlagen: {exc}")
        release_slot(reservation_key, interaction.user.id)
        return False


class TermOfferModal(discord.ui.Modal, title="Race-Termine anbieten"):
    termin_1 = discord.ui.TextInput(
        label="Termin 1",
        placeholder="z. B. 12.09.2026 20:00",
        required=True,
        max_length=30,
    )
    termin_2 = discord.ui.TextInput(
        label="Termin 2 (optional)",
        placeholder="z. B. 13.09.2026 18:30",
        required=False,
        max_length=30,
    )
    termin_3 = discord.ui.TextInput(
        label="Termin 3 (optional)",
        placeholder="z. B. 15.09.2026 20:30",
        required=False,
        max_length=30,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Diese Funktion ist nur auf dem TFL-Server verfügbar.",
                ephemeral=True,
            )
            return

        raw_values = [
            str(self.termin_1.value or "").strip(),
            str(self.termin_2.value or "").strip(),
            str(self.termin_3.value or "").strip(),
        ]
        raw_values = [v for v in raw_values if v]

        if not raw_values:
            await interaction.response.send_message("Bitte mindestens einen Termin eintragen.", ephemeral=True)
            return

        parsed: list[dt] = []
        errors: list[str] = []
        now = dt.now(BERLIN_TZ)

        for i, raw in enumerate(raw_values, start=1):
            try:
                value = _parse_offer_datetime(raw)
            except ValueError:
                errors.append(f"Termin {i}: Bitte `TT.MM.JJJJ HH:MM` verwenden.")
                continue

            if value <= now:
                errors.append(f"Termin {i}: Der Termin liegt nicht in der Zukunft.")
                continue

            if any(existing == value for existing in parsed):
                errors.append(f"Termin {i}: Dieser Termin wurde doppelt eingetragen.")
                continue

            parsed.append(value)

        if errors:
            await interaction.response.send_message("\n".join(errors), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            profile = await asyncio.to_thread(find_member_profile, interaction.user)
            if profile is None:
                await interaction.edit_original_response(
                    content="Dein Spielername wurde in den Divisionstabellen nicht gefunden."
                )
                return

            slots = [OfferSlot(index=i, when=value) for i, value in enumerate(parsed)]

            # Bereits beim Erfassen verhindern, dass der Anbieter selbst zu diesem
            # Zeitpunkt schon ein TFL-Spiel im Sheet stehen hat.
            for slot in slots:
                conflict = await asyncio.to_thread(
                    player_has_schedule_at,
                    profile.division,
                    profile.player_name,
                    slot.timestamp,
                )
                if conflict:
                    await interaction.edit_original_response(
                        content=(
                            f"Für **{slot.timestamp}** ist bei dir bereits ein anderes "
                            "TFL-Spiel eingetragen."
                        ),
                        view=None,
                    )
                    return

            view = OfferConfirmView(
                owner_id=interaction.user.id,
                profile=profile,
                slots=slots,
            )
            slot_lines = "\n".join(f"• **{slot.long_label}**" for slot in slots)
            await interaction.edit_original_response(
                content=(
                    "📅 **Diese Termine anbieten?**\n\n"
                    f"{slot_lines}\n\n"
                    "Mit **Termine anbieten** werden sie im Divisionschat veröffentlicht."
                ),
                view=view,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"❌ Terminangebot konnte nicht vorbereitet werden: {exc}",
                view=None,
            )


class OfferConfirmView(discord.ui.View):
    def __init__(self, *, owner_id: int, profile: PlayerProfile, slots: list[OfferSlot]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.profile = profile
        self.slots = slots

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Auswahl gehört nicht dir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Termine anbieten", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        try:
            # Vor Veröffentlichung nochmals prüfen: zwischen Modal und Bestätigung
            # kann bereits ein anderer Termin eingetragen worden sein.
            for slot in self.slots:
                conflict = await asyncio.to_thread(
                    player_has_schedule_at,
                    self.profile.division,
                    self.profile.player_name,
                    slot.timestamp,
                )
                if conflict:
                    await interaction.edit_original_response(
                        content=(
                            f"Für **{slot.timestamp}** ist inzwischen bereits ein anderes "
                            "TFL-Spiel eingetragen. Es wurde nichts veröffentlicht."
                        ),
                        view=None,
                    )
                    self.stop()
                    return

            channel = await _get_division_channel(interaction.client, self.profile.division)
            if channel is None or not hasattr(channel, "send"):
                await interaction.edit_original_response(
                    content="Der Divisionschat konnte nicht gefunden werden.",
                    view=None,
                )
                self.stop()
                return

            view = TermOfferView(
                creator_id=interaction.user.id,
                creator_name=self.profile.player_name,
                division=self.profile.division,
                slots=self.slots,
            )

            message = await channel.send(
                content=view.render_public_content(),
                view=view,
            )
            view.message_id = message.id
            view.channel_id = message.channel.id
            _OFFER_VIEWS[(message.channel.id, message.id)] = view

            await interaction.edit_original_response(
                content=(
                    f"✅ Deine {len(self.slots)} Termin"
                    f"{'e' if len(self.slots) != 1 else ''} wurden in "
                    f"**{self.profile.division}.DIV** angeboten."
                ),
                view=None,
            )
            self.stop()
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"❌ Terminangebot konnte nicht veröffentlicht werden: {exc}",
                view=None,
            )
            self.stop()

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Terminangebot abgebrochen.", view=None)
        self.stop()


class TermSlotButton(discord.ui.Button):
    def __init__(self, slot: OfferSlot):
        super().__init__(
            label=slot.short_label,
            style=discord.ButtonStyle.primary,
            row=0,
        )
        self.slot = slot

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, TermOfferView):
            return

        await view.handle_slot_click(interaction, self.slot)


class TermOfferView(discord.ui.View):
    def __init__(self, creator_id: int, creator_name: str, division: int, slots: list[OfferSlot]):
        super().__init__(timeout=None)
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.division = division
        self.slots = slots
        self.message_id: int | None = None
        self.channel_id: int | None = None
        self.booked_slots: set[int] = set()
        self.removed_slots: set[int] = set()

        for slot in slots:
            self.add_item(TermSlotButton(slot))

    def reservation_key(self, slot_index: int) -> str:
        return f"{self.channel_id}:{self.message_id}:{slot_index}"

    async def handle_slot_click(self, interaction: discord.Interaction, slot: OfferSlot):
        if interaction.user.id == self.creator_id:
            await interaction.response.send_message(
                "Du kannst dein eigenes Terminangebot nicht annehmen.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        reservation_key = self.reservation_key(slot.index)
        if not reserve_slot(reservation_key, interaction.user.id):
            await interaction.response.send_message(
                "Dieser Termin wird gerade bereits von einem anderen Spieler bearbeitet.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            reactor = await asyncio.to_thread(find_member_profile, interaction.user)
            if reactor is None:
                release_slot(reservation_key, interaction.user.id)
                await interaction.edit_original_response(
                    content="Dein Spielername wurde in den Divisionstabellen nicht gefunden."
                )
                return

            state = await asyncio.to_thread(
                get_pair_state,
                self.division,
                self.creator_name,
                reactor.player_name,
            )
            available: list[MatchRow] = state["available"]
            played: list[MatchRow] = state["played"]
            scheduled: list[MatchRow] = state["scheduled"]

            if not available:
                release_slot(reservation_key, interaction.user.id)
                if len(played) >= 2:
                    text = "Ihr habt bereits beide Begegnungen gespielt."
                elif scheduled:
                    text = "Für eure noch offene Begegnung ist bereits ein Termin eingetragen."
                else:
                    text = "Zwischen euch ist aktuell keine freie Begegnung mehr verfügbar."
                await interaction.edit_original_response(content=text)
                return

            if len(available) == 1:
                match = available[0]
                ok = await _send_mode_dm(
                    interaction=interaction,
                    division=self.division,
                    match=match,
                    slot=slot,
                    reservation_key=reservation_key,
                    offer_channel_id=self.channel_id or interaction.channel_id,
                    offer_message_id=self.message_id or interaction.message.id,
                    slot_index=slot.index,
                )
                if not ok:
                    await interaction.edit_original_response(
                        content=(
                            f"Der Heimspieler **{match.home}** konnte nicht per DM erreicht werden. "
                            "Der Termin wurde wieder freigegeben."
                        )
                    )
                    return

                if normalize_name(match.home) == normalize_name(reactor.player_name):
                    await interaction.edit_original_response(
                        content="✅ Du hast Heimrecht. Ich habe dir die Modusauswahl per DM geschickt."
                    )
                else:
                    await interaction.edit_original_response(
                        content=f"✅ **{match.home}** hat Heimrecht und erhält jetzt die Modusauswahl per DM."
                    )
                return

            choice = HomeAwayChoiceView(
                owner_id=interaction.user.id,
                division=self.division,
                reactor_name=reactor.player_name,
                available_matches=available,
                slot=slot,
                reservation_key=reservation_key,
                offer_channel_id=self.channel_id or interaction.channel_id,
                offer_message_id=self.message_id or interaction.message.id,
                slot_index=slot.index,
            )
            await interaction.edit_original_response(
                content=(
                    f"Gegen **{self.creator_name}** sind noch beide Begegnungen frei.\n"
                    "Welches Spiel möchtest du zuerst machen?"
                ),
                view=choice,
            )
        except Exception as exc:
            release_slot(reservation_key, interaction.user.id)
            await interaction.edit_original_response(
                content=f"❌ Termin konnte nicht geprüft werden: {exc}"
            )

    def active_slots(self) -> list[OfferSlot]:
        return [
            slot for slot in self.slots
            if slot.index not in self.booked_slots and slot.index not in self.removed_slots
        ]

    def render_public_content(self) -> str:
        lines = []
        for slot in self.slots:
            if slot.index in self.booked_slots:
                state = " ✅ vergeben"
            elif slot.index in self.removed_slots:
                state = " ❌ zurückgezogen"
            else:
                state = ""
            lines.append(f"• **{slot.long_label}**{state}")

        footer = (
            "Klicke auf den passenden Termin, um das Spiel zu vereinbaren."
            if self.active_slots()
            else "Aktuell ist kein Termin aus diesem Angebot mehr verfügbar."
        )
        return (
            f"📅 **{self.creator_name} bietet folgende Termine für Races an:**\n\n"
            + "\n".join(lines)
            + f"\n\n{footer}"
        )

    async def _refresh_message(self, client: discord.Client) -> None:
        if self.channel_id is None or self.message_id is None:
            return

        try:
            channel = client.get_channel(self.channel_id)
            if channel is None:
                channel = await client.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            await message.edit(
                content=self.render_public_content(),
                view=self if self.active_slots() else None,
            )
            if not self.active_slots():
                _OFFER_VIEWS.pop((self.channel_id, self.message_id), None)
        except Exception as exc:
            print(f"⚠️ [TERMINBÖRSE] Offer-Post konnte nicht aktualisiert werden: {exc}")

    async def mark_booked(self, client: discord.Client, slot_index: int) -> None:
        self.booked_slots.add(slot_index)
        for item in self.children:
            if isinstance(item, TermSlotButton) and item.slot.index == slot_index:
                item.disabled = True
                item.style = discord.ButtonStyle.secondary
                item.label = f"✅ {item.slot.short_label}"
                break
        await self._refresh_message(client)

    async def remove_slot(self, client: discord.Client, slot_index: int) -> bool:
        if slot_index in self.booked_slots or slot_index in self.removed_slots:
            return False

        self.removed_slots.add(slot_index)
        release_slot(self.reservation_key(slot_index))
        for item in self.children:
            if isinstance(item, TermSlotButton) and item.slot.index == slot_index:
                item.disabled = True
                item.style = discord.ButtonStyle.secondary
                item.label = f"❌ {item.slot.short_label}"
                break
        await self._refresh_message(client)
        return True

    async def withdraw_all(self, client: discord.Client) -> int:
        removed = 0
        for slot in self.slots:
            if slot.index in self.booked_slots or slot.index in self.removed_slots:
                continue
            self.removed_slots.add(slot.index)
            release_slot(self.reservation_key(slot.index))
            removed += 1

        for item in self.children:
            if isinstance(item, TermSlotButton) and item.slot.index in self.removed_slots:
                item.disabled = True
                item.style = discord.ButtonStyle.secondary
                item.label = f"❌ {item.slot.short_label}"

        await self._refresh_message(client)
        return removed


class HomeAwayChoiceView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        division: int,
        reactor_name: str,
        available_matches: list[MatchRow],
        slot: OfferSlot,
        reservation_key: str,
        offer_channel_id: int,
        offer_message_id: int,
        slot_index: int,
    ):
        super().__init__(timeout=RESERVATION_SECONDS)
        self.owner_id = owner_id
        self.division = division
        self.reactor_name = reactor_name
        self.available_matches = available_matches
        self.slot = slot
        self.reservation_key = reservation_key
        self.offer_channel_id = offer_channel_id
        self.offer_message_id = offer_message_id
        self.slot_index = slot_index

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Auswahl gehört nicht dir.", ephemeral=True)
            return False
        return True

    def _find_match(self, want_home: bool) -> MatchRow | None:
        target = normalize_name(self.reactor_name)
        for match in self.available_matches:
            if want_home and normalize_name(match.home) == target:
                return match
            if not want_home and normalize_name(match.away) == target:
                return match
        return None

    async def _choose(self, interaction: discord.Interaction, want_home: bool):
        match = self._find_match(want_home)
        if match is None:
            release_slot(self.reservation_key, self.owner_id)
            await interaction.response.edit_message(
                content="Die gewünschte Begegnung ist nicht mehr verfügbar.",
                view=None,
            )
            return

        # Vor der DM nochmals live prüfen, damit keine inzwischen belegte Begegnung benutzt wird.
        state = await asyncio.to_thread(
            get_pair_state,
            self.division,
            match.home,
            match.away,
        )
        live_rows = {m.row_index: m for m in state["available"]}
        match = live_rows.get(match.row_index)
        if match is None:
            release_slot(self.reservation_key, self.owner_id)
            await interaction.response.edit_message(
                content="Diese Begegnung wurde inzwischen anderweitig terminiert.",
                view=None,
            )
            return

        ok = await _send_mode_dm(
            interaction=interaction,
            division=self.division,
            match=match,
            slot=self.slot,
            reservation_key=self.reservation_key,
            offer_channel_id=self.offer_channel_id,
            offer_message_id=self.offer_message_id,
            slot_index=self.slot_index,
        )
        if not ok:
            await interaction.response.edit_message(
                content=(
                    f"Der Heimspieler **{match.home}** konnte nicht per DM erreicht werden. "
                    "Der Termin wurde wieder freigegeben."
                ),
                view=None,
            )
            return

        if normalize_name(match.home) == normalize_name(self.reactor_name):
            text = "✅ Du spielst zuerst dein Heimspiel. Die Modusauswahl liegt in deinen DMs."
        else:
            text = f"✅ Du spielst zuerst dein Gastspiel. **{match.home}** erhält jetzt die Modusauswahl per DM."

        await interaction.response.edit_message(content=text, view=None)
        self.stop()

    @discord.ui.button(label="Mein Heimspiel", style=discord.ButtonStyle.primary)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, True)

    @discord.ui.button(label="Mein Gastspiel", style=discord.ButtonStyle.secondary)
    async def away_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, False)

    async def on_timeout(self):
        release_slot(self.reservation_key, self.owner_id)


class ModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str]):
        options = [discord.SelectOption(label=mode, value=mode) for mode in modes[:25]]
        super().__init__(
            placeholder="Spielmodus auswählen",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, ModeChoiceView):
            return
        view.selected_mode = self.values[0]
        await interaction.response.edit_message(content=view.render_text(), view=view)


class ModeChoiceView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        division: int,
        match: MatchRow,
        slot: OfferSlot,
        allowed_modes: list[str],
        ban_1: str,
        ban_2: str,
        reservation_key: str,
        reservation_owner_id: int,
        offer_channel_id: int,
        offer_message_id: int,
        slot_index: int,
    ):
        super().__init__(timeout=RESERVATION_SECONDS)
        self.owner_id = owner_id
        self.division = division
        self.match = match
        self.slot = slot
        self.allowed_modes = allowed_modes
        self.ban_1 = ban_1
        self.ban_2 = ban_2
        self.reservation_key = reservation_key
        self.reservation_owner_id = reservation_owner_id
        self.offer_channel_id = offer_channel_id
        self.offer_message_id = offer_message_id
        self.slot_index = slot_index
        self.selected_mode: str | None = None
        self.add_item(ModeSelect(allowed_modes))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Modusauswahl gehört nicht dir.", ephemeral=True)
            return False
        return True

    def render_text(self) -> str:
        bans = [b for b in (self.ban_1, self.ban_2) if b]
        if len(bans) >= 2:
            ban_text = f"**{bans[0]}** & **{bans[1]}**"
        elif len(bans) == 1:
            ban_text = f"**{bans[0]}**"
        else:
            ban_text = "keine Streichmodi hinterlegt"

        selected = self.selected_mode or "noch nicht gewählt"
        return (
            "🎮 **Spielmodus wählen**\n\n"
            f"**Spiel:** {self.match.home} vs. {self.match.away}\n"
            f"**Termin:** {self.slot.long_label}\n\n"
            "Du hast Heimrecht und bestimmst den Spielmodus.\n"
            f"**{self.match.away}** hat folgende Spielmodis gebannt: {ban_text}.\n\n"
            f"**Aktuelle Auswahl:** {selected}\n"
            "Wähle einen Modus und bestätige anschließend."
        )

    @discord.ui.button(label="Modus bestätigen", style=discord.ButtonStyle.success, row=1)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_mode:
            await interaction.response.send_message(
                "Bitte zuerst einen Spielmodus auswählen.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            if interaction.guild is None:
                # Component-Interaktionen in DMs enthalten guild nicht. Der Guild-Kontext
                # wird daher über den Client und die bekannte Server-ID aus matchcenter geholt.
                guild = interaction.client.get_guild(matchcenter.GUILD_ID)
                if guild is None:
                    guild = await interaction.client.fetch_guild(matchcenter.GUILD_ID)
            else:
                guild = interaction.guild

            result = await finalize_match_schedule(
                guild=guild,
                actor=interaction.user,
                division=self.division,
                row_index=self.match.row_index,
                home=self.match.home,
                away=self.match.away,
                mode=self.selected_mode,
                slot=self.slot,
            )

            offer_view = _OFFER_VIEWS.get((self.offer_channel_id, self.offer_message_id))
            if offer_view is not None:
                await offer_view.mark_booked(interaction.client, self.slot_index)

            release_slot(self.reservation_key, self.reservation_owner_id)
            self.stop()

            await interaction.edit_original_response(
                content=(
                    "✅ **Spieltermin eingetragen**\n\n"
                    f"**{result['home']} vs. {result['away']}**\n"
                    f"📅 {self.slot.long_label}\n"
                    f"🎮 {result['mode']}\n"
                    f"🔗 {result['event_url'] or result['multistream_url']}"
                ),
                view=None,
            )
        except Exception as exc:
            release_slot(self.reservation_key, self.reservation_owner_id)
            await interaction.edit_original_response(
                content=f"❌ Der Spieltermin wurde nicht eingetragen: {exc}",
                view=None,
            )

    async def on_timeout(self):
        release_slot(self.reservation_key, self.reservation_owner_id)


async def open_term_offer_modal(interaction: discord.Interaction) -> None:
    """Einstiegspunkt für /player → Termine vorschlagen."""
    await interaction.response.send_modal(TermOfferModal())


# =========================================================
# EIGENE TERMINANGEBOTE VERWALTEN
# =========================================================


def _own_active_offer_views(user_id: int) -> list[TermOfferView]:
    offers = []
    for view in list(_OFFER_VIEWS.values()):
        if view.creator_id != user_id:
            continue
        if not view.active_slots():
            continue
        offers.append(view)

    offers.sort(
        key=lambda v: min((slot.when for slot in v.active_slots()), default=dt.max.replace(tzinfo=BERLIN_TZ))
    )
    return offers[:25]


class MyOfferSelect(discord.ui.Select):
    def __init__(self, offers: list[TermOfferView]):
        options = []
        for view in offers[:25]:
            active = view.active_slots()
            first = active[0].short_label if active else "keine Termine"
            options.append(
                discord.SelectOption(
                    label=f"{first} · {len(active)} offen"[:100],
                    description=f"{view.division}.DIV · Angebot mit {len(view.slots)} Termin(en)"[:100],
                    value=f"{view.channel_id}:{view.message_id}",
                )
            )

        super().__init__(
            placeholder="Terminangebot auswählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            channel_id_s, message_id_s = self.values[0].split(":", 1)
            key = (int(channel_id_s), int(message_id_s))
        except Exception:
            await interaction.response.send_message("Das Terminangebot konnte nicht gelesen werden.", ephemeral=True)
            return

        offer = _OFFER_VIEWS.get(key)
        if offer is None or offer.creator_id != interaction.user.id or not offer.active_slots():
            await interaction.response.edit_message(
                content="Dieses Terminangebot ist nicht mehr verfügbar.",
                view=MyOffersListView(interaction.user.id, _own_active_offer_views(interaction.user.id)),
            )
            return

        await interaction.response.edit_message(
            content=_render_my_offer_management_text(offer),
            view=MyOfferManageView(interaction.user.id, offer),
        )


class MyOffersListView(discord.ui.View):
    def __init__(self, owner_id: int, offers: list[TermOfferView]):
        super().__init__(timeout=900)
        self.owner_id = owner_id
        if offers:
            self.add_item(MyOfferSelect(offers))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Verwaltung gehört nicht dir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Schließen", style=discord.ButtonStyle.secondary, row=2)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Terminangebots-Verwaltung geschlossen.", view=None)


def _render_my_offer_management_text(offer: TermOfferView) -> str:
    active = offer.active_slots()
    lines = [f"• **{slot.long_label}**" for slot in active]
    return (
        f"📌 **Mein Terminangebot · {offer.division}.DIV**\n\n"
        + ("\n".join(lines) if lines else "Keine offenen Termine mehr.")
        + "\n\nDu kannst einzelne Termine entfernen oder das gesamte restliche Angebot zurückziehen."
    )


class MyOfferRemoveButton(discord.ui.Button):
    def __init__(self, slot: OfferSlot, row: int):
        super().__init__(
            label=f"🗑 {slot.short_label}"[:80],
            style=discord.ButtonStyle.danger,
            row=row,
        )
        self.slot = slot

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, MyOfferManageView):
            return

        await interaction.response.defer()
        removed = await view.offer.remove_slot(interaction.client, self.slot.index)
        offers = _own_active_offer_views(interaction.user.id)

        if not removed:
            await interaction.edit_original_response(
                content="Dieser Termin ist bereits vergeben oder wurde schon entfernt.",
                view=MyOffersListView(interaction.user.id, offers),
            )
            return

        if not view.offer.active_slots():
            await interaction.edit_original_response(
                content="✅ Der letzte offene Termin wurde entfernt. Das Angebot ist damit geschlossen.",
                view=MyOffersListView(interaction.user.id, offers) if offers else None,
            )
            return

        await interaction.edit_original_response(
            content=_render_my_offer_management_text(view.offer),
            view=MyOfferManageView(interaction.user.id, view.offer),
        )


class MyOfferManageView(discord.ui.View):
    def __init__(self, owner_id: int, offer: TermOfferView):
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.offer = offer

        for idx, slot in enumerate(offer.active_slots()[:3]):
            self.add_item(MyOfferRemoveButton(slot, row=idx // 3))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Verwaltung gehört nicht dir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Alles zurückziehen", style=discord.ButtonStyle.danger, row=1)
    async def withdraw_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        count = await self.offer.withdraw_all(interaction.client)
        offers = _own_active_offer_views(interaction.user.id)
        await interaction.edit_original_response(
            content=f"✅ {count} offene{'r' if count == 1 else ''} Termin{' wurde' if count == 1 else 'e wurden'} zurückgezogen.",
            view=MyOffersListView(interaction.user.id, offers) if offers else None,
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        offers = _own_active_offer_views(interaction.user.id)
        await interaction.response.edit_message(
            content="📌 **Meine Terminangebote**\nWähle ein Angebot aus.",
            view=MyOffersListView(interaction.user.id, offers),
        )


async def open_my_offers_menu(interaction: discord.Interaction) -> None:
    offers = _own_active_offer_views(interaction.user.id)
    if not offers:
        await interaction.response.send_message(
            "Du hast aktuell keine offenen Terminangebote.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "📌 **Meine Terminangebote**\nWähle ein Angebot aus.",
        view=MyOffersListView(interaction.user.id, offers),
        ephemeral=True,
    )


# =========================================================
# BEREITS EINGETRAGENE TERMINE ÄNDERN / ABSAGEN
# =========================================================


def get_player_scheduled_matches(profile: PlayerProfile) -> list[MatchRow]:
    ws = matchcenter.get_div_ws_from_label(f"Div {profile.division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)
    target = normalize_name(profile.player_name)
    out: list[MatchRow] = []

    for row_index, row in enumerate(rows, start=1):
        if row_index == 1:
            continue
        home = _cell(row, 3)
        marker = _cell(row, 4)
        away = _cell(row, 5)
        timestamp = _cell(row, 1)
        mode = _cell(row, 2)
        if not home or not away or marker.lower() != "vs" or not timestamp:
            continue
        if target not in {normalize_name(home), normalize_name(away)}:
            continue
        out.append(
            MatchRow(
                row_index=row_index,
                home=home,
                away=away,
                timestamp=timestamp,
                marker_or_result=marker,
                mode=mode,
            )
        )

    def sort_key(match: MatchRow):
        try:
            return _parse_offer_datetime(match.timestamp)
        except Exception:
            return BERLIN_TZ.localize(dt.max.replace(tzinfo=None))

    out.sort(key=sort_key)
    return out[:25]


def _get_live_scheduled_match(division: int, row_index: int) -> MatchRow:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)
    if row_index < 1 or row_index > len(rows):
        raise RuntimeError("Die Begegnung wurde im Sheet nicht mehr gefunden.")

    row = rows[row_index - 1]
    match = MatchRow(
        row_index=row_index,
        home=_cell(row, 3),
        away=_cell(row, 5),
        timestamp=_cell(row, 1),
        marker_or_result=_cell(row, 4),
        mode=_cell(row, 2),
    )
    if not match.home or not match.away or not match.is_scheduled:
        raise RuntimeError("Für diese Begegnung ist inzwischen kein offener Termin mehr eingetragen.")
    return match


def _read_schedule_snapshot(division: int, row_index: int) -> dict:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)
    if row_index < 1 or row_index > len(rows):
        raise RuntimeError("Die Begegnung wurde im Sheet nicht mehr gefunden.")
    row = rows[row_index - 1]
    return {
        "timestamp": _cell(row, 1),
        "mode": _cell(row, 2),
        "home": _cell(row, 3),
        "marker": _cell(row, 4),
        "away": _cell(row, 5),
        "link": _cell(row, 6),
        "reporter": _cell(row, 7),
    }


def _write_schedule_snapshot(division: int, row_index: int, snapshot: dict) -> None:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    sheet_name = _sheet_name(ws, f"{division}.DIV")
    reqs = [
        {"range": f"B{row_index}:C{row_index}", "values": [[snapshot.get("timestamp", ""), snapshot.get("mode", "")]]},
        {"range": f"G{row_index}:H{row_index}", "values": [[snapshot.get("link", ""), snapshot.get("reporter", "")]]},
    ]
    sheet_write_call(
        lambda: ws.batch_update(reqs),
        invalidate_prefixes=matchcenter.matchcenter_invalidate_prefixes(sheet_name),
    )


def _clear_schedule(division: int, row_index: int) -> None:
    _rollback_league_schedule(division, row_index)


def _verify_schedule_timestamp(division: int, row_index: int, timestamp: str, mode: str) -> None:
    match = _get_live_scheduled_match(division, row_index)
    if clean_text(match.timestamp) != clean_text(timestamp):
        raise RuntimeError("Der neue Termin wurde im Sheet nicht korrekt gespeichert.")
    if clean_text(match.mode) != clean_text(mode):
        raise RuntimeError("Der Spielmodus wurde beim Verschieben unerwartet verändert.")


def _verify_schedule_cleared(division: int, row_index: int) -> None:
    ws = matchcenter.get_div_ws_from_label(f"Div {division}")
    rows = matchcenter.get_matchcenter_values(ws, force_refresh=True)
    if row_index < 1 or row_index > len(rows):
        raise RuntimeError("Die Begegnung wurde nach dem Austragen nicht mehr gefunden.")
    row = rows[row_index - 1]
    if _cell(row, 1) or _cell(row, 2) or _cell(row, 6) or _cell(row, 7):
        raise RuntimeError("Der Termin konnte im Sheet nicht vollständig entfernt werden.")
    if _cell(row, 4).lower() != "vs":
        raise RuntimeError("Die Begegnung ist nicht mehr offen und konnte deshalb nicht abgesagt werden.")


async def _find_discord_event_for_match(
    guild: discord.Guild,
    division: int,
    match: MatchRow,
):
    try:
        events = await guild.fetch_scheduled_events()
    except Exception as exc:
        raise RuntimeError(f"Discord-Events konnten nicht geladen werden: {exc}") from exc

    old_dt = None
    try:
        old_dt = _parse_offer_datetime(match.timestamp)
    except Exception:
        pass

    home_key = normalize_name(match.home)
    away_key = normalize_name(match.away)
    div_key = normalize_name(f"Div {division}")
    candidates = []

    for event in events:
        name_key = normalize_name(getattr(event, "name", ""))
        if home_key not in name_key or away_key not in name_key:
            continue
        if div_key and div_key not in name_key:
            # Ältere Eventnamen ohne exakten Div-String trotzdem zulassen,
            # solange Zeit und Paarung eindeutig passen.
            pass

        start_time = getattr(event, "start_time", None)
        distance = 10**12
        if old_dt is not None and start_time is not None:
            try:
                distance = abs((start_time.astimezone(BERLIN_TZ) - old_dt).total_seconds())
            except Exception:
                pass
        candidates.append((distance, event))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    # Bei vorhandenem alten Datum nur einen zeitlich plausiblen Treffer verwenden.
    if old_dt is not None and candidates[0][0] > 6 * 3600:
        return None
    return candidates[0][1]


async def _notify_schedule_change_players(
    guild: discord.Guild,
    match: MatchRow,
    text: str,
) -> None:
    for player_name in (match.home, match.away):
        member = await matchcenter.find_member_by_player_name(guild, player_name)
        if member is None:
            continue
        try:
            await member.send(text)
        except Exception as exc:
            print(f"⚠️ [TERMINÄNDERUNG] DM an {player_name} fehlgeschlagen: {exc}")


async def apply_schedule_change(
    *,
    guild: discord.Guild,
    division: int,
    row_index: int,
    requested_old_timestamp: str,
    action: str,
    actor_name: str,
    new_when: dt | None = None,
) -> dict:
    live_match = await asyncio.to_thread(_get_live_scheduled_match, division, row_index)
    if clean_text(live_match.timestamp) != clean_text(requested_old_timestamp):
        raise RuntimeError("Der Termin wurde zwischenzeitlich bereits verändert.")

    snapshot = await asyncio.to_thread(_read_schedule_snapshot, division, row_index)
    event = await _find_discord_event_for_match(guild, division, live_match)

    if action == "reschedule":
        if new_when is None:
            raise RuntimeError("Der neue Termin fehlt.")
        if new_when <= dt.now(BERLIN_TZ):
            raise RuntimeError("Der neue Termin muss in der Zukunft liegen.")

        new_timestamp = new_when.strftime("%d.%m.%Y %H:%M")
        for player in (live_match.home, live_match.away):
            conflict = await asyncio.to_thread(
                player_has_schedule_at,
                division,
                player,
                new_timestamp,
                row_index,
            )
            if conflict:
                raise RuntimeError(f"{player} hat zu diesem Zeitpunkt bereits ein anderes TFL-Spiel.")

        link = snapshot.get("link") or await asyncio.to_thread(
            matchcenter.build_multistream_url,
            live_match.home,
            live_match.away,
        )
        await asyncio.to_thread(
            matchcenter.write_league_schedule,
            row_index,
            live_match.mode,
            link,
            f"Termin verschoben: {actor_name}",
            new_timestamp,
            f"Div {division}",
        )

        try:
            await asyncio.to_thread(
                _verify_schedule_timestamp,
                division,
                row_index,
                new_timestamp,
                live_match.mode,
            )

            end_when = new_when + timedelta(hours=2)
            if event is not None:
                await event.edit(
                    start_time=new_when,
                    end_time=end_when,
                    description=f"TFL-Termin nach Zustimmung verschoben von {actor_name}",
                )
            else:
                title = f"Div {division} | {live_match.home} vs. {live_match.away} | {live_match.mode}"
                event = await matchcenter.create_scheduled_event(
                    guild,
                    title,
                    link,
                    new_when,
                    end_when,
                    f"TFL-Termin nach Zustimmung verschoben von {actor_name}",
                )
        except Exception:
            await asyncio.to_thread(_write_schedule_snapshot, division, row_index, snapshot)
            raise

        text = (
            "✅ **Spieltermin verschoben**\n\n"
            f"**{live_match.home} vs. {live_match.away}**\n"
            f"📅 Neu: **{new_when.strftime('%d.%m.%Y · %H:%M')} Uhr**\n"
            f"🎮 {live_match.mode}"
        )
        await _notify_schedule_change_players(guild, live_match, text)

        channel = await _get_division_channel(guild, division)
        if channel is not None and hasattr(channel, "send"):
            try:
                await channel.send(
                    f"📅 **Termin verschoben:** {live_match.home} vs. {live_match.away} → "
                    f"{new_when.strftime('%d.%m.%Y %H:%M')} Uhr"
                )
            except Exception:
                pass

        return {"action": action, "timestamp": new_timestamp, "match": live_match}

    if action == "cancel":
        await asyncio.to_thread(_clear_schedule, division, row_index)
        try:
            await asyncio.to_thread(_verify_schedule_cleared, division, row_index)
            if event is not None:
                await event.delete()
        except Exception:
            await asyncio.to_thread(_write_schedule_snapshot, division, row_index, snapshot)
            raise

        text = (
            "❌ **Spieltermin abgesagt**\n\n"
            f"**{live_match.home} vs. {live_match.away}**\n"
            f"Der Termin **{live_match.timestamp} Uhr** wurde nach Zustimmung entfernt.\n"
            "Die Begegnung ist wieder offen und kann neu terminiert werden."
        )
        await _notify_schedule_change_players(guild, live_match, text)

        channel = await _get_division_channel(guild, division)
        if channel is not None and hasattr(channel, "send"):
            try:
                await channel.send(
                    f"❌ **Termin abgesagt:** {live_match.home} vs. {live_match.away} "
                    f"({live_match.timestamp} Uhr). Die Begegnung ist wieder offen."
                )
            except Exception:
                pass

        return {"action": action, "timestamp": "", "match": live_match}

    raise RuntimeError("Unbekannte Terminänderung.")


class ScheduledMatchSelect(discord.ui.Select):
    def __init__(self, profile: PlayerProfile, matches: list[MatchRow]):
        self.profile = profile
        options = []
        target = normalize_name(profile.player_name)
        for match in matches[:25]:
            opponent = match.away if normalize_name(match.home) == target else match.home
            options.append(
                discord.SelectOption(
                    label=f"{match.timestamp} · {opponent}"[:100],
                    description=f"{match.home} vs. {match.away} · {match.mode or 'Modus offen'}"[:100],
                    value=str(match.row_index),
                )
            )
        super().__init__(placeholder="Eingetragenen Termin auswählen …", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            row_index = int(self.values[0])
            match = await asyncio.to_thread(_get_live_scheduled_match, self.profile.division, row_index)
        except Exception as exc:
            await interaction.edit_original_response(content=f"❌ Termin konnte nicht geladen werden: {exc}", view=None)
            return

        await interaction.edit_original_response(
            content=(
                "🗓️ **Termin verwalten**\n\n"
                f"**{match.home} vs. {match.away}**\n"
                f"📅 {match.timestamp} Uhr\n"
                f"🎮 {match.mode or 'Modus offen'}\n\n"
                "Eine Änderung wird erst ausgeführt, wenn der Gegner zustimmt."
            ),
            view=ScheduledMatchActionView(interaction.user.id, self.profile, match),
        )


class ScheduledMatchesListView(discord.ui.View):
    def __init__(self, owner_id: int, profile: PlayerProfile, matches: list[MatchRow]):
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.profile = profile
        self.add_item(ScheduledMatchSelect(profile, matches))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Terminverwaltung gehört nicht dir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Schließen", style=discord.ButtonStyle.secondary, row=2)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Terminverwaltung geschlossen.", view=None)


class ScheduledMatchActionView(discord.ui.View):
    def __init__(self, owner_id: int, profile: PlayerProfile, match: MatchRow):
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.profile = profile
        self.match = match

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Diese Terminverwaltung gehört nicht dir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Termin verschieben", style=discord.ButtonStyle.primary, row=0)
    async def reschedule_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            RescheduleExistingMatchModal(self.profile, self.match)
        )

    @discord.ui.button(label="Termin absagen", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_schedule_change_approval_request(
            interaction=interaction,
            profile=self.profile,
            match=self.match,
            action="cancel",
            new_when=None,
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        matches = await asyncio.to_thread(get_player_scheduled_matches, self.profile)
        await interaction.edit_original_response(
            content="🗓️ **Termin verschieben / absagen**\nWähle einen bereits eingetragenen Termin.",
            view=ScheduledMatchesListView(interaction.user.id, self.profile, matches),
        )


class RescheduleExistingMatchModal(discord.ui.Modal, title="Termin verschieben"):
    new_datetime = discord.ui.TextInput(
        label="Neuer Termin",
        placeholder="TT.MM.JJJJ HH:MM",
        required=True,
        max_length=30,
    )

    def __init__(self, profile: PlayerProfile, match: MatchRow):
        super().__init__()
        self.profile = profile
        self.match = match

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.new_datetime.value or "").strip()
        try:
            new_when = _parse_offer_datetime(raw)
        except ValueError:
            await interaction.response.send_message(
                "Bitte das Format `TT.MM.JJJJ HH:MM` verwenden.",
                ephemeral=True,
            )
            return

        if new_when <= dt.now(BERLIN_TZ):
            await interaction.response.send_message("Der neue Termin muss in der Zukunft liegen.", ephemeral=True)
            return

        await _send_schedule_change_approval_request(
            interaction=interaction,
            profile=self.profile,
            match=self.match,
            action="reschedule",
            new_when=new_when,
        )


async def _send_schedule_change_approval_request(
    *,
    interaction: discord.Interaction,
    profile: PlayerProfile,
    match: MatchRow,
    action: str,
    new_when: dt | None,
) -> None:
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    if guild is None:
        guild = interaction.client.get_guild(matchcenter.GUILD_ID)
    if guild is None:
        try:
            guild = await interaction.client.fetch_guild(matchcenter.GUILD_ID)
        except Exception:
            guild = None
    if guild is None:
        await interaction.edit_original_response(content="Der TFL-Server konnte nicht geladen werden.")
        return

    try:
        live_match = await asyncio.to_thread(_get_live_scheduled_match, profile.division, match.row_index)
    except Exception as exc:
        await interaction.edit_original_response(content=f"❌ {exc}")
        return

    target = normalize_name(profile.player_name)
    opponent_name = live_match.away if normalize_name(live_match.home) == target else live_match.home
    opponent = await matchcenter.find_member_by_player_name(guild, opponent_name)
    if opponent is None:
        await interaction.edit_original_response(
            content=f"Der Gegner **{opponent_name}** konnte auf Discord nicht gefunden werden."
        )
        return

    if action == "reschedule":
        new_text = new_when.strftime("%d.%m.%Y · %H:%M") if new_when else "?"
        request_text = (
            "🗓️ **Anfrage: Spieltermin verschieben**\n\n"
            f"**{live_match.home} vs. {live_match.away}**\n"
            f"Bisher: **{live_match.timestamp} Uhr**\n"
            f"Neu: **{new_text} Uhr**\n"
            f"🎮 {live_match.mode or 'Modus offen'}\n\n"
            f"Angefragt von **{interaction.user.display_name}**. Stimmst du der Änderung zu?"
        )
    else:
        request_text = (
            "❌ **Anfrage: Spieltermin absagen**\n\n"
            f"**{live_match.home} vs. {live_match.away}**\n"
            f"Termin: **{live_match.timestamp} Uhr**\n"
            f"🎮 {live_match.mode or 'Modus offen'}\n\n"
            f"Angefragt von **{interaction.user.display_name}**. Stimmst du der Absage zu?"
        )

    view = ScheduleChangeApprovalView(
        approver_id=opponent.id,
        requester_id=interaction.user.id,
        requester_name=interaction.user.display_name,
        division=profile.division,
        row_index=live_match.row_index,
        old_timestamp=live_match.timestamp,
        home=live_match.home,
        away=live_match.away,
        mode=live_match.mode,
        action=action,
        new_when=new_when,
    )

    try:
        await opponent.send(request_text, view=view)
    except Exception as exc:
        await interaction.edit_original_response(
            content=f"Die Zustimmungsanfrage konnte nicht an **{opponent_name}** gesendet werden: {exc}"
        )
        return

    verb = "Verschiebung" if action == "reschedule" else "Absage"
    await interaction.edit_original_response(
        content=f"✅ Die Anfrage zur **{verb}** wurde an **{opponent_name}** geschickt. Erst nach Zustimmung wird etwas geändert.",
        view=None,
    )


class ScheduleChangeApprovalView(discord.ui.View):
    def __init__(
        self,
        *,
        approver_id: int,
        requester_id: int,
        requester_name: str,
        division: int,
        row_index: int,
        old_timestamp: str,
        home: str,
        away: str,
        mode: str,
        action: str,
        new_when: dt | None,
    ):
        super().__init__(timeout=24 * 60 * 60)
        self.approver_id = approver_id
        self.requester_id = requester_id
        self.requester_name = requester_name
        self.division = division
        self.row_index = row_index
        self.old_timestamp = old_timestamp
        self.home = home
        self.away = away
        self.mode = mode
        self.action = action
        self.new_when = new_when
        self.processing = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.approver_id:
            await interaction.response.send_message("Diese Anfrage ist nicht für dich bestimmt.", ephemeral=True)
            return False
        return True

    async def _notify_requester(self, client: discord.Client, text: str):
        try:
            user = client.get_user(self.requester_id) or await client.fetch_user(self.requester_id)
            await user.send(text)
        except Exception as exc:
            print(f"⚠️ [TERMINÄNDERUNG] Rückmeldung an Antragsteller fehlgeschlagen: {exc}")

    @discord.ui.button(label="Zustimmen", style=discord.ButtonStyle.success, row=0)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processing:
            await interaction.response.send_message("Die Anfrage wird bereits verarbeitet.", ephemeral=True)
            return
        self.processing = True
        await interaction.response.defer()

        guild = interaction.client.get_guild(matchcenter.GUILD_ID)
        if guild is None:
            try:
                guild = await interaction.client.fetch_guild(matchcenter.GUILD_ID)
            except Exception:
                guild = None

        if guild is None:
            self.processing = False
            await interaction.edit_original_response(content="❌ Der TFL-Server konnte nicht geladen werden.", view=self)
            return

        try:
            result = await apply_schedule_change(
                guild=guild,
                division=self.division,
                row_index=self.row_index,
                requested_old_timestamp=self.old_timestamp,
                action=self.action,
                actor_name=self.requester_name,
                new_when=self.new_when,
            )
        except Exception as exc:
            self.processing = False
            await interaction.edit_original_response(
                content=f"❌ Die Änderung konnte nicht durchgeführt werden: {exc}",
                view=self,
            )
            await self._notify_requester(
                interaction.client,
                f"❌ Deine Terminänderung für **{self.home} vs. {self.away}** konnte nicht umgesetzt werden: {exc}",
            )
            return

        if result["action"] == "reschedule":
            final_text = (
                "✅ **Terminverschiebung bestätigt und eingetragen.**\n\n"
                f"{self.home} vs. {self.away}\n"
                f"Neuer Termin: **{self.new_when.strftime('%d.%m.%Y · %H:%M')} Uhr**"
            )
        else:
            final_text = (
                "✅ **Terminabsage bestätigt.**\n\n"
                f"{self.home} vs. {self.away} ist wieder ohne Termin offen."
            )

        await interaction.edit_original_response(content=final_text, view=None)
        await self._notify_requester(interaction.client, final_text)
        self.stop()

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger, row=0)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        action_text = "Terminverschiebung" if self.action == "reschedule" else "Terminabsage"
        text = f"❌ **{action_text} abgelehnt.** Der bestehende Termin bleibt unverändert."
        await interaction.response.edit_message(content=text, view=None)
        await self._notify_requester(
            interaction.client,
            f"❌ Deine Anfrage zur **{action_text}** für **{self.home} vs. {self.away}** wurde abgelehnt.",
        )
        self.stop()


async def open_schedule_manage_menu(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Diese Funktion ist nur auf dem TFL-Server verfügbar.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        profile = await asyncio.to_thread(find_member_profile, interaction.user)
        if profile is None:
            await interaction.edit_original_response(content="Dein Spielername wurde in keiner Division gefunden.")
            return

        matches = await asyncio.to_thread(get_player_scheduled_matches, profile)
        if not matches:
            await interaction.edit_original_response(content="Du hast aktuell keinen eingetragenen offenen Spieltermin.")
            return

        await interaction.edit_original_response(
            content="🗓️ **Termin verschieben / absagen**\nWähle einen bereits eingetragenen Termin.",
            view=ScheduledMatchesListView(interaction.user.id, profile, matches),
        )
    except Exception as exc:
        await interaction.edit_original_response(content=f"❌ Terminverwaltung konnte nicht geladen werden: {exc}")

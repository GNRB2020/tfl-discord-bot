"""
Google-Sheets helpers for the TFNL Ladder ELO system.

Dieses Modul:
- legt benötigte Sheets/Header automatisch an
- liest/schreibt aktuelle ELO-Ratings
- schreibt Rating-History
- verarbeitet veröffentlichte Matches idempotent
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from sheet_guard import (
    get_all_records_cached,
    row_values_cached,
    sheet_write_call,
    invalidate_cache as invalidate_global_sheet_cache,
)

from ladder_elo import (
    START_ELO,
    SCOPE_SEASON_OVERALL,
    SCOPE_SEASON_MODE,
    SCOPE_ALLTIME_OVERALL,
    SCOPE_ALLTIME_MODE,
    PairingPlayer,
    calculate_new_elo,
    calculate_pairing_elo,
    calculate_winrate,
    create_elo_pairings,
    sort_standings_rows,
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

TFNL_SPREADSHEET_ID = os.getenv(
    "TFNL_SPREADSHEET_ID",
    "1TamFbS5cRCcgSJFoQEohXdv03tVhk0VynvleeiVBQsM",
).strip()

CREDS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json"),
).strip()

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

SETTINGS_SHEET_NAME = "Settings"
SETTINGS_HEADERS = ["Key", "Value"]
ACTIVE_SEASON_KEY = "ACTIVE_SEASON"
DEFAULT_ACTIVE_SEASON = "TFNL-S1"

CORE_SHEETS_REQUIRING_SEASON = [
    "Schedule",
    "Signup",
    "Matches",
    "Players",
]

RATINGS_SHEET_NAME = "Ladder_Ratings"
RATING_HISTORY_SHEET_NAME = "Ladder_RatingHistory"
SEED_COMPARISON_SHEET_NAME = "Ladder_SeedComparison"

RATINGS_HEADERS = [
    "Player ID",
    "Player Name",
    "Season",
    "Mode",
    "Scope",
    "Elo",
    "Wins",
    "Draws",
    "Lose",
    "Games",
    "Winrate",
    "Updated At",
]

RATING_HISTORY_HEADERS = [
    "Rating Event ID",
    "Season",
    "Slot ID",
    "Date",
    "Mode",
    "Race Type",
    "Player ID",
    "Player Name",
    "Opponent Info",
    "Placement",
    "Score",
    "Elo Scope",
    "Elo Before",
    "Opponent Elo Used",
    "Elo After",
    "Elo Change",
    "Result Type",
    "Created At",
]

SEED_COMPARISON_HEADERS = [
    "Season",
    "Slot ID",
    "Date",
    "Mode",
    "Placement",
    "Player ID",
    "Player Name",
    "Time",
    "Status",
    "Winner Time",
    "Gap To Winner",
    "Created At",
]

_WORKSHEET_CACHE: dict[str, gspread.Worksheet] = {}
_ELO_SHEETS_READY = False
_LAST_ELO_SETUP_STATUS: dict | None = None



def normalize_text(value) -> str:
    return str(value or "").strip()


def normalize_mode(value) -> str:
    return normalize_text(value) or "ALL"


def now_text() -> str:
    return datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")


def int_value(value) -> int:
    try:
        return int(float(str(value).replace(",", ".").strip()))
    except Exception:
        return 0


def float_value(value, default: float = START_ELO) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(str(value).replace(",", ".").strip())
    except Exception:
        return float(default)


def format_elo(value) -> str:
    return str(round(float_value(value), 1))


def format_elo_change(value) -> str:
    """
    Anzeigeformat für Discord/interne Rückgaben.
    Beispiel: +16.0, -16.0, +0.0
    """
    return f"{float_value(value, 0.0):+.1f}"


def format_elo_change_for_sheet(value) -> str:
    """
    Google Sheets interpretiert Werte mit führendem Plus bei USER_ENTERED
    teilweise als Formel. Dadurch entsteht in der Spalte `Elo Change`
    der Zellfehler `ERROR!`.

    Ein führender Apostroph erzwingt Textspeicherung. In Google Sheets wird
    der Apostroph nicht angezeigt; sichtbar bleibt also normal `+16.0`.
    Negative Werte brauchen den Schutz nicht, werden aber ebenfalls sauber
    als Text behandelt.
    """
    return "'" + format_elo_change(value)


def get_spreadsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(TFNL_SPREADSHEET_ID)


def get_or_create_sheet(title: str, rows: int = 1000, cols: int = 30):
    cached = _WORKSHEET_CACHE.get(title)

    if cached is not None:
        return cached

    spreadsheet = get_spreadsheet()

    try:
        sheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = sheet_write_call(
            lambda: spreadsheet.add_worksheet(title=title, rows=rows, cols=cols),
            invalidate_prefixes=[
                f"records:{title}",
                f"values:{title}",
                f"row:{title}:",
                f"col:{title}:",
                f"cell:{title}:",
            ],
        )

    _WORKSHEET_CACHE[title] = sheet
    return sheet


def invalidate_elo_cache(sheet_name: str | None = None):
    if sheet_name is None:
        for name in (
            SETTINGS_SHEET_NAME,
            RATINGS_SHEET_NAME,
            RATING_HISTORY_SHEET_NAME,
            SEED_COMPARISON_SHEET_NAME,
            *CORE_SHEETS_REQUIRING_SEASON,
        ):
            invalidate_elo_cache(name)
        return

    invalidate_global_sheet_cache(f"records:{sheet_name}")
    invalidate_global_sheet_cache(f"values:{sheet_name}")
    invalidate_global_sheet_cache(f"row:{sheet_name}:")
    invalidate_global_sheet_cache(f"col:{sheet_name}:")
    invalidate_global_sheet_cache(f"cell:{sheet_name}:")


def ensure_headers(sheet, required_headers: list[str]) -> list[str]:
    sheet_name = getattr(sheet, "title", "")
    existing_headers = row_values_cached(
        lambda: sheet,
        sheet_name=sheet_name,
        row=1,
        ttl_seconds=300,
    )

    if not existing_headers:
        sheet_write_call(
            lambda: sheet.update("A1", [required_headers]),
            invalidate_prefixes=[
                f"records:{sheet_name}",
                f"values:{sheet_name}",
                f"row:{sheet_name}:",
            ],
        )
        return required_headers[:]

    headers = existing_headers[:]
    missing_headers = [header for header in required_headers if header not in headers]

    if missing_headers:
        start_col = len(headers) + 1
        end_col = len(headers) + len(missing_headers)
        start_a1 = gspread.utils.rowcol_to_a1(1, start_col)
        end_a1 = gspread.utils.rowcol_to_a1(1, end_col)

        sheet_write_call(
            lambda: sheet.update(f"{start_a1}:{end_a1}", [missing_headers]),
            invalidate_prefixes=[
                f"records:{sheet_name}",
                f"values:{sheet_name}",
                f"row:{sheet_name}:",
            ],
        )
        headers.extend(missing_headers)

    return headers


def ensure_sheet_with_headers(
    title: str,
    required_headers: list[str],
    rows: int = 1000,
    cols: int | None = None,
):
    sheet = get_or_create_sheet(
        title=title,
        rows=rows,
        cols=cols or max(30, len(required_headers)),
    )
    headers = ensure_headers(sheet, required_headers)
    return sheet, headers


def ensure_settings_sheet() -> str:
    sheet, _ = ensure_sheet_with_headers(
        SETTINGS_SHEET_NAME,
        SETTINGS_HEADERS,
        rows=100,
        cols=len(SETTINGS_HEADERS),
    )

    records = get_all_records_cached(
        lambda: sheet,
        sheet_name=SETTINGS_SHEET_NAME,
        ttl_seconds=60,
    )

    for row_index, row in enumerate(records, start=2):
        if normalize_text(row.get("Key")) == ACTIVE_SEASON_KEY:
            value = normalize_text(row.get("Value"))

            if value:
                return value

            sheet_write_call(
                lambda: sheet.update_cell(row_index, 2, DEFAULT_ACTIVE_SEASON),
                invalidate_prefixes=[
                    f"records:{SETTINGS_SHEET_NAME}",
                    f"values:{SETTINGS_SHEET_NAME}",
                    f"row:{SETTINGS_SHEET_NAME}:",
                    f"cell:{SETTINGS_SHEET_NAME}:",
                ],
            )
            return DEFAULT_ACTIVE_SEASON

    sheet_write_call(
        lambda: sheet.append_row([ACTIVE_SEASON_KEY, DEFAULT_ACTIVE_SEASON], value_input_option="USER_ENTERED"),
        invalidate_prefixes=[
            f"records:{SETTINGS_SHEET_NAME}",
            f"values:{SETTINGS_SHEET_NAME}",
        ],
    )
    return DEFAULT_ACTIVE_SEASON


def get_active_season() -> str:
    return ensure_settings_sheet()


def ensure_core_season_columns() -> list[str]:
    touched = []

    for sheet_name in CORE_SHEETS_REQUIRING_SEASON:
        sheet = get_or_create_sheet(sheet_name)
        existing_headers = row_values_cached(
            lambda: sheet,
            sheet_name=sheet_name,
            row=1,
            ttl_seconds=300,
        )

        if not existing_headers:
            continue

        if "Season" not in existing_headers:
            next_col = len(existing_headers) + 1
            sheet_write_call(
                lambda: sheet.update_cell(1, next_col, "Season"),
                invalidate_prefixes=[
                    f"records:{sheet_name}",
                    f"values:{sheet_name}",
                    f"row:{sheet_name}:",
                ],
            )
            touched.append(sheet_name)

    return touched


def ensure_ladder_elo_sheets(force_refresh: bool = False) -> dict:
    global _ELO_SHEETS_READY, _LAST_ELO_SETUP_STATUS

    if _ELO_SHEETS_READY and _LAST_ELO_SETUP_STATUS is not None and not force_refresh:
        return _LAST_ELO_SETUP_STATUS

    active_season = ensure_settings_sheet()
    season_columns_added = ensure_core_season_columns()

    ensure_sheet_with_headers(
        RATINGS_SHEET_NAME,
        RATINGS_HEADERS,
        rows=1000,
        cols=len(RATINGS_HEADERS),
    )

    ensure_sheet_with_headers(
        RATING_HISTORY_SHEET_NAME,
        RATING_HISTORY_HEADERS,
        rows=5000,
        cols=len(RATING_HISTORY_HEADERS),
    )

    ensure_sheet_with_headers(
        SEED_COMPARISON_SHEET_NAME,
        SEED_COMPARISON_HEADERS,
        rows=5000,
        cols=len(SEED_COMPARISON_HEADERS),
    )

    _LAST_ELO_SETUP_STATUS = {
        "active_season": active_season,
        "season_columns_added": season_columns_added,
        "sheets": [
            SETTINGS_SHEET_NAME,
            RATINGS_SHEET_NAME,
            RATING_HISTORY_SHEET_NAME,
            SEED_COMPARISON_SHEET_NAME,
        ],
        "checked_at": now_text(),
    }
    _ELO_SHEETS_READY = True

    return _LAST_ELO_SETUP_STATUS


def scope_key_parts(scope: str, season: str, mode: str) -> tuple[str, str]:
    selected_mode = normalize_mode(mode)

    if scope == SCOPE_SEASON_OVERALL:
        return normalize_text(season), "ALL"

    if scope == SCOPE_SEASON_MODE:
        return normalize_text(season), selected_mode

    if scope == SCOPE_ALLTIME_OVERALL:
        return "ALL_TIME", "ALL"

    if scope == SCOPE_ALLTIME_MODE:
        return "ALL_TIME", selected_mode

    raise ValueError(f"Unbekannter ELO-Scope: {scope}")


def get_ratings_sheet():
    ensure_ladder_elo_sheets()
    return get_or_create_sheet(RATINGS_SHEET_NAME)


def get_history_sheet():
    ensure_ladder_elo_sheets()
    return get_or_create_sheet(RATING_HISTORY_SHEET_NAME)


def load_ratings_rows_with_index() -> list[tuple[int, dict]]:
    rows = get_all_records_cached(
        get_ratings_sheet,
        sheet_name=RATINGS_SHEET_NAME,
        ttl_seconds=30,
    )
    return list(enumerate(rows, start=2))


def load_history_rows() -> list[dict]:
    return get_all_records_cached(
        get_history_sheet,
        sheet_name=RATING_HISTORY_SHEET_NAME,
        ttl_seconds=30,
    )


def load_history_event_ids(force_refresh: bool = False) -> set[str]:
    """
    Idempotenz-Schutz für process_match_elo().

    Fehlte im aktuellen Stand, obwohl process_match_elo() die Funktion aufruft.
    Dadurch brach die ELO-Verarbeitung nach Matchabschluss mit NameError ab.
    """
    rows = get_all_records_cached(
        get_history_sheet,
        sheet_name=RATING_HISTORY_SHEET_NAME,
        ttl_seconds=300,
        force_refresh=force_refresh,
    )

    return {
        normalize_text(row.get("Rating Event ID"))
        for row in rows
        if normalize_text(row.get("Rating Event ID"))
    }


def get_match_elo_changes(
    match_id: str,
    scope: str = SCOPE_SEASON_OVERALL,
) -> dict[str, str]:
    selected_match_id = normalize_text(match_id)
    changes: dict[str, str] = {}

    if not selected_match_id:
        return changes

    for row in load_history_rows():
        event_id = normalize_text(row.get("Rating Event ID"))

        if not event_id.startswith(f"{selected_match_id}:"):
            continue

        if normalize_text(row.get("Elo Scope")) != scope:
            continue

        player_id = normalize_text(row.get("Player ID"))
        elo_change = normalize_text(row.get("Elo Change"))

        if player_id and elo_change:
            changes[player_id] = elo_change

    return changes


def get_slot_elo_changes(
    slot_id: str,
    scope: str = SCOPE_SEASON_OVERALL,
) -> dict[str, str]:
    selected_slot_id = normalize_text(slot_id)
    totals: dict[str, float] = {}

    if not selected_slot_id:
        return {}

    for row in load_history_rows():
        if normalize_text(row.get("Slot ID")) != selected_slot_id:
            continue

        if normalize_text(row.get("Elo Scope")) != scope:
            continue

        player_id = normalize_text(row.get("Player ID"))

        if not player_id:
            continue

        try:
            change = float(normalize_text(row.get("Elo Change")).replace(",", "."))
        except Exception:
            change = 0.0

        totals[player_id] = totals.get(player_id, 0.0) + change

    return {
        player_id: f"{change:+.1f}"
        for player_id, change in totals.items()
    }


def find_rating_row(
    player_id: str,
    season: str,
    mode: str,
    scope: str,
) -> tuple[int | None, dict | None]:
    selected_season, selected_mode = scope_key_parts(scope, season, mode)

    for row_index, row in load_ratings_rows_with_index():
        if (
            normalize_text(row.get("Player ID")) == normalize_text(player_id)
            and normalize_text(row.get("Season")) == selected_season
            and normalize_text(row.get("Mode")) == selected_mode
            and normalize_text(row.get("Scope")) == scope
        ):
            return row_index, row

    return None, None


def get_rating_value(
    player_id: str,
    season: str,
    mode: str,
    scope: str,
    default: float = START_ELO,
) -> float:
    _, row = find_rating_row(player_id, season, mode, scope)

    if not row:
        return float(default)

    return float_value(row.get("Elo"), default)


def upsert_rating_row(
    player_id: str,
    player_name: str,
    season: str,
    mode: str,
    scope: str,
    elo: float,
    result_type: str,
):
    sheet = get_ratings_sheet()
    selected_season, selected_mode = scope_key_parts(scope, season, mode)
    row_index, current = find_rating_row(player_id, season, mode, scope)

    wins = int_value(current.get("Wins")) if current else 0
    draws = int_value(current.get("Draws")) if current else 0
    lose = int_value(current.get("Lose")) if current else 0

    if result_type == "Sieg":
        wins += 1
    elif result_type == "Remis":
        draws += 1
    else:
        lose += 1

    games = wins + draws + lose
    winrate = calculate_winrate(wins, draws, lose)

    values = [
        normalize_text(player_id),
        normalize_text(player_name),
        selected_season,
        selected_mode,
        scope,
        format_elo(elo),
        wins,
        draws,
        lose,
        games,
        f"{winrate:.1f}",
        now_text(),
    ]

    if row_index:
        sheet_write_call(
            lambda: sheet.update(f"A{row_index}:L{row_index}", [values], value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{RATINGS_SHEET_NAME}",
                f"values:{RATINGS_SHEET_NAME}",
                f"row:{RATINGS_SHEET_NAME}:",
            ],
        )
    else:
        sheet_write_call(
            lambda: sheet.append_row(values, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{RATINGS_SHEET_NAME}",
                f"values:{RATINGS_SHEET_NAME}",
            ],
        )


def build_pairing_players(
    participants: list[dict],
    season: str,
    mode: str,
) -> list[PairingPlayer]:
    players: list[PairingPlayer] = []

    for participant in participants:
        player_id = normalize_text(participant.get("discord_id") or participant.get("Player ID"))
        name = normalize_text(participant.get("name") or participant.get("Player Name"))

        season_mode_elo = get_rating_value(
            player_id,
            season,
            mode,
            SCOPE_SEASON_MODE,
            START_ELO,
        )
        alltime_mode_elo = get_rating_value(
            player_id,
            season,
            mode,
            SCOPE_ALLTIME_MODE,
            START_ELO,
        )
        season_overall_elo = get_rating_value(
            player_id,
            season,
            "",
            SCOPE_SEASON_OVERALL,
            START_ELO,
        )
        alltime_overall_elo = get_rating_value(
            player_id,
            "ALL_TIME",
            "",
            SCOPE_ALLTIME_OVERALL,
            START_ELO,
        )

        pairing_elo = (
            0.35 * season_mode_elo
            + 0.15 * alltime_mode_elo
            + 0.35 * season_overall_elo
            + 0.15 * alltime_overall_elo
        )

        players.append(
            PairingPlayer(
                player_id=player_id,
                name=name,
                pairing_elo=pairing_elo,
            )
        )

    return players


def score_from_result(result_type: str) -> float:
    normalized = normalize_text(result_type).lower()

    if normalized == "sieg":
        return 1.0

    if normalized == "remis":
        return 0.5

    return 0.0


def placement_from_result(result_type: str) -> int:
    normalized = normalize_text(result_type).lower()

    if normalized == "sieg":
        return 1

    if normalized == "remis":
        return 2

    return 3


def parse_match_players(match_row: dict) -> list[dict]:
    players = []

    for no in (1, 2, 3):
        player_id = normalize_text(match_row.get(f"Spieler {no} Discord ID"))
        player_name = normalize_text(match_row.get(f"Spieler {no} Name"))

        if not player_id:
            continue

        result_type = normalize_text(match_row.get(f"Ergebnis Spieler {no}"))

        if not result_type:
            continue

        players.append(
            {
                "no": no,
                "player_id": player_id,
                "name": player_name,
                "result_type": result_type,
                "score": score_from_result(result_type),
                "placement": placement_from_result(result_type),
            }
        )

    return players


def append_history_rows(rows: list[list]):
    if rows:
        sheet_write_call(
            lambda: get_history_sheet().append_rows(rows, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{RATING_HISTORY_SHEET_NAME}",
                f"values:{RATING_HISTORY_SHEET_NAME}",
            ],
        )


def process_match_elo(match_row: dict, schedule_row: dict | None = None) -> dict:
    """
    Verarbeitet ein bereits mit Ergebnis versehenes Match.
    Idempotenz: Bereits vorhandene Rating Event IDs werden übersprungen.
    """
    ensure_ladder_elo_sheets()

    match_id = normalize_text(match_row.get("Match ID"))
    slot_id = normalize_text(match_row.get("Slot ID"))
    race_type = normalize_text(match_row.get("Matchtyp"))
    season = normalize_text(match_row.get("Season")) or get_active_season()

    if schedule_row:
        date_text = normalize_text(schedule_row.get("Datum"))
        mode = normalize_text(schedule_row.get("Modus"))
    else:
        date_text = ""
        mode = normalize_text(match_row.get("Modus"))

    if not mode:
        mode = "Unknown"

    players = parse_match_players(match_row)

    if len(players) < 2:
        return {"processed": 0, "skipped": 0, "reason": "not_enough_players"}

    existing_event_ids = load_history_event_ids()
    created_at = now_text()
    fallback_active_season = get_active_season()

    scopes = [
        SCOPE_SEASON_OVERALL,
        SCOPE_SEASON_MODE,
        SCOPE_ALLTIME_OVERALL,
        SCOPE_ALLTIME_MODE,
    ]

    history_rows: list[list] = []
    elo_changes: dict[str, str] = {}
    processed = 0
    skipped = 0

    for scope in scopes:
        old_elos = {
            player["player_id"]: get_rating_value(
                player["player_id"],
                season,
                mode,
                scope,
                START_ELO,
            )
            for player in players
        }

        for player in players:
            event_id = f"{match_id}:{scope}:{player['player_id']}"

            if event_id in existing_event_ids:
                skipped += 1
                continue

            opponents = [other for other in players if other["player_id"] != player["player_id"]]

            if not opponents:
                continue

            opponent_elo = sum(old_elos[other["player_id"]] for other in opponents) / len(opponents)
            elo_before = old_elos[player["player_id"]]
            elo_after, elo_change = calculate_new_elo(elo_before, opponent_elo, player["score"])

            opponent_info = ", ".join(
                f"{opponent['name']} ({round(old_elos[opponent['player_id']], 1)})"
                for opponent in opponents
            )

            history_rows.append(
                [
                    event_id,
                    season,
                    slot_id,
                    date_text,
                    mode,
                    race_type,
                    player["player_id"],
                    player["name"],
                    opponent_info,
                    player["placement"],
                    player["score"],
                    scope,
                    format_elo(elo_before),
                    format_elo(opponent_elo),
                    format_elo(elo_after),
                    format_elo_change_for_sheet(elo_change),
                    player["result_type"],
                    created_at,
                ]
            )

            if scope == SCOPE_SEASON_OVERALL:
                elo_changes[player["player_id"]] = format_elo_change(elo_change)

            upsert_rating_row(
                player_id=player["player_id"],
                player_name=player["name"],
                season=season,
                mode=mode,
                scope=scope,
                elo=elo_after,
                result_type=player["result_type"],
            )

            processed += 1

    append_history_rows(history_rows)

    return {
        "processed": processed,
        "skipped": skipped,
        "match_id": match_id,
        "slot_id": slot_id,
        "elo_changes": elo_changes,
    }


def clear_elo_tables():
    ratings_sheet = get_ratings_sheet()
    history_sheet = get_history_sheet()

    if ratings_sheet.row_count > 1:
        sheet_write_call(
            lambda: ratings_sheet.batch_clear([f"A2:L{ratings_sheet.row_count}"]),
            invalidate_prefixes=[
                f"records:{RATINGS_SHEET_NAME}",
                f"values:{RATINGS_SHEET_NAME}",
                f"row:{RATINGS_SHEET_NAME}:",
            ],
        )

    if history_sheet.row_count > 1:
        sheet_write_call(
            lambda: history_sheet.batch_clear([f"A2:R{history_sheet.row_count}"]),
            invalidate_prefixes=[
                f"records:{RATING_HISTORY_SHEET_NAME}",
                f"values:{RATING_HISTORY_SHEET_NAME}",
                f"row:{RATING_HISTORY_SHEET_NAME}:",
            ],
        )


def rebuild_elo_from_matches(matches_rows: list[dict], schedule_rows: list[dict]) -> dict:
    """
    Baut ELO komplett neu auf.

    Wichtig:
    Diese Funktion arbeitet absichtlich speicherbasiert und schreibt am Ende gesammelt.
    Dadurch werden beim Rebuild nicht pro Match mehrfach Ratings/History aus Google Sheets gelesen.
    """
    ensure_ladder_elo_sheets()
    clear_elo_tables()

    schedule_by_slot = {
        normalize_text(row.get("Slot ID")): row
        for row in schedule_rows
        if normalize_text(row.get("Slot ID"))
    }

    ratings: dict[tuple[str, str, str, str], dict] = {}
    history_rows: list[list] = []
    created_at = now_text()

    scopes = [
        SCOPE_SEASON_OVERALL,
        SCOPE_SEASON_MODE,
        SCOPE_ALLTIME_OVERALL,
        SCOPE_ALLTIME_MODE,
    ]

    processed_matches = 0
    processed_events = 0
    skipped_matches = 0

    def get_rating_state(player_id: str, player_name: str, season: str, mode: str, scope: str) -> dict:
        selected_season, selected_mode = scope_key_parts(scope, season, mode)
        key = (normalize_text(player_id), selected_season, selected_mode, scope)

        if key not in ratings:
            ratings[key] = {
                "player_id": normalize_text(player_id),
                "player_name": normalize_text(player_name),
                "season": selected_season,
                "mode": selected_mode,
                "scope": scope,
                "elo": float(START_ELO),
                "wins": 0,
                "draws": 0,
                "lose": 0,
            }

        if normalize_text(player_name):
            ratings[key]["player_name"] = normalize_text(player_name)

        return ratings[key]

    for match_row in matches_rows:
        if normalize_text(match_row.get("Veröffentlicht")).lower() != "ja":
            continue

        if normalize_text(match_row.get("Status")).lower() != "finished":
            continue

        match_id = normalize_text(match_row.get("Match ID"))
        slot_id = normalize_text(match_row.get("Slot ID"))
        race_type = normalize_text(match_row.get("Matchtyp"))
        schedule_row = schedule_by_slot.get(slot_id, {})

        season = (
            normalize_text(match_row.get("Season"))
            or normalize_text(schedule_row.get("Season"))
            or fallback_active_season
        )
        mode = (
            normalize_text(schedule_row.get("Modus"))
            or normalize_text(match_row.get("Modus"))
            or "Unknown"
        )
        date_text = normalize_text(schedule_row.get("Datum"))

        players = parse_match_players(match_row)

        if len(players) < 2:
            skipped_matches += 1
            continue

        match_had_events = False

        for scope in scopes:
            old_elos = {}

            for player in players:
                state = get_rating_state(
                    player_id=player["player_id"],
                    player_name=player["name"],
                    season=season,
                    mode=mode,
                    scope=scope,
                )
                old_elos[player["player_id"]] = float(state["elo"])

            for player in players:
                opponents = [
                    other
                    for other in players
                    if other["player_id"] != player["player_id"]
                ]

                if not opponents:
                    continue

                state = get_rating_state(
                    player_id=player["player_id"],
                    player_name=player["name"],
                    season=season,
                    mode=mode,
                    scope=scope,
                )

                opponent_elo = (
                    sum(old_elos[other["player_id"]] for other in opponents)
                    / len(opponents)
                )
                elo_before = old_elos[player["player_id"]]
                elo_after, elo_change = calculate_new_elo(
                    elo_before,
                    opponent_elo,
                    player["score"],
                )

                result_type = player["result_type"]

                if result_type == "Sieg":
                    state["wins"] += 1
                elif result_type == "Remis":
                    state["draws"] += 1
                else:
                    state["lose"] += 1

                state["elo"] = elo_after

                opponent_info = ", ".join(
                    f"{opponent['name']} ({round(old_elos[opponent['player_id']], 1)})"
                    for opponent in opponents
                )

                history_rows.append(
                    [
                        f"{match_id}:{scope}:{player['player_id']}",
                        season,
                        slot_id,
                        date_text,
                        mode,
                        race_type,
                        player["player_id"],
                        player["name"],
                        opponent_info,
                        player["placement"],
                        player["score"],
                        scope,
                        format_elo(elo_before),
                        format_elo(opponent_elo),
                        format_elo(elo_after),
                        format_elo_change_for_sheet(elo_change),
                        result_type,
                        created_at,
                    ]
                )

                processed_events += 1
                match_had_events = True

        if match_had_events:
            processed_matches += 1
        else:
            skipped_matches += 1

    rating_rows: list[list] = []

    for key in sorted(ratings.keys(), key=lambda item: (item[3], item[1], item[2], item[0])):
        state = ratings[key]
        games = int(state["wins"]) + int(state["draws"]) + int(state["lose"])
        winrate = calculate_winrate(
            int(state["wins"]),
            int(state["draws"]),
            int(state["lose"]),
        )

        rating_rows.append(
            [
                state["player_id"],
                state["player_name"],
                state["season"],
                state["mode"],
                state["scope"],
                format_elo(state["elo"]),
                state["wins"],
                state["draws"],
                state["lose"],
                games,
                f"{winrate:.1f}",
                created_at,
            ]
        )

    ratings_sheet = get_ratings_sheet()
    history_sheet = get_history_sheet()

    if rating_rows:
        sheet_write_call(
            lambda: ratings_sheet.append_rows(rating_rows, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{RATINGS_SHEET_NAME}",
                f"values:{RATINGS_SHEET_NAME}",
            ],
        )

    if history_rows:
        # In sinnvollen Blöcken schreiben, damit Google Sheets nicht an Payload-Größen scheitert.
        chunk_size = 500

        for index in range(0, len(history_rows), chunk_size):
            chunk = history_rows[index:index + chunk_size]
            sheet_write_call(
                lambda chunk=chunk: history_sheet.append_rows(
                    chunk,
                    value_input_option="USER_ENTERED",
                ),
                invalidate_prefixes=[
                    f"records:{RATING_HISTORY_SHEET_NAME}",
                    f"values:{RATING_HISTORY_SHEET_NAME}",
                ],
            )

    return {
        "processed_matches": processed_matches,
        "processed_events": processed_events,
        "skipped_matches": skipped_matches,
        "rating_rows": len(rating_rows),
        "history_rows": len(history_rows),
    }


def build_standings_rows(scope: str, season: str, mode: str = "", limit: int | None = None) -> list[dict]:
    ensure_ladder_elo_sheets()

    selected_season, selected_mode = scope_key_parts(scope, season, mode)
    rows = []

    for _, row in load_ratings_rows_with_index():
        if normalize_text(row.get("Scope")) != scope:
            continue

        if normalize_text(row.get("Season")) != selected_season:
            continue

        if normalize_text(row.get("Mode")) != selected_mode:
            continue

        rows.append(row)

    sorted_rows = sort_standings_rows(rows)

    if limit:
        return sorted_rows[:limit]

    return sorted_rows

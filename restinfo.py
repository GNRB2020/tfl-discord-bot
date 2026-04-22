import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

DIV_COL_LEFT = 4
DIV_COL_MARKER = 5
DIV_COL_RIGHT = 6

CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

GC = None
WB = None
SHEETS_ENABLED = True

try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    GC = gspread.authorize(CREDS)
    WB = GC.open(SPREADSHEET_TITLE)
except Exception:
    SHEETS_ENABLED = False
    WB = None


def sheets_required():
    if not SHEETS_ENABLED or WB is None:
        raise RuntimeError("Google Sheets nicht verbunden (SHEETS_ENABLED=False).")


def _cell(row, idx0):
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


def normalize_name(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


# =========================================================
# RESTPROGRAMM
# =========================================================
def list_rest_players(div_number: str) -> list[str]:
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    players = []
    seen = set()

    max_row_index = min(9, len(rows))
    for idx in range(1, max_row_index):
        row = rows[idx]
        name = _cell(row, 11)  # L
        if not name:
            continue

        low = normalize_name(name)
        if low not in seen:
            seen.add(low)
            players.append(name)

    return players


def list_restprogramm(div_number: str, player_name: str):
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    matches = []
    target = normalize_name(player_name)

    for idx, row in enumerate(rows[1:], start=2):
        heim = _cell(row, DIV_COL_LEFT - 1)
        marker = _cell(row, DIV_COL_MARKER - 1)
        gast = _cell(row, DIV_COL_RIGHT - 1)

        if marker.lower() != "vs":
            continue

        if normalize_name(heim) == target or normalize_name(gast) == target:
            matches.append(
                {
                    "row_index": idx,
                    "heim": heim,
                    "gast": gast,
                }
            )

    return matches


def format_restprogramm_text(div_number: str, player: str) -> str:
    matches = list_restprogramm(div_number, player)

    if not matches:
        return (
            f"Division {div_number} – Restprogramm für **{player}**:\n"
            "Es sind keine offenen Spiele mehr in der Tabelle (E != 'vs')."
        )

    lines = [
        f"Division {div_number} – Restprogramm für **{player}**:",
        "",
    ]

    for m in matches:
        heim = m["heim"]
        gast = m["gast"]

        if normalize_name(heim) == normalize_name(player):
            info = f"**{heim} (H)** vs {gast}"
        elif normalize_name(gast) == normalize_name(player):
            info = f"{heim} vs **{gast} (A)**"
        else:
            info = f"{heim} vs {gast}"

        lines.append(f"- {info}")

    return "\n".join(lines)


def find_divisions_with_open_matches(player_name: str) -> list[str]:
    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            matches = list_restprogramm(div_number, player_name)
        except Exception:
            continue

        if matches:
            found.append(div_number)

    return found


def find_divisions_with_player(player_name: str) -> list[str]:
    target = normalize_name(player_name)
    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            players = list_rest_players(div_number)
        except Exception:
            continue

        for player in players:
            if normalize_name(player) == target:
                found.append(div_number)
                break

    return found


def get_open_restprogramm_text_for_name_candidates(name_candidates: list[str]) -> str:
    clean_candidates = []
    seen = set()

    for name in name_candidates:
        if not name:
            continue
        norm = normalize_name(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        clean_candidates.append(name.strip())

    for candidate in clean_candidates:
        open_divisions = find_divisions_with_open_matches(candidate)

        if len(open_divisions) == 1:
            return format_restprogramm_text(open_divisions[0], candidate)

        if len(open_divisions) > 1:
            lines = [
                f"Für **{candidate}** wurden offene Spiele in mehreren Divisionen gefunden:",
                "",
            ]
            for div in open_divisions:
                lines.append(f"- Division {div}")
            lines.append("")
            lines.append("Nutze bitte **Andere** und wähle die Division manuell.")
            return "\n".join(lines)

    for candidate in clean_candidates:
        player_divisions = find_divisions_with_player(candidate)

        if len(player_divisions) == 1:
            return (
                f"Division {player_divisions[0]} – Restprogramm für **{candidate}**:\n"
                "Es sind keine offenen Spiele mehr in der Tabelle (E != 'vs')."
            )

        if len(player_divisions) > 1:
            lines = [
                f"Für **{candidate}** wurden Einträge in mehreren Divisionen gefunden, aber aktuell keine offenen Spiele:",
                "",
            ]
            for div in player_divisions:
                lines.append(f"- Division {div}")
            lines.append("")
            lines.append("Nutze bitte **Andere** und wähle die Division manuell.")
            return "\n".join(lines)

    if clean_candidates:
        tried = ", ".join(f"`{name}`" for name in clean_candidates)
        return (
            "Für dich wurde kein passendes Restprogramm gefunden.\n"
            f"Verwendete Namensvarianten: {tried}\n\n"
            "Nutze bitte **Andere** und wähle Division + Spieler manuell."
        )

    return (
        "Für dich wurde kein passendes Restprogramm gefunden.\n"
        "Nutze bitte **Andere** und wähle Division + Spieler manuell."
    )


# =========================================================
# STREICHMODUS
# =========================================================
def list_streichungen(div_number: str):
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    entries = []
    max_row_index = min(9, len(rows))  # Zeile 2-9 -> Index 1-8

    for idx in range(1, max_row_index):
        row = rows[idx]
        spieler = _cell(row, 11)  # L
        modus_m = _cell(row, 12)  # M
        modus_n = _cell(row, 13)  # N

        if spieler:
            entries.append(
                {
                    "spieler": spieler,
                    "modus_m": modus_m,
                    "modus_n": modus_n,
                }
            )

    return entries


def get_streich_text_for_division(div_number: str) -> str:
    entries = list_streichungen(div_number)

    if not entries:
        return f"Keine Streichmodi in Division {div_number} hinterlegt."

    lines = [f"Streichmodi in Division {div_number}:", ""]

    for entry in entries:
        spieler = entry["spieler"]
        parts = []

        if entry["modus_m"]:
            parts.append(entry["modus_m"])
        if entry["modus_n"]:
            parts.append(entry["modus_n"])

        if parts:
            lines.append(f"- **{spieler}**: " + " | ".join(parts))
        else:
            lines.append(f"- **{spieler}**")

    return "\n".join(lines)


def find_own_division_for_name_candidates(name_candidates: list[str]) -> str | None:
    clean_candidates = []
    seen = set()

    for name in name_candidates:
        if not name:
            continue
        norm = normalize_name(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        clean_candidates.append(name.strip())

    for candidate in clean_candidates:
        divisions = find_divisions_with_player(candidate)
        if len(divisions) == 1:
            return divisions[0]

    return None


def get_own_division_streich_text(name_candidates: list[str]) -> str:
    div_number = find_own_division_for_name_candidates(name_candidates)

    if not div_number:
        tried = [x for x in name_candidates if x]
        if tried:
            return (
                "Für dich konnte keine eindeutige Division gefunden werden.\n"
                f"Verwendete Namensvarianten: {', '.join(f'`{x}`' for x in tried)}\n\n"
                "Nutze bitte **Andere Divisionen**."
            )

        return (
            "Für dich konnte keine eindeutige Division gefunden werden.\n"
            "Nutze bitte **Andere Divisionen**."
        )

    return get_streich_text_for_division(div_number)

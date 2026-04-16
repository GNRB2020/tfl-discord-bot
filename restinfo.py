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
        low = name.lower()
        if low not in seen:
            seen.add(low)
            players.append(name)

    return players


def list_restprogramm(div_number: str, player_name: str):
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    matches = []
    target = player_name.strip().lower()

    for idx, row in enumerate(rows[1:], start=2):
        heim = _cell(row, DIV_COL_LEFT - 1)
        marker = _cell(row, DIV_COL_MARKER - 1)
        gast = _cell(row, DIV_COL_RIGHT - 1)

        if marker.lower() != "vs":
            continue

        if heim.lower() == target or gast.lower() == target:
            matches.append(
                {
                    "row_index": idx,
                    "heim": heim,
                    "gast": gast,
                },
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

        if heim.lower() == player.lower():
            info = f"**{heim} (H)** vs {gast}"
        elif gast.lower() == player.lower():
            info = f"{heim} vs **{gast} (A)**"
        else:
            info = f"{heim} vs {gast}"

        lines.append(f"- {info}")

    return "\n".join(lines)


def find_divisions_with_open_matches(player_name: str) -> list[str]:
    target = player_name.strip().lower()
    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            matches = list_restprogramm(div_number, target)
        except Exception:
            continue

        if matches:
            found.append(div_number)

    return found


def find_divisions_with_player(player_name: str) -> list[str]:
    target = player_name.strip().lower()
    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            players = list_rest_players(div_number)
        except Exception:
            continue

        for player in players:
            if player.strip().lower() == target:
                found.append(div_number)
                break

    return found


def get_open_restprogramm_text_for_player(player_name: str) -> str:
    open_divisions = find_divisions_with_open_matches(player_name)

    if len(open_divisions) == 1:
        return format_restprogramm_text(open_divisions[0], player_name)

    if len(open_divisions) > 1:
        lines = [
            f"Für **{player_name}** wurden offene Spiele in mehreren Divisionen gefunden:",
            "",
        ]
        for div in open_divisions:
            lines.append(f"- Division {div}")
        lines.append("")
        lines.append("Nutze bitte **Andere** und wähle die Division manuell.")
        return "\n".join(lines)

    player_divisions = find_divisions_with_player(player_name)

    if len(player_divisions) == 1:
        return (
            f"Division {player_divisions[0]} – Restprogramm für **{player_name}**:\n"
            "Es sind keine offenen Spiele mehr in der Tabelle (E != 'vs')."
        )

    if len(player_divisions) > 1:
        lines = [
            f"Für **{player_name}** wurden Einträge in mehreren Divisionen gefunden, aber aktuell keine offenen Spiele:",
            "",
        ]
        for div in player_divisions:
            lines.append(f"- Division {div}")
        lines.append("")
        lines.append("Nutze bitte **Andere** und wähle die Division manuell.")
        return "\n".join(lines)

    return (
        f"Für **{player_name}** wurde kein passendes Restprogramm gefunden.\n"
        "Nutze bitte **Andere** und wähle Division + Spieler manuell."
    )

import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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


def list_streichungen(div_number: str):
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    eintraege = []
    max_row_index = min(9, len(rows))

    for idx in range(1, max_row_index):
        row = rows[idx]
        spieler = _cell(row, 11)  # L
        modus_m = _cell(row, 12)  # M
        modus_n = _cell(row, 13)  # N

        if spieler:
            eintraege.append(
                {
                    "spieler": spieler,
                    "modus_m": modus_m,
                    "modus_n": modus_n,
                }
            )

    return eintraege


def list_div_players(div_number: str) -> list[str]:
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    seen = set()
    players = []

    for row in rows[1:]:
        left = _cell(row, 3)   # D
        right = _cell(row, 5)  # F

        for p in (left, right):
            if not p:
                continue
            norm = normalize_name(p)
            if norm not in seen:
                seen.add(norm)
                players.append(p)

    return players


def format_streichungen_text(div_number: str) -> str:
    eintraege = list_streichungen(div_number)

    if not eintraege:
        return f"Keine Streichungen in Division {div_number} hinterlegt (L2-L9 leer)."

    lines = [f"📝 Streichungen in Division {div_number}:", ""]

    for e in eintraege:
        spieler = e["spieler"]
        parts = []

        if e["modus_m"]:
            parts.append(e["modus_m"])
        if e["modus_n"]:
            parts.append(e["modus_n"])

        if parts:
            lines.append(f"- **{spieler}**: " + " | ".join(parts))
        else:
            lines.append(f"- **{spieler}**")

    return "\n".join(lines)


def find_player_divisions(name_candidates: list[str]) -> list[str]:
    clean_candidates = []
    seen = set()

    for name in name_candidates:
        if not name:
            continue
        norm = normalize_name(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        clean_candidates.append(norm)

    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            players = list_div_players(div_number)
        except Exception:
            continue

        player_norms = {normalize_name(p) for p in players}
        if any(candidate in player_norms for candidate in clean_candidates):
            found.append(div_number)

    return found


def get_own_division_streich_text(name_candidates: list[str]) -> str:
    divisions = find_player_divisions(name_candidates)

    if len(divisions) == 1:
        return format_streichungen_text(divisions[0])

    if len(divisions) > 1:
        lines = [
            "Du wurdest in mehreren Divisionen gefunden:",
            "",
        ]
        for div in divisions:
            lines.append(f"- Division {div}")
        lines.append("")
        lines.append("Nutze bitte **Andere Divisionen** und wähle die Division manuell.")
        return "\n".join(lines)

    tried = [n for n in name_candidates if n]
    tried_txt = ", ".join(f"`{n}`" for n in tried) if tried else "-"
    return (
        "Für dich konnte keine Division ermittelt werden.\n"
        f"Verwendete Namensvarianten: {tried_txt}\n\n"
        "Nutze bitte **Andere Divisionen** und wähle die Division manuell."
    )

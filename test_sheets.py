import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Berechtigungen für Zugriff auf Google Sheets und Drive
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# JSON-Datei mit deinem Service-Account (muss im selben Ordner wie dieses Skript liegen)
creds = ServiceAccountCredentials.from_json_keyfile_name("tfl-schedulebot.json", scope)

# Verbindung zum Google Sheet herstellen
client = gspread.authorize(creds)

# Sheet-Name & Tabellennamen exakt wie im Google Sheet
SHEET_NAME = "Season #3 - Spielbetrieb"
TAB_NAME = "League & Cup Schedule"

try:
    # Öffne das Google Sheet
    sheet = client.open(SHEET_NAME)
    print("✅ Dokument geöffnet:", sheet.title)

    # Liste der vorhandenen Blätter anzeigen
    print("📄 Tabellenblätter:")
    for wks in sheet.worksheets():
        print("  ▶", wks.title)

    # Zugriff auf das benannte Tabellenblatt
    worksheet = sheet.worksheet(TAB_NAME)
    print("📘 Benutztes Blatt:", worksheet.title)

    # Test: Erste Zeile auslesen
    first_row = worksheet.row_values(1)
    print("📋 Erste Zeile:", first_row)

except Exception as e:
    print("❌ Fehler beim Zugriff:", e)

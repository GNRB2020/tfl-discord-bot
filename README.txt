TFL Portal 1.5 – Bot + API (GitHub Weboberfläche)

1. Im Repository GNRB2020/tfl-discord-bot auf main die api.py durch diese api.py ersetzen. Committen.
2. Im selben Hauptverzeichnis die division_tables.py durch diese division_tables.py ersetzen. Committen.
3. Render-Dienste tfl-discord-api und tfl-discord-bot neu deployen.
4. Bestehende Umgebungsvariablen TFL_WEB_TOKEN (beide Dienste) sowie TFL_API_URL (Bot) bleiben unverändert.
5. Nach dem Tabellenlauf testen: https://tfl-discord-api.onrender.com/api/web/competitions?competition=cup
   und https://tfl-discord-api.onrender.com/api/web/competitions?competition=coop-a
6. Joomla 1.5 ist eine unabhängige Installation; Cup/Coop sind erst nach diesem Update live.

Hinweis: Beide Dateien direkt auf main, KEINE Dateien aus Unterverzeichnissen hochladen.
Keine neuen Credentials oder Datenbankmigrationen erforderlich.
Python kompiliert; Produktiv-API nicht lokal ausgeführt. Die Cup-Daten kommen aus dem bestehenden Cup-Spielplan per schedule.py. Coop-Gruppen aus bereits gelesenen Sheets.

Vor dem Einspielen GitHub-Commits notieren; bei Render-Problemen kann auf alten Commit zurückgestellt werden.

from pathlib import Path
import re
import shutil
import py_compile
import sys

BOT_FILE = Path("bot.py")
BACKUP_FILE = Path("bot.py.backup_before_disable_commands")

DISABLED_MANUAL_COMMANDS = [
    "matchcenter",
    "showpicks",
    "result",
    "asyncplay",
    "cupresult",
    "cuptermin",
    "pick",
    "quali",
    "rest",
    "signup",
    "streich",
    "termin",
]

NEW_BLOCK = '''class TFLBot(commands.Bot):
    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        extensions = [
            "signup",
            "schedule",
            "ladder",
            "matchcenter",
            "asnyc",
            "player",
            "restream_requests",
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ {ext}.py geladen")
            except Exception:
                print(f"❌ FEHLER beim Laden von {ext}.py:")
                traceback.print_exc()

        # =========================================================
        # Manuelle Slash-Commands deaktivieren
        #
        # WICHTIG:
        # Die Extensions bleiben geladen.
        # Dadurch funktionieren Buttons/Views aus /player weiter.
        # Entfernt wird nur die manuelle Ausführbarkeit als Slash-Command.
        # =========================================================
        disabled_manual_commands = {
            "matchcenter",
            "showpicks",
            "result",
            "asyncplay",
            "cupresult",
            "cuptermin",
            "pick",
            "quali",
            "rest",
            "signup",
            "streich",
            "termin",
        }

        print(
            "TREE GLOBAL VOR COPY:",
            [cmd.name for cmd in self.tree.get_commands()],
        )

        print(
            "TREE GUILD VOR COPY:",
            [cmd.name for cmd in self.tree.get_commands(guild=guild)],
        )

        # Globale Commands in die Guild kopieren
        self.tree.copy_global_to(guild=guild)

        print(
            "TREE GUILD NACH COPY:",
            [cmd.name for cmd in self.tree.get_commands(guild=guild)],
        )

        # Danach gezielt aus Global- und Guild-Tree entfernen
        for cmd_name in disabled_manual_commands:
            removed_global = self.tree.remove_command(cmd_name)
            removed_guild = self.tree.remove_command(cmd_name, guild=guild)

            if removed_global or removed_guild:
                print(f"🧹 Slash-Command deaktiviert: /{cmd_name}")

        print(
            "TREE GLOBAL VOR SYNC:",
            [cmd.name for cmd in self.tree.get_commands()],
        )

        print(
            "TREE GUILD VOR SYNC:",
            [cmd.name for cmd in self.tree.get_commands(guild=guild)],
        )

        synced = await self.tree.sync(guild=guild)

        print("✅ Slash Commands synchronisiert:")
        for cmd in synced:
            print(f" - /{cmd.name}")
'''

def main():
    if not BOT_FILE.exists():
        print("❌ bot.py nicht gefunden. Script muss im Repo-Hauptordner liegen.")
        sys.exit(1)

    original = BOT_FILE.read_text(encoding="utf-8")

    pattern = re.compile(
        r"class TFLBot\\(commands\\.Bot\\):\\n"
        r"(?:.|\\n)*?"
        r"(?=\\nclient = TFLBot\\()",
        re.MULTILINE,
    )

    match = pattern.search(original)

    if not match:
        print("❌ Konnte den TFLBot/setup_hook-Block nicht eindeutig finden.")
        print("Keine Änderung vorgenommen.")
        sys.exit(1)

    if not BACKUP_FILE.exists():
        shutil.copyfile(BOT_FILE, BACKUP_FILE)
        print(f"✅ Backup erstellt: {BACKUP_FILE}")
    else:
        print(f"ℹ️ Backup existiert bereits: {BACKUP_FILE}")

    updated = pattern.sub(NEW_BLOCK, original, count=1)

    BOT_FILE.write_text(updated, encoding="utf-8")
    print("✅ bot.py wurde aktualisiert.")

    try:
        py_compile.compile(str(BOT_FILE), doraise=True)
        print("✅ Syntaxprüfung erfolgreich.")
    except py_compile.PyCompileError as e:
        print("❌ Syntaxfehler nach Änderung.")
        print("Backup wird wiederhergestellt.")
        shutil.copyfile(BACKUP_FILE, BOT_FILE)
        print("✅ Backup wiederhergestellt.")
        print(e)
        sys.exit(1)

    print("")
    print("Fertig. Diese Commands werden nicht mehr manuell registriert:")
    for cmd in DISABLED_MANUAL_COMMANDS:
        print(f" - /{cmd}")

    print("")
    print("Die Extensions bleiben geladen. /player-Buttons behalten dadurch ihre Funktionen.")


if __name__ == "__main__":
    main()

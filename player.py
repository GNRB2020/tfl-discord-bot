            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            name_candidates = get_name_candidates(member)

            state = await asyncio.to_thread(
                load_streichmodus_state_for_name_candidates,
                name_candidates,
            )

            if not state["found"]:
                raise RuntimeError("Du wurdest in keiner Division in Spalte L gefunden.")

            div_number = state["div_number"]

            modes = await asyncio.to_thread(
                get_division_modes_for_streichmodus,
                div_number,
            )

            if not modes:
                raise RuntimeError(
                    f"Für Division {div_number} wurden keine erlaubten Streichmodi im Sheet gefunden."
                )

            view = StreichmodusSettingView(
                owner_id=interaction.user.id,
                modes=modes,
                mode_1=state["mode_1"],
                mode_2=state["mode_2"],
                div_number=div_number,
                change_used=state["change_used"],
            )

            await interaction.edit_original_response(
                embed=view.build_embed(),
                view=view,
                content=None,
            )

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    f"Fehler beim Laden: {e}",
                ),
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
                ),
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_player_dashboard(interaction)


# =========================================================
# COG
# =========================================================

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="player", description="Öffnet das Spielermenü")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def player(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await show_player_dashboard(
                interaction,
                already_deferred=True,
            )
        except Exception as exc:
            print(f"❌ [PLAYER] /player konnte nicht aufgebaut werden: {exc}")
            traceback.print_exc()
            try:
                await interaction.edit_original_response(
                    content=(
                        "❌ Das Spieler-Dashboard konnte gerade nicht aufgebaut werden. "
                        "Bitte versuche /player erneut."
                    ),
                    embed=None,
                    view=None,
                    attachments=[],
                )
            except Exception:
                try:
                    await interaction.followup.send(
                        "❌ Das Spieler-Dashboard konnte gerade nicht aufgebaut werden. Bitte versuche /player erneut.",
                        ephemeral=True,
                    )
                except Exception:
                    pass


async def setup(bot: commands.Bot):
    # /player ist die Kernfunktion. Zusatzfunktionen wie Achievements dürfen
    # das Laden des Cogs niemals verhindern.
    try:
        _install_achievement_hooks()
    except Exception as exc:
        print(f"⚠️ [PLAYER] Achievement-Hooks konnten nicht installiert werden: {exc}")
        traceback.print_exc()

    await bot.add_cog(PlayerCog(bot))

    # Persistente Buttons offener Anfragen nach Neustart wieder registrieren.
    await restore_exit_request_views(bot)

    # Offene Terminangebote ebenfalls persistent registrieren. Alte Posts aus
    # Versionen ohne Persistenz werden nach on_ready automatisch migriert.
    try:
        await term_offers.restore_persistent_offer_views(bot)
    except Exception as exc:
        print(f"⚠️ [PLAYER] Terminangebote konnten nicht wiederhergestellt werden: {exc}")

    # Fristen liegen im Google Sheet und überstehen dadurch Bot-Neustarts.
    if not hasattr(bot, "_exit_request_monitor_task"):
        bot._exit_request_monitor_task = asyncio.create_task(
            exit_request_monitor_loop(bot)
        )

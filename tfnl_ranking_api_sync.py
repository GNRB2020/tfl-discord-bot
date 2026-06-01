"""
tfnl_ranking_api_sync.py

Sendet TFNL-ELO-Rankings aus Google Sheets an die Website-API.

Erwartete Datenquelle:
- Ladder_Ratings aus ladder_elo_sheets.py

Erwartete API-Ziele:
- POST /api/update/tfnl-season-ranking
- POST /api/update/tfnl-overall-ranking
"""

from __future__ import annotations

import os
from typing import Any

import aiohttp

from ladder_elo import (
    SCOPE_SEASON_OVERALL,
    SCOPE_SEASON_MODE,
    SCOPE_ALLTIME_OVERALL,
    SCOPE_ALLTIME_MODE,
)

from ladder_elo_sheets import (
    load_ratings_rows_with_index,
    normalize_text,
    int_value,
    float_value,
)


DEFAULT_API_BASE = "https://tfl-discord-api.onrender.com"

SEASON_SCOPES = {
    SCOPE_SEASON_OVERALL,
    SCOPE_SEASON_MODE,
}

OVERALL_SCOPES = {
    SCOPE_ALLTIME_OVERALL,
    SCOPE_ALLTIME_MODE,
}


def _get_api_base(api_base: str | None = None) -> str:
    selected = (
        api_base
        or os.getenv("TFL_API_BASE")
        or os.getenv("API_BASE")
        or DEFAULT_API_BASE
    )

    return selected.rstrip("/")


def _rating_row_to_api_item(row: dict[str, Any]) -> dict[str, Any] | None:
    player_id = normalize_text(row.get("Player ID"))
    player_name = normalize_text(row.get("Player Name"))
    season = normalize_text(row.get("Season"))
    mode = normalize_text(row.get("Mode")) or "ALL"
    scope = normalize_text(row.get("Scope"))

    if not player_id and not player_name:
        return None

    if not scope:
        return None

    elo = float_value(row.get("Elo"), 1000.0)
    wins = int_value(row.get("Wins"))
    draws = int_value(row.get("Draws"))
    lose = int_value(row.get("Lose"))
    games = int_value(row.get("Games"))

    if games <= 0:
        games = wins + draws + lose

    winrate = float_value(row.get("Winrate"), 0.0)

    return {
        "player_id": player_id,
        "player_name": player_name or player_id or "Unbekannt",
        "season": season,
        "mode": mode,
        "scope": scope,
        "elo": elo,
        "wins": wins,
        "draws": draws,
        "lose": lose,
        "games": games,
        "winrate": winrate,
        "updated_at": normalize_text(row.get("Updated At")),
    }


def build_tfnl_ranking_payloads() -> dict[str, list[dict[str, Any]]]:
    """
    Baut beide Website-Payloads direkt aus Ladder_Ratings.

    Rückgabe:
    {
      "season": [...],
      "overall": [...]
    }
    """
    rows_with_index = load_ratings_rows_with_index()

    season_items: list[dict[str, Any]] = []
    overall_items: list[dict[str, Any]] = []

    for _row_index, row in rows_with_index:
        item = _rating_row_to_api_item(row)

        if item is None:
            continue

        scope = item["scope"]

        if scope in SEASON_SCOPES:
            season_items.append(item)
        elif scope in OVERALL_SCOPES:
            overall_items.append(item)

    season_items.sort(
        key=lambda item: (
            str(item.get("season", "")),
            str(item.get("scope", "")),
            str(item.get("mode", "")),
            -float(item.get("elo", 0)),
            str(item.get("player_name", "")).lower(),
        )
    )

    overall_items.sort(
        key=lambda item: (
            str(item.get("scope", "")),
            str(item.get("mode", "")),
            -float(item.get("elo", 0)),
            str(item.get("player_name", "")).lower(),
        )
    )

    return {
        "season": season_items,
        "overall": overall_items,
    }


async def _post_items(
    session: aiohttp.ClientSession,
    url: str,
    items: list[dict[str, Any]],
    timeout_seconds: int,
) -> tuple[int, str]:
    async with session.post(
        url,
        json={"items": items},
        timeout=timeout_seconds,
    ) as response:
        text = await response.text()
        return response.status, text[:500]


async def publish_tfnl_rankings_to_api(
    api_base: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """
    Veröffentlicht Season- und Overall-Ranking an die API.

    Diese Funktion ist für den Bot gedacht und kann z. B. im bestehenden
    push_updates_to_api() nach upcoming/results aufgerufen werden.
    """
    base = _get_api_base(api_base)
    payloads = build_tfnl_ranking_payloads()

    result: dict[str, Any] = {
        "api_base": base,
        "season_count": len(payloads["season"]),
        "overall_count": len(payloads["overall"]),
        "season_status": None,
        "overall_status": None,
        "ok": False,
    }

    async with aiohttp.ClientSession() as session:
        season_status, season_text = await _post_items(
            session=session,
            url=f"{base}/api/update/tfnl-season-ranking",
            items=payloads["season"],
            timeout_seconds=timeout_seconds,
        )

        overall_status, overall_text = await _post_items(
            session=session,
            url=f"{base}/api/update/tfnl-overall-ranking",
            items=payloads["overall"],
            timeout_seconds=timeout_seconds,
        )

    result["season_status"] = season_status
    result["overall_status"] = overall_status
    result["season_response"] = season_text
    result["overall_response"] = overall_text
    result["ok"] = 200 <= season_status < 300 and 200 <= overall_status < 300

    return result

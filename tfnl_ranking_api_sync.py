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
    load_history_rows,
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


def _history_row_to_result_player(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": normalize_text(row.get("Player ID")),
        "player_name": normalize_text(row.get("Player Name")) or "Unbekannt",
        "placement": int_value(row.get("Placement")),
        "score": float_value(row.get("Score"), 0.0),
        "result_type": normalize_text(row.get("Result Type")),
        "elo_before": float_value(row.get("Elo Before"), 1000.0),
        "elo_after": float_value(row.get("Elo After"), 1000.0),
        "elo_change": float_value(row.get("Elo Change"), 0.0),
    }


def build_tfnl_results_payload() -> list[dict[str, Any]]:
    """
    Baut veröffentlichte TFNL-Ergebnisse aus Ladder_RatingHistory.

    Wichtig:
    - Es wird nur season_overall genutzt, damit jedes Match nicht vierfach
      durch die unterschiedlichen ELO-Scopes auftaucht.
    - Gruppierung erfolgt primär über Rating Event ID.
    """
    history_rows = load_history_rows()
    grouped: dict[str, dict[str, Any]] = {}

    for row in history_rows:
        scope = normalize_text(row.get("Elo Scope"))
        if scope != SCOPE_SEASON_OVERALL:
            continue

        event_id = normalize_text(row.get("Rating Event ID"))
        if not event_id:
            continue

        item = grouped.setdefault(event_id, {
            "id": event_id,
            "rating_event_id": event_id,
            "season": normalize_text(row.get("Season")),
            "slot_id": normalize_text(row.get("Slot ID")),
            "date": normalize_text(row.get("Date")),
            "mode": normalize_text(row.get("Mode")),
            "race_type": normalize_text(row.get("Race Type")),
            "created_at": normalize_text(row.get("Created At")),
            "players": [],
        })

        player = _history_row_to_result_player(row)

        if player["player_id"] or player["player_name"]:
            item["players"].append(player)

    results: list[dict[str, Any]] = []

    for item in grouped.values():
        players = item["players"]
        players.sort(key=lambda player: (
            int(player.get("placement") or 999),
            str(player.get("player_name", "")).lower(),
        ))

        winner = next(
            (player for player in players if int(player.get("placement") or 999) == 1),
            players[0] if players else None,
        )

        item["winner_name"] = winner.get("player_name") if winner else ""
        item["player_count"] = len(players)
        item["result_text"] = " · ".join(
            f"{player.get('placement')}. {player.get('player_name')}"
            for player in players
            if player.get("player_name")
        )

        results.append(item)

    results.sort(
        key=lambda item: (
            str(item.get("date", "")),
            str(item.get("created_at", "")),
            str(item.get("id", "")),
        ),
        reverse=True,
    )

    return results


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
    tfnl_results = build_tfnl_results_payload()

    result: dict[str, Any] = {
        "api_base": base,
        "season_count": len(payloads["season"]),
        "overall_count": len(payloads["overall"]),
        "results_count": len(tfnl_results),
        "season_status": None,
        "overall_status": None,
        "results_status": None,
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

        results_status, results_text = await _post_items(
            session=session,
            url=f"{base}/api/update/tfnl-results",
            items=tfnl_results,
            timeout_seconds=timeout_seconds,
        )

    result["season_status"] = season_status
    result["overall_status"] = overall_status
    result["results_status"] = results_status
    result["season_response"] = season_text
    result["overall_response"] = overall_text
    result["results_response"] = results_text
    result["ok"] = (
        200 <= season_status < 300
        and 200 <= overall_status < 300
        and 200 <= results_status < 300
    )

    return result

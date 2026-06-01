"""
tfnl_ranking_api_sync.py

Sendet TFNL-Frontenddaten an die Website-API:
- Season Ranking
- Overall Ranking
- TFNL Results

Datenquellen:
- Ladder_Ratings
- Ladder_RatingHistory
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


def _match_id_from_rating_event_id(event_id: str) -> str:
    """
    Rating Event IDs haben das Format:
    <Match ID>:<Scope>:<Player ID>

    Für Ergebnislisten und echte Match-Zählung darf NICHT die komplette
    Rating Event ID genutzt werden, sonst wird ein 1on1 als mehrere Events
    gezählt.
    """
    value = normalize_text(event_id)

    if ":" in value:
        return value.split(":", 1)[0].strip()

    return value


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


def build_match_count_stats() -> dict[str, Any]:
    """
    Zählt echte Matches aus Ladder_RatingHistory.

    Grundlage ist Elo Scope season_overall bzw. alltime_overall.
    Pro Match wird aus Rating Event ID nur die Match ID vor dem ersten ":"
    gezählt. Dadurch wird ein 1on1 nicht als 2 Spiele und nicht durch
    mehrere ELO-Scopes mehrfach gezählt.
    """
    stats: dict[str, Any] = {
        "season_total": {},
        "season_mode": {},
        "alltime_total": 0,
        "alltime_mode": {},
    }

    season_match_ids: dict[str, set[str]] = {}
    season_mode_match_ids: dict[tuple[str, str], set[str]] = {}
    alltime_match_ids: set[str] = set()
    alltime_mode_match_ids: dict[str, set[str]] = {}

    for row in load_history_rows():
        scope = normalize_text(row.get("Elo Scope"))
        event_id = normalize_text(row.get("Rating Event ID"))
        match_id = _match_id_from_rating_event_id(event_id)
        season = normalize_text(row.get("Season"))
        mode = normalize_text(row.get("Mode")) or "Unknown"

        if not match_id:
            continue

        if scope == SCOPE_SEASON_OVERALL:
            season_match_ids.setdefault(season, set()).add(match_id)

        if scope == SCOPE_SEASON_MODE:
            season_mode_match_ids.setdefault((season, mode), set()).add(match_id)

        if scope == SCOPE_ALLTIME_OVERALL:
            alltime_match_ids.add(match_id)

        if scope == SCOPE_ALLTIME_MODE:
            alltime_mode_match_ids.setdefault(mode, set()).add(match_id)

    stats["season_total"] = {
        season: len(match_ids)
        for season, match_ids in season_match_ids.items()
    }

    stats["season_mode"] = {
        f"{season}|||{mode}": len(match_ids)
        for (season, mode), match_ids in season_mode_match_ids.items()
    }

    stats["alltime_total"] = len(alltime_match_ids)

    stats["alltime_mode"] = {
        mode: len(match_ids)
        for mode, match_ids in alltime_mode_match_ids.items()
    }

    return stats


def build_tfnl_ranking_payloads() -> dict[str, list[dict[str, Any]]]:
    """
    Baut beide Website-Payloads direkt aus Ladder_Ratings.
    Zusätzliche Match-Counts kommen aus Ladder_RatingHistory.
    """
    rows_with_index = load_ratings_rows_with_index()
    match_stats = build_match_count_stats()

    season_items: list[dict[str, Any]] = []
    overall_items: list[dict[str, Any]] = []

    for _row_index, row in rows_with_index:
        item = _rating_row_to_api_item(row)

        if item is None:
            continue

        scope = item["scope"]
        season = item.get("season", "")
        mode = item.get("mode", "ALL")

        if scope == SCOPE_SEASON_OVERALL:
            item["match_count_total"] = int(match_stats["season_total"].get(season, 0))
            season_items.append(item)

        elif scope == SCOPE_SEASON_MODE:
            item["match_count_total"] = int(match_stats["season_total"].get(season, 0))
            item["match_count_mode"] = int(match_stats["season_mode"].get(f"{season}|||{mode}", 0))
            season_items.append(item)

        elif scope == SCOPE_ALLTIME_OVERALL:
            item["match_count_total"] = int(match_stats["alltime_total"])
            overall_items.append(item)

        elif scope == SCOPE_ALLTIME_MODE:
            item["match_count_total"] = int(match_stats["alltime_total"])
            item["match_count_mode"] = int(match_stats["alltime_mode"].get(mode, 0))
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
    result_type = normalize_text(row.get("Result Type"))
    normalized_result = result_type.lower()

    if normalized_result == "sieg":
        result = "win"
    elif normalized_result == "remis":
        result = "draw"
    else:
        result = "loss"

    return {
        "player_id": normalize_text(row.get("Player ID")),
        "player_name": normalize_text(row.get("Player Name")) or "Unbekannt",
        "name": normalize_text(row.get("Player Name")) or "Unbekannt",
        "placement": int_value(row.get("Placement")),
        "score": float_value(row.get("Score"), 0.0),
        "result_type": result_type,
        "result": result,
        "time": "",
        "elo_before": float_value(row.get("Elo Before"), 1000.0),
        "elo_after": float_value(row.get("Elo After"), 1000.0),
        "elo_change": float_value(row.get("Elo Change"), 0.0),
    }


def _score_text_from_players(players: list[dict[str, Any]]) -> str:
    if len(players) == 2:
        a = players[0]
        b = players[1]

        if a.get("result") == "draw" or b.get("result") == "draw":
            return "1:1"

        if a.get("result") == "win":
            return "1:0"

        if b.get("result") == "win":
            return "0:1"

    if len(players) >= 3:
        return " / ".join(
            f"{player.get('placement')}. {player.get('player_name')}"
            for player in players
            if player.get("player_name")
        )

    return ""


def build_tfnl_results_payload() -> list[dict[str, Any]]:
    """
    Baut veröffentlichte TFNL-Ergebnisse aus Ladder_RatingHistory.

    Wichtig:
    - Es wird nur season_overall genutzt, damit jedes Match nur einmal
      auftaucht.
    - Gruppierung erfolgt über die Match ID vor dem ersten ":" in
      Rating Event ID.
    """
    history_rows = load_history_rows()
    grouped: dict[str, dict[str, Any]] = {}

    for row in history_rows:
        scope = normalize_text(row.get("Elo Scope"))

        if scope != SCOPE_SEASON_OVERALL:
            continue

        rating_event_id = normalize_text(row.get("Rating Event ID"))
        match_id = _match_id_from_rating_event_id(rating_event_id)

        if not match_id:
            continue

        item = grouped.setdefault(match_id, {
            "id": match_id,
            "match_id": match_id,
            "rating_event_id": rating_event_id,
            "season": normalize_text(row.get("Season")),
            "slot_id": normalize_text(row.get("Slot ID")) or match_id,
            "slotId": normalize_text(row.get("Slot ID")) or match_id,
            "slot": normalize_text(row.get("Slot ID")) or match_id,
            "date": normalize_text(row.get("Date")),
            "start_time": normalize_text(row.get("Date")),
            "startTime": normalize_text(row.get("Date")),
            "mode": normalize_text(row.get("Mode")) or "Unknown",
            "race_type": normalize_text(row.get("Race Type")) or "Race",
            "matchType": normalize_text(row.get("Race Type")) or "Race",
            "status": "finished",
            "created_at": normalize_text(row.get("Created At")),
            "players": [],
            "_seen_players": set(),
        })

        player = _history_row_to_result_player(row)
        player_key = player["player_id"] or player["player_name"]

        if player_key and player_key not in item["_seen_players"]:
            item["_seen_players"].add(player_key)
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
            None,
        )

        item["winner_name"] = winner.get("player_name") if winner else ""
        item["player_count"] = len(players)
        item["score"] = _score_text_from_players(players)
        item["result_text"] = " · ".join(
            f"{player.get('placement')}. {player.get('player_name')}"
            for player in players
            if player.get("player_name")
        )

        if len(players) >= 1:
            item["player1"] = players[0].get("player_name", "")
        if len(players) >= 2:
            item["player2"] = players[1].get("player_name", "")
        if len(players) >= 3:
            item["player3"] = players[2].get("player_name", "")

        item.pop("_seen_players", None)
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
    Veröffentlicht Season-Ranking, Overall-Ranking und TFNL Results an die API.
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

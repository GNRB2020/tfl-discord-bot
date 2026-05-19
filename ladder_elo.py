"""
TFNL Ladder ELO helpers.

Dieses Modul enthält bewusst keine Discord- oder Google-Sheets-Logik.
Es ist für reine Berechnung, Pairing-Logik und Tabellen-Sortierung gedacht.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import random
from typing import Iterable

START_ELO = 1000.0
DEFAULT_K_FACTOR = 32.0

SCOPE_SEASON_OVERALL = "season_overall"
SCOPE_SEASON_MODE = "season_mode"
SCOPE_ALLTIME_OVERALL = "alltime_overall"
SCOPE_ALLTIME_MODE = "alltime_mode"

ELO_SCOPES = (
    SCOPE_SEASON_OVERALL,
    SCOPE_SEASON_MODE,
    SCOPE_ALLTIME_OVERALL,
    SCOPE_ALLTIME_MODE,
)

PAIRING_ELO_WINDOWS = (50, 75, 100, 150, 200, None)
LAST_OPPONENT_LIMIT = 5


@dataclass(frozen=True)
class EloPlayer:
    player_id: str
    name: str
    elo: float = START_ELO


@dataclass(frozen=True)
class EloResult:
    player_id: str
    name: str
    score: float
    placement: int
    result_type: str
    elo_before: float
    opponent_elo_used: float
    elo_after: float
    elo_change: float


@dataclass(frozen=True)
class PairingPlayer:
    player_id: str
    name: str
    pairing_elo: float = START_ELO


def safe_float(value, default: float = START_ELO) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def expected_score(player_elo: float, opponent_elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent_elo - player_elo) / 400.0))


def calculate_new_elo(
    player_elo: float,
    opponent_elo: float,
    score: float,
    k_factor: float = DEFAULT_K_FACTOR,
) -> tuple[float, float]:
    expected = expected_score(player_elo, opponent_elo)
    change = k_factor * (score - expected)
    return player_elo + change, change


def score_to_result_type(score: float) -> str:
    if score >= 1.0:
        return "Sieg"
    if score <= 0.0:
        return "Niederlage"
    return "Remis"


def calculate_1on1_results(
    player_a: EloPlayer,
    player_b: EloPlayer,
    score_a: float,
    k_factor: float = DEFAULT_K_FACTOR,
) -> list[EloResult]:
    score_b = 1.0 - score_a

    new_a, change_a = calculate_new_elo(player_a.elo, player_b.elo, score_a, k_factor)
    new_b, change_b = calculate_new_elo(player_b.elo, player_a.elo, score_b, k_factor)

    if score_a > score_b:
        placement_a, placement_b = 1, 2
    elif score_b > score_a:
        placement_a, placement_b = 2, 1
    else:
        placement_a, placement_b = 1, 1

    return [
        EloResult(
            player_id=player_a.player_id,
            name=player_a.name,
            score=score_a,
            placement=placement_a,
            result_type=score_to_result_type(score_a),
            elo_before=player_a.elo,
            opponent_elo_used=player_b.elo,
            elo_after=new_a,
            elo_change=change_a,
        ),
        EloResult(
            player_id=player_b.player_id,
            name=player_b.name,
            score=score_b,
            placement=placement_b,
            result_type=score_to_result_type(score_b),
            elo_before=player_b.elo,
            opponent_elo_used=player_a.elo,
            elo_after=new_b,
            elo_change=change_b,
        ),
    ]


def calculate_3way_results(
    placed_players: list[EloPlayer],
    k_factor: float = DEFAULT_K_FACTOR,
) -> list[EloResult]:
    if len(placed_players) != 3:
        raise ValueError("3way benötigt exakt drei Spieler in Platzierungsreihenfolge.")

    placement_scores = {
        1: 1.0,
        2: 0.5,
        3: 0.0,
    }

    results: list[EloResult] = []

    for placement, player in enumerate(placed_players, start=1):
        opponents = [other for other in placed_players if other.player_id != player.player_id]
        opponent_average = sum(other.elo for other in opponents) / len(opponents)
        score = placement_scores[placement]
        new_elo, change = calculate_new_elo(player.elo, opponent_average, score, k_factor)

        results.append(
            EloResult(
                player_id=player.player_id,
                name=player.name,
                score=score,
                placement=placement,
                result_type=score_to_result_type(score),
                elo_before=player.elo,
                opponent_elo_used=opponent_average,
                elo_after=new_elo,
                elo_change=change,
            )
        )

    return results


def calculate_pairing_elo(
    season_mode_elo,
    alltime_mode_elo,
    default: float = START_ELO,
) -> float:
    season_value = safe_float(season_mode_elo, default)
    alltime_value = safe_float(alltime_mode_elo, default)
    return 0.7 * season_value + 0.3 * alltime_value


def get_weight_for_elo_distance(distance: float) -> int:
    distance = abs(float(distance))

    if distance <= 50:
        return 5
    if distance <= 100:
        return 3
    if distance <= 150:
        return 2
    return 1


def weighted_choice_by_elo_distance(
    base_player: PairingPlayer,
    candidates: list[PairingPlayer],
) -> PairingPlayer:
    if not candidates:
        raise ValueError("Keine Kandidaten vorhanden.")

    weights = [
        get_weight_for_elo_distance(base_player.pairing_elo - candidate.pairing_elo)
        for candidate in candidates
    ]
    return random.choices(candidates, weights=weights, k=1)[0]


def has_recent_opponent_conflict(
    group: Iterable[PairingPlayer],
    recent_opponents: dict[str, set[str]],
) -> bool:
    group_list = list(group)

    for player_a, player_b in combinations(group_list, 2):
        if player_b.player_id in recent_opponents.get(player_a.player_id, set()):
            return True
        if player_a.player_id in recent_opponents.get(player_b.player_id, set()):
            return True

    return False


def choose_3way_group(
    players: list[PairingPlayer],
    recent_opponents: dict[str, set[str]] | None = None,
) -> list[PairingPlayer]:
    if len(players) < 3:
        raise ValueError("Für ein 3way werden mindestens drei Spieler benötigt.")

    recent_opponents = recent_opponents or {}
    all_groups = list(combinations(players, 3))

    conflict_free = [
        list(group) for group in all_groups
        if not has_recent_opponent_conflict(group, recent_opponents)
    ]

    candidate_groups = conflict_free if conflict_free else [list(group) for group in all_groups]

    def span(group: list[PairingPlayer]) -> float:
        ratings = [player.pairing_elo for player in group]
        return max(ratings) - min(ratings)

    best_span = min(span(group) for group in candidate_groups)
    best_groups = [group for group in candidate_groups if span(group) == best_span]
    return list(random.choice(best_groups))


def choose_1on1_opponent(
    base_player: PairingPlayer,
    open_players: list[PairingPlayer],
    recent_opponents: dict[str, set[str]] | None = None,
) -> PairingPlayer:
    recent_opponents = recent_opponents or {}

    if not open_players:
        raise ValueError("Keine offenen Gegner vorhanden.")

    for window in PAIRING_ELO_WINDOWS:
        if window is None:
            window_candidates = open_players[:]
        else:
            window_candidates = [
                player for player in open_players
                if abs(player.pairing_elo - base_player.pairing_elo) <= window
            ]

        if not window_candidates:
            continue

        without_recent = [
            player for player in window_candidates
            if player.player_id not in recent_opponents.get(base_player.player_id, set())
            and base_player.player_id not in recent_opponents.get(player.player_id, set())
        ]

        if without_recent:
            return weighted_choice_by_elo_distance(base_player, without_recent)

    # Letzte-5-Regel wird erst hier gelockert.
    return weighted_choice_by_elo_distance(base_player, open_players)


def create_elo_pairings(
    players: list[PairingPlayer],
    recent_opponents: dict[str, set[str]] | None = None,
) -> list[list[PairingPlayer]]:
    if len(players) < 2:
        return []

    recent_opponents = recent_opponents or {}
    open_players = players[:]
    random.shuffle(open_players)

    pairings: list[list[PairingPlayer]] = []

    if len(open_players) % 2 == 1:
        three_way = choose_3way_group(open_players, recent_opponents)
        three_way_ids = {player.player_id for player in three_way}
        open_players = [player for player in open_players if player.player_id not in three_way_ids]
        pairings.append(three_way)

    while open_players:
        base_player = open_players.pop(0)
        opponent = choose_1on1_opponent(base_player, open_players, recent_opponents)
        open_players = [player for player in open_players if player.player_id != opponent.player_id]
        pairings.append([base_player, opponent])

    return pairings


def calculate_winrate(wins: int, draws: int, losses: int) -> float:
    games = int(wins) + int(draws) + int(losses)

    if games <= 0:
        return 0.0

    return ((int(wins) + int(draws) * 0.5) / games) * 100.0


def sort_standings_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            -safe_float(row.get("Elo"), START_ELO),
            -safe_float(row.get("Winrate"), 0.0),
            -safe_float(row.get("Wins"), 0.0),
            str(row.get("Player Name") or row.get("Name") or "").lower(),
        ),
    )

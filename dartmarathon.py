from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from aiohttp import WSMsgType, web

from dartmarathon_shop import ShopManager

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "dartmarathon_templates"
STATIC_DIR = BASE_DIR / "dartmarathon_static"
STATE_FILE = Path(
    os.getenv(
        "DARTMARATHON_STATE_FILE",
        str(BASE_DIR / "dartmarathon_state.json"),
    )
)
CONTROL_PASSWORD = os.getenv(
    "DARTMARATHON_CONTROL_PASSWORD",
    "",
).strip()
CONTROL_COOKIE_NAME = "dart_control"
CONTROL_COOKIE_MAX_AGE = 60 * 60 * 24 * 30

PREFIX = "/dartmarathon"
SCHEMA_VERSION = 5
ASSET_VERSION = "6.3.0"

INITIAL_PAUSE_SECONDS = 15 * 60
MAX_PAUSE_SECONDS = 30 * 60
MAX_HISTORY = 30
MAX_UNDO = 50
SAVE_INTERVAL_SECONDS = 3.0
POPUP_DURATION_MS = 20_000

PLAYERS = ("tzmarty", "korsar")
PLAYER_NAMES = {
    "tzmarty": "Tzmarty",
    "korsar": "Korsar",
}

MATCH_MODES = {
    "sido": "SI/DO",
    "set": "Setmodus",
    "bull_do": "Bull In / DO",
    "dido": "DI/DO",
    "cricket": "Cricket",
    "bobs27": "Bobs27",
}

AD_POPUPS = {
    "foltershop": {
        "label": "Foltershop",
        "image": f"{PREFIX}/static/ads/foltershop.png",
    },
    "malteser": {
        "label": "Malteser",
        "image": f"{PREFIX}/static/ads/malteser.png",
    },
    "koala": {
        "label": "KoalaDarts",
        "image": f"{PREFIX}/static/ads/koala.png",
    },
}

_state_lock = asyncio.Lock()
_clients: set[web.WebSocketResponse] = set()
_ticker_task: asyncio.Task | None = None
_auto_popup_cursor_seconds = 0

SHOP = ShopManager(
    prefix=PREFIX,
    base_dir=BASE_DIR,
    template_dir=TEMPLATE_DIR,
)


def _empty_special_detail() -> Dict[str, Any]:
    return {
        "hf": [],
        "bf": [],
        "180": 0,
        "177": 0,
        "174": 0,
        "171": 0,
        "ld": [],
    }


def default_state() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stream_elapsed": 0.0,
        "stream_running": False,
        "stream_started_at": None,
        "pause_seconds": float(INITIAL_PAUSE_SECONDS),
        "pause_active": False,
        "pause_started_at": None,
        "pause_used_seconds": 0.0,
        "own_donations": 0.0,
        "event_ended": False,

        # Altbestände aus der alten Zähler-Version bleiben erhalten.
        "legacy_legs": {
            "tzmarty": 0,
            "korsar": 0,
        },
        "legacy_special_totals": {
            "tzmarty": 0,
            "korsar": 0,
        },

        # Neue Match-Daten.
        "matches": [],
        "next_match_id": 1,

        "history": [],
        "undo_stack": [],
    }


def _old_special_total(raw: Any, player: str) -> int:
    if not isinstance(raw, dict):
        return 0

    player_data = raw.get(player)
    if isinstance(player_data, dict):
        total = 0
        for value in player_data.values():
            if isinstance(value, (int, float)):
                total += max(0, int(value))
        return total

    # Sehr alte globale Struktur.
    if player == "tzmarty":
        return sum(
            max(0, int(raw.get(key, 0) or 0))
            for key in (
                "highfinish",
                "bullfinish",
                "lowdarts",
                "score171",
            )
        )

    return 0


def _sanitize_special_detail(raw: Any) -> Dict[str, Any]:
    clean = _empty_special_detail()

    if not isinstance(raw, dict):
        return clean

    for key in ("hf", "bf", "ld"):
        values = raw.get(key, [])
        if isinstance(values, list):
            parsed: list[int] = []
            for value in values:
                try:
                    parsed.append(int(value))
                except (TypeError, ValueError):
                    continue
            clean[key] = parsed

    for key in ("180", "177", "174", "171"):
        try:
            clean[key] = max(
                0,
                int(raw.get(key, 0) or 0),
            )
        except (TypeError, ValueError):
            clean[key] = 0

    return clean


def _sanitize_match(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    try:
        match_id = int(raw.get("id", 0))
    except (TypeError, ValueError):
        return None

    if match_id <= 0:
        return None

    mode = str(raw.get("mode", "sido"))
    if mode not in MATCH_MODES:
        mode = "sido"

    result = raw.get("result", {})
    if not isinstance(result, dict):
        result = {}

    def nonnegative(name: str) -> int:
        try:
            return max(
                0,
                int(result.get(name, 0) or 0),
            )
        except (TypeError, ValueError):
            return 0

    clean_result = {
        "tzmarty_legs": nonnegative("tzmarty_legs"),
        "korsar_legs": nonnegative("korsar_legs"),
        "tzmarty_sets": nonnegative("tzmarty_sets"),
        "korsar_sets": nonnegative("korsar_sets"),
    }

    raw_specials = raw.get("specials", {})
    if not isinstance(raw_specials, dict):
        raw_specials = {}

    clean_specials = {
        player: _sanitize_special_detail(
            raw_specials.get(player, {})
        )
        for player in PLAYERS
    }

    try:
        theoretical = max(
            0.0,
            float(
                raw.get(
                    "pause_theoretical_seconds",
                    0.0,
                )
            ),
        )
    except (TypeError, ValueError):
        theoretical = 0.0

    try:
        applied = max(
            0.0,
            float(
                raw.get(
                    "pause_credit_applied_seconds",
                    0.0,
                )
            ),
        )
    except (TypeError, ValueError):
        applied = 0.0

    return {
        "id": match_id,
        "created_at": str(
            raw.get("created_at", "")
        ),
        "updated_at": str(
            raw.get("updated_at", "")
        ),
        "mode": mode,
        "result": clean_result,
        "specials": clean_specials,
        "pause_theoretical_seconds": theoretical,
        "pause_credit_applied_seconds": min(
            applied,
            theoretical,
        ),
    }


def _sanitize_state(data: Dict[str, Any]) -> Dict[str, Any]:
    clean = default_state()

    if not isinstance(data, dict):
        return clean

    for key in (
        "stream_elapsed",
        "stream_running",
        "stream_started_at",
        "pause_seconds",
        "pause_active",
        "pause_started_at",
        "pause_used_seconds",
        "own_donations",
        "event_ended",
        "history",
        "undo_stack",
    ):
        if key in data:
            clean[key] = data[key]

    clean["stream_elapsed"] = max(
        0.0,
        float(clean.get("stream_elapsed", 0.0)),
    )
    clean["stream_running"] = bool(
        clean.get("stream_running", False)
    )

    clean["pause_seconds"] = min(
        MAX_PAUSE_SECONDS,
        max(
            0.0,
            float(
                clean.get(
                    "pause_seconds",
                    INITIAL_PAUSE_SECONDS,
                )
            ),
        ),
    )
    clean["pause_active"] = bool(
        clean.get("pause_active", False)
    )
    clean["pause_used_seconds"] = max(
        0.0,
        float(
            clean.get(
                "pause_used_seconds",
                0.0,
            )
        ),
    )
    clean["own_donations"] = max(
        0.0,
        round(
            float(
                clean.get(
                    "own_donations",
                    0.0,
                )
            ),
            2,
        ),
    )
    clean["event_ended"] = bool(
        clean.get("event_ended", False)
    )

    # Wenn bereits Matchdaten vorhanden sind, werden sie unabhängig von
    # einer früheren Schema-Version erhalten.
    if isinstance(data.get("matches"), list):
        raw_legacy_legs = data.get(
            "legacy_legs",
            {},
        )
        raw_legacy_specials = data.get(
            "legacy_special_totals",
            {},
        )

        if not isinstance(
            raw_legacy_legs,
            dict,
        ):
            raw_legacy_legs = {}

        if not isinstance(
            raw_legacy_specials,
            dict,
        ):
            raw_legacy_specials = {}

        for player in PLAYERS:
            try:
                clean["legacy_legs"][player] = max(
                    0,
                    int(
                        raw_legacy_legs.get(
                            player,
                            0,
                        )
                    ),
                )
            except (TypeError, ValueError):
                clean["legacy_legs"][player] = 0

            try:
                clean[
                    "legacy_special_totals"
                ][player] = max(
                    0,
                    int(
                        raw_legacy_specials.get(
                            player,
                            0,
                        )
                    ),
                )
            except (TypeError, ValueError):
                clean[
                    "legacy_special_totals"
                ][player] = 0

        matches: list[Dict[str, Any]] = []

        for item in data.get("matches", []):
            cleaned = _sanitize_match(item)

            if cleaned:
                matches.append(cleaned)

        matches.sort(
            key=lambda item: item["id"]
        )

        clean["matches"] = matches

        max_id = max(
            (
                item["id"]
                for item in matches
            ),
            default=0,
        )

        try:
            requested_next = int(
                data.get(
                    "next_match_id",
                    max_id + 1,
                )
            )
        except (TypeError, ValueError):
            requested_next = max_id + 1

        clean["next_match_id"] = max(
            max_id + 1,
            requested_next,
        )

    else:
        # Migration aus der alten reinen Zähler-Version.
        old_legs = data.get(
            "legs",
            {},
        )

        if not isinstance(
            old_legs,
            dict,
        ):
            old_legs = {}

        for player in PLAYERS:
            try:
                clean["legacy_legs"][player] = max(
                    0,
                    int(
                        old_legs.get(
                            player,
                            0,
                        )
                    ),
                )
            except (TypeError, ValueError):
                clean["legacy_legs"][player] = 0

            clean[
                "legacy_special_totals"
            ][player] = _old_special_total(
                data.get(
                    "specials",
                    {},
                ),
                player,
            )

    clean["history"] = list(
        clean.get("history", [])
    )[-MAX_HISTORY:]

    clean["undo_stack"] = list(
        clean.get("undo_stack", [])
    )[-MAX_UNDO:]

    clean["schema_version"] = (
        SCHEMA_VERSION
    )

    return clean


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return default_state()

    try:
        raw = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        return _sanitize_state(
            raw
            if isinstance(raw, dict)
            else {}
        )

    except Exception as exc:
        print(
            "[DART] State konnte nicht "
            f"geladen werden: {exc}"
        )
        return default_state()


def _save_state_locked() -> None:
    try:
        STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_file = (
            STATE_FILE.with_suffix(
                STATE_FILE.suffix + ".tmp"
            )
        )

        temp_file.write_text(
            json.dumps(
                _state,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        os.replace(
            temp_file,
            STATE_FILE,
        )

    except Exception as exc:
        print(
            "[DART] State konnte nicht "
            f"gespeichert werden: {exc}"
        )


def _now() -> float:
    return time.time()


def _clock(
    seconds: float,
    with_hours: bool = False,
) -> str:
    value = max(
        0,
        int(seconds),
    )

    if with_hours:
        hours, remainder = divmod(
            value,
            3600,
        )

        minutes, secs = divmod(
            remainder,
            60,
        )

        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{secs:02d}"
        )

    minutes, secs = divmod(
        value,
        60,
    )

    return (
        f"{minutes:02d}:"
        f"{secs:02d}"
    )


def _timestamp() -> str:
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _add_history_locked(
    text: str,
) -> None:
    _state["history"].append({
        "time": datetime.now().strftime(
            "%H:%M:%S"
        ),
        "text": text,
    })

    _state["history"] = (
        _state["history"][
            -MAX_HISTORY:
        ]
    )


def _reconcile_running_timers_locked(
    save: bool = False,
) -> None:
    now = _now()
    changed = False

    if _state["stream_running"]:
        started = _state.get(
            "stream_started_at"
        )

        if isinstance(
            started,
            (int, float),
        ):
            _state["stream_elapsed"] += max(
                0.0,
                now - float(started),
            )

        _state["stream_started_at"] = now
        changed = True

    if _state["pause_active"]:
        started = _state.get(
            "pause_started_at"
        )

        if isinstance(
            started,
            (int, float),
        ):
            elapsed = max(
                0.0,
                now - float(started),
            )

            actually_used = min(
                elapsed,
                _state["pause_seconds"],
            )

            _state["pause_seconds"] = max(
                0.0,
                _state["pause_seconds"]
                - elapsed,
            )

            _state[
                "pause_used_seconds"
            ] += actually_used

        _state["pause_started_at"] = now
        changed = True

        if _state["pause_seconds"] <= 0:
            _state["pause_seconds"] = 0.0
            _state["pause_active"] = False
            _state["pause_started_at"] = None

            if not _state["event_ended"]:
                _state["event_ended"] = True

                _add_history_locked(
                    "Pausenkonto abgelaufen – "
                    "Event beendet"
                )

            changed = True

    if changed and save:
        _save_state_locked()


def _snapshot_locked() -> Dict[str, Any]:
    snapshot = deepcopy(_state)

    snapshot.pop(
        "undo_stack",
        None,
    )

    return snapshot


def _push_undo_locked(
    label: str,
) -> None:
    _reconcile_running_timers_locked(
        save=False
    )

    _state["undo_stack"].append({
        "label": label,
        "snapshot": _snapshot_locked(),
    })

    _state["undo_stack"] = (
        _state["undo_stack"][
            -MAX_UNDO:
        ]
    )


def _grant_pause_credit_locked(
    seconds: float,
) -> float:
    if _state["event_ended"]:
        return 0.0

    _reconcile_running_timers_locked(
        save=False
    )

    before = _state["pause_seconds"]

    _state["pause_seconds"] = min(
        MAX_PAUSE_SECONDS,
        max(
            0.0,
            before
            + max(
                0.0,
                seconds,
            ),
        ),
    )

    return max(
        0.0,
        _state["pause_seconds"]
        - before,
    )


def _remove_pause_credit_locked(
    seconds: float,
) -> float:
    _reconcile_running_timers_locked(
        save=False
    )

    before = _state["pause_seconds"]

    _state["pause_seconds"] = max(
        0.0,
        before
        - max(
            0.0,
            seconds,
        ),
    )

    removed = max(
        0.0,
        before
        - _state["pause_seconds"],
    )

    if (
        _state["pause_active"]
        and _state["pause_seconds"] <= 0
    ):
        _state["pause_seconds"] = 0.0
        _state["pause_active"] = False
        _state["pause_started_at"] = None
        _state["event_ended"] = True

        _add_history_locked(
            "Pausenkonto durch Korrektur "
            "abgelaufen – Event beendet"
        )

    return removed


def _special_count(
    detail: Dict[str, Any],
) -> int:
    return (
        len(detail.get("hf", []))
        + len(detail.get("bf", []))
        + max(
            0,
            int(detail.get("180", 0)),
        )
        + max(
            0,
            int(detail.get("177", 0)),
        )
        + max(
            0,
            int(detail.get("174", 0)),
        )
        + max(
            0,
            int(detail.get("171", 0)),
        )
        + len(detail.get("ld", []))
    )


def _match_leg_totals(
    match: Dict[str, Any],
) -> Dict[str, int]:
    result = match["result"]

    return {
        "tzmarty": max(
            0,
            int(
                result.get(
                    "tzmarty_legs",
                    0,
                )
            ),
        ),
        "korsar": max(
            0,
            int(
                result.get(
                    "korsar_legs",
                    0,
                )
            ),
        ),
    }


def _match_special_totals(
    match: Dict[str, Any],
) -> Dict[str, int]:
    return {
        player: _special_count(
            match["specials"][player]
        )
        for player in PLAYERS
    }


def _match_theoretical_pause(
    match: Dict[str, Any],
) -> int:
    legs = _match_leg_totals(match)
    specials = (
        _match_special_totals(match)
    )

    return (
        30 * sum(legs.values())
        + 60 * sum(
            specials.values()
        )
    )


def _aggregate_legs_locked() -> Dict[str, int]:
    totals = deepcopy(
        _state["legacy_legs"]
    )

    for match in _state["matches"]:
        match_legs = (
            _match_leg_totals(match)
        )

        for player in PLAYERS:
            totals[player] += (
                match_legs[player]
            )

    return totals


def _aggregate_special_totals_locked() -> Dict[str, int]:
    totals = deepcopy(
        _state[
            "legacy_special_totals"
        ]
    )

    for match in _state["matches"]:
        match_specials = (
            _match_special_totals(
                match
            )
        )

        for player in PLAYERS:
            totals[player] += (
                match_specials[player]
            )

    return totals


def _aggregate_special_detail_locked(
    player: str,
) -> Dict[str, Any]:
    aggregate = _empty_special_detail()

    for match in _state["matches"]:
        detail = (
            match["specials"][player]
        )

        aggregate["hf"].extend(
            detail["hf"]
        )
        aggregate["bf"].extend(
            detail["bf"]
        )
        aggregate["ld"].extend(
            detail["ld"]
        )

        for key in (
            "180",
            "177",
            "174",
            "171",
        ):
            aggregate[key] += int(
                detail[key]
            )

    aggregate["legacy"] = (
        _state[
            "legacy_special_totals"
        ].get(player, 0)
    )

    aggregate["total"] = (
        _special_count(aggregate)
        + aggregate["legacy"]
    )

    return aggregate


def _match_result_text(
    match: Dict[str, Any],
) -> str:
    result = match["result"]

    if match["mode"] == "set":
        return (
            "Sets "
            f"{result['tzmarty_sets']}:"
            f"{result['korsar_sets']}"
            " · Legs "
            f"{result['tzmarty_legs']}:"
            f"{result['korsar_legs']}"
        )

    return (
        f"{result['tzmarty_legs']}:"
        f"{result['korsar_legs']}"
    )


def _public_match(
    match: Dict[str, Any],
) -> Dict[str, Any]:
    special_totals = (
        _match_special_totals(match)
    )

    return {
        "id": match["id"],
        "created_at": (
            match.get(
                "created_at",
                "",
            )
        ),
        "updated_at": (
            match.get(
                "updated_at",
                "",
            )
        ),
        "mode": match["mode"],
        "mode_label": (
            MATCH_MODES[
                match["mode"]
            ]
        ),
        "result": deepcopy(
            match["result"]
        ),
        "result_text": (
            _match_result_text(match)
        ),
        "specials": deepcopy(
            match["specials"]
        ),
        "special_totals": (
            special_totals
        ),
        "special_total": sum(
            special_totals.values()
        ),
        "pause_theoretical_seconds": int(
            match.get(
                "pause_theoretical_seconds",
                0,
            )
        ),
        "pause_credit_applied_seconds": int(
            match.get(
                "pause_credit_applied_seconds",
                0,
            )
        ),
    }


def _metrics_locked() -> Dict[str, Any]:
    legs = _aggregate_legs_locked()
    specials = _aggregate_special_totals_locked()

    total_legs = sum(legs.values())
    total_specials = sum(specials.values())

    stream_hours = (
        _state["stream_elapsed"]
        / 3600.0
    )

    match_count = len(_state["matches"])
    match_wins = {
        "tzmarty": 0,
        "korsar": 0,
    }
    match_draws = 0
    match_legs_total = 0
    match_specials_total = 0

    for match in _state["matches"]:
        match_legs = _match_leg_totals(match)
        match_specials = _match_special_totals(match)

        match_legs_total += sum(match_legs.values())
        match_specials_total += sum(match_specials.values())

        result = match["result"]

        if (
            match["mode"] == "set"
            and (
                int(result.get("tzmarty_sets", 0))
                + int(result.get("korsar_sets", 0))
            ) > 0
        ):
            left = int(result.get("tzmarty_sets", 0))
            right = int(result.get("korsar_sets", 0))
        else:
            left = match_legs["tzmarty"]
            right = match_legs["korsar"]

        if left > right:
            match_wins["tzmarty"] += 1
        elif right > left:
            match_wins["korsar"] += 1
        else:
            match_draws += 1

    return {
        "legs": legs,
        "special_totals": specials,
        "total_legs": total_legs,
        "total_specials": total_specials,
        "specials_per_leg": (
            round(total_specials / total_legs, 2)
            if total_legs
            else 0.0
        ),
        "legs_per_hour": (
            round(total_legs / stream_hours, 1)
            if stream_hours > 0
            else 0.0
        ),
        "specials_per_hour": (
            round(total_specials / stream_hours, 1)
            if stream_hours > 0
            else 0.0
        ),
        "match_count": match_count,
        "match_wins": match_wins,
        "match_draws": match_draws,
        "avg_legs_per_match": (
            round(match_legs_total / match_count, 1)
            if match_count
            else 0.0
        ),
        "avg_specials_per_match": (
            round(match_specials_total / match_count, 1)
            if match_count
            else 0.0
        ),
    }


def _public_state_locked() -> Dict[str, Any]:
    _reconcile_running_timers_locked(
        save=False
    )

    metrics = _metrics_locked()
    shop = SHOP.public_state()
    own_donation_cents = int(round(float(_state["own_donations"]) * 100))
    shop["own_donations_cents"] = own_donation_cents
    shop["own_donations"] = f"{own_donation_cents / 100:.2f}"
    shop["event_total_cents"] = int(shop["summary"]["paid_cents"]) + own_donation_cents
    shop["event_total"] = f"{shop['event_total_cents'] / 100:.2f}"

    return {
        "stream_seconds": int(
            _state["stream_elapsed"]
        ),
        "stream_display": _clock(
            _state["stream_elapsed"],
            with_hours=True,
        ),
        "stream_running": (
            _state["stream_running"]
        ),

        "pause_seconds": int(
            _state["pause_seconds"]
        ),
        "pause_display": _clock(
            _state["pause_seconds"]
        ),
        "pause_active": (
            _state["pause_active"]
        ),
        "pause_full": (
            _state["pause_seconds"]
            >= MAX_PAUSE_SECONDS
        ),
        "pause_used_seconds": int(
            _state["pause_used_seconds"]
        ),
        "pause_used_display": _clock(
            _state["pause_used_seconds"],
            with_hours=True,
        ),

        "event_ended": (
            _state["event_ended"]
        ),

        "legs": metrics["legs"],
        "player_special_totals": (
            metrics["special_totals"]
        ),
        "total_legs": metrics["total_legs"],
        "total_specials": metrics["total_specials"],
        "specials_per_leg": metrics["specials_per_leg"],
        "legs_per_hour": metrics["legs_per_hour"],
        "specials_per_hour": metrics["specials_per_hour"],

        "match_count": metrics["match_count"],
        "match_wins": deepcopy(metrics["match_wins"]),
        "match_draws": metrics["match_draws"],
        "avg_legs_per_match": metrics["avg_legs_per_match"],
        "avg_specials_per_match": metrics["avg_specials_per_match"],

        "special_detail": {
            player: _aggregate_special_detail_locked(player)
            for player in PLAYERS
        },

        "own_donations": round(
            _state["own_donations"],
            2,
        ),

        "shop": shop,

        "matches": [
            _public_match(match)
            for match in reversed(
                _state["matches"]
            )
        ],

        "history": deepcopy(
            _state["history"]
        ),

        "can_undo": bool(
            _state["undo_stack"]
        ),
    }


def _parse_int_list(
    raw: Any,
    minimum: int,
    maximum: int | None = None,
) -> list[int]:
    if raw is None:
        return []

    if not isinstance(raw, list):
        raise ValueError(
            "Liste erwartet"
        )

    values: list[int] = []

    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError):
            raise ValueError(
                "Ungültige Zahl"
            )

        if value < minimum:
            raise ValueError(
                "Wert außerhalb des "
                "erlaubten Bereichs"
            )

        if (
            maximum is not None
            and value > maximum
        ):
            raise ValueError(
                "Wert außerhalb des "
                "erlaubten Bereichs"
            )

        values.append(value)

    return values


def _parse_count(
    raw: Any,
) -> int:
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        raise ValueError(
            "Ungültige Anzahl"
        )

    if value < 0 or value > 999:
        raise ValueError(
            "Ungültige Anzahl"
        )

    return value


def _parse_special_detail(
    raw: Any,
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}

    return {
        "hf": _parse_int_list(
            raw.get("hf", []),
            100,
        ),
        "bf": _parse_int_list(
            raw.get("bf", []),
            50,
        ),
        "180": _parse_count(
            raw.get("180", 0)
        ),
        "177": _parse_count(
            raw.get("177", 0)
        ),
        "174": _parse_count(
            raw.get("174", 0)
        ),
        "171": _parse_count(
            raw.get("171", 0)
        ),
        "ld": _parse_int_list(
            raw.get("ld", []),
            9,
            18,
        ),
    }


def _parse_match_payload(
    message: Dict[str, Any],
) -> Dict[str, Any]:
    mode = str(
        message.get(
            "mode",
            "sido",
        )
    )

    if mode not in MATCH_MODES:
        raise ValueError(
            "Ungültiger Spielmodus"
        )

    result = message.get(
        "result",
        {},
    )

    if not isinstance(result, dict):
        raise ValueError(
            "Ergebnis fehlt"
        )

    def nonnegative_int(
        name: str,
    ) -> int:
        try:
            value = int(
                result.get(
                    name,
                    0,
                )
            )
        except (TypeError, ValueError):
            raise ValueError(
                "Ergebnis enthält "
                "ungültige Werte"
            )

        if value < 0 or value > 999:
            raise ValueError(
                "Ergebnis enthält "
                "ungültige Werte"
            )

        return value

    clean_result = {
        "tzmarty_legs": (
            nonnegative_int(
                "tzmarty_legs"
            )
        ),
        "korsar_legs": (
            nonnegative_int(
                "korsar_legs"
            )
        ),
        "tzmarty_sets": (
            nonnegative_int(
                "tzmarty_sets"
            )
        ),
        "korsar_sets": (
            nonnegative_int(
                "korsar_sets"
            )
        ),
    }

    if (
        clean_result[
            "tzmarty_legs"
        ]
        + clean_result[
            "korsar_legs"
        ]
        <= 0
    ):
        raise ValueError(
            "Bitte ein Spielergebnis "
            "mit mindestens einem Leg "
            "eintragen."
        )

    if (
        mode == "set"
        and (
            clean_result[
                "tzmarty_sets"
            ]
            + clean_result[
                "korsar_sets"
            ]
            <= 0
        )
    ):
        raise ValueError(
            "Beim Setmodus bitte auch "
            "das Settergebnis eintragen."
        )

    raw_specials = message.get(
        "specials",
        {},
    )

    if not isinstance(
        raw_specials,
        dict,
    ):
        raw_specials = {}

    specials = {
        player: (
            _parse_special_detail(
                raw_specials.get(
                    player,
                    {},
                )
            )
        )
        for player in PLAYERS
    }

    parsed = {
        "mode": mode,
        "result": clean_result,
        "specials": specials,
    }

    parsed[
        "pause_theoretical_seconds"
    ] = _match_theoretical_pause(
        parsed
    )

    parsed[
        "pause_credit_applied_seconds"
    ] = 0.0

    return parsed


def _find_match_index(
    match_id: int,
) -> int | None:
    for index, match in enumerate(
        _state["matches"]
    ):
        if match["id"] == match_id:
            return index

    return None


def _popup_ad(
    sponsor: str,
) -> Dict[str, Any]:
    ad = AD_POPUPS[sponsor]

    return {
        "type": "ad_popup",
        "sponsor": sponsor,
        "label": ad["label"],
        "image": ad["image"],
        "position": "right",
        "duration_ms": (
            POPUP_DURATION_MS
        ),
    }


def _popup_recent_matches_locked() -> Dict[str, Any]:
    matches = []

    for match in reversed(
        _state["matches"][-5:]
    ):
        matches.append({
            "id": match["id"],
            "mode": MATCH_MODES[
                match["mode"]
            ],
            "result": (
                _match_result_text(
                    match
                )
            ),
        })

    return {
        "type": (
            "recent_matches_popup"
        ),
        "matches": matches,
        "duration_ms": (
            POPUP_DURATION_MS
        ),
    }


def _popup_specials_locked() -> Dict[str, Any]:
    return {
        "type": "specials_popup",
        "players": {
            player: (
                _aggregate_special_detail_locked(
                    player
                )
            )
            for player in PLAYERS
        },
        "duration_ms": (
            POPUP_DURATION_MS
        ),
    }


def _popup_stats_locked(
    hour: int | None = None,
) -> Dict[str, Any]:
    metrics = _metrics_locked()

    title = "EVENT-KENNZAHLEN"

    if hour in (
        6,
        12,
        18,
        24,
    ):
        title = (
            f"{hour}-STUNDEN-"
            "MEILENSTEIN"
        )

    return {
        "type": "stats_popup",
        "title": title,
        "stats": {
            **metrics,
            "pause_used_display": _clock(
                _state["pause_used_seconds"],
                with_hours=True,
            ),
        },
        "duration_ms": POPUP_DURATION_MS,
    }


def _collect_auto_popups_locked(
    previous: int,
    current: int,
) -> list[Dict[str, Any]]:
    if current <= previous:
        return []

    # Nach Server-Unterbrechungen keine alte Stunde nachspielen.
    if current - previous > 120:
        previous = current - 2

    targets = {
        0: "stats",
        600: "foltershop",
        1200: "recent",
        1800: "malteser",
        2400: "specials",
        3000: "koala",
    }

    payloads: list[
        Dict[str, Any]
    ] = []

    start_hour = max(
        0,
        previous // 3600,
    )

    end_hour = (
        current // 3600
    )

    for hour in range(
        start_hour,
        end_hour + 1,
    ):
        for offset, kind in (
            targets.items()
        ):
            boundary = (
                hour * 3600
                + offset
            )

            # 00:00:00 darf nichts auslösen.
            if boundary <= 0:
                continue

            if not (
                previous
                < boundary
                <= current
            ):
                continue

            if kind == "stats":
                payloads.append(
                    _popup_stats_locked(
                        hour=hour
                    )
                )
            elif kind == "recent":
                payloads.append(
                    _popup_recent_matches_locked()
                )
            elif kind == "specials":
                payloads.append(
                    _popup_specials_locked()
                )
            else:
                payloads.append(
                    _popup_ad(kind)
                )

    # Niemals mehrere verpasste Popups gleichzeitig nachholen.
    return payloads[-1:]


def _session_cookie_value() -> str:
    if not CONTROL_PASSWORD:
        return ""

    return hashlib.sha256(
        (
            "dartmarathon-control-session:"
            + CONTROL_PASSWORD
        ).encode("utf-8")
    ).hexdigest()


def _password_matches(
    value: str | None,
) -> bool:
    if not CONTROL_PASSWORD:
        return False

    if not value:
        return False

    return secrets.compare_digest(
        value,
        CONTROL_PASSWORD,
    )


def _request_can_control(
    request: web.Request,
) -> bool:
    expected = _session_cookie_value()

    if not expected:
        return False

    current = request.cookies.get(
        CONTROL_COOKIE_NAME,
        "",
    )

    return bool(
        current
        and secrets.compare_digest(
            current,
            expected,
        )
    )


_state = _load_state()
_reconcile_running_timers_locked(
    save=True
)

# Beim Prozessstart gilt die vorhandene Streamzeit als bereits verarbeitet.
_auto_popup_cursor_seconds = int(
    _state["stream_elapsed"]
)


async def _send_error(
    ws: web.WebSocketResponse,
    message: str,
) -> None:
    if ws.closed:
        return

    try:
        await ws.send_json({
            "type": "error",
            "message": message,
        })
    except Exception:
        pass


async def _send_ack(
    ws: web.WebSocketResponse,
    payload: Dict[str, Any],
) -> None:
    if ws.closed:
        return

    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def _broadcast_payload(
    payload: Dict[str, Any],
) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
    )

    dead: list[
        web.WebSocketResponse
    ] = []

    for ws in list(_clients):
        if ws.closed:
            dead.append(ws)
            continue

        try:
            await ws.send_str(
                encoded
            )
        except Exception:
            dead.append(ws)

    for ws in dead:
        _clients.discard(ws)


async def _broadcast_state() -> None:
    async with _state_lock:
        payload = {
            "type": "state",
            "data": (
                _public_state_locked()
            ),
        }

    await _broadcast_payload(
        payload
    )


async def _mutate(
    label: str,
    fn,
) -> bool:
    async with _state_lock:
        _push_undo_locked(label)

        changed = fn()

        if changed is False:
            _state[
                "undo_stack"
            ].pop()
            return False

        _add_history_locked(label)
        _save_state_locked()

    await _broadcast_state()
    return True


async def _process_message(
    ws: web.WebSocketResponse,
    message: Dict[str, Any],
) -> None:
    global _state
    global _auto_popup_cursor_seconds

    msg_type = message.get("type")

    if isinstance(msg_type, str) and msg_type.startswith("shop_"):
        handled, error = await SHOP.handle_control_message(message)
        if handled:
            await _broadcast_state()
        else:
            await _send_error(ws, error or "Shop-Aktion fehlgeschlagen.")
        return

    if msg_type == "stream_action":
        action = message.get("action")

        if action == "start":
            def fn():
                if _state[
                    "stream_running"
                ]:
                    return False

                _state[
                    "stream_running"
                ] = True

                _state[
                    "stream_started_at"
                ] = _now()

                return True

            changed = await _mutate(
                "Streamlaufzeit gestartet",
                fn,
            )

            if not changed:
                await _send_error(
                    ws,
                    "Streamlaufzeit läuft bereits.",
                )

        elif action == "stop":
            def fn():
                if not _state[
                    "stream_running"
                ]:
                    return False

                _reconcile_running_timers_locked(
                    save=False
                )

                _state[
                    "stream_running"
                ] = False

                _state[
                    "stream_started_at"
                ] = None

                return True

            changed = await _mutate(
                "Streamlaufzeit gestoppt",
                fn,
            )

            if not changed:
                await _send_error(
                    ws,
                    "Streamlaufzeit ist bereits gestoppt.",
                )

        elif action == "reset":
            def fn():
                global _auto_popup_cursor_seconds

                _reconcile_running_timers_locked(
                    save=False
                )

                if (
                    _state[
                        "stream_elapsed"
                    ] <= 0
                    and not _state[
                        "stream_running"
                    ]
                ):
                    return False

                _state[
                    "stream_elapsed"
                ] = 0.0

                _state[
                    "stream_running"
                ] = False

                _state[
                    "stream_started_at"
                ] = None

                _auto_popup_cursor_seconds = 0

                return True

            changed = await _mutate(
                "Streamlaufzeit zurückgesetzt",
                fn,
            )

            if not changed:
                await _send_error(
                    ws,
                    "Streamlaufzeit ist bereits 00:00:00.",
                )

        return

    if msg_type == "pause_action":
        action = message.get("action")

        if action == "start":
            def fn():
                _reconcile_running_timers_locked(
                    save=False
                )

                if (
                    _state[
                        "pause_active"
                    ]
                    or _state[
                        "event_ended"
                    ]
                    or _state[
                        "pause_seconds"
                    ] <= 0
                ):
                    return False

                _state[
                    "pause_active"
                ] = True

                _state[
                    "pause_started_at"
                ] = _now()

                return True

            changed = await _mutate(
                "Pause gestartet",
                fn,
            )

            if not changed:
                await _send_error(
                    ws,
                    "Pause kann aktuell nicht gestartet werden.",
                )

        elif action == "stop":
            def fn():
                if not _state[
                    "pause_active"
                ]:
                    return False

                _reconcile_running_timers_locked(
                    save=False
                )

                _state[
                    "pause_active"
                ] = False

                _state[
                    "pause_started_at"
                ] = None

                return True

            changed = await _mutate(
                "Pause gestoppt",
                fn,
            )

            if not changed:
                await _send_error(
                    ws,
                    "Pause läuft aktuell nicht.",
                )

        elif action == "reset":
            def fn():
                _state[
                    "pause_seconds"
                ] = float(
                    INITIAL_PAUSE_SECONDS
                )

                _state[
                    "pause_active"
                ] = False

                _state[
                    "pause_started_at"
                ] = None

                _state[
                    "event_ended"
                ] = False

                return True

            await _mutate(
                "Pausenkonto auf 15:00 zurückgesetzt",
                fn,
            )

        elif action == "unlock":
            def fn():
                if not _state[
                    "event_ended"
                ]:
                    return False

                _state[
                    "event_ended"
                ] = False

                _state[
                    "pause_active"
                ] = False

                _state[
                    "pause_started_at"
                ] = None

                if _state[
                    "pause_seconds"
                ] <= 0:
                    _state[
                        "pause_seconds"
                    ] = float(
                        INITIAL_PAUSE_SECONDS
                    )

                return True

            changed = await _mutate(
                "Event manuell wieder freigegeben",
                fn,
            )

            if not changed:
                await _send_error(
                    ws,
                    "Event ist nicht beendet.",
                )

        return

    if msg_type == "pause_adjust":
        try:
            seconds = int(
                message.get(
                    "seconds",
                    0,
                )
            )
        except (TypeError, ValueError):
            await _send_error(
                ws,
                "Ungültige Pausenkorrektur.",
            )
            return

        if (
            seconds == 0
            or abs(seconds)
            > MAX_PAUSE_SECONDS
        ):
            await _send_error(
                ws,
                "Ungültige Pausenkorrektur.",
            )
            return

        def fn():
            if (
                _state["event_ended"]
                and seconds > 0
            ):
                return False

            before = (
                _state[
                    "pause_seconds"
                ]
            )

            if seconds > 0:
                _grant_pause_credit_locked(
                    seconds
                )
            else:
                _remove_pause_credit_locked(
                    abs(seconds)
                )

            return (
                _state[
                    "pause_seconds"
                ]
                != before
            )

        sign = (
            "+"
            if seconds > 0
            else ""
        )

        changed = await _mutate(
            (
                "Pausenkonto manuell "
                f"{sign}{seconds} Sek."
            ),
            fn,
        )

        if not changed:
            await _send_error(
                ws,
                "Pausenkonto konnte nicht geändert werden.",
            )

        return

    if msg_type == "match_save":
        if _state["event_ended"]:
            await _send_error(
                ws,
                "Event ist beendet. "
                "Bitte zuerst wieder freigeben.",
            )
            return

        try:
            parsed = (
                _parse_match_payload(
                    message
                )
            )
        except ValueError as exc:
            await _send_error(
                ws,
                str(exc),
            )
            return

        raw_id = message.get("id")

        if raw_id in (
            None,
            "",
            0,
            "0",
        ):
            match_id = None
        else:
            try:
                match_id = int(
                    raw_id
                )
            except (TypeError, ValueError):
                await _send_error(
                    ws,
                    "Ungültige Match-ID",
                )
                return

        if match_id is None:
            new_id = (
                _state[
                    "next_match_id"
                ]
            )

            def fn():
                match = deepcopy(
                    parsed
                )

                match["id"] = new_id
                match["created_at"] = (
                    _timestamp()
                )
                match["updated_at"] = (
                    match[
                        "created_at"
                    ]
                )

                theoretical = (
                    match[
                        "pause_theoretical_seconds"
                    ]
                )

                applied = (
                    _grant_pause_credit_locked(
                        theoretical
                    )
                )

                match[
                    "pause_credit_applied_seconds"
                ] = applied

                _state[
                    "matches"
                ].append(match)

                _state[
                    "next_match_id"
                ] = new_id + 1

                return True

            await _mutate(
                f"Match #{new_id} gespeichert",
                fn,
            )

            await _send_ack(
                ws,
                {
                    "type": "match_saved",
                    "id": new_id,
                    "operation": "created",
                    "message": (
                        f"Match #{new_id} gespeichert."
                    ),
                },
            )

            return

        index = _find_match_index(
            match_id
        )

        if index is None:
            await _send_error(
                ws,
                "Match nicht gefunden",
            )
            return

        def fn():
            old = (
                _state[
                    "matches"
                ][index]
            )

            new = deepcopy(parsed)

            new["id"] = old["id"]
            new["created_at"] = (
                old.get(
                    "created_at",
                    _timestamp(),
                )
            )
            new["updated_at"] = (
                _timestamp()
            )

            old_theoretical = float(
                old.get(
                    "pause_theoretical_seconds",
                    0.0,
                )
            )

            old_applied = float(
                old.get(
                    "pause_credit_applied_seconds",
                    0.0,
                )
            )

            new_theoretical = float(
                new[
                    "pause_theoretical_seconds"
                ]
            )

            new_applied = old_applied

            if (
                new_theoretical
                > old_theoretical
            ):
                extra = (
                    new_theoretical
                    - old_theoretical
                )

                new_applied += (
                    _grant_pause_credit_locked(
                        extra
                    )
                )

            elif (
                new_theoretical
                < old_theoretical
            ):
                reduction = min(
                    old_applied,
                    old_theoretical
                    - new_theoretical,
                )

                _remove_pause_credit_locked(
                    reduction
                )

                new_applied = max(
                    0.0,
                    old_applied
                    - reduction,
                )

            new[
                "pause_credit_applied_seconds"
            ] = min(
                new_applied,
                new_theoretical,
            )

            _state[
                "matches"
            ][index] = new

            return True

        await _mutate(
            f"Match #{match_id} bearbeitet",
            fn,
        )

        await _send_ack(
            ws,
            {
                "type": "match_saved",
                "id": match_id,
                "operation": "updated",
                "message": (
                    f"Match #{match_id} aktualisiert."
                ),
            },
        )

        return

    if msg_type == "match_delete":
        try:
            match_id = int(
                message.get(
                    "id",
                    0,
                )
            )
        except (TypeError, ValueError):
            await _send_error(
                ws,
                "Ungültige Match-ID",
            )
            return

        index = _find_match_index(
            match_id
        )

        if index is None:
            await _send_error(
                ws,
                "Match nicht gefunden",
            )
            return

        def fn():
            match = (
                _state["matches"].pop(
                    index
                )
            )

            applied = float(
                match.get(
                    "pause_credit_applied_seconds",
                    0.0,
                )
            )

            if applied > 0:
                _remove_pause_credit_locked(
                    applied
                )

            return True

        await _mutate(
            f"Match #{match_id} gelöscht",
            fn,
        )

        await _send_ack(
            ws,
            {
                "type": "match_deleted",
                "id": match_id,
                "message": (
                    f"Match #{match_id} gelöscht."
                ),
            },
        )

        return

    if msg_type == "donation_adjust":
        try:
            amount = round(
                float(
                    message.get(
                        "amount",
                        0,
                    )
                ),
                2,
            )
        except (TypeError, ValueError):
            await _send_error(
                ws,
                "Ungültiger Spendenbetrag.",
            )
            return

        if (
            amount == 0
            or abs(amount) > 10000
            or _state["event_ended"]
        ):
            await _send_error(
                ws,
                "Spendenbetrag kann aktuell nicht übernommen werden.",
            )
            return

        actual = amount

        if amount < 0:
            actual = -min(
                abs(amount),
                _state[
                    "own_donations"
                ],
            )

            if actual == 0:
                await _send_error(
                    ws,
                    "Keine eigene Spende zum Abziehen vorhanden.",
                )
                return

        def fn():
            _state[
                "own_donations"
            ] = round(
                _state[
                    "own_donations"
                ]
                + actual,
                2,
            )

            if actual > 0:
                _grant_pause_credit_locked(
                    actual * 60
                )
            else:
                _remove_pause_credit_locked(
                    abs(actual) * 60
                )

            return True

        sign = (
            "+"
            if actual > 0
            else ""
        )

        await _mutate(
            (
                "Eigene Spende "
                f"{sign}{actual:.2f} €"
            ),
            fn,
        )

        return

    if msg_type == "popup_action":
        kind = str(
            message.get(
                "kind",
                "",
            )
        )

        async with _state_lock:
            if kind == "recent_matches":
                payload = (
                    _popup_recent_matches_locked()
                )
            elif kind == "specials":
                payload = (
                    _popup_specials_locked()
                )
            elif kind == "stats":
                payload = (
                    _popup_stats_locked()
                )
            elif kind in AD_POPUPS:
                payload = (
                    _popup_ad(kind)
                )
            else:
                await _send_error(
                    ws,
                    "Unbekannte Einblendung.",
                )
                return

        await _broadcast_payload(
            payload
        )

        await _send_ack(
            ws,
            {
                "type": "popup_sent",
                "kind": kind,
            },
        )

        return

    if msg_type == "undo":
        async with _state_lock:
            _reconcile_running_timers_locked(
                save=False
            )

            if not _state[
                "undo_stack"
            ]:
                await _send_error(
                    ws,
                    "Keine Aktion zum Rückgängigmachen vorhanden.",
                )
                return

            item = _state[
                "undo_stack"
            ].pop()

            remaining = deepcopy(
                _state[
                    "undo_stack"
                ]
            )

            restored = deepcopy(
                item["snapshot"]
            )

            restored[
                "undo_stack"
            ] = remaining

            _state = restored

            _add_history_locked(
                "Rückgängig: "
                f"{item['label']}"
            )

            _save_state_locked()

            _auto_popup_cursor_seconds = int(
                _state[
                    "stream_elapsed"
                ]
            )

        await _broadcast_state()
        return

    if msg_type == "full_reset":
        async with _state_lock:
            _state = default_state()

            _add_history_locked(
                "Gesamtes Event zurückgesetzt"
            )

            _save_state_locked()

            _auto_popup_cursor_seconds = 0

        await _broadcast_state()

        await _send_ack(
            ws,
            {
                "type": "full_reset_done",
            },
        )

        return

    await _send_error(
        ws,
        "Unbekannter Befehl.",
    )


async def _serve_template(
    name: str,
) -> web.Response:
    path = TEMPLATE_DIR / name

    if not path.exists():
        raise web.HTTPNotFound()

    response = web.Response(
        text=path.read_text(
            encoding="utf-8"
        ),
        content_type="text/html",
    )

    # Verhindert HTML/JS/CSS-Mischstände nach einem Deploy.
    response.headers[
        "Cache-Control"
    ] = (
        "no-store, no-cache, "
        "must-revalidate, max-age=0"
    )

    return response


async def _control(
    request: web.Request,
) -> web.StreamResponse:
    if not CONTROL_PASSWORD:
        return web.Response(
            text=(
                "Dartmarathon-Control ist nicht konfiguriert. "
                "Bitte DARTMARATHON_CONTROL_PASSWORD in Render setzen."
            ),
            status=503,
            content_type="text/plain",
            headers={
                "Cache-Control": "no-store",
            },
        )

    if _request_can_control(request):
        return await _serve_template(
            "control.html"
        )

    return await _serve_template(
        "login.html"
    )


async def _login(
    request: web.Request,
) -> web.StreamResponse:
    if not CONTROL_PASSWORD:
        return web.Response(
            text=(
                "Dartmarathon-Control ist nicht konfiguriert. "
                "Bitte DARTMARATHON_CONTROL_PASSWORD in Render setzen."
            ),
            status=503,
            content_type="text/plain",
            headers={
                "Cache-Control": "no-store",
            },
        )

    data = await request.post()

    password = str(
        data.get(
            "password",
            "",
        )
    )

    if not _password_matches(password):
        html = (
            TEMPLATE_DIR
            / "login.html"
        ).read_text(
            encoding="utf-8"
        )

        html = html.replace(
            "<!--LOGIN_ERROR-->",
            (
                '<div class="login-error">'
                "Kennwort nicht korrekt."
                "</div>"
            ),
        )

        response = web.Response(
            text=html,
            content_type="text/html",
            status=403,
        )

        response.headers[
            "Cache-Control"
        ] = "no-store"

        return response

    response = web.HTTPFound(
        f"{PREFIX}/control"
    )

    response.set_cookie(
        CONTROL_COOKIE_NAME,
        _session_cookie_value(),
        httponly=True,
        samesite="Strict",
        secure=request.secure,
        max_age=CONTROL_COOKIE_MAX_AGE,
        path=f"{PREFIX}/",
    )

    return response


async def _logout(
    request: web.Request,
) -> web.StreamResponse:
    response = web.HTTPFound(
        f"{PREFIX}/control"
    )

    response.del_cookie(
        CONTROL_COOKIE_NAME,
        path=f"{PREFIX}/",
    )

    return response


async def _root(
    _request: web.Request,
) -> web.StreamResponse:
    raise web.HTTPFound(
        f"{PREFIX}/control"
    )


async def _overlay(
    _request: web.Request,
) -> web.Response:
    return await _serve_template(
        "overlay.html"
    )


async def _preview(
    _request: web.Request,
) -> web.Response:
    return await _serve_template(
        "preview.html"
    )


async def _ws(
    request: web.Request,
) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(
        heartbeat=25
    )

    await ws.prepare(
        request
    )

    can_control = (
        _request_can_control(
            request
        )
    )

    _clients.add(ws)

    async with _state_lock:
        await ws.send_json({
            "type": "state",
            "data": (
                _public_state_locked()
            ),
            "can_control": (
                can_control
            ),
        })

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    message = json.loads(
                        msg.data
                    )
                except json.JSONDecodeError:
                    await _send_error(
                        ws,
                        "Ungültige Nachricht.",
                    )
                    continue

                if not can_control:
                    await _send_error(
                        ws,
                        "Control-Zugriff nicht autorisiert.",
                    )
                    continue

                try:
                    await _process_message(
                        ws,
                        message,
                    )
                except Exception as exc:
                    print(
                        "[DART] Fehler bei "
                        "Control-Aktion: "
                        f"{exc}"
                    )

                    await _send_error(
                        ws,
                        "Die Aktion konnte serverseitig "
                        "nicht verarbeitet werden.",
                    )

            elif msg.type in (
                WSMsgType.CLOSE,
                WSMsgType.CLOSED,
                WSMsgType.ERROR,
            ):
                break

    finally:
        _clients.discard(ws)

    return ws


def _shop_event_state() -> Dict[str, Any]:
    return {
        "pause_active": bool(_state.get("pause_active", False)),
        "pause_seconds": float(_state.get("pause_seconds", 0.0) or 0.0),
        "event_ended": bool(_state.get("event_ended", False)),
    }


async def _apply_shop_event_action(
    action_type: str,
    action_value: int,
    order_id: int,
) -> Dict[str, Any]:
    if action_type != "pause_minus":
        return {
            "applied": True,
            "actual_value": 0,
        }

    async with _state_lock:
        _reconcile_running_timers_locked(save=False)

        # Pausendiebe dürfen niemals während einer aktiv laufenden Pause wirken.
        if _state["pause_active"]:
            return {
                "applied": False,
                "deferred": True,
                "reason": "pause_active",
            }

        if _state["event_ended"]:
            return {
                "applied": True,
                "actual_value": 0,
                "reason": "event_ended",
            }

        before = float(_state["pause_seconds"])
        requested = max(0.0, float(action_value))

        # Der Shop darf das Event niemals durch einen Pausendieb beenden.
        minimum = 1.0
        after = max(minimum, before - requested)
        actual = max(0.0, before - after)

        _state["pause_seconds"] = after

        _add_history_locked(
            "Foltershop Pausendieb "
            f"#{order_id}: -{int(actual)} Sek."
        )
        _save_state_locked()

        return {
            "applied": True,
            "actual_value": int(actual),
            "pause_seconds": int(after),
        }


async def _shop_import(
    request: web.Request,
) -> web.Response:
    if not _request_can_control(request):
        return web.json_response(
            {
                "ok": False,
                "errors": ["Nicht angemeldet."],
            },
            status=403,
        )

    return await SHOP.import_items(request)


async def _ticker() -> None:
    global _auto_popup_cursor_seconds

    last_save = 0.0

    try:
        while True:
            await asyncio.sleep(0.25)

            try:
                auto_payloads: list[
                    Dict[str, Any]
                ] = []

                async with _state_lock:
                    _reconcile_running_timers_locked(
                        save=False
                    )

                    current = int(
                        _state[
                            "stream_elapsed"
                        ]
                    )

                    if (
                        current
                        < _auto_popup_cursor_seconds
                    ):
                        _auto_popup_cursor_seconds = (
                            current
                        )

                    elif _state[
                        "stream_running"
                    ]:
                        auto_payloads = (
                            _collect_auto_popups_locked(
                                _auto_popup_cursor_seconds,
                                current,
                            )
                        )

                        _auto_popup_cursor_seconds = (
                            current
                        )

                    now = _now()

                    if (
                        now - last_save
                        >= SAVE_INTERVAL_SECONDS
                    ):
                        _save_state_locked()
                        last_save = now

                # Bezahlte Pausendiebe, die während einer laufenden Pause
                # bestätigt wurden, werden erst nach Ende dieser Pause angewendet.
                await SHOP.process_pending_actions()

                for payload in auto_payloads:
                    await _broadcast_payload(
                        payload
                    )

                await _broadcast_state()

            except Exception as exc:
                # Der Ticker darf bei einem einzelnen Fehler nicht sterben.
                print(
                    "[DART] Ticker-Fehler: "
                    f"{exc}"
                )

    except asyncio.CancelledError:
        async with _state_lock:
            _save_state_locked()

        raise


async def _cleanup_ctx(
    _app: web.Application,
):
    global _ticker_task

    _ticker_task = (
        asyncio.create_task(
            _ticker(),
            name="dartmarathon-ticker",
        )
    )

    print(
        "[DART] Dartmarathon-Ticker "
        "gestartet"
    )

    yield

    if _ticker_task:
        _ticker_task.cancel()

        try:
            await _ticker_task
        except asyncio.CancelledError:
            pass

        _ticker_task = None


def register_dartmarathon(
    app: web.Application,
) -> None:
    SHOP.set_callbacks(
        _broadcast_state,
        _broadcast_payload,
        _shop_event_state,
        _apply_shop_event_action,
    )

    app.router.add_get(
        f"{PREFIX}",
        _root,
    )

    app.router.add_get(
        f"{PREFIX}/control",
        _control,
    )

    app.router.add_post(
        f"{PREFIX}/login",
        _login,
    )

    app.router.add_post(
        f"{PREFIX}/logout",
        _logout,
    )

    app.router.add_get(
        f"{PREFIX}/overlay",
        _overlay,
    )

    app.router.add_get(
        f"{PREFIX}/preview",
        _preview,
    )

    app.router.add_get(
        f"{PREFIX}/ws",
        _ws,
    )

    app.router.add_post(
        f"{PREFIX}/shop/api/import-items",
        _shop_import,
    )

    SHOP.register_routes(app)

    app.router.add_static(
        f"{PREFIX}/static/",
        path=STATIC_DIR,
        name="dartmarathon_static",
    )

    app.cleanup_ctx.append(
        _cleanup_ctx
    )

    print(
        "[DART] Routen registriert: "
        "/dartmarathon/control, "
        "/overlay, /preview, /ws"
    )

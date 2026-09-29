from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from aiohttp import WSMsgType, web

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "dartmarathon_templates"
STATIC_DIR = BASE_DIR / "dartmarathon_static"
STATE_FILE = Path(os.getenv("DARTMARATHON_STATE_FILE", str(BASE_DIR / "dartmarathon_state.json")))
CONTROL_TOKEN = os.getenv("DARTMARATHON_CONTROL_TOKEN", "").strip()

INITIAL_PAUSE_SECONDS = 15 * 60
MAX_PAUSE_SECONDS = 30 * 60
MAX_HISTORY = 10
MAX_UNDO = 50
SAVE_INTERVAL_SECONDS = 3.0
PREFIX = "/dartmarathon"

PLAYERS = ("tzmarty", "korsar")
SPECIAL_CATEGORIES = ("highfinish", "bullfinish", "lowdarts", "score171")

PLAYER_NAMES = {
    "tzmarty": "Tzmarty",
    "korsar": "Korsar",
}

SPECIAL_NAMES = {
    "highfinish": "Highfinish 100+",
    "bullfinish": "Bullfinish",
    "lowdarts": "Low Darts <18",
    "score171": "Score 171+",
}

AD_POPUPS = {
    "foltershop": {"label": "Foltershop", "image": "/dartmarathon/static/ads/foltershop.png", "position": "right"},
    "malteser": {"label": "Malteser", "image": "/dartmarathon/static/ads/malteser.png", "position": "center"},
    "koala": {"label": "KoalaDarts", "image": "/dartmarathon/static/ads/koala.png", "position": "center"},
}

_state_lock = asyncio.Lock()
_clients: set[web.WebSocketResponse] = set()
_ticker_task: asyncio.Task | None = None


def _empty_specials() -> Dict[str, Dict[str, int]]:
    return {
        player: {category: 0 for category in SPECIAL_CATEGORIES}
        for player in PLAYERS
    }


def default_state() -> Dict[str, Any]:
    return {
        "stream_elapsed": 0.0,
        "stream_running": False,
        "stream_started_at": None,
        "pause_seconds": float(INITIAL_PAUSE_SECONDS),
        "pause_active": False,
        "pause_started_at": None,
        "pause_used_seconds": 0.0,
        "legs": {"tzmarty": 0, "korsar": 0},
        "specials": _empty_specials(),
        # Nur eigene Spenden von Tzmarty/Korsar.
        # Zuschauer-Spenden bleiben vollständig bei StreamElements.
        "own_donations": 0.0,
        "event_ended": False,
        "history": [],
        "undo_stack": [],
    }


def _sanitize_state(data: Dict[str, Any]) -> Dict[str, Any]:
    clean = default_state()
    if isinstance(data, dict):
        for key in clean:
            if key in data:
                clean[key] = data[key]

    clean["stream_elapsed"] = max(0.0, float(clean.get("stream_elapsed", 0.0)))
    clean["stream_running"] = bool(clean.get("stream_running", False))
    clean["pause_seconds"] = min(
        MAX_PAUSE_SECONDS,
        max(0.0, float(clean.get("pause_seconds", INITIAL_PAUSE_SECONDS))),
    )
    clean["pause_active"] = bool(clean.get("pause_active", False))
    clean["pause_used_seconds"] = max(0.0, float(clean.get("pause_used_seconds", 0.0)))
    clean["event_ended"] = bool(clean.get("event_ended", False))
    clean["own_donations"] = max(
        0.0,
        round(float(clean.get("own_donations", 0.0)), 2),
    )

    if not isinstance(clean.get("legs"), dict):
        clean["legs"] = {}
    for player in PLAYERS:
        clean["legs"][player] = max(0, int(clean["legs"].get(player, 0)))

    raw_specials = clean.get("specials")
    if not isinstance(raw_specials, dict):
        raw_specials = {}

    new_specials = _empty_specials()

    # Migration der alten Version:
    # Früher gab es Specials nur global pro Kategorie.
    # Damit vorhandene Test-/Bestandswerte nicht verloren gehen,
    # werden diese einmalig Tzmarty zugeordnet.
    old_format = any(category in raw_specials for category in SPECIAL_CATEGORIES)

    if old_format:
        for category in SPECIAL_CATEGORIES:
            new_specials["tzmarty"][category] = max(
                0,
                int(raw_specials.get(category, 0)),
            )
    else:
        for player in PLAYERS:
            player_specials = raw_specials.get(player, {})
            if not isinstance(player_specials, dict):
                player_specials = {}
            for category in SPECIAL_CATEGORIES:
                new_specials[player][category] = max(
                    0,
                    int(player_specials.get(category, 0)),
                )

    clean["specials"] = new_specials
    clean["history"] = list(clean.get("history", []))[-MAX_HISTORY:]
    clean["undo_stack"] = list(clean.get("undo_stack", []))[-MAX_UNDO:]
    return clean


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return default_state()
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return _sanitize_state(raw if isinstance(raw, dict) else {})
    except Exception as exc:
        print(f"[DART] State konnte nicht geladen werden: {exc}")
        return default_state()


def _save_state_locked() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        tmp.write_text(
            json.dumps(_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, STATE_FILE)
    except Exception as exc:
        print(f"[DART] State konnte nicht gespeichert werden: {exc}")


def _now() -> float:
    return time.time()


def _clock(seconds: float, with_hours: bool = False) -> str:
    value = max(0, int(seconds))
    if with_hours:
        h, rem = divmod(value, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    m, s = divmod(value, 60)
    return f"{m:02d}:{s:02d}"


def _add_history_locked(text: str) -> None:
    _state["history"].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "text": text,
    })
    _state["history"] = _state["history"][-MAX_HISTORY:]


def _reconcile_running_timers_locked(save: bool = False) -> None:
    now = _now()
    changed = False

    if _state["stream_running"]:
        started = _state.get("stream_started_at")
        if isinstance(started, (int, float)):
            _state["stream_elapsed"] += max(0.0, now - float(started))
        _state["stream_started_at"] = now
        changed = True

    if _state["pause_active"]:
        started = _state.get("pause_started_at")
        if isinstance(started, (int, float)):
            _state["pause_seconds"] = max(
                0.0,
                _state["pause_seconds"] - max(0.0, now - float(started)),
            )
        _state["pause_started_at"] = now
        changed = True

        if _state["pause_seconds"] <= 0:
            _state["pause_seconds"] = 0.0
            _state["pause_active"] = False
            _state["pause_started_at"] = None
            if not _state["event_ended"]:
                _state["event_ended"] = True
                _add_history_locked("Pausenkonto abgelaufen – Event beendet")
            changed = True

    if changed and save:
        _save_state_locked()


def _snapshot_locked() -> Dict[str, Any]:
    snap = deepcopy(_state)
    snap.pop("undo_stack", None)
    return snap


def _push_undo_locked(label: str) -> None:
    _reconcile_running_timers_locked(save=False)
    _state["undo_stack"].append({
        "label": label,
        "snapshot": _snapshot_locked(),
    })
    _state["undo_stack"] = _state["undo_stack"][-MAX_UNDO:]


def _add_pause_time_locked(seconds: float) -> bool:
    if _state["event_ended"]:
        return False
    _reconcile_running_timers_locked(save=False)
    before = _state["pause_seconds"]
    _state["pause_seconds"] = min(
        MAX_PAUSE_SECONDS,
        max(0.0, before + seconds),
    )
    return _state["pause_seconds"] != before


def _remove_pause_time_locked(seconds: float) -> bool:
    _reconcile_running_timers_locked(save=False)
    before = _state["pause_seconds"]
    _state["pause_seconds"] = max(0.0, before - seconds)

    if _state["pause_active"] and _state["pause_seconds"] <= 0:
        _state["pause_seconds"] = 0.0
        _state["pause_active"] = False
        _state["pause_started_at"] = None
        _state["event_ended"] = True
        _add_history_locked(
            "Pausenkonto durch Korrektur abgelaufen – Event beendet"
        )

    return _state["pause_seconds"] != before


def _player_special_total_locked(player: str) -> int:
    return sum(_state["specials"][player].values())


def _total_specials_locked() -> int:
    return sum(
        _player_special_total_locked(player)
        for player in PLAYERS
    )


def _public_state_locked() -> Dict[str, Any]:
    _reconcile_running_timers_locked(save=False)

    return {
        "stream_seconds": int(_state["stream_elapsed"]),
        "stream_display": _clock(
            _state["stream_elapsed"],
            with_hours=True,
        ),
        "stream_running": _state["stream_running"],
        "pause_seconds": int(_state["pause_seconds"]),
        "pause_display": _clock(_state["pause_seconds"]),
        "pause_active": _state["pause_active"],
        "pause_full": _state["pause_seconds"] >= MAX_PAUSE_SECONDS,
        "pause_used_seconds": int(_state["pause_used_seconds"]),
        "pause_used_display": _clock(_state["pause_used_seconds"], with_hours=True),
        "event_ended": _state["event_ended"],
        "legs": deepcopy(_state["legs"]),
        "total_legs": total_legs,
        "specials": deepcopy(_state["specials"]),
        "player_special_totals": {
            player: _player_special_total_locked(player)
            for player in PLAYERS
        },
        "total_specials": total_specials,
        "legs_per_hour": round(legs_per_hour, 1),
        "specials_per_hour": round(specials_per_hour, 1),
        "own_donations": round(_state["own_donations"], 2),
        "history": deepcopy(_state["history"]),
        "can_undo": bool(_state["undo_stack"]),
    }


def _token_matches(value: str | None) -> bool:
    if not CONTROL_TOKEN:
        return True
    if not value:
        return False
    return secrets.compare_digest(value, CONTROL_TOKEN)


def _request_can_control(request: web.Request) -> bool:
    return _token_matches(request.cookies.get("dart_control"))


_state = _load_state()
_reconcile_running_timers_locked(save=True)


async def _broadcast_payload(payload: Dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False)
    dead: list[web.WebSocketResponse] = []
    for ws in list(_clients):
        if ws.closed:
            dead.append(ws)
            continue
        try:
            await ws.send_str(encoded)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


async def _broadcast_state() -> None:
    async with _state_lock:
        payload = json.dumps(
            {
                "type": "state",
                "data": _public_state_locked(),
            },
            ensure_ascii=False,
        )

    dead: list[web.WebSocketResponse] = []

    for ws in list(_clients):
        if ws.closed:
            dead.append(ws)
            continue
        try:
            await ws.send_str(payload)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _clients.discard(ws)


async def _mutate(label: str, fn) -> bool:
    async with _state_lock:
        _push_undo_locked(label)
        changed = fn()

        if changed is False:
            _state["undo_stack"].pop()
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

    msg_type = message.get("type")

    if msg_type == "stream_action":
        action = message.get("action")

        if action == "start":
            def fn():
                if _state["stream_running"]:
                    return False
                _state["stream_running"] = True
                _state["stream_started_at"] = _now()
                return True

            await _mutate("Streamlaufzeit gestartet", fn)

        elif action == "stop":
            def fn():
                if not _state["stream_running"]:
                    return False
                _reconcile_running_timers_locked(save=False)
                _state["stream_running"] = False
                _state["stream_started_at"] = None
                return True

            await _mutate("Streamlaufzeit gestoppt", fn)

        elif action == "reset":
            def fn():
                _reconcile_running_timers_locked(save=False)

                if (
                    _state["stream_elapsed"] <= 0
                    and not _state["stream_running"]
                ):
                    return False

                _state["stream_elapsed"] = 0.0
                _state["stream_running"] = False
                _state["stream_started_at"] = None
                return True

            await _mutate("Streamlaufzeit zurückgesetzt", fn)

        return

    if msg_type == "pause_action":
        action = message.get("action")

        if action == "start":
            def fn():
                _reconcile_running_timers_locked(save=False)

                if (
                    _state["pause_active"]
                    or _state["event_ended"]
                    or _state["pause_seconds"] <= 0
                ):
                    return False

                _state["pause_active"] = True
                _state["pause_started_at"] = _now()
                return True

            await _mutate("Pause gestartet", fn)

        elif action == "stop":
            def fn():
                if not _state["pause_active"]:
                    return False

                _reconcile_running_timers_locked(save=False)
                _state["pause_active"] = False
                _state["pause_started_at"] = None
                return True

            await _mutate("Pause gestoppt", fn)

        elif action == "reset":
            def fn():
                _state["pause_seconds"] = float(INITIAL_PAUSE_SECONDS)
                _state["pause_active"] = False
                _state["pause_started_at"] = None
                _state["event_ended"] = False
                return True

            await _mutate(
                "Pausenkonto auf 15:00 zurückgesetzt",
                fn,
            )

        elif action == "unlock":
            def fn():
                if not _state["event_ended"]:
                    return False

                _state["event_ended"] = False
                _state["pause_active"] = False
                _state["pause_started_at"] = None
                return True

            await _mutate(
                "Event manuell wieder freigegeben",
                fn,
            )

        return

    if msg_type == "pause_adjust":
        try:
            seconds = int(message.get("seconds", 0))
        except (TypeError, ValueError):
            return

        if seconds == 0 or abs(seconds) > MAX_PAUSE_SECONDS:
            return

        def fn():
            if _state["event_ended"] and seconds > 0:
                return False

            if seconds > 0:
                return _add_pause_time_locked(seconds)

            if _state["pause_seconds"] <= 0:
                return False

            return _remove_pause_time_locked(abs(seconds))

        sign = "+" if seconds > 0 else ""

        await _mutate(
            f"Pausenkonto manuell {sign}{seconds} Sek.",
            fn,
        )
        return

    if msg_type == "leg_adjust":
        player = message.get("player")

        try:
            delta = int(message.get("delta", 0))
        except (TypeError, ValueError):
            return

        if player not in PLAYERS or delta not in (-1, 1):
            return

        player_name = PLAYER_NAMES[player]

        def fn():
            if _state["event_ended"]:
                return False

            if delta > 0:
                _state["legs"][player] += 1
                _add_pause_time_locked(30)
                return True

            if _state["legs"][player] <= 0:
                return False

            _state["legs"][player] -= 1
            _remove_pause_time_locked(30)
            return True

        await _mutate(
            f"{player_name}: Leg {'+' if delta > 0 else '-'}1",
            fn,
        )
        return

    if msg_type == "special_adjust":
        player = message.get("player")
        category = message.get("category")

        try:
            delta = int(message.get("delta", 0))
        except (TypeError, ValueError):
            return

        if (
            player not in PLAYERS
            or category not in SPECIAL_CATEGORIES
            or delta not in (-1, 1)
        ):
            return

        def fn():
            if _state["event_ended"]:
                return False

            if delta > 0:
                _state["specials"][player][category] += 1
                _add_pause_time_locked(60)
                return True

            if _state["specials"][player][category] <= 0:
                return False

            _state["specials"][player][category] -= 1
            _remove_pause_time_locked(60)
            return True

        await _mutate(
            (
                f"{PLAYER_NAMES[player]}: "
                f"{SPECIAL_NAMES[category]} "
                f"{'+' if delta > 0 else '-'}1"
            ),
            fn,
        )
        return

    if msg_type == "donation_adjust":
        try:
            amount = round(float(message.get("amount", 0)), 2)
        except (TypeError, ValueError):
            return

        if (
            amount == 0
            or abs(amount) > 10000
            or _state["event_ended"]
        ):
            return

        actual_amount = amount

        if amount < 0:
            actual_amount = -min(
                abs(amount),
                _state["own_donations"],
            )
            if actual_amount == 0:
                return

        def fn():
            _state["own_donations"] = round(
                _state["own_donations"] + actual_amount,
                2,
            )

            if actual_amount > 0:
                _add_pause_time_locked(
                    actual_amount * 60
                )
            else:
                _remove_pause_time_locked(
                    abs(actual_amount) * 60
                )

            return True

        sign = "+" if actual_amount > 0 else ""

        await _mutate(
            f"Eigene Spende {sign}{actual_amount:.2f} €",
            fn,
        )
        return

    if msg_type == "ad_popup":
        sponsor = str(message.get("sponsor", "")).lower()
        if sponsor not in AD_POPUPS:
            return
        ad = AD_POPUPS[sponsor]
        await _broadcast_payload({
            "type": "ad_popup",
            "sponsor": sponsor,
            "label": ad["label"],
            "image": ad["image"],
            "position": ad["position"],
            "duration_ms": 20000,
        })
        async with _state_lock:
            _add_history_locked(f"Werbeeinblendung: {ad['label']}")
            _save_state_locked()
        await _broadcast_state()
        return

    if msg_type == "undo":
        async with _state_lock:
            _reconcile_running_timers_locked(save=False)

            if not _state["undo_stack"]:
                await ws.send_json({
                    "type": "error",
                    "message": (
                        "Keine Aktion zum Rückgängigmachen vorhanden."
                    ),
                })
                return

            item = _state["undo_stack"].pop()
            remaining_stack = deepcopy(_state["undo_stack"])
            restored = deepcopy(item["snapshot"])
            restored["undo_stack"] = remaining_stack
            _state = restored

            _add_history_locked(
                f"Rückgängig: {item['label']}"
            )
            _save_state_locked()

        await _broadcast_state()
        return

    if msg_type == "full_reset":
        async with _state_lock:
            _state = default_state()
            _add_history_locked(
                "Gesamtes Event zurückgesetzt"
            )
            _save_state_locked()

        await _broadcast_state()
        return


async def _serve_template(name: str) -> web.Response:
    path = TEMPLATE_DIR / name

    if not path.exists():
        raise web.HTTPNotFound()

    return web.Response(
        text=path.read_text(encoding="utf-8"),
        content_type="text/html",
    )


async def _control(request: web.Request) -> web.StreamResponse:
    if not CONTROL_TOKEN or _request_can_control(request):
        return await _serve_template("control.html")

    token = request.query.get("token", "")

    if _token_matches(token):
        response = web.HTTPFound(f"{PREFIX}/control")
        response.set_cookie(
            "dart_control",
            token,
            httponly=True,
            samesite="Lax",
            secure=request.secure,
            max_age=60 * 60 * 24 * 30,
        )
        return response

    return await _serve_template("login.html")


async def _login(request: web.Request) -> web.StreamResponse:
    data = await request.post()
    token = str(data.get("token", ""))

    if not _token_matches(token):
        html = (
            TEMPLATE_DIR / "login.html"
        ).read_text(encoding="utf-8")
        html = html.replace(
            "<!--LOGIN_ERROR-->",
            '<div class="login-error">Token nicht korrekt.</div>',
        )
        return web.Response(
            text=html,
            content_type="text/html",
            status=403,
        )

    response = web.HTTPFound(f"{PREFIX}/control")
    response.set_cookie(
        "dart_control",
        token,
        httponly=True,
        samesite="Lax",
        secure=request.secure,
        max_age=60 * 60 * 24 * 30,
    )
    return response


async def _logout(
    request: web.Request,
) -> web.StreamResponse:
    response = web.HTTPFound(f"{PREFIX}/control")
    response.del_cookie("dart_control")
    return response


async def _root(
    _request: web.Request,
) -> web.StreamResponse:
    raise web.HTTPFound(f"{PREFIX}/control")


async def _overlay(
    _request: web.Request,
) -> web.Response:
    return await _serve_template("overlay.html")


async def _preview(
    _request: web.Request,
) -> web.Response:
    return await _serve_template("preview.html")


async def _ws(
    request: web.Request,
) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)

    can_control = _request_can_control(request)
    _clients.add(ws)

    async with _state_lock:
        await ws.send_json({
            "type": "state",
            "data": _public_state_locked(),
            "can_control": can_control,
        })

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    message = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                if not can_control:
                    await ws.send_json({
                        "type": "error",
                        "message": (
                            "Control-Zugriff nicht autorisiert."
                        ),
                    })
                    continue

                await _process_message(
                    ws,
                    message,
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


async def _ticker() -> None:
    last_save = 0.0

    try:
        while True:
            await asyncio.sleep(0.25)

            async with _state_lock:
                _reconcile_running_timers_locked(
                    save=False
                )

                now = _now()

                if (
                    now - last_save
                    >= SAVE_INTERVAL_SECONDS
                ):
                    _save_state_locked()
                    last_save = now

            await _broadcast_state()

    except asyncio.CancelledError:
        async with _state_lock:
            _save_state_locked()
        raise


async def _cleanup_ctx(
    _app: web.Application,
):
    global _ticker_task

    _ticker_task = asyncio.create_task(
        _ticker(),
        name="dartmarathon-ticker",
    )

    print("[DART] Dartmarathon-Ticker gestartet")

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
    """Registriert alle Dartmarathon-Routen im vorhandenen aiohttp-Webserver."""

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
    app.router.add_static(
        f"{PREFIX}/static/",
        path=STATIC_DIR,
        name="dartmarathon_static",
    )

    app.cleanup_ctx.append(_cleanup_ctx)

    print(
        "[DART] Routen registriert: "
        "/dartmarathon/control, /overlay, /preview, /ws"
    )

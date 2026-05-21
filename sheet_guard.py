# sheet_guard.py
from __future__ import annotations

import os
import random
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

try:
    from gspread.exceptions import APIError
except Exception:  # fallback, falls gspread beim Import noch nicht verfügbar ist
    APIError = Exception


# =========================================================
# ZENTRALER GOOGLE-SHEETS-SCHUTZ
# =========================================================

SHEET_GUARD_VERSION = "sheet-guard-optimized-v1"
print(f"[SHEET_GUARD] geladen: {SHEET_GUARD_VERSION}")


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    """
    Liest Integer-Werte aus ENV robust ein.
    Ungültige Werte fallen auf den Default zurück.
    """
    raw = os.getenv(name, "").strip()

    if raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except Exception:
            value = default

    if minimum is not None:
        value = max(minimum, value)

    if maximum is not None:
        value = min(maximum, value)

    return value


@dataclass
class CacheEntry:
    created_at: float
    value: Any


_CACHE: dict[str, CacheEntry] = {}

# Wenn Google 429 liefert, blocken wir weitere echte Reads kurz.
_QUOTA_COOLDOWN_UNTIL = 0.0
_LAST_QUOTA_LOG_AT = 0.0

# Per Render-ENV steuerbar.
# Ziel: weniger echte Sheet-Reads, weniger Retry-Druck bei 429, stabilere Ladezeiten.
DEFAULT_READ_TTL_SECONDS = _env_int("SHEET_GUARD_READ_TTL_SECONDS", 90, minimum=0, maximum=3600)
DEFAULT_WRITE_RETRIES = _env_int("SHEET_GUARD_WRITE_RETRIES", 2, minimum=0, maximum=10)
DEFAULT_READ_RETRIES = _env_int("SHEET_GUARD_READ_RETRIES", 2, minimum=0, maximum=10)
DEFAULT_QUOTA_COOLDOWN_SECONDS = _env_int("SHEET_GUARD_QUOTA_COOLDOWN_SECONDS", 60, minimum=5, maximum=600)
DEFAULT_RETRY_MAX_SLEEP_SECONDS = _env_int("SHEET_GUARD_RETRY_MAX_SLEEP_SECONDS", 8, minimum=1, maximum=60)
DEFAULT_CACHE_MAX_ENTRIES = _env_int("SHEET_GUARD_CACHE_MAX_ENTRIES", 300, minimum=50, maximum=5000)


def _now() -> float:
    return time.time()


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "quota exceeded" in text
        or "too many requests" in text
        or "rate limit" in text
    )


def _set_quota_cooldown(seconds: int | None = None):
    global _QUOTA_COOLDOWN_UNTIL
    selected_seconds = seconds if seconds is not None else DEFAULT_QUOTA_COOLDOWN_SECONDS
    _QUOTA_COOLDOWN_UNTIL = max(_QUOTA_COOLDOWN_UNTIL, _now() + selected_seconds)


def is_quota_cooldown_active() -> bool:
    return _now() < _QUOTA_COOLDOWN_UNTIL


def seconds_until_quota_retry() -> int:
    if not is_quota_cooldown_active():
        return 0
    return max(0, int(_QUOTA_COOLDOWN_UNTIL - _now()))


def should_log_quota_warning(interval_seconds: int = 60) -> bool:
    """
    Verhindert Discord-/Console-Spam.
    Gibt nur alle X Sekunden True zurück.
    """
    global _LAST_QUOTA_LOG_AT
    now = _now()
    if now - _LAST_QUOTA_LOG_AT >= interval_seconds:
        _LAST_QUOTA_LOG_AT = now
        return True
    return False


def invalidate_cache(key_prefix: str | None = None):
    """
    key_prefix=None: alles löschen
    key_prefix="records:Schedule": nur passende Keys löschen
    """
    if key_prefix is None:
        _CACHE.clear()
        return

    for key in list(_CACHE.keys()):
        if key.startswith(key_prefix):
            _CACHE.pop(key, None)


def _prune_cache_if_needed():
    """
    Verhindert, dass der Prozess bei vielen dynamischen Keys unnötig Cache ansammelt.
    Entfernt die ältesten Einträge, wenn das Limit überschritten wird.
    """
    if len(_CACHE) <= DEFAULT_CACHE_MAX_ENTRIES:
        return

    overflow = len(_CACHE) - DEFAULT_CACHE_MAX_ENTRIES
    oldest_keys = sorted(_CACHE.keys(), key=lambda key: _CACHE[key].created_at)[:overflow]

    for key in oldest_keys:
        _CACHE.pop(key, None)


def get_cache_value(key: str, ttl_seconds: int):
    if ttl_seconds <= 0:
        _CACHE.pop(key, None)
        return None

    entry = _CACHE.get(key)
    if not entry:
        return None

    if _now() - entry.created_at > ttl_seconds:
        _CACHE.pop(key, None)
        return None

    return deepcopy(entry.value)


def set_cache_value(key: str, value: Any):
    _CACHE[key] = CacheEntry(created_at=_now(), value=deepcopy(value))
    _prune_cache_if_needed()


def _sleep_for_retry(attempt: int):
    # Exponential Backoff mit Jitter, aber bewusst gedeckelt.
    base = min(2 ** attempt, DEFAULT_RETRY_MAX_SLEEP_SECONDS)
    jitter = random.uniform(0.1, 0.7)
    time.sleep(base + jitter)


def run_sheet_call(
    func: Callable[[], Any],
    *,
    retries: int = DEFAULT_READ_RETRIES,
    allow_stale_on_quota: bool = False,
    stale_cache_key: str | None = None,
):
    """
    Zentraler Wrapper für echte Google-Sheets-Calls.

    - Fängt 429 ab
    - setzt globalen Cooldown
    - macht Exponential Backoff
    - kann bei 429 alte Cache-Daten zurückgeben
    """
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc

            if not _is_quota_error(exc):
                raise

            _set_quota_cooldown()

            if allow_stale_on_quota and stale_cache_key:
                entry = _CACHE.get(stale_cache_key)
                if entry is not None:
                    return deepcopy(entry.value)

            if attempt >= retries:
                raise

            _sleep_for_retry(attempt)

    if last_exc:
        raise last_exc

    raise RuntimeError("Unbekannter Fehler in run_sheet_call().")


def get_all_records_cached(
    worksheet_getter: Callable[[], Any],
    *,
    sheet_name: str,
    ttl_seconds: int = DEFAULT_READ_TTL_SECONDS,
    force_refresh: bool = False,
):
    cache_key = f"records:{sheet_name}"

    if not force_refresh:
        cached = get_cache_value(cache_key, ttl_seconds)
        if cached is not None:
            return cached

    if is_quota_cooldown_active():
        entry = _CACHE.get(cache_key)
        if entry is not None:
            return deepcopy(entry.value)

    def call():
        return worksheet_getter().get_all_records()

    rows = run_sheet_call(
        call,
        retries=DEFAULT_READ_RETRIES,
        allow_stale_on_quota=True,
        stale_cache_key=cache_key,
    )
    set_cache_value(cache_key, rows)
    return deepcopy(rows)


def get_all_values_cached(
    worksheet_getter: Callable[[], Any],
    *,
    sheet_name: str,
    ttl_seconds: int = DEFAULT_READ_TTL_SECONDS,
    force_refresh: bool = False,
):
    cache_key = f"values:{sheet_name}"

    if not force_refresh:
        cached = get_cache_value(cache_key, ttl_seconds)
        if cached is not None:
            return cached

    if is_quota_cooldown_active():
        entry = _CACHE.get(cache_key)
        if entry is not None:
            return deepcopy(entry.value)

    def call():
        return worksheet_getter().get_all_values()

    values = run_sheet_call(
        call,
        retries=DEFAULT_READ_RETRIES,
        allow_stale_on_quota=True,
        stale_cache_key=cache_key,
    )
    set_cache_value(cache_key, values)
    return deepcopy(values)


def row_values_cached(
    worksheet_getter: Callable[[], Any],
    *,
    sheet_name: str,
    row: int,
    ttl_seconds: int = DEFAULT_READ_TTL_SECONDS,
):
    cache_key = f"row:{sheet_name}:{row}"

    cached = get_cache_value(cache_key, ttl_seconds)
    if cached is not None:
        return cached

    if is_quota_cooldown_active():
        entry = _CACHE.get(cache_key)
        if entry is not None:
            return deepcopy(entry.value)

    def call():
        return worksheet_getter().row_values(row)

    values = run_sheet_call(
        call,
        retries=DEFAULT_READ_RETRIES,
        allow_stale_on_quota=True,
        stale_cache_key=cache_key,
    )
    set_cache_value(cache_key, values)
    return deepcopy(values)


def col_values_cached(
    worksheet_getter: Callable[[], Any],
    *,
    sheet_name: str,
    col: int,
    ttl_seconds: int = DEFAULT_READ_TTL_SECONDS,
):
    cache_key = f"col:{sheet_name}:{col}"

    cached = get_cache_value(cache_key, ttl_seconds)
    if cached is not None:
        return cached

    if is_quota_cooldown_active():
        entry = _CACHE.get(cache_key)
        if entry is not None:
            return deepcopy(entry.value)

    def call():
        return worksheet_getter().col_values(col)

    values = run_sheet_call(
        call,
        retries=DEFAULT_READ_RETRIES,
        allow_stale_on_quota=True,
        stale_cache_key=cache_key,
    )
    set_cache_value(cache_key, values)
    return deepcopy(values)


def acell_cached(
    worksheet_getter: Callable[[], Any],
    *,
    sheet_name: str,
    cell: str,
    ttl_seconds: int = DEFAULT_READ_TTL_SECONDS,
):
    cache_key = f"cell:{sheet_name}:{cell}"

    cached = get_cache_value(cache_key, ttl_seconds)
    if cached is not None:
        return cached

    if is_quota_cooldown_active():
        entry = _CACHE.get(cache_key)
        if entry is not None:
            return deepcopy(entry.value)

    def call():
        return worksheet_getter().acell(cell).value

    value = run_sheet_call(
        call,
        retries=DEFAULT_READ_RETRIES,
        allow_stale_on_quota=True,
        stale_cache_key=cache_key,
    )
    set_cache_value(cache_key, value)
    return value


def sheet_write_call(func: Callable[[], Any], *, invalidate_prefixes: list[str] | None = None):
    """
    Zentraler Wrapper für Writes.
    Danach betroffene Caches invalidieren.
    """
    result = run_sheet_call(func, retries=DEFAULT_WRITE_RETRIES)

    for prefix in invalidate_prefixes or []:
        invalidate_cache(prefix)

    return result

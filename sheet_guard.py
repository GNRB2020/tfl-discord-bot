# sheet_guard.py
from __future__ import annotations

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

@dataclass
class CacheEntry:
    created_at: float
    value: Any


_CACHE: dict[str, CacheEntry] = {}

# Wenn Google 429 liefert, blocken wir weitere echte Reads kurz.
_QUOTA_COOLDOWN_UNTIL = 0.0
_LAST_QUOTA_LOG_AT = 0.0

DEFAULT_READ_TTL_SECONDS = 30
DEFAULT_WRITE_RETRIES = 4
DEFAULT_READ_RETRIES = 4


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


def _set_quota_cooldown(seconds: int = 60):
    global _QUOTA_COOLDOWN_UNTIL
    _QUOTA_COOLDOWN_UNTIL = max(_QUOTA_COOLDOWN_UNTIL, _now() + seconds)


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


def get_cache_value(key: str, ttl_seconds: int):
    entry = _CACHE.get(key)
    if not entry:
        return None

    if _now() - entry.created_at > ttl_seconds:
        _CACHE.pop(key, None)
        return None

    return deepcopy(entry.value)


def set_cache_value(key: str, value: Any):
    _CACHE[key] = CacheEntry(created_at=_now(), value=deepcopy(value))


def _sleep_for_retry(attempt: int):
    # Exponential Backoff mit Jitter, aber bewusst gedeckelt.
    base = min(2 ** attempt, 16)
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

            _set_quota_cooldown(60)

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

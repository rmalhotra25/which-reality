"""
Persistent scan cache for slow scanners (dividend path, CEF).

Why this exists: the dividend-path and CEF scanners used to cache their
results in /tmp (cache_dividend_path.json, 6-hour TTL; cache_cef_scan.json,
4-hour TTL). Render wipes /tmp on every redeploy, restart, and spin-down,
so after a deploy the cache was empty and both Income tab endpoints ran a
full live scan synchronously, fetching dozens of tickers through yfinance
and timing out at 25 seconds (Oct 27 2026). The Income tab then crashed
on the null dividend data.

This cache stores the same JSON payloads in the app database instead:
Postgres on Render (DATABASE_URL), SQLite locally. The table survives
redeploys. If the database is unavailable, it falls back to the old /tmp
file so local development still works, and logs a warning.

Keys are namespaced per scan, e.g. "dividend_path:61000:500" and "cef_scan".
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scan_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    cached_at DOUBLE PRECISION NOT NULL
)
"""

_KEY_RE = re.compile(r"[^A-Za-z0-9_:\-.]")


def _file_path(key: str) -> str:
    safe = _KEY_RE.sub("_", key)
    return os.path.join("/tmp", f"scan_cache_{safe}.json")


def _db_get(key: str):
    from database import engine
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text(_TABLE_SQL))
        conn.commit()
        row = conn.execute(
            text("SELECT payload, cached_at FROM scan_cache WHERE cache_key = :k"),
            {"k": key},
        ).fetchone()
    if not row:
        return None
    return {"payload": json.loads(row[0]), "cached_at": float(row[1])}


def _db_set(key: str, payload: dict) -> None:
    from database import engine
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text(_TABLE_SQL))
        conn.execute(
            text(
                "INSERT INTO scan_cache (cache_key, payload, cached_at)"
                " VALUES (:k, :p, :t)"
                " ON CONFLICT (cache_key) DO UPDATE"
                " SET payload = EXCLUDED.payload, cached_at = EXCLUDED.cached_at"
            ),
            {"k": key, "p": json.dumps(payload), "t": time.time()},
        )
        conn.commit()


def _file_get(key: str):
    path = _file_path(key)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return {"payload": data, "cached_at": float(data.get("cached_at", 0))}


def _file_set(key: str, payload: dict) -> None:
    data = dict(payload)
    data["cached_at"] = time.time()
    with open(_file_path(key), "w") as f:
        json.dump(data, f)


def get_cache(key: str, ttl_seconds: float) -> dict | None:
    """Return the cached payload for key if it is younger than ttl, else None."""
    try:
        entry = _db_get(key)
        source = "database"
    except Exception as e:
        logger.warning("scan_cache DB read failed for %s, using /tmp fallback: %s", key, e)
        try:
            entry = _file_get(key)
        except Exception:
            return None
        source = "file"
    if not entry:
        return None
    if time.time() - entry["cached_at"] > ttl_seconds:
        return None
    payload = entry["payload"]
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.setdefault("cached_at", entry["cached_at"])
        payload.setdefault("cache_source", source)
    return payload


def set_cache(key: str, payload: dict) -> None:
    """Store payload for key, stamping it with the current time."""
    data = dict(payload)
    data["cached_at"] = time.time()
    try:
        _db_set(key, data)
    except Exception as e:
        logger.warning("scan_cache DB write failed for %s, using /tmp fallback: %s", key, e)
        try:
            _file_set(key, data)
        except Exception as write_err:
            logger.warning("scan_cache file write failed for %s: %s", key, write_err)

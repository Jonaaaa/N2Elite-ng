"""Amiibo identification: map an NTAG215 dump to its amiibo (name/series/type).

The 8-byte amiibo model ID lives at tag offset 0x54 (big-endian) in the
*unencrypted* region, so identification needs no keys. The bundled database
(amiibo_db.json) is public amiibo metadata (from amiiboapi.org / the 8bitDream
AmiiboAPI fork) — no keys, no copyrighted tag data. Fully offline.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

AMIIBO_ID_OFFSET = 0x54
AMIIBO_ID_LENGTH = 8

# The bundled snapshot ships with the app; an optional user override (downloaded
# via `n2elite sync`) takes precedence when present, so identification data can be
# refreshed without a new release. Both are plain offline JSON — no keys.
_BUNDLED_DB = os.path.join(os.path.dirname(__file__), "amiibo_db.json")
_USER_DB = Path(os.path.expanduser("~")) / ".n2elite" / "amiibo_db.json"


def user_db_path() -> Path:
    """Where a downloaded database override is stored."""
    return _USER_DB


def _db_path() -> str:
    return str(_USER_DB) if _USER_DB.is_file() else _BUNDLED_DB


@lru_cache(maxsize=1)
def _db() -> dict[str, dict]:
    try:
        with open(_db_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def reload() -> None:
    """Drop the cached database (call after downloading a new one)."""
    _db.cache_clear()


def all_ids() -> list[str]:
    """All amiibo IDs known to the active database."""
    return list(_db().keys())


def amiibo_id(dump: bytes) -> str:
    """Return the amiibo model ID as '0x%016x' (lowercase) from a dump."""
    if len(dump) < AMIIBO_ID_OFFSET + AMIIBO_ID_LENGTH:
        raise ValueError("dump too small to contain an amiibo id")
    raw = dump[AMIIBO_ID_OFFSET:AMIIBO_ID_OFFSET + AMIIBO_ID_LENGTH]
    return "0x%016x" % int.from_bytes(raw, "big")


def info_for_id(amiibo_id_hex: str) -> dict | None:
    """Full record {name, character, series, game, type} for an ID, or None."""
    return _db().get(amiibo_id_hex.lower())


def identify(dump: bytes) -> tuple[str, str | None]:
    """Return (amiibo_id_hex, name_or_None) for a dump."""
    aid = amiibo_id(dump)
    rec = info_for_id(aid)
    return aid, (rec.get("name") if rec else None)


def info(dump: bytes) -> tuple[str, dict | None]:
    """Return (amiibo_id_hex, full_record_or_None) for a dump."""
    aid = amiibo_id(dump)
    return aid, info_for_id(aid)


def describe(dump: bytes) -> str:
    """One-line human description, e.g. 'Link - Archer (Legend Of Zelda, Figure)'."""
    aid, rec = info(dump)
    if is_blank(dump):
        return "(blank / uninitialised tag)"
    if not rec:
        return f"(unknown amiibo {aid})"
    extra = ", ".join(x for x in (rec.get("series"), rec.get("type")) if x)
    return f"{rec.get('name', aid)}" + (f" ({extra})" if extra else "")


_EMPTY_IDS = (b"\x00" * 8, b"\xff" * 8)


def is_empty_id(amiibo_id_hex: str) -> bool:
    """True for the empty/uninitialised amiibo IDs (all 00 or all FF)."""
    s = amiibo_id_hex.lower().removeprefix("0x")
    return s in ("0000000000000000", "ffffffffffffffff")


def is_blank(dump: bytes) -> bool:
    """True if the bank/tag has no amiibo (id is all zeros or all 0xFF)."""
    return dump[AMIIBO_ID_OFFSET:AMIIBO_ID_OFFSET + AMIIBO_ID_LENGTH] in _EMPTY_IDS

"""Optional offline-data downloads (opt-in; online only while running).

Two helpers that let n2elite-ng run fully offline afterwards:
  * download_database() — fetch the latest AmiiboAPI metadata and rebuild the
    local amiibo database (names/series/character/type) used for identification.
  * download_all_images() — pre-cache every amiibo figure image so the
    "Show image" feature works with no network access.

Same safety posture as images.py: HTTPS + certificate validation, fixed public
hosts, per-response size caps, timeouts, and content validation (JSON parse for
the database, PNG-magic for images). Nothing is ever uploaded — only public
amiibo metadata/artwork is downloaded, keyed by amiibo ID.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import database, images


def human_bytes(n: float) -> str:
    """Human-readable size, e.g. 1536 -> '1.5 KB'."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"

# Full AmiiboAPI metadata (8bitDream fork — the same public source as the images).
_DB_URL = "https://raw.githubusercontent.com/8bitDream/AmiiboAPI/master/database/amiibo.json"
_DB_MAX_BYTES = 16_000_000  # generous cap; the file is ~200 KB
_TIMEOUT = 20
_MAX_WORKERS = 8  # be gentle on the public host


def _fetch_bytes(url: str, max_bytes: int) -> bytes:
    """HTTPS GET with cert validation, timeout, and a hard size cap."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "n2elite-ng"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            if getattr(resp, "status", 200) != 200:
                raise OSError(f"download failed (HTTP {resp.status})")
            data = resp.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise OSError(f"download failed: {e}") from e
    if len(data) > max_bytes:
        raise OSError("download exceeds size limit")
    return data


def _norm_id(fid: str) -> str:
    return "0x" + fid.lower().removeprefix("0x").rjust(16, "0")


def _transform(full: dict) -> dict:
    """Rebuild our compact {id: {name,character,game,series,type}} database from
    the full AmiiboAPI schema. Validated to reproduce the bundled DB exactly.

    The 16-hex amiibo ID encodes its own metadata keys:
      [0:4] character  [0:3] game series  [6:8] figure type  [12:14] amiibo series
    """
    amiibos = full.get("amiibos", {})
    chars = full.get("characters", {})
    games = full.get("game_series", {})
    types = full.get("types", {})
    series = full.get("amiibo_series", {})
    out: dict[str, dict] = {}
    for fid, rec in amiibos.items():
        s = _norm_id(fid)[2:]
        out[_norm_id(fid)] = {
            "name": rec.get("name"),
            "character": chars.get("0x" + s[0:4]),
            "game": games.get("0x" + s[0:3]),
            "series": series.get("0x" + s[12:14]),
            "type": types.get("0x" + s[6:8]),
        }
    return out


def download_database(dest: str | os.PathLike | None = None) -> int:
    """Fetch the latest AmiiboAPI metadata and write the local database override.

    Writes to ``~/.n2elite/amiibo_db.json`` (preferred over the bundled snapshot).
    Returns the number of amiibo written. Raises OSError/ValueError on failure.
    """
    data = _fetch_bytes(_DB_URL, _DB_MAX_BYTES)
    full = json.loads(data.decode("utf-8"))  # ValueError on malformed JSON
    if not isinstance(full, dict) or "amiibos" not in full:
        raise ValueError("unexpected amiibo database format")
    compact = _transform(full)
    if not compact:
        raise ValueError("amiibo database came back empty")
    path = Path(dest) if dest else database.user_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(compact, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")
    tmp.replace(path)  # atomic
    database.reload()
    return len(compact)


def all_amiibo_ids() -> list[str]:
    """Every real amiibo ID in the local database (excludes empty/blank IDs)."""
    return [k for k in database.all_ids() if not database.is_empty_id(k)]


def download_all_images(ids=None, on_progress=None, workers: int = 6) -> dict:
    """Pre-cache amiibo images for offline use. Bounded concurrency; skips ones
    already cached; each fetch is the hardened images.fetch_image (HTTPS, cert,
    size cap, PNG validation, atomic write).

    ``on_progress(done, total, ok, failed, bytes_downloaded, speed_bytes_per_s)``
    is called after each image. Returns
    ``{"total", "ok", "skipped", "failed", "bytes", "seconds"}``. Some IDs
    legitimately have no artwork upstream (404) and count as ``failed`` without
    raising.
    """
    if ids is None:
        ids = all_amiibo_ids()
    total = len(ids)
    todo = [a for a in ids if images.cached_image(a) is None]
    skipped = total - len(todo)
    ok = 0
    failed = 0
    done = skipped
    nbytes = 0
    start = time.monotonic()

    def emit():
        if on_progress:
            elapsed = max(1e-6, time.monotonic() - start)
            on_progress(done, total, ok, failed, nbytes, nbytes / elapsed)

    emit()
    workers = max(1, min(int(workers), _MAX_WORKERS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(images.fetch_image, a): a for a in todo}
        for fut in concurrent.futures.as_completed(futures):
            try:
                path = fut.result()
                ok += 1
                try:
                    nbytes += path.stat().st_size
                except OSError:
                    pass
            except OSError:
                failed += 1  # e.g. 404 = no artwork for this amiibo — expected
            done += 1
            emit()
    return {"total": total, "ok": ok, "skipped": skipped, "failed": failed,
            "bytes": nbytes, "seconds": time.monotonic() - start}

"""Optional amiibo figure images — an opt-in network feature (see also sync.py).

Disabled by default: an image is fetched only when the user explicitly asks
(e.g. clicks "Show image") or runs an offline-data download. Images are public
amiibo product icons keyed by the 8-byte amiibo ID (from AmiiboAPI), cached
locally so each is fetched at most once. No personal data is ever sent — only a
GET for a public icon by amiibo ID.

Safety: HTTPS with certificate validation, fixed host, short timeout, response
size cap, and PNG-magic validation before the file is written.
"""
from __future__ import annotations

import os
import ssl
import urllib.request
from pathlib import Path

# Fixed, public source (the 8bitDream AmiiboAPI fork used by amiiboapi.org).
# {head}/{tail} are 8 hex digits each of the amiibo ID.
_IMG_URL = "https://raw.githubusercontent.com/8bitDream/AmiiboAPI/master/images/icon_{head}-{tail}.png"
_MAX_BYTES = 2_000_000  # 2 MB cap — icons are ~100-200 KB
_TIMEOUT = 15

_DEFAULT_CACHE_DIR = Path(os.path.expanduser("~")) / ".n2elite" / "images"
_cache_dir = _DEFAULT_CACHE_DIR


def set_cache_dir(path: str | os.PathLike) -> None:
    """Choose where fetched amiibo images are cached."""
    global _cache_dir
    _cache_dir = Path(path)


def cache_dir() -> Path:
    return _cache_dir


def _id_int(amiibo_id_hex: str) -> int:
    return int(amiibo_id_hex, 16) & 0xFFFFFFFFFFFFFFFF


def image_url(amiibo_id_hex: str) -> str:
    v = _id_int(amiibo_id_hex)
    return _IMG_URL.format(head=f"{(v >> 32) & 0xFFFFFFFF:08x}", tail=f"{v & 0xFFFFFFFF:08x}")


def cache_path(amiibo_id_hex: str) -> Path:
    return _cache_dir / f"{_id_int(amiibo_id_hex):016x}.png"


def cached_image(amiibo_id_hex: str) -> Path | None:
    """Return the cached image path if present, without any network access."""
    p = cache_path(amiibo_id_hex)
    return p if p.exists() else None


def fetch_image(amiibo_id_hex: str) -> Path:
    """Fetch (opt-in, online) the amiibo icon and cache it. Returns the local path.

    Raises OSError on any failure (offline, not found, too large, not a PNG).
    """
    cached = cached_image(amiibo_id_hex)
    if cached:
        return cached
    url = image_url(amiibo_id_hex)
    ctx = ssl.create_default_context()  # validates certs
    req = urllib.request.Request(url, headers={"User-Agent": "n2elite-ng"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            if getattr(resp, "status", 200) != 200:
                raise OSError(f"image fetch failed (HTTP {resp.status})")
            data = resp.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise OSError(f"could not fetch amiibo image: {e}") from e
    if len(data) > _MAX_BYTES:
        raise OSError("amiibo image exceeds size limit")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OSError("no image found for this amiibo (or not a PNG)")
    _cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_path(amiibo_id_hex)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest

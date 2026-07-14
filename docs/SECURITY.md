# Security & Privacy Posture

This project was built to be safe with no vulnerabilities and no privacy leaks.
Summary of the audited posture:

## Privacy — nothing leaves your machine
- **Offline by default.** The core app makes no network calls — no telemetry, no
  update checks, nothing uploaded. The bundled `amiibo_db.json` is read locally.
- **Opt-in online features (two, both download-only):**
  - **"Show image"** (`n2elite/amiibo/images.py`) fetches an amiibo's public figure
    icon from a fixed host (AmiiboAPI on GitHub) *only* when you explicitly ask, then
    caches it locally so it never re-fetches.
  - **"Download offline data"** / `n2elite sync` (`n2elite/amiibo/sync.py`) optionally
    downloads the full amiibo database and pre-caches every figure image, so the app
    then runs with no network at all. Bounded concurrency; already-cached files are
    skipped.
  Both send only GETs for public data keyed by amiibo ID — no personal data, no dumps,
  no keys. Both use HTTPS with certificate validation, fixed public hosts, a short
  timeout, per-response size caps (2 MB per image, 16 MB for the database), and content
  validation (PNG-magic for images, JSON parse for the database) before anything is
  written (atomically). Nothing else in the app ever touches the network.
- **Your keys stay yours.** `key_retail.bin` is only ever read, used for in-memory
  key derivation, and never printed, logged, transmitted, or written back. It is
  git-ignored, as are `*.bin`, `dumps/`, `backups/`, and captured serial logs.

## Safety — no dangerous execution
- No `eval`, `exec`, `__import__`, `pickle`/`marshal` (no untrusted deserialization),
  no `subprocess`, `os.system`, `os.popen`, or `shell=True`.
- All external input is length-validated before use: amiibo dumps must be 540/572
  bytes; key files must be 160 bytes; MFRC522/NTAG responses are bounded and checked.
- Serial I/O uses timeouts and bounded retries — no unbounded blocking or hangs.

## Device safety
- Reads are non-destructive. Writes are gated: a valid size is required, the GUI
  confirms before writing, and the workflow is backup-first.
- **No firmware flashing.** The N2 firmware-update path exists in the reference tools
  but is deliberately NOT implemented — it carries a bricking risk (per user directive).

## Supply chain
- Runtime dependencies: `pyserial`, `pycryptodome` (both mainstream, with minimum
  versions declared in `pyproject.toml`). Crypto uses `pycryptodome` (AES) + the
  standard library `hmac`/
  `hashlib` — no hand-rolled primitives.
- Build tooling (PyInstaller, a portable Python for Wine) is used only at build time
  and is not part of the shipped app.

## Reporting
This is a personal-use interoperability tool. Report issues privately to the
maintainer; do not include your `key_retail.bin` or any amiibo dumps in reports.

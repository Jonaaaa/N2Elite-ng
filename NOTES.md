# N2Elite-ng — Engineering Notes

Purpose: an OS-agnostic (Windows/Linux/macOS) open-source replacement for the
abandoned **N2 Manager** app, to manage the **N2 Elite / Amiiqo USB dongle**.
Inspired by / porting concepts from TagMo (github.com/HiddenRamblings/TagMo).

The serial + N2 command protocol is fully reverse-engineered and confirmed live on
real hardware — see `docs/PROTOCOL.md` for the authoritative spec.

## Golden rules (design principles)
1. **Non-destructive first.** The device holds the user's data. No write/erase/
   set-bank-count runs until a verified full backup of every bank exists; the GUI
   confirms before any destructive action.
2. **Never bundle Nintendo keys.** `key_retail.bin` (unfixed-info + locked-secret)
   is user-supplied and copyrighted. It is `.gitignore`d and never committed,
   transmitted, or logged.
3. **Offline by default.** No telemetry, update checks, or analytics. The only
   network is two opt-in, download-only features — the "Show image" fetch and
   `sync` (offline-data download) — both HTTPS, fixed host, cert-verified,
   size/time-capped, content-validated (PNG magic / JSON parse).
4. **No firmware flashing.** The reference tools expose it; we deliberately do not —
   it carries a bricking risk (user directive).

## Hardware (confirmed)
- Device: **N2 Elite USB reader/writer stand** (aka Amiiqo USB).
- NFC frontend chip: **NXP MFRC522**.
- PC link: **Silicon Labs CP2102 USB-UART bridge** → `/dev/ttyUSB0` (Linux),
  `COMx` (Windows), `/dev/cu.SLAB_USBtoUART` (macOS). VID:PID `10c4:ea60`.
- For serial access on Linux, add the user to the `dialout` group rather than
  running as root.

## Architecture (as shipped)
1. `n2elite/transport.py` — serial transport: MFRC522 UART **register bridge**
   (write/read register over the CP2102 link), robust connect with 9600↔921600
   baud auto-detect after every reset. (CRC_A is at the NFC layer, `crc.py`.)
2. `n2elite/mfrc522.py` — MFRC522 driver + ISO14443-3A activation (REQA/WUPA +
   anticollision SELECT).
3. `n2elite/device.py` — the N2 Elite command set over that transport.
4. `n2elite/amiibo/` — amiibo crypto (AES-128-CTR + HMAC-SHA256, user keys) +
   offline identify (`amiibo_db.json`) + opt-in images.
5. `n2elite/cli.py` + `n2elite/gui.py` — CLI and Tkinter GUI. PyInstaller binaries
   per OS via `n2elite.spec`.

## N2 Elite / NTAG215 command set (NFC-level; see PROTOCOL.md for the full spec)
NTAG215 standard:
- 0x60 GET_VERSION `60`
- 0x3C READ_SIG    `3c`
- 0x30 READ        `30 [page]`               -> 16 bytes
- 0x3A FAST_READ   `3a [start] [end]`         -> up to 252 bytes
- 0xA2 WRITE       `a2 [page] [4 bytes]`
- 0x1B PWD_AUTH    `1b [4-byte pwd]`          -> returns 8080
N2 Elite proprietary:
- 0x55 N2_GET_INFO      `55`      -> 4 bytes: active slot, bank count, button, FW ver
- 0x43 N2_GET_ID        `43`      -> 16-byte device ID (first 11 shown to user)
- 0xA9 N2_SET_BANK_CNT  `a9 [n]`  (a9 c8 = 200 banks, the max)     ⚠️ DESTRUCTIVE-ish
- 0x3B N2_FAST_READ     `3b [start] [end] [bank]`
- 0xA5 N2_WRITE         `a5 [page] [bank] [4 bytes]`               ⚠️ WRITE
- 0xAE N2_FAST_WRITE    `ae [start] [bank] [size] [data]`          ⚠️ WRITE
- 0x46 N2_LOCK          `46`      -> 0x0a
- 0x44 N2_UNLOCK prep   `44`
- 0x45 N2_UNLOCK final  `45`      (after button press)
- 0xA7 N2_SELECT_BANK   `a7 [bank]` -> 0x0a

## Sizes (confirmed)
- **Bank dump = 143 pages × 4 = 572 bytes** (0x23C); pages 0x87–0x8E hold the
  32-byte ECC signature block.
- **Amiibo .bin (NTAG215, as used by TagMo) = 135 pages × 4 = 540 bytes** (0x21C).

## Amiibo crypto (from kevinbrewster + amiitool)
- Encryption: AES-128-CTR for data + HMAC-SHA256 tags; key material derived via
  DRBG(HMAC-SHA256) from `unfixed-info.bin` / `locked-secret.bin` + tag salt.
- NTAG215 password = f(UID) via XOR (PWD_AUTH). See amiitool reference impl.
- Ported from socram8888/amiitool; parser reference Falco20019/libamiibo.
- The 8-byte amiibo model ID at tag offset 0x54 (big-endian) is **unencrypted**, so
  identification (`amiibo_db.json`) needs no keys.

## Key gotchas
- The N2 is an **active token**: energise the RF field once, then poll wake+select
  **without** re-init (re-init resets it before it boots).
- Baud only settles after a clean power-cycle + connect that re-detects baud after
  every soft reset. Antenna coupling is placement/orientation dependent.
- Setting bank count reboots the N2 → `device.reactivate()` afterward.
- A **locked** N2 exposes only its active bank as a plain NTAG215; manager functions
  need an unlock first (hold the disc's Cycle button *before* placing it on the reader).

## Status
Complete and proven live: read/identify, dump-all-banks backup, write/overwrite,
byte-identical dump→restore, set active bank, set bank count (max 200), lock/unlock,
offline amiibo decrypt/encrypt. Linux + Windows binaries build via PyInstaller
(Windows cross-built under Wine with a portable Python, no host changes).

## Decisions log
- Language: **Python 3** (pyserial cross-platform + fast iteration; deps in `.venv/`).
  PyInstaller produces per-OS binaries for non-Python users.
- Data source: bundled `amiibo_db.json` snapshot (public AmiiboAPI metadata); figure
  images fetched opt-in and cached. `n2elite sync` (see `amiibo/sync.py`) optionally
  downloads the full DB (rebuilt into a `~/.n2elite/amiibo_db.json` override that
  `database.py` prefers) and pre-caches every image for fully-offline use.

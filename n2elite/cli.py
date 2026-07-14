"""Command-line interface for N2Elite-ng.

Read/backup commands are non-destructive. Write commands (later) require an
explicit backup to exist first.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .device import BANK_DUMP_SIZE, N2Elite
from .mfrc522 import NfcError
from .transport import TransportError, find_ports


def _connect(args) -> N2Elite:
    dev = N2Elite(port=args.port)
    ver = dev.open()
    print(f"Connected on {dev.port} — MFRC522 v0x{ver:02X}")
    return dev


def cmd_ports(args) -> int:
    ports = find_ports()
    if not ports:
        print("No serial ports found.")
        return 1
    print("Serial ports (best candidate first):")
    for p in ports:
        print(f"  {p}")
    return 0


def cmd_info(args) -> int:
    dev = _connect(args)
    try:
        uid = dev.activate(timeout=args.wait)
        print(f"Tag UID    : {uid.hex().upper()}  (SAK 0x{dev.sak:02X})")
        if dev.is_n2_elite():
            info = dev.get_info()
            print("Type       : N2 Elite (unlocked)")
            print(f"Device ID  : {dev.get_id().hex().upper()}")
            print(f"Info       : {info}")
        else:
            print("Type       : responding as plain NTAG215")
            print("             (a locked N2 Elite looks like this — run `unlock`)")
    finally:
        dev.close()
    return 0


def cmd_unlock(args) -> int:
    dev = _connect(args)
    try:
        dev.activate(timeout=args.wait)
        if dev.is_n2_elite():
            print("Already unlocked:", dev.get_info())
            return 0
        # TagMo sends 0x44 then 0x45 back-to-back (no button wait).
        print("Sending unlock (0x44 -> 0x45)...")
        prep = dev.unlock_prep()
        fin = dev.unlock_finalize()
        if prep is None and fin is None:
            print("The N2 did not answer the unlock commands. This N2 is not "
                  "responding to ANY management command (0x55/0x43/0x44 all time "
                  "out) — it may need a firmware update or is in amiibo-only mode.")
            return 1
        time.sleep(0.2)
        try:
            dev._select()
        except Exception:
            pass
        if dev.is_n2_elite():
            print("Unlocked!", dev.get_info())
            return 0
        print("Still not answering N2 commands after unlock.")
        return 1
    finally:
        dev.close()


def cmd_backup(args) -> int:
    dev = _connect(args)
    try:
        uid = dev.activate()
        info = dev.get_info()
        print(f"Tag UID {uid.hex().upper()} — {info}")
        n = info.bank_count
        if not 1 <= n <= 200:
            print(f"Refusing backup: implausible bank count {n}", file=sys.stderr)
            return 2

        out = Path(args.out) if args.out else Path("backups") / f"n2_{uid.hex().upper()}"
        out.mkdir(parents=True, exist_ok=True)
        combined = bytearray()
        for bank in range(n):
            data = dev.dump_bank(bank)
            (out / f"bank_{bank:03d}.bin").write_bytes(data)
            combined += data
            print(f"  bank {bank:3d}/{n - 1}: {len(data)} bytes  ✓")
        (out / "all_banks.bin").write_bytes(combined)
        print(f"\nBackup complete: {n} banks ({len(combined)} bytes) -> {out}")
        print(f"Each bank is {BANK_DUMP_SIZE} bytes (143 NTAG215 pages).")
    finally:
        dev.close()
    return 0


def cmd_monitor(args) -> int:
    dev = _connect(args)
    print(f"VersionReg confirms the serial link (MFRC522 v0x{dev.version:02X}).")
    print("Watching for a tag — place the N2 Elite disc on the reader. Ctrl-C to stop.")
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            uid = dev.poll_tag()
            if uid:
                print(f"\nTAG DETECTED  UID={uid.hex().upper()}  SAK=0x{dev.sak:02X}")
                if dev.is_n2_elite():
                    info = dev.get_info()
                    print(f"  N2 Elite   : {info}")
                    print(f"  Device ID  : {dev.get_id().hex().upper()}")
                else:
                    print("  Type       : plain NTAG215 (use `read` to dump it)")
                return 0
            print(".", end="", flush=True)
            time.sleep(0.4)
        print("\nNo tag detected within the time window.")
        return 1
    finally:
        dev.close()


def cmd_read(args) -> int:
    dev = _connect(args)
    try:
        uid = dev.activate(timeout=args.wait)
        print(f"Tag UID {uid.hex().upper()} (SAK 0x{dev.sak:02X})")
        is_n2 = dev.is_n2_elite()
        print(f"N2 Elite commands: {'supported' if is_n2 else 'not answered (reading as plain NTAG215)'}")
        data = dev.dump_ntag()
        out = Path(args.out) if args.out else Path("backups") / f"ntag_{uid.hex().upper()}.bin"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"Read {len(data)} bytes (standard NTAG215) -> {out}")
        _print_identity(data)
        return 0
    finally:
        dev.close()


def _print_identity(data: bytes) -> None:
    from .amiibo import info, is_blank

    if is_blank(data):
        print("  Amiibo   : (blank / uninitialised tag)")
        return
    aid, rec = info(data)
    print(f"  Amiibo ID: {aid}")
    if not rec:
        print("  Amiibo   : (unknown — not in local database)")
        return
    print(f"  Amiibo   : {rec.get('name', '?')}")
    print(f"  Series   : {rec.get('series', '?')}  ({rec.get('type', '?')})")
    if rec.get("game"):
        print(f"  Game     : {rec['game']}")


def cmd_identify(args) -> int:
    data = Path(args.input).read_bytes()
    if len(data) not in (540, 572) and len(data) % 572 != 0:
        print(f"Warning: unusual file size {len(data)} (expected 540/572).", file=sys.stderr)
    _print_identity(data[:572])
    return 0


def cmd_decrypt(args) -> int:
    from .amiibo import AmiiboError, AmiiboKeys, unpack

    try:
        keys = AmiiboKeys.load(args.keys)
        tag = Path(args.input).read_bytes()
        plain, valid = unpack(keys, tag)
    except (AmiiboError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    Path(args.output).write_bytes(plain)
    print(f"Decrypted -> {args.output}  (HMAC {'VALID' if valid else 'INVALID — wrong keys or not an amiibo'})")
    return 0 if valid else 2


def cmd_encrypt(args) -> int:
    from .amiibo import AmiiboError, AmiiboKeys, pack

    try:
        keys = AmiiboKeys.load(args.keys)
        plain = Path(args.input).read_bytes()
        tag = pack(keys, plain)
    except (AmiiboError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    Path(args.output).write_bytes(tag)
    print(f"Encrypted -> {args.output}")
    return 0


def cmd_sync(args) -> int:
    """Download offline data: refresh the amiibo database and/or cache all images."""
    from .amiibo import images, sync
    from .config import Config

    cfg = Config()
    images.set_cache_dir(cfg.cache_dir)
    do_db = not args.images_only
    do_img = not args.database_only

    if do_db:
        print("Updating amiibo database…", flush=True)
        n = sync.download_database()
        print(f"  database updated: {n} amiibo.")
    if do_img:
        ids = sync.all_amiibo_ids()
        print(f"Caching {len(ids)} amiibo images to {images.cache_dir()} "
              f"(skipping already-cached)…", flush=True)
        state = {"last": -1}

        def prog(done, total, ok, failed, nbytes, speed):
            if done == total or done - state["last"] >= 25:
                state["last"] = done
                print(f"\r  {done}/{total}  fetched={ok} unavailable={failed}  "
                      f"{sync.human_bytes(nbytes)} @ {sync.human_bytes(speed)}/s",
                      end="", flush=True)

        res = sync.download_all_images(ids=ids, on_progress=prog, workers=args.workers)
        print()
        print(f"  images: {res['ok']} fetched, {res['skipped']} already cached, "
              f"{res['failed']} unavailable.")
        secs = max(res["seconds"], 1e-6)
        print(f"  downloaded {sync.human_bytes(res['bytes'])} in {secs:.1f}s "
              f"({sync.human_bytes(res['bytes'] / secs)}/s average).")
    print("Offline data ready — the app can now run without network access.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="n2elite", description="Manage the N2 Elite / Amiiqo USB dongle (offline)."
    )
    p.add_argument("--version", action="version", version=f"n2elite-ng {__version__}")
    p.add_argument("-p", "--port", help="serial port (auto-detected if omitted)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="list serial ports").set_defaults(func=cmd_ports)
    i = sub.add_parser("info", help="show device info (read-only)")
    i.add_argument("-w", "--wait", type=float, default=20.0, help="seconds to wait for a tag")
    i.set_defaults(func=cmd_info)
    u = sub.add_parser("unlock", help="unlock a locked N2 Elite (needs the button)")
    u.add_argument("-w", "--wait", type=float, default=20.0, help="seconds to wait for a tag")
    u.add_argument("--button-wait", type=int, default=10, help="seconds to press the button")
    u.set_defaults(func=cmd_unlock)
    b = sub.add_parser("backup", help="dump all banks to .bin files (read-only)")
    b.add_argument("-o", "--out", help="output directory")
    b.set_defaults(func=cmd_backup)
    m = sub.add_parser("monitor", help="watch for a tag (hold connection open)")
    m.add_argument("-s", "--seconds", type=float, default=60.0, help="how long to watch")
    m.set_defaults(func=cmd_monitor)
    r = sub.add_parser("read", help="read the active tag as a standard NTAG215 .bin")
    r.add_argument("-o", "--out", help="output .bin path")
    r.add_argument("-w", "--wait", type=float, default=20.0, help="seconds to wait for a tag")
    r.set_defaults(func=cmd_read)
    dec = sub.add_parser("decrypt", help="decrypt an amiibo .bin with your key_retail.bin")
    dec.add_argument("-k", "--keys", required=True, help="path to key_retail.bin")
    dec.add_argument("input", help="encrypted amiibo .bin")
    dec.add_argument("output", help="output decrypted .bin")
    dec.set_defaults(func=cmd_decrypt)
    enc = sub.add_parser("encrypt", help="encrypt a decrypted amiibo .bin with your keys")
    enc.add_argument("-k", "--keys", required=True, help="path to key_retail.bin")
    enc.add_argument("input", help="decrypted amiibo .bin")
    enc.add_argument("output", help="output encrypted .bin")
    enc.set_defaults(func=cmd_encrypt)
    idf = sub.add_parser("identify", help="identify which amiibo a .bin file is")
    idf.add_argument("input", help="amiibo .bin file")
    idf.set_defaults(func=cmd_identify)
    sy = sub.add_parser("sync", help="download offline data (amiibo database + all images)")
    sy.add_argument("--database-only", action="store_true",
                    help="only refresh the amiibo database, skip images")
    sy.add_argument("--images-only", action="store_true",
                    help="only download images, skip the database")
    sy.add_argument("--workers", type=int, default=6,
                    help="parallel image downloads, 1-8 (default 6)")
    sy.set_defaults(func=cmd_sync)
    sub.add_parser("gui", help="launch the graphical interface").set_defaults(func=cmd_gui)
    return p


def cmd_gui(args) -> int:
    from .gui import main as gui_main

    return gui_main()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (TransportError, NfcError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

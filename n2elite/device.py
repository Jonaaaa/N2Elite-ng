"""High-level N2 Elite / Amiiqo device operations built on the MFRC522 driver.

Read/backup operations are non-destructive. Write operations are deliberately
gated behind an explicit backup-first workflow (see cli).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .crc import append_crc_a
from .mfrc522 import MFRC522, NfcError, NfcTimeout
from .transport import SerialTransport, autodetect_port

# N2 Elite / NTAG215 command opcodes
NTAG_READ = 0x30
NTAG_FAST_READ = 0x3A
NTAG_GET_VERSION = 0x60
N2_GET_INFO = 0x55
N2_GET_ID = 0x43
N2_FAST_READ = 0x3B      # 3b start stop bank
N2_WRITE = 0xA5          # a5 page bank d0 d1 d2 d3
N2_SET_BANK_CNT = 0xA9
N2_SELECT_BANK = 0xA7
N2_LOCK = 0x46
N2_UNLOCK_PREP = 0x44
N2_UNLOCK_FIN = 0x45
NTAG_PWD_AUTH = 0x1B

NTAG215_PAGES = 135         # standard NTAG215 user+config = 135 pages
NTAG215_SIZE = NTAG215_PAGES * 4     # 540 bytes (0x21C) — standard amiibo .bin
PAGES_PER_BANK = 0x8F        # pages 0..0x8E inclusive = 143 pages
BANK_DUMP_SIZE = PAGES_PER_BANK * 4  # 572 bytes (0x23C)
LAST_PAGE = 0x8E
CHUNK_PAGES = 15             # max pages per FAST_READ (15*4 + 2 CRC <= 64B FIFO)
TAG_BOOT_DELAY = 0.3         # the N2 is an active token; let it boot in the field


@dataclass
class DeviceInfo:
    active_bank: int
    bank_count: int
    button_state: int
    firmware: int
    raw: bytes

    def __str__(self) -> str:
        return (
            f"firmware=0x{self.firmware:02X} banks={self.bank_count} "
            f"active_bank={self.active_bank} button=0x{self.button_state:02X}"
        )


class N2Elite:
    def __init__(self, port: str | None = None, timeout: float = 1.0):
        self.port = port or autodetect_port()
        self.transport = SerialTransport(self.port, timeout=timeout)
        self.mfrc = MFRC522(self.transport)
        self.version: int | None = None
        self.uid: bytes | None = None
        self.sak: int | None = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> int:
        """Open port and initialise the MFRC522. Returns chip version.

        connect() leaves the RF field on; we then let the (active) N2 token boot.
        """
        self.transport.open()
        self.version = self.mfrc.connect()
        time.sleep(TAG_BOOT_DELAY)
        return self.version

    def _select(self) -> bytes:
        # Try WUPA (wakes halted tags) then REQA; some tokens answer only one.
        last: Exception | None = None
        for wake in (self.mfrc.wakeup_a, self.mfrc.request_a):
            try:
                wake()
                self.uid, self.sak = self.mfrc.select()
                return self.uid
            except (NfcTimeout, NfcError) as e:
                last = e
        raise last if last else NfcTimeout("no tag")

    def poll_tag(self) -> bytes | None:
        """One detection cycle (wake + select) with the field kept stable.

        Does NOT re-init the RF — cycling the antenna resets the active token
        before it can boot, which makes detection unreliable.
        """
        try:
            return self._select()
        except (NfcTimeout, NfcError):
            return None

    def wait_for_tag(self, timeout: float = 10.0) -> bytes:
        """Poll until a tag is selected, or raise NfcTimeout.

        Mostly keeps the field stable (so the active token stays booted), but
        re-energises periodically to recover a token that never came up.
        """
        deadline = time.monotonic() + timeout
        self.mfrc.init()             # energise the field once
        time.sleep(TAG_BOOT_DELAY)   # let the active token boot
        while time.monotonic() < deadline:
            uid = self.poll_tag()
            if uid:
                return uid
            time.sleep(0.08)
        raise NfcTimeout(
            "no tag detected — place the N2 disc centered flat on the reader pad"
        )

    def activate(self, timeout: float = 10.0) -> bytes:
        """Wait for and select the tag. Returns UID."""
        return self.wait_for_tag(timeout)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "N2Elite":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- read-only queries -------------------------------------------------
    def get_info(self) -> DeviceInfo:
        raw = self.mfrc.transceive_crc(bytes([N2_GET_INFO]))
        b = raw + bytes(max(0, 4 - len(raw)))
        return DeviceInfo(
            active_bank=b[0], bank_count=b[1], button_state=b[2], firmware=b[3], raw=raw
        )

    def get_id(self) -> bytes:
        return self.mfrc.transceive_crc(bytes([N2_GET_ID]))

    def is_n2_elite(self) -> bool:
        """True if the tag answers the N2-proprietary management protocol.

        Two independent checks (matching TagMo): N2 GET_INFO (0x55) responds, or
        the N2 signature (0x43) responds with 0xFF in its last 5 bytes.
        """
        try:
            self.mfrc.transceive_crc(bytes([N2_GET_INFO]))
            return True
        except (NfcTimeout, NfcError):
            pass
        try:
            sig = self.mfrc.transceive_crc(bytes([N2_GET_ID]))  # 0x43 = N2 read-sig
            if len(sig) >= 32 and sig[27:32] == b"\xff\xff\xff\xff\xff":
                return True
        except (NfcTimeout, NfcError):
            pass
        return False

    # -- standard NTAG215 access (works on plain amiibo and the N2 active bank) --
    def _transceive_retry(self, frame: bytes, expected: int, tries: int = 6) -> bytes:
        """Transceive, re-selecting the tag (no RF re-init) on transient failures."""
        last: Exception | None = None
        for _ in range(tries):
            try:
                r = self.mfrc.transceive_crc(frame)
                if len(r) == expected:
                    return r
                last = NfcError(f"got {len(r)}B, expected {expected}B")
            except (NfcTimeout, NfcError) as e:
                last = e
            try:
                self._select()  # tag may have dropped out; re-select, field stays on
            except (NfcTimeout, NfcError):
                pass
        raise NfcError(f"read failed for {frame.hex()}: {last}")

    def read_page(self, page: int) -> bytes:
        """Standard NTAG READ: 16 bytes (4 pages) starting at `page`."""
        return self._transceive_retry(bytes([NTAG_READ, page]), 16)

    def fast_read_ntag(self, start: int, stop: int) -> bytes:
        """Standard NTAG FAST_READ: pages [start..stop] inclusive."""
        return self._transceive_retry(
            bytes([NTAG_FAST_READ, start, stop]), (stop - start + 1) * 4
        )

    def dump_ntag(self, pages: int = NTAG215_PAGES) -> bytes:
        """Dump the active tag as a standard NTAG215 image (default 540 bytes)."""
        out = bytearray()
        page = 0
        while page < pages:
            stop = min(pages - 1, page + CHUNK_PAGES - 1)
            out += self.fast_read_ntag(page, stop)
            page = stop + 1
        return bytes(out)

    def fast_read(self, start: int, stop: int, bank: int) -> bytes:
        """Read pages [start..stop] (inclusive) from `bank`."""
        return self.mfrc.transceive_crc(bytes([N2_FAST_READ, start, stop, bank]))

    # -- N2 unlock / lock / settings (require the N2 in management mode) --------
    def unlock_prep(self) -> bytes | None:
        """N2_UNLOCK step 1. The physical button must then be pressed."""
        try:
            return self.mfrc.transceive_crc(bytes([N2_UNLOCK_PREP]))
        except (NfcTimeout, NfcError):
            return None

    def unlock_finalize(self) -> bytes | None:
        """N2_UNLOCK step 2, after the button press."""
        try:
            return self.mfrc.transceive_crc(bytes([N2_UNLOCK_FIN]))
        except (NfcTimeout, NfcError):
            return None

    def lock(self) -> bytes | None:
        try:
            return self.mfrc.transceive_crc(bytes([N2_LOCK]))
        except (NfcTimeout, NfcError):
            return None

    def reactivate(self, tries: int = 12) -> bool:
        """Re-select the tag after a command that reboots the N2 (e.g. set bank
        count). Returns True once selected."""
        for _ in range(tries):
            try:
                self.activate(timeout=5)
                return True
            except (NfcTimeout, NfcError):
                time.sleep(0.3)
        return False

    def set_bank_count(self, count: int) -> None:
        if not 1 <= count <= 200:
            raise ValueError("bank count must be 1..200")
        self.mfrc.transceive_crc(bytes([N2_SET_BANK_CNT, count]))
        time.sleep(0.4)      # the N2 reboots to apply the new count
        self.reactivate()

    def select_bank(self, bank: int) -> None:
        """Set the active bank (N2_SELECT_BANK 0xA7). The N2 re-inits, so re-select."""
        try:
            self.mfrc.transceive_crc(bytes([N2_SELECT_BANK, bank]))
        except (NfcTimeout, NfcError):
            pass  # the N2 may drop the tag as it switches
        time.sleep(0.3)
        self.reactivate()

    def write_bank(self, bank: int, data: bytes) -> None:
        """Write a 540- or 572-byte image into a bank (per-page N2_WRITE 0xA5).

        DESTRUCTIVE. The caller must ensure the bank is backed up first.
        """
        if len(data) not in (NTAG215_SIZE, BANK_DUMP_SIZE):
            raise ValueError(f"image must be {NTAG215_SIZE} or {BANK_DUMP_SIZE} bytes")
        # Auth formality (the N2 answers PWD_AUTH 0x8080 regardless).
        page0 = self._transceive_retry(bytes([NTAG_FAST_READ, 0, 0]), 4)
        try:
            self.mfrc.transceive_crc(bytes([NTAG_PWD_AUTH]) + page0[:4])
        except (NfcTimeout, NfcError):
            pass
        for page in range(len(data) // 4):
            chunk = data[page * 4:page * 4 + 4]
            self._write_tolerant(bytes([N2_WRITE, page, bank]) + chunk)

    def empty_bank(self, bank: int) -> None:
        """Erase a bank (write a blank image so it reads as empty). DESTRUCTIVE."""
        self.write_bank(bank, b"\x00" * BANK_DUMP_SIZE)

    def _write_tolerant(self, frame: bytes, tries: int = 4) -> None:
        """Send a write command; accept any/no ACK, re-selecting on drop."""
        crc_frame = append_crc_a(frame)
        for _ in range(tries):
            try:
                self.mfrc.transceive(crc_frame)
                return
            except NfcTimeout:
                return  # writes often return only a short ACK / nothing framed
            except NfcError:
                try:
                    self._select()
                except (NfcTimeout, NfcError):
                    pass
        raise NfcError(f"write failed for {frame.hex()}")

    def read_bank_amiibo_id(self, bank: int) -> bytes:
        """Read only a bank's 8-byte amiibo ID (pages 0x15-0x16) — fast listing."""
        return self.fast_read(0x15, 0x16, bank)[:8]

    def list_banks(self) -> list[tuple[int, str | None, str | None]]:
        """[(bank, amiibo_id_hex, name)] for every bank. Requires an unlocked N2."""
        from .amiibo import info_for_id

        info = self.get_info()
        result: list[tuple[int, str | None, str | None]] = []
        for b in range(info.bank_count):
            try:
                raw = self.read_bank_amiibo_id(b)
                aid = "0x%016x" % int.from_bytes(raw, "big")
                rec = info_for_id(aid)
                result.append((b, aid, rec.get("name") if rec else None))
            except (NfcTimeout, NfcError):
                try:
                    self._select()
                except (NfcTimeout, NfcError):
                    pass
                result.append((b, None, None))
        return result

    def dump_bank(self, bank: int) -> bytes:
        """Dump all 143 pages (572 bytes) of a bank. Non-destructive."""
        out = bytearray()
        page = 0
        while page <= LAST_PAGE:
            stop = min(LAST_PAGE, page + CHUNK_PAGES - 1)
            chunk = self.fast_read(page, stop, bank)
            expected = (stop - page + 1) * 4
            if len(chunk) != expected:
                raise NfcError(
                    f"bank {bank}: pages {page}..{stop} returned {len(chunk)}B, "
                    f"expected {expected}B"
                )
            out += chunk
            page = stop + 1
        if len(out) != BANK_DUMP_SIZE:
            raise NfcError(f"bank {bank}: got {len(out)}B, expected {BANK_DUMP_SIZE}")
        return bytes(out)

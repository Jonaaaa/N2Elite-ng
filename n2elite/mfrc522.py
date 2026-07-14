"""MFRC522 NFC controller driver over the serial register bridge.

Port of the MFRC522 + ISO14443-3A logic used by the official N2 Elite Manager
(itself a port of miguelbalboa/rfid). Provides register init, tag activation
(REQA + anticollision SELECT), and CRC-framed transceive used by NTAG215 / N2
Elite commands.
"""
from __future__ import annotations

import time

DEFAULT_TRANSCEIVE_TIMEOUT = 1.5  # seconds; MFRC522 hardware timer ~0.5s

from .crc import append_crc_a
from .transport import BAUD_FAST, BAUD_INIT, SerialTransport, TransportError


class NfcError(Exception):
    pass


class NfcTimeout(NfcError):
    pass


class NfcCollision(NfcError):
    pass


class MFRC522:
    # --- registers ---
    CommandReg = 0x01
    ComIrqReg = 0x04
    DivIrqReg = 0x05
    ErrorReg = 0x06
    Status2Reg = 0x08
    FIFODataReg = 0x09
    FIFOLevelReg = 0x0A
    ControlReg = 0x0C
    BitFramingReg = 0x0D
    CollReg = 0x0E
    ModeReg = 0x11
    TxControlReg = 0x14
    TxASKReg = 0x15
    RFCfgReg = 0x26
    SerialSpeedReg = 0x1F
    CRCResultRegH = 0x21
    CRCResultRegL = 0x22
    TModeReg = 0x2A
    TPrescalerReg = 0x2B
    TReloadRegH = 0x2C
    TReloadRegL = 0x2D
    VersionReg = 0x37

    # --- PCD commands ---
    CMD_Idle = 0x00
    CMD_CalcCRC = 0x03
    CMD_Transceive = 0x0C
    CMD_SoftReset = 0x0F

    # --- PICC (tag) commands ---
    PICC_REQA = 0x26
    PICC_WUPA = 0x52
    PICC_CT = 0x88
    PICC_SEL_CL1 = 0x93
    PICC_SEL_CL2 = 0x95
    PICC_SEL_CL3 = 0x97
    PICC_HLTA = 0x50

    WAIT_IRQ_RX = 0x30  # RxIRq | IdleIRq

    def __init__(self, transport: SerialTransport):
        self.t = transport

    # -- register helpers --------------------------------------------------
    def write_command(self, cmd: int) -> None:
        self.t.write_register(self.CommandReg, cmd)

    def set_register_bits(self, reg: int, mask: int) -> None:
        self.t.write_register(reg, self.t.read_register(reg) | mask)

    def clear_register_bits(self, reg: int, mask: int) -> None:
        self.t.write_register(reg, self.t.read_register(reg) & (~mask & 0xFF))

    # -- init / reset ------------------------------------------------------
    def connect(self) -> int:
        """Connect and initialise the MFRC522. Returns VersionReg.

        The MFRC522 UART auto-bauds on the first byte after reset, and this
        dongle's soft-reset effect on the UART speed is inconsistent (it may stay
        at 921600 or drop to 9600). So we always *re-detect* the baud after a
        reset before touching any register. A full soft reset is required to put
        the analog/RF front end into a working state (fresh power-on defaults).
        """
        baud = self._detect_baud()
        if baud is None:
            baud = BAUD_INIT  # assume fresh; first byte will auto-baud it
        # Clean soft reset from wherever it currently is.
        self.t.set_baud(baud)
        self.t.flush()
        try:
            self.write_command(self.CMD_SoftReset)
        except TransportError:
            pass
        time.sleep(0.06)
        # Re-detect where the UART landed after the reset.
        baud = self._detect_baud()
        if baud is None:
            # Fresh auto-baud: poke at 9600 to lock it, then detect again.
            self.t.set_baud(BAUD_INIT)
            self.t.flush()
            try:
                self.t.read_register(self.VersionReg)
            except TransportError:
                pass
            baud = self._detect_baud() or BAUD_INIT
        # Ensure we end up at the fast baud for throughput.
        if baud == BAUD_INIT:
            self._switch_to_fast()
        else:
            self.t.set_baud(BAUD_FAST)
            self.t.flush()
        self.init()
        ver = self.t.read_register(self.VersionReg)
        if ver in (0x00, 0xFF):
            raise NfcError(
                f"MFRC522 not detected (VersionReg=0x{ver:02X}); check the dongle/cabling"
            )
        return ver

    def _probe_version(self, baud: int) -> bool:
        """Set baud and check whether an MFRC522 answers (VersionReg 0x90-0x9F)."""
        self.t.set_baud(baud)
        self.t.flush()
        try:
            for _ in range(3):
                if 0x90 <= self.t.read_register(self.VersionReg) <= 0x9F:
                    return True
        except TransportError:
            return False
        return False

    def _detect_baud(self) -> int | None:
        for b in (BAUD_INIT, BAUD_FAST):
            if self._probe_version(b):
                return b
        return None

    def _switch_to_fast(self) -> None:
        """From 9600 (reset, powered): raise the UART to 921600 via SerialSpeedReg."""
        self.t.set_baud(BAUD_INIT)
        self.t.flush()
        # wait for PowerDown (bit 0x10 of CommandReg) to clear
        for _ in range(100):
            if not (self.t.read_register(self.CommandReg) & 0x10):
                break
            time.sleep(0.005)
        self.t.write_register(self.SerialSpeedReg, 0x1C)
        time.sleep(0.01)
        self.t.set_baud(BAUD_FAST)
        self.t.flush()
        for _ in range(0x80):
            if self.t.read_register(self.SerialSpeedReg) == 0x1C:
                return
        raise NfcError("baud handshake failed (SerialSpeedReg not confirmed at 921600)")

    def shutdown(self) -> None:
        """Best-effort: soft-reset so the chip's UART returns to 9600 for next time."""
        try:
            self.write_command(self.CMD_SoftReset)
            time.sleep(0.02)
        except Exception:
            pass

    def init(self) -> None:
        time.sleep(0.05)
        self.t.write_register(self.TModeReg, 0x8D)
        self.t.write_register(self.TPrescalerReg, 0xA9)
        self.t.write_register(self.TReloadRegH, 0x03)
        self.t.write_register(self.TReloadRegL, 0xE8)
        self.t.write_register(self.TxASKReg, 0x40)
        self.t.write_register(self.ModeReg, 0x3D)
        self.t.write_register(self.RFCfgReg, 0x40)
        self.antenna_on()

    def antenna_on(self) -> None:
        val = self.t.read_register(self.TxControlReg)
        if (val & 0x03) != 0x03:
            self.t.write_register(self.TxControlReg, val | 0x03)

    def antenna_off(self) -> None:
        self.clear_register_bits(self.TxControlReg, 0x03)

    # -- low-level transceive ---------------------------------------------
    def communicate(
        self,
        command: int,
        wait_irq: int,
        send: bytes,
        tx_last_bits: int = 0,
        rx_align: int = 0,
    ) -> tuple[bytes, int]:
        """Send `send` via `command`; return (fifo_bytes, valid_bits_of_last_byte)."""
        bit_framing = ((rx_align & 0x07) << 4) | (tx_last_bits & 0x07)
        self.write_command(self.CMD_Idle)          # stop any active command
        self.t.write_register(self.ComIrqReg, 0x7F)  # clear all interrupt bits
        self.set_register_bits(self.FIFOLevelReg, 0x80)  # flush FIFO
        self.t.write_register_bytes(self.FIFODataReg, send)
        self.t.write_register(self.BitFramingReg, bit_framing)
        self.write_command(command)
        if command == self.CMD_Transceive:
            self.set_register_bits(self.BitFramingReg, 0x80)  # StartSend

        deadline = time.monotonic() + DEFAULT_TRANSCEIVE_TIMEOUT
        while True:
            n = self.t.read_register(self.ComIrqReg)
            if n & wait_irq:
                break
            if n & 0x01:  # TimerIRq -> nothing received in time
                raise NfcTimeout("no tag detected")
            if time.monotonic() > deadline:
                raise NfcTimeout("no tag detected (timeout)")

        err = self.t.read_register(self.ErrorReg)
        if err & 0x13:  # BufferOvfl | ParityErr | ProtocolErr
            raise NfcError(f"transceive error (ErrorReg=0x{err:02X})")

        n = self.t.read_register(self.FIFOLevelReg)
        back = self.t.read_register_bytes(self.FIFODataReg, n)
        valid_bits = self.t.read_register(self.ControlReg) & 0x07

        if err & 0x08:  # CollErr
            raise NfcCollision("anticollision collision")
        return back, valid_bits

    def transceive(
        self, send: bytes, tx_last_bits: int = 0, rx_align: int = 0
    ) -> tuple[bytes, int]:
        return self.communicate(
            self.CMD_Transceive, self.WAIT_IRQ_RX, send, tx_last_bits, rx_align
        )

    def transceive_crc(self, send: bytes) -> bytes:
        """Append CRC_A, transceive, strip the 2 response CRC bytes."""
        frame = append_crc_a(send)
        back, _ = self.transceive(frame)
        if len(back) < 2:
            raise NfcError(f"short response ({len(back)} bytes) to cmd 0x{send[0]:02X}")
        return back[:-2]

    # -- ISO14443-3A activation -------------------------------------------
    def request_a(self) -> bytes:
        return self._reqa_wupa(self.PICC_REQA)

    def wakeup_a(self) -> bytes:
        return self._reqa_wupa(self.PICC_WUPA)

    def _reqa_wupa(self, command: int) -> bytes:
        self.clear_register_bits(self.CollReg, 0x80)  # clear ValuesAfterColl
        atqa, valid = self.communicate(
            self.CMD_Transceive, self.WAIT_IRQ_RX, bytes([command]), tx_last_bits=7
        )
        if len(atqa) != 2 or valid != 0:
            raise NfcError("invalid ATQA (no tag / bad response)")
        return atqa

    def select(self) -> tuple[bytes, int]:
        """ISO14443-3A anticollision + SELECT. Returns (uid, sak)."""
        uid: list[int] = []
        cascade_levels = (self.PICC_SEL_CL1, self.PICC_SEL_CL2, self.PICC_SEL_CL3)
        sak = 0
        for level, sel in enumerate(cascade_levels):
            # buffer: SEL, NVB, then up to 4 UID bytes + BCC
            buf = bytearray([sel, 0x20])
            # full anticollision (NVB=0x20): ask tag for its UID CLn
            recv, _ = self.communicate(self.CMD_Transceive, self.WAIT_IRQ_RX, bytes(buf))
            if len(recv) != 5:
                raise NfcError(f"anticollision CL{level + 1} bad length {len(recv)}")
            uid_bytes = recv[:4]
            bcc = recv[4]
            if bcc != (uid_bytes[0] ^ uid_bytes[1] ^ uid_bytes[2] ^ uid_bytes[3]):
                raise NfcError(f"BCC check failed at CL{level + 1}")

            # SELECT: SEL, NVB=0x70, 4 UID bytes, BCC, + CRC_A
            sel_frame = bytes([sel, 0x70]) + uid_bytes + bytes([bcc])
            resp = self.transceive_crc(sel_frame)
            if len(resp) != 1:
                raise NfcError(f"SELECT CL{level + 1} bad SAK length {len(resp)}")
            sak = resp[0]

            if uid_bytes[0] == self.PICC_CT:
                # cascade tag: first byte is CT, real UID continues next level
                uid.extend(uid_bytes[1:4])
            else:
                uid.extend(uid_bytes[:4])
                break
            if not (sak & 0x04):
                break
        return bytes(uid), sak

    def halt_a(self) -> None:
        # HLTA has no response; a response means it failed. Ignore timeout = success.
        try:
            self.transceive_crc(bytes([self.PICC_HLTA, 0x00]))
        except NfcTimeout:
            pass

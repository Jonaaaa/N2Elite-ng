"""Serial register-bridge transport to the N2 Elite / Amiiqo USB dongle.

The dongle is an NXP MFRC522 exposed over a CP2102 UART. This layer implements the
genuine MFRC522 UART register protocol (confirmed by decompiling the official app):

  write reg:  TX (reg & 0x3F)         -> RX 1 byte (addr echo, discarded) -> TX value
  read  reg:  TX (reg & 0x3F) | 0x80  -> RX 1 byte (register value)

Cross-platform: works with any pyserial-supported port name (Linux /dev/ttyUSB*,
Windows COMx, macOS /dev/cu.SLAB_USBtoUART).
"""
from __future__ import annotations

import glob
import sys
import time

import serial
from serial.tools import list_ports

BAUD_INIT = 9600      # MFRC522 UART default after power-on / soft reset
BAUD_FAST = 921600    # after SerialSpeedReg = 0x1C

# CP2102 USB-UART bridge used by the N2 Elite dongle
CP210X_VID = 0x10C4
CP210X_PID = 0xEA60


class TransportError(Exception):
    pass


def find_ports() -> list[str]:
    """Return candidate serial ports, CP210x devices first."""
    cp210x, others = [], []
    for p in list_ports.comports():
        if (p.vid, p.pid) == (CP210X_VID, CP210X_PID):
            cp210x.append(p.device)
        else:
            others.append(p.device)
    if not cp210x and not others and sys.platform.startswith("linux"):
        others = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    return cp210x + others


def describe_ports() -> list[tuple[str, str]]:
    """Return (device, label) pairs, CP210x first, with a human description."""
    out: list[tuple[str, str]] = []
    others: list[tuple[str, str]] = []
    for p in list_ports.comports():
        desc = (p.description or "").strip()
        if (p.vid, p.pid) == (CP210X_VID, CP210X_PID):
            out.append((p.device, f"{p.device} — Silicon Labs CP210x (N2 dongle)"))
        else:
            others.append((p.device, f"{p.device} — {desc}" if desc else p.device))
    return out + others


def autodetect_port() -> str:
    ports = find_ports()
    if not ports:
        raise TransportError(
            "No serial port found. Plug in the N2 Elite USB dongle. "
            "On Linux, ensure your user is in the 'dialout' group."
        )
    return ports[0]


class SerialTransport:
    def __init__(self, port: str, timeout: float = 1.0):
        self.port_name = port
        self.timeout = timeout
        self.ser: serial.Serial | None = None

    # -- lifecycle ---------------------------------------------------------
    def open(self, baud: int = BAUD_INIT, grab_seconds: float = 6.0) -> None:
        """Open the port. Retries transient 'access denied'/busy errors for up to
        `grab_seconds` to win the enumeration race some OSes create on plug-in."""
        deadline = time.monotonic() + max(0.0, grab_seconds)
        while True:
            try:
                self.ser = serial.Serial(
                    self.port_name,
                    baudrate=baud,
                    timeout=self.timeout,
                    write_timeout=self.timeout,
                )
                self.flush()
                return
            except serial.SerialException as e:
                msg = str(e).lower()
                transient = "denied" in msg or "permission" in msg or "busy" in msg
                if transient and time.monotonic() < deadline:
                    time.sleep(0.25)
                    continue
                if transient:
                    raise TransportError(
                        f"{self.port_name} is in use or access was denied. Close any other "
                        f"program using it (the original N2 Manager, a serial terminal, or a "
                        f"second copy of this app), pick the 'Silicon Labs CP210x' port, or "
                        f"unplug/replug the dongle, then try again."
                    ) from e
                raise TransportError(f"could not open {self.port_name}: {e}") from e

    def set_baud(self, baud: int) -> None:
        if self.ser is None:
            raise TransportError("port not open")
        self.ser.baudrate = baud

    def flush(self) -> None:
        if self.ser is not None:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            finally:
                self.ser = None

    def __enter__(self) -> "SerialTransport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- register bridge ---------------------------------------------------
    def write_register(self, reg: int, value: int) -> None:
        if self.ser is None:
            raise TransportError("port not open")
        addr = reg & 0x3F  # bit7 = 0 -> write
        self.ser.write(bytes([addr]))
        echo = self.ser.read(1)  # address echo
        if len(echo) != 1:
            raise TransportError(f"no echo writing reg 0x{reg:02X} (device unresponsive)")
        self.ser.write(bytes([value & 0xFF]))

    def write_register_bytes(self, reg: int, values: bytes) -> None:
        for v in values:
            self.write_register(reg, v)

    def read_register(self, reg: int) -> int:
        if self.ser is None:
            raise TransportError("port not open")
        addr = (reg & 0x3F) | 0x80  # bit7 = 1 -> read
        self.ser.write(bytes([addr]))
        b = self.ser.read(1)
        if len(b) != 1:
            raise TransportError(f"no response reading reg 0x{reg:02X} (device unresponsive)")
        return b[0]

    def read_register_bytes(self, reg: int, count: int) -> bytes:
        return bytes(self.read_register(reg) for _ in range(count))

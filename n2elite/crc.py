"""ISO/IEC 14443-3 Type A CRC (CRC_A).

Matches the official app's software CrcA.ComputeCrc (polynomial 0x8408, init 0x6363).
Returned as (low_byte, high_byte); appended to an NFC frame low byte first.
"""
from __future__ import annotations


def crc_a(data: bytes) -> tuple[int, int]:
    crc = 0x6363
    for b in data:
        b ^= crc & 0xFF
        b = (b ^ (b << 4)) & 0xFF
        crc = ((crc >> 8) ^ (b << 8) ^ (b << 3) ^ (b >> 4)) & 0xFFFF
    return crc & 0xFF, (crc >> 8) & 0xFF


def append_crc_a(data: bytes) -> bytes:
    lo, hi = crc_a(data)
    return bytes(data) + bytes([lo, hi])


def check_crc_a(data: bytes) -> bool:
    """True if the last two bytes are a valid CRC_A over the preceding bytes."""
    if len(data) < 2:
        return False
    lo, hi = crc_a(data[:-2])
    return data[-2] == lo and data[-1] == hi

"""Tests for amiibo identification (offline name lookup)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from n2elite.amiibo import database


def _dump_with_id(id_bytes: bytes) -> bytes:
    d = bytearray(540)
    d[0x54:0x5C] = id_bytes
    return bytes(d)


def test_amiibo_id_extraction():
    d = _dump_with_id(bytes.fromhex("0100000003530902"))
    assert database.amiibo_id(d) == "0x0100000003530902"


def test_known_lookup():
    # Link - Archer (Breath of the Wild)
    d = _dump_with_id(bytes.fromhex("0100000003530902"))
    aid, name = database.identify(d)
    assert aid == "0x0100000003530902"
    assert name == "Link - Archer"


def test_blank_detection():
    assert database.is_blank(_dump_with_id(b"\x00" * 8))
    assert not database.is_blank(_dump_with_id(bytes.fromhex("0100000003530902")))


def test_database_loads():
    assert len(database._db()) > 500


def test_rich_info():
    d = _dump_with_id(bytes.fromhex("0100000003530902"))
    aid, rec = database.info(d)
    assert rec and rec["name"] == "Link - Archer"
    assert rec["series"] and rec["type"] == "Figure"
    assert "Link - Archer" in database.describe(d)


if __name__ == "__main__":
    test_amiibo_id_extraction()
    test_known_lookup()
    test_blank_detection()
    test_database_loads()
    print("all amiibo id tests passed")

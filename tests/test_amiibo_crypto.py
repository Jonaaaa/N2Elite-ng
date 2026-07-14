"""Self-consistency tests for the amiibo crypto port (no real Nintendo keys)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from n2elite.amiibo import crypto
from n2elite.amiibo.crypto import AmiiboKeys
from n2elite.crc import crc_a


def make_key(seed: int) -> bytes:
    """Deterministic 160-byte pseudo key with a valid structure."""
    import hashlib
    out = bytearray()
    for half in range(2):
        blob = bytearray()
        i = 0
        while len(blob) < 80:
            blob += hashlib.sha256(bytes([seed, half, i])).digest()
            i += 1
        blob = blob[:80]
        # type string: printable + NUL terminator
        blob[16:30] = (b"testkey %d\x00" % half).ljust(14, b"\x00")
        blob[30] = 0                      # rfu
        blob[31] = [16, 14][half]         # magicBytesSize (<=16)
        out += blob
    return bytes(out)


def test_crc_a_hlta():
    assert crc_a(bytes([0x50, 0x00])) == (0x57, 0xCD)


def test_pack_unpack_roundtrip():
    keys = AmiiboKeys.from_bytes(make_key(1))
    import hashlib
    plain = bytearray()
    i = 0
    while len(plain) < crypto.DUMP_SIZE:
        plain += hashlib.sha256(bytes([0xAB, i])).digest()
        i += 1
    plain = bytes(plain[: crypto.DUMP_SIZE])

    tag1 = crypto.pack(keys, plain)
    assert len(tag1) == crypto.DUMP_SIZE

    canon, valid1 = crypto.unpack(keys, tag1)
    assert valid1, "unpack of freshly packed dump must validate"

    # Re-packing the canonical plaintext must be deterministic/idempotent.
    tag2 = crypto.pack(keys, canon)
    assert tag2 == tag1, "pack is not deterministic/idempotent"

    plain2, valid2 = crypto.unpack(keys, tag2)
    assert valid2
    assert plain2 == canon, "decrypt did not round-trip"


def test_wrong_key_fails_validation():
    k1 = AmiiboKeys.from_bytes(make_key(1))
    k2 = AmiiboKeys.from_bytes(make_key(2))
    import hashlib
    plain = (hashlib.sha256(b"x").digest() * 20)[: crypto.DUMP_SIZE]
    tag = crypto.pack(k1, plain)
    _, valid = crypto.unpack(k2, tag)  # different keys
    assert not valid, "validation must fail with the wrong keys"


if __name__ == "__main__":
    test_crc_a_hlta()
    test_pack_unpack_roundtrip()
    test_wrong_key_fails_validation()
    print("all amiibo crypto tests passed")

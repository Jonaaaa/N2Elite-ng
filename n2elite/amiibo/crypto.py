"""Amiibo NTAG215 crypto — faithful port of amiitool (MIT, socram8888).

Implements the amiibo key derivation (HMAC-SHA256 DRBG), AES-128-CTR cipher, and
HMAC-SHA256 signatures used to pack/unpack (encrypt/decrypt) 540-byte NTAG215
amiibo dumps. Keys come from the user's own `key_retail.bin` (unfixed-info +
locked-secret, 160 bytes). No keys are bundled; nothing touches the network.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from Crypto.Cipher import AES
from Crypto.Util import Counter

DUMP_SIZE = 540          # NTAG215 dump / amiibo .bin
MASTERKEY_SIZE = 80
KEYFILE_SIZE = 2 * MASTERKEY_SIZE  # 160

HMAC_POS_DATA = 0x008
HMAC_POS_TAG = 0x1B4


class AmiiboError(Exception):
    pass


def _hmac256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


@dataclass
class MasterKey:
    """One 80-byte master key (data or tag)."""
    hmac_key: bytes       # 16
    type_string: bytes    # 14
    magic_size: int       # 1 (rfu byte skipped)
    magic_bytes: bytes    # 16
    xor_pad: bytes        # 32

    @classmethod
    def parse(cls, b: bytes) -> "MasterKey":
        if len(b) != MASTERKEY_SIZE:
            raise AmiiboError("master key must be 80 bytes")
        hmac_key = b[0:16]
        type_string = b[16:30]
        # b[30] = rfu
        magic_size = b[31]
        magic_bytes = b[32:48]
        xor_pad = b[48:80]
        if magic_size > 16:
            raise AmiiboError("invalid key (magicBytesSize > 16)")
        return cls(hmac_key, type_string, magic_size, magic_bytes, xor_pad)


@dataclass
class DerivedKeys:
    aes_key: bytes   # 16
    aes_iv: bytes    # 16
    hmac_key: bytes  # 16


@dataclass
class AmiiboKeys:
    data: MasterKey
    tag: MasterKey

    @classmethod
    def from_bytes(cls, b: bytes) -> "AmiiboKeys":
        if len(b) != KEYFILE_SIZE:
            raise AmiiboError(f"key file must be {KEYFILE_SIZE} bytes, got {len(b)}")
        return cls(MasterKey.parse(b[0:80]), MasterKey.parse(b[80:160]))

    @classmethod
    def load(cls, path: str) -> "AmiiboKeys":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())


# -- key derivation --------------------------------------------------------
def _calc_seed(dump: bytes) -> bytes:
    s = bytearray(64)
    s[0x00:0x02] = dump[0x029:0x02B]
    # s[0x02:0x10] left zero
    s[0x10:0x18] = dump[0x1D4:0x1DC]
    s[0x18:0x20] = dump[0x1D4:0x1DC]
    s[0x20:0x40] = dump[0x1E8:0x208]
    return bytes(s)


def _prepare_seed(mk: MasterKey, seed: bytes) -> bytes:
    out = bytearray()
    # 1: type string, copied up to and including the first NUL (memccpy)
    ts = mk.type_string
    nul = ts.find(0)
    out += ts if nul == -1 else ts[: nul + 1]
    # 2: (16 - magic_size) leading bytes of the seed
    leading = 16 - mk.magic_size
    out += seed[0:leading]
    # 3: magic bytes
    out += mk.magic_bytes[: mk.magic_size]
    # 4: seed bytes 0x10..0x20
    out += seed[0x10:0x20]
    # 5: seed bytes 0x20..0x40 XOR xor_pad
    out += bytes(seed[0x20 + i] ^ mk.xor_pad[i] for i in range(32))
    return bytes(out)


def _drbg(hmac_key: bytes, seed: bytes, out_size: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < out_size:
        out += _hmac256(hmac_key, bytes([(counter >> 8) & 0xFF, counter & 0xFF]) + seed)
        counter += 1
    return bytes(out[:out_size])


def _keygen(mk: MasterKey, internal: bytes) -> DerivedKeys:
    prepared = _prepare_seed(mk, _calc_seed(internal))
    d = _drbg(mk.hmac_key, prepared, 48)
    return DerivedKeys(d[0:16], d[16:32], d[32:48])


# -- format conversion (tag <-> internal) ----------------------------------
def tag_to_internal(tag: bytes) -> bytearray:
    if len(tag) != DUMP_SIZE:
        raise AmiiboError(f"dump must be {DUMP_SIZE} bytes")
    i = bytearray(DUMP_SIZE)
    i[0x000:0x008] = tag[0x008:0x010]
    i[0x008:0x028] = tag[0x080:0x0A0]
    i[0x028:0x04C] = tag[0x010:0x034]
    i[0x04C:0x1B4] = tag[0x0A0:0x208]
    i[0x1B4:0x1D4] = tag[0x034:0x054]
    i[0x1D4:0x1DC] = tag[0x000:0x008]
    i[0x1DC:0x208] = tag[0x054:0x080]
    i[0x208:0x21C] = tag[0x208:0x21C]  # trailing config, carried through
    return i


def internal_to_tag(intl: bytes) -> bytearray:
    t = bytearray(DUMP_SIZE)
    t[0x008:0x010] = intl[0x000:0x008]
    t[0x080:0x0A0] = intl[0x008:0x028]
    t[0x010:0x034] = intl[0x028:0x04C]
    t[0x0A0:0x208] = intl[0x04C:0x1B4]
    t[0x034:0x054] = intl[0x1B4:0x1D4]
    t[0x000:0x008] = intl[0x1D4:0x1DC]
    t[0x054:0x080] = intl[0x1DC:0x208]
    t[0x208:0x21C] = intl[0x208:0x21C]
    return t


def _cipher_into(dk: DerivedKeys, src: bytes, out: bytearray) -> None:
    ctr = Counter.new(128, initial_value=int.from_bytes(dk.aes_iv, "big"))
    aes = AES.new(dk.aes_key, AES.MODE_CTR, counter=ctr)
    out[0x02C:0x1B4] = aes.encrypt(bytes(src[0x02C:0x1B4]))
    out[0x000:0x008] = src[0x000:0x008]
    out[0x028:0x02C] = src[0x028:0x02C]
    out[0x1D4:0x208] = src[0x1D4:0x208]
    out[0x208:0x21C] = src[0x208:0x21C]
    # HMAC regions (0x008..0x028, 0x1B4..0x1D4) intentionally left untouched.


# -- public API ------------------------------------------------------------
def unpack(keys: AmiiboKeys, tag: bytes) -> tuple[bytes, bool]:
    """Decrypt a tag-format amiibo dump. Returns (plain_internal, hmac_valid)."""
    internal = tag_to_internal(tag)
    data_keys = _keygen(keys.data, internal)
    tag_keys = _keygen(keys.tag, internal)

    plain = bytearray(DUMP_SIZE)
    _cipher_into(data_keys, internal, plain)
    # Tag HMAC first — the data HMAC covers it.
    plain[0x1B4:0x1D4] = _hmac256(tag_keys.hmac_key, bytes(plain[0x1D4:0x1D4 + 0x34]))
    plain[0x008:0x028] = _hmac256(data_keys.hmac_key, bytes(plain[0x029:0x029 + 0x1DF]))

    valid = (
        plain[0x008:0x028] == internal[0x008:0x028]
        and plain[0x1B4:0x1D4] == internal[0x1B4:0x1D4]
    )
    return bytes(plain), valid


def pack(keys: AmiiboKeys, plain: bytes) -> bytes:
    """Encrypt an internal-format (decrypted) amiibo dump into tag format."""
    if len(plain) != DUMP_SIZE:
        raise AmiiboError(f"dump must be {DUMP_SIZE} bytes")
    tag_keys = _keygen(keys.tag, plain)
    data_keys = _keygen(keys.data, plain)

    cipher = bytearray(DUMP_SIZE)
    cipher[0x1B4:0x1D4] = _hmac256(tag_keys.hmac_key, bytes(plain[0x1D4:0x1D4 + 0x34]))
    data_hmac_input = (
        bytes(plain[0x029:0x029 + 0x18B])
        + bytes(cipher[0x1B4:0x1B4 + 0x20])
        + bytes(plain[0x1D4:0x1D4 + 0x34])
    )
    cipher[0x008:0x028] = _hmac256(data_keys.hmac_key, data_hmac_input)
    _cipher_into(data_keys, plain, cipher)
    return bytes(internal_to_tag(cipher))

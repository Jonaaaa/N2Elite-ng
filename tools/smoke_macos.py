"""Exercise the frozen CLI offline with synthetic keys and tag bytes."""
from pathlib import Path
import hashlib
import importlib.util
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from n2elite.amiibo import crypto


def main():
    cli = str(ROOT / "dist/macos/n2elite-ng-cli")
    subprocess.run([cli, "--version"], check=True, timeout=30)
    subprocess.run([cli, "--help"], check=True, capture_output=True, timeout=30)
    ports = subprocess.run(
        [cli, "ports"], capture_output=True, text=True, timeout=30,
    )
    no_ports = (
        ports.returncode == 1 and ports.stdout.strip() == "No serial ports found."
        and not ports.stderr
    )
    if not no_ports:
        ports.check_returncode()
    print(ports.stdout)
    spec = importlib.util.spec_from_file_location(
        "crypto_tests", ROOT / "tests/test_amiibo_crypto.py"
    )
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)

    with tempfile.TemporaryDirectory(prefix="n2elite-macos-smoke-") as temp:
        folder = Path(temp)
        keys = tests.make_key(1)
        (folder / "synthetic-keys.bin").write_bytes(keys)
        plain = (hashlib.sha256(b"macos packaging smoke test").digest() * 20)[:crypto.DUMP_SIZE]
        packed = crypto.pack(crypto.AmiiboKeys.from_bytes(keys), plain)
        (folder / "encrypted.bin").write_bytes(packed)
        for command in (
            ["decrypt", "-k", "synthetic-keys.bin", "encrypted.bin", "decrypted.bin"],
            ["encrypt", "-k", "synthetic-keys.bin", "decrypted.bin", "roundtrip.bin"],
        ):
            subprocess.run([cli, *command], check=True, cwd=folder, timeout=30)
        if (folder / "roundtrip.bin").read_bytes() != packed:
            raise RuntimeError("Frozen CLI crypto round-trip differs")

        tag = bytearray(540)
        tag[0x54:0x5C] = bytes.fromhex("0100000003530902")
        (folder / "synthetic-id.bin").write_bytes(tag)
        result = subprocess.run(
            [cli, "identify", "synthetic-id.bin"], cwd=folder,
            check=True, capture_output=True, text=True, timeout=30,
        )
        if "Link - Archer" not in result.stdout:
            raise RuntimeError(f"Bundled database lookup failed: {result.stdout}")
        print(result.stdout)
    print("Frozen CLI crypto and bundled database checks passed.")


if __name__ == "__main__":
    main()

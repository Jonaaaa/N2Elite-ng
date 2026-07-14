"""Offline test for the AmiiboAPI -> compact-DB transform (no network)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from n2elite.amiibo import sync  # noqa: E402


def test_transform_maps_id_fields():
    # A minimal AmiiboAPI-shaped payload; Mario 0x0000000000000002.
    full = {
        "amiibos": {"0x0000000000000002": {"name": "Mario"}},
        "characters": {"0x0000": "Mario"},
        "game_series": {"0x000": "Super Mario"},
        "amiibo_series": {"0x00": "Super Smash Bros."},
        "types": {"0x00": "Figure"},
    }
    out = sync._transform(full)
    assert out["0x0000000000000002"] == {
        "name": "Mario",
        "character": "Mario",
        "game": "Super Mario",
        "series": "Super Smash Bros.",
        "type": "Figure",
    }


def test_transform_reproduces_bundled_db_shape():
    # The transform must emit exactly the fields the bundled DB uses.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "n2elite", "amiibo", "amiibo_db.json"),
              encoding="utf-8") as f:
        bundled = json.load(f)
    sample_id, sample_rec = next(iter(bundled.items()))
    assert set(sample_rec) == {"name", "character", "game", "series", "type"}
    # normalise + empty-id filtering behave as sync expects
    assert sync._norm_id("0x2") == "0x0000000000000002"
    assert sync._norm_id("0000000000000002") == "0x0000000000000002"


if __name__ == "__main__":
    test_transform_maps_id_fields()
    test_transform_reproduces_bundled_db_shape()
    print("ok")

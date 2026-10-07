#!/usr/bin/env python3
"""Seed only DSC1 fuzz targets with independent normative witnesses."""
import hashlib
import json
from pathlib import Path

from structured_correspondence import witnesses

ROOT = Path(__file__).resolve().parents[1]


def add(target, data):
    directory = ROOT / "fuzz/corpus" / target
    directory.mkdir(parents=True, exist_ok=True)
    (directory / hashlib.sha256(data).hexdigest()).write_bytes(data)


def main():
    for vector in json.loads((ROOT / "tests/structured/vectors.json").read_text())["vectors"]:
        add("structured_decode", bytes.fromhex(vector["packet_hex"]))
    for _, raw in witnesses():
        if len(raw) <= 70000:
            add("structured_roundtrip", raw)


if __name__ == "__main__":
    main()

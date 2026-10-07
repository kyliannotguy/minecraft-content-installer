#!/usr/bin/env python3
"""Backward-compatible world extraction entry point.

The implementation lives in minecraft_content.py so launcher discovery,
inspection, extraction, and synchronization share the same safety checks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from minecraft_content import ContentError, extract_world


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely extract a Minecraft world ZIP")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("saves_dir", type=Path)
    parser.add_argument("--name")
    args = parser.parse_args()
    try:
        destination, count = extract_world(args.zip_path.expanduser().resolve(), args.saves_dir, args.name)
    except (ContentError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Installed world: {destination}")
    print(f"Files written: {count}")
    print(f"Verified: {destination / 'level.dat'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

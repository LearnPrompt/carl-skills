#!/usr/bin/env python3
"""Install all installable Carl Skills into Hermes Agent."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry.json"


def load_registry() -> dict:
    with REGISTRY.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install all installable Carl Skills into Hermes Agent.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--yes", "-y", action="store_true", help="Pass --yes to hermes skills install.")
    parser.add_argument("--category", default="carl-skills", help="Hermes skill category folder.")
    args = parser.parse_args()

    registry = load_registry()
    skills = [s for s in registry.get("skills", []) if s.get("installable")]

    if not skills:
        print("No installable skills found in registry.json")
        return 0

    hermes = shutil.which("hermes")
    if not hermes and not args.dry_run:
        print("ERROR: hermes CLI not found. Install Hermes Agent first or run with --dry-run.", file=sys.stderr)
        return 1

    for skill in skills:
        identifier = skill.get("raw_skill_url") or skill.get("path")
        if not identifier:
            print(f"SKIP {skill.get('id', '<unknown>')}: no install URL/path")
            continue

        cmd = [hermes or "hermes", "skills", "install", identifier, "--category", args.category]
        if args.yes:
            cmd.append("--yes")

        print("+ " + " ".join(cmd))
        if not args.dry_run:
            subprocess.run(cmd, check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Inventory lab files with before/after SHA-256. This is not a system-wide change log."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def excluded(name: str) -> bool:
    key = name.casefold()
    return (key in {".git", ".private", "__pycache__", "state.json"}
            or key.startswith(".env") or key.endswith(".pyc"))


def inventory(root: Path) -> dict[str, str]:
    files = {}
    for directory, folders, names in os.walk(root, followlinks=False):
        base = Path(directory)
        folders[:] = sorted(name for name in folders if not excluded(name)
                            and (base / name).resolve() == base / name)
        for name in sorted(names):
            path = base / name
            if name == "manifest.json" or excluded(name) or path.resolve() != path or not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            files[path.relative_to(root).as_posix()] = digest.hexdigest()
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("--baseline", action="store_true", help="capture an existing lab before changes")
    args = parser.parse_args()
    root = args.lab.resolve()
    if not (root / "PREDICTIONS.md").is_file():
        parser.error("select a lab root containing PREDICTIONS.md")
    path = root / "manifest.json"
    if path.is_symlink():
        parser.error("manifest.json may not be a link")
    if args.baseline and path.exists():
        parser.error("a manifest already exists; the baseline is left unchanged")
    actual = inventory(root)
    before = actual if args.baseline else None
    if path.is_file():
        stored = json.loads(path.read_text(encoding="utf-8"))
        before = stored.get("baseline")
    rows = {name: {"before": (before or {}).get(name), "after": actual.get(name)}
            for name in sorted((before or {}).keys() | actual.keys())}
    with path.open("x" if args.baseline else "w", encoding="utf-8") as stream:
        json.dump({"schema": 1, "baseline": before, "files": rows}, stream,
                  indent=2, ensure_ascii=False)
        stream.write("\n")
    state = 'unknown' if before is None else (f'{len(before)} prior files' if before else 'new lab (no prior files)')
    print(f"manifest: {len(rows)} files; baseline: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

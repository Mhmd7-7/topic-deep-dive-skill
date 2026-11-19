#!/usr/bin/env python3
"""Write one fresh, unused prediction before recording a new lab command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from tempfile import NamedTemporaryFile
from datetime import datetime, timezone
from pathlib import Path

MAX_TEXT = 400


def find_lab_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "PREDICTIONS.md").is_file():
            return candidate
    return current


def local_path(name: str) -> Path:
    path = find_lab_root() / name
    if path.resolve() != path:
        raise ValueError(f"{name} may not be a link")
    return path


def read_ledger() -> list[dict]:
    path = local_path("predictions.jsonl")
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    if any(not isinstance(row, dict) or type(row.get("id")) is not int
           or not isinstance(row.get("at"), str) or not isinstance(row.get("text"), str) for row in rows):
        raise ValueError("invalid prediction ledger row")
    return rows


def binding(row: dict) -> str:
    """Hash only the immutable prediction fields; usage is added to the ledger later."""
    data = {key: row[key] for key in ("id", "at", "written_ns", "text") if key in row}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def status_of(row: dict) -> str:
    if row.get("used_by") is not None:
        return f"run #{row['used_by']}"
    if row.get("cancelled_at"):
        return f"cancelled: {row['cancel_reason']}"
    return "open"


def atomic_text(path: Path, text: str) -> None:
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                            prefix=f".{path.name}.", delete=False) as stream:
        staged = Path(stream.name)
        try:
            stream.write(text)
            stream.close()
            os.replace(staged, path)
        finally:
            stream.close()
            staged.unlink(missing_ok=True)


def write_ledger(rows: list[dict]) -> None:
    path = local_path("predictions.jsonl")
    view_path = local_path("PREDICTIONS.md")
    atomic_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    view = ["# Predictions", "", "Written before the run they belong to.", ""]
    view.extend(f"- **P{row['id']}** `{row['at']}` — {row['text']} ({status_of(row)})" for row in rows)
    atomic_text(view_path, "\n".join(view) + "\n")


def pending(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("used_by") is None and not row.get("cancelled_at")]


def open_entries(max_age_minutes: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [row for row in pending(read_ledger())
            if 0 <= (now - datetime.fromisoformat(row["at"])).total_seconds() <= max_age_minutes * 60]


def reconcile(initial_runs: dict[int, int]) -> None:
    """Recover usage if recording stopped after committing a run but before updating its prediction."""
    rows = read_ledger()
    changed = False
    for row in rows:
        run_id = initial_runs.get(row["id"])
        if run_id is not None and row.get("used_by") is None and not row.get("cancelled_at"):
            row["used_by"] = run_id
            changed = True
    if changed:
        write_ledger(rows)


def reconcile_runs(runs: list[dict]) -> None:
    initial = {}
    for run in runs:
        if type(run.get("prediction_id")) is int:
            initial.setdefault(run["prediction_id"], run["id"])
    reconcile(initial)


def acknowledge(run_id: int, prediction_id: int) -> None:
    reconcile({prediction_id: run_id})


def single_line(text: str) -> str:
    text = text.strip()
    if not text or len(text) > MAX_TEXT or any(ch in text for ch in "\r\n"):
        raise ValueError(f"use a nonempty single line of at most {MAX_TEXT} characters")
    return text


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add").add_argument("text")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("reason")
    cancel.add_argument("--id", type=int)
    sub.add_parser("status")
    args = parser.parse_args(argv[1:])
    try:
        root = find_lab_root()
        if root != Path.cwd().resolve() or not (root / "PREDICTIONS.md").is_file():
            raise ValueError("run this command from the lab root (the directory with PREDICTIONS.md)")
        from run_log import load_runs

        reconcile_runs(load_runs(root))
        rows = read_ledger()
        if args.cmd == "status":
            for row in rows:
                print(f"P{row['id']} {row['at']} [{status_of(row)}] {row['text']}")
            if not rows:
                print("no predictions recorded")
        elif args.cmd == "add":
            if pending(rows):
                raise ValueError("a prediction is already open; run it or cancel it with a reason")
            text = single_line(args.text)
            row = {"id": max((item["id"] for item in rows), default=0) + 1,
                   "written_ns": time.time_ns(), "at": datetime.now(timezone.utc).isoformat(),
                   "text": text, "used_by": None}
            write_ledger(rows + [row])
            print(f"recorded P{row['id']}")
        else:
            candidates = [row for row in pending(rows) if args.id is None or row["id"] == args.id]
            if len(candidates) != 1:
                raise ValueError("expected one open prediction; use --id to identify it if there are several")
            chosen = candidates[0]
            chosen.update(cancel_reason=single_line(args.reason), cancelled_at=datetime.now(timezone.utc).isoformat())
            write_ledger(rows)
            print(f"cancelled P{chosen['id']}")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

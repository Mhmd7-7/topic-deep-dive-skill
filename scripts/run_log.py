#!/usr/bin/env python3
"""Record a predicted experiment and hash the resulting evidence (not its truth).

Run from the lab root. Pass the command as separate arguments after `--`.
Replay runs code; it is opt-in for reviewed offline, lab-contained commands only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import prediction
from manifest import excluded

TRACKED = ("out", "transfer")
REPLAY_ENV = {"path", "pathext", "systemroot", "windir", "comspec", "temp", "tmp", "tmpdir",
              "lang", "lc_all", "lc_ctype"}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_json(data: object) -> str:
    return sha_bytes(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def snapshot(root: Path) -> dict[str, dict]:
    files = {}
    for folder in TRACKED:
        start = root / folder
        if not start.is_dir() or start.resolve() != start:
            continue
        for directory, folders, names in os.walk(start, followlinks=False):
            base = Path(directory)
            folders[:] = sorted(name for name in folders if not excluded(name)
                                and (base / name).resolve() == base / name)
            for name in sorted(names):
                path = base / name
                if excluded(name) or path.resolve() != path or not path.is_file():
                    continue
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        digest.update(block)
                files[path.relative_to(root).as_posix()] = {
                    "sha": digest.hexdigest(), "mtime_ns": path.stat().st_mtime_ns}
    return files


def load_runs(root: Path) -> list[dict]:
    ledger = root / "runs.jsonl"
    if ledger.resolve() != ledger:
        raise ValueError("runs.jsonl may not be a link")
    if not ledger.exists():
        return []
    runs = []
    previous = ""
    for line in ledger.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("run ledger contains an invalid row")
        ignore = {"hash"} if row.get("schema") == 2 else {"hash", "prev_hash"}
        public = {key: value for key, value in row.items() if key not in ignore}
        if row.get("id") != len(runs) + 1 or row.get("prev_hash") != previous or row.get("hash") != sha_json(public):
            raise ValueError("run ledger hash chain is invalid; inspect it before continuing")
        previous = row["hash"]
        runs.append(row)
    return runs


def execute(command: list[str], root: Path, run_id: int, timeout: float, *,
            offline_replay: bool = False) -> tuple[int, bytes, bytes, str]:
    env = ({k: v for k, v in os.environ.items() if k.casefold() in REPLAY_ENV}
           if offline_replay else os.environ.copy())
    env.update(TOPIC_LAB_RUN_ID=str(run_id), PYTHONDONTWRITEBYTECODE="1")
    program = command[0]
    if not Path(program).anchor and any(separator in program for separator in "/\\"):
        program = str(root / program)
    try:
        result = subprocess.run([program, *command[1:]], cwd=root, env=env,
                                capture_output=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr, "exited"
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or b"", exc.stderr or b"", "timeout"
    except OSError as exc:
        return 127, b"", type(exc).__name__.encode("ascii"), "launch-error"


def record(root: Path, command: list[str], allow_replication: bool,
           replay_safe: bool, timeout: float, case: str | None) -> int:
    rows = load_runs(root)
    prediction.reconcile_runs(rows)
    previous = next((row for row in rows if row.get("case") == case and (row.get("argv") == command or
                     ("argv" not in row and row.get("cmd") == " ".join(command)))), None)
    open_rows = prediction.open_entries(60)
    if previous:
        if not allow_replication:
            raise ValueError(f"command already recorded as run #{previous['id']}; use --allow-replication")
        if open_rows:
            raise ValueError("replication reuses its original prediction; cancel the unused one first")
        chosen = next((p for p in prediction.read_ledger() if p["id"] == previous["prediction_id"]), None)
        if chosen is None:
            raise ValueError("original prediction is missing")
    else:
        if len(open_rows) != 1:
            raise ValueError(f"expected one fresh open prediction, found {len(open_rows)}; use prediction.py")
        chosen = open_rows[0]

    run_id = len(rows) + 1
    before = snapshot(root)
    started = time.time_ns()
    status, stdout, stderr, outcome = execute(command, root, run_id, timeout, offline_replay=replay_safe)
    after = snapshot(root)
    changed = [name for name, meta in after.items() if before.get(name) != meta]
    removed = sorted(before.keys() - after.keys())
    entry = {
        "id": run_id,
        "schema": 2,
        "at": datetime.now(timezone.utc).isoformat(),
        "started_ns": started,
        "cmd": shlex.join(command),  # display only; never parse it to replay
        "argv": command,
        "cmd_hash": sha_json(command),
        "exit": status,
        "outcome": outcome,
        "timeout_s": timeout,
        "stdout_sha": sha_bytes(stdout),
        "stderr_sha": sha_bytes(stderr),
        "prediction_id": chosen["id"],
        "prediction_sha": prediction.binding(chosen),
        "replication": previous is not None,
        "case": case,
        "replay_safe": replay_safe and not removed and not any(name in before for name in changed),
        "out": after,
        "changed": changed,
        "removed": removed,
    }
    entry["prev_hash"] = rows[-1]["hash"] if rows else ""
    entry["hash"] = sha_json(entry)
    with (root / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if previous is None:
        prediction.acknowledge(run_id, chosen["id"])
    print(f"run #{run_id}: {outcome}, exit={status}; P{chosen['id']}; "
          f"{'replication; ' if previous else ''}{len(entry['changed'])} evidence file(s) changed")
    return status if status >= 0 else 1


def replay(root: Path, run_id: int) -> int:
    row = next((item for item in load_runs(root) if item["id"] == run_id), None)
    if row is None:
        raise ValueError(f"no such run: {run_id}")
    if row.get("replay_safe") is not True or not isinstance(row.get("argv"), list):
        raise ValueError("run was not recorded with --replay-safe; no command was executed")
    command = row["argv"]
    if not command or not all(isinstance(part, str) for part in command):
        raise ValueError("recorded argument vector is invalid")
    report_path = root / "replay.json"
    if report_path.resolve() != report_path:
        raise ValueError("replay.json may not be a link")
    products = set(row["changed"])

    def ignore(directory: str, names: list[str]) -> set[str]:
        base = Path(directory)
        return {name for name in names if excluded(name) or name in {"replay.json", "runs.jsonl"}
                or (base / name).resolve() != base / name
                or (base / name).relative_to(root).as_posix() in products}

    arguments = [Path(value) for value in command[1:]]
    if any(path.anchor or ".." in path.parts for path in arguments):
        raise ValueError("replay needs lab-relative input/output arguments; no command was executed")
    program = command[0]
    executable = Path(program)
    if ".." in executable.parts:
        raise ValueError("replay does not accept parent-relative executables")
    with tempfile.TemporaryDirectory(prefix="topic-replay-") as work:
        copy = Path(work).resolve() / "lab"
        shutil.copytree(root, copy, ignore=ignore)
        if executable.is_absolute() and executable.is_relative_to(root):
            program = str(copy / executable.relative_to(root))
        before = snapshot(copy)
        status, stdout, stderr, outcome = execute([program, *command[1:]], copy, run_id,
                                                  row["timeout_s"], offline_replay=True)
        actual = snapshot(copy)
    changed = {name for name, meta in actual.items() if before.get(name) != meta}
    removed = before.keys() - actual.keys()
    evidence = {name: actual.get(name, {}).get("sha") == row["out"][name]["sha"]
                for name in sorted(products) if PurePosixPath(name).parts[0] in TRACKED}
    report = {"id": run_id, "exit_match": status == row["exit"], "outcome_match": outcome == row["outcome"],
              "stdout_match": sha_bytes(stdout) == row["stdout_sha"],
              "stderr_match": sha_bytes(stderr) == row["stderr_sha"], "evidence_matches": evidence,
              "changed_paths_match": changed == products and not removed}
    matches = all(value for key, value in report.items() if key.endswith("_match")) and all(evidence.values())
    report["matches"] = matches
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"replay #{run_id}: {'matched' if matches else 'different'}; see replay.json")
    return 0 if matches else 1


def main(argv: list[str]) -> int:
    args = argv[1:]
    try:
        root = prediction.find_lab_root()
        if root != Path.cwd().resolve() or not (root / "PREDICTIONS.md").is_file():
            raise ValueError("run this command from the lab root (the directory with PREDICTIONS.md)")
        if args == ["seal"]:
            rows = load_runs(root)
            if not rows:
                raise ValueError("no runs recorded")
            if any(row.get("schema") != 2 for row in rows):
                raise ValueError("sealing requires a fresh lab with only new-format runs")
            print(rows[-1]["hash"])
            return 0
        if args[:1] == ["replay"]:
            parser = argparse.ArgumentParser(prog="run_log.py replay")
            parser.add_argument("--id", type=int, required=True)
            return replay(root, parser.parse_args(args[1:]).id)
        parser = argparse.ArgumentParser(description=__doc__,
                                         usage="%(prog)s [options] -- program [arguments ...]")
        parser.add_argument("--allow-replication", action="store_true")
        parser.add_argument("--case", help="short label for a variation using the same command")
        parser.add_argument("--replay-safe", action="store_true")
        parser.add_argument("--timeout", type=float, default=90, help="per-run timeout in seconds (default: 90)")
        split = args.index("--") if "--" in args else len(args)
        options = parser.parse_args(args[:split])
        command = args[split + 1:]
        if not command:
            parser.error("a command must follow --")
        if not math.isfinite(options.timeout) or options.timeout <= 0:
            parser.error("--timeout must be a positive finite duration")
        case = prediction.single_line(options.case) if options.case is not None else None
        return record(root, command, options.allow_replication, options.replay_safe, options.timeout, case)
    except (OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

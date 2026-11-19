#!/usr/bin/env python3
"""Predeclare transfer criteria, then compute arm verdicts from observations.

    python scripts/transfer.py plan transfer/plan.json          # before the recorded run
    python scripts/transfer.py check transfer/observations.json # writes transfer/transfer_result.json

A plan states, per arm, the criterion the recommended or naive method must meet and whether this
arm predicts the criterion is met or unmet. A negative arm therefore predicts `unmet`: the naive
method should fail the same criterion the positive arm must satisfy. The verdict is computed here;
the `pass` field is never taken on trust.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from prediction import atomic_text, find_lab_root

SCHEMA = 1
RESULT_SCHEMA = 2
KINDS = ("positive", "negative")
EXPECTATIONS = ("met", "unmet")
OPS = ("equals", "not_equals", "contains", "matches")


def read_json(path: Path, what: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {what}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{what} is not valid JSON: {exc}") from exc


def check_criterion(criterion: object, where: str) -> dict:
    if not isinstance(criterion, dict):
        raise ValueError(f"{where}: criterion must be an object with op and value")
    op = criterion.get("op")
    if op not in OPS:
        raise ValueError(f"{where}: criterion op must be one of {', '.join(OPS)}")
    if "value" not in criterion:
        raise ValueError(f"{where}: criterion needs a value")
    value = criterion["value"]
    if op == "matches":
        if not isinstance(value, str) or not value:
            raise ValueError(f"{where}: matches needs a nonempty regular expression")
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"{where}: invalid regular expression: {exc}") from exc
    if op == "contains" and isinstance(value, (list, dict)):
        raise ValueError(f"{where}: contains needs a scalar value")
    return {"op": op, "value": value}


def normalize_arm(arm: object, where: str) -> dict:
    """Validate one planned arm and return the fields the checker recomputes."""
    if not isinstance(arm, dict):
        raise ValueError(f"{where}: arm must be an object")
    kind = arm.get("kind")
    if kind not in KINDS:
        raise ValueError(f"{where}: kind must be positive or negative")
    case = arm.get("case")
    if not isinstance(case, str) or not case.strip():
        raise ValueError(f"{where}: describe the case in a nonempty string")
    expect = arm.get("expect")
    if expect not in EXPECTATIONS:
        raise ValueError(f"{where}: expect must be met or unmet")
    if kind == "negative" and expect != "unmet":
        raise ValueError(f"{where}: a negative arm must predict that the criterion is unmet")
    if kind == "positive" and expect != "met":
        raise ValueError(f"{where}: a positive arm must predict that the criterion is met")
    return {"kind": kind, "case": case.strip(), "expect": expect,
            "criterion": check_criterion(arm.get("criterion"), where)}


def evaluate(criterion: dict, observed: object) -> bool:
    """Return whether an observed value meets a predeclared criterion."""
    op, value = criterion["op"], criterion["value"]
    if op == "equals":
        return observed == value
    if op == "not_equals":
        return observed != value
    if op == "contains":
        if isinstance(observed, str):
            return value in observed
        if isinstance(observed, list):
            return value in observed
        return False
    text = observed if isinstance(observed, str) else json.dumps(observed, ensure_ascii=False, sort_keys=True)
    return bool(re.search(value, text))


def verdict(arm: dict, observed: object) -> dict:
    met = evaluate(arm["criterion"], observed)
    return {"met": met, "pass": met == (arm["expect"] == "met")}


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_evidence(value: object, root: Path) -> str:
    """Accept only an existing lab-local evidence file under out/ or transfer/."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("each observation needs an evidence path")
    parts = PurePosixPath(value.strip()).parts
    if parts[0] not in ("out", "transfer") or ".." in parts or "\\" in value or ":" in value:
        raise ValueError(f"evidence must be a relative path under out/ or transfer/: {value}")
    path = root / value
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"evidence file is missing locally: {value}")
    return value


def plan(source: Path, root: Path, replace: bool) -> int:
    document = read_json(source, str(source))
    arms = document.get("arms") if isinstance(document, dict) else None
    if not isinstance(arms, list) or len(arms) != 2:
        raise ValueError("the plan must contain exactly two arms: one positive and one negative")
    normalized = [normalize_arm(arm, f"arm {number}") for number, arm in enumerate(arms, 1)]
    if sorted(arm["kind"] for arm in normalized) != ["negative", "positive"]:
        raise ValueError("the plan needs exactly one positive and one negative arm")
    target = root / "transfer" / "criteria.json"
    if target.exists() and not replace:
        raise ValueError("transfer/criteria.json already exists; predeclared criteria are not rewritten")
    payload = {"schema": SCHEMA, "written_ns": time.time_ns(),
               "at": datetime.now(timezone.utc).isoformat(), "arms": normalized}
    atomic_text(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"criteria recorded in {target.relative_to(root).as_posix()} before the run: "
          f"{', '.join(arm['kind'] + ' expects ' + arm['expect'] for arm in normalized)}")
    return 0


def check(source: Path, root: Path, replace: bool) -> int:
    criteria_path = root / "transfer" / "criteria.json"
    if not criteria_path.is_file():
        raise ValueError("transfer/criteria.json is missing; record the criteria before running")
    document = read_json(criteria_path, "transfer/criteria.json")
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or not isinstance(document.get("arms"), list):
        raise ValueError("transfer/criteria.json is not a plan written by this helper")
    observed = read_json(source, str(source))
    if not isinstance(observed, dict):
        raise ValueError("observations must be an object keyed by positive and negative")
    arms = []
    failed = []
    for number, planned in enumerate(document["arms"], 1):
        arm = normalize_arm(planned, f"criteria.json arm {number}")
        entry = observed.get(arm["kind"])
        if not isinstance(entry, dict) or "observed" not in entry or entry["observed"] is None:
            raise ValueError(f"no observation recorded for the {arm['kind']} arm")
        item = {**arm, "observed": entry["observed"],
                "evidence": relative_evidence(entry.get("evidence"), root)}
        item.update(verdict(arm, item["observed"]))
        if not item["pass"]:
            failed.append(arm["kind"])
        arms.append(item)
    missing = [kind for kind in KINDS if kind not in {arm["kind"] for arm in arms}]
    if missing:
        raise ValueError(f"the criteria do not cover these arms: {', '.join(missing)}")
    result_path = root / "transfer" / "transfer_result.json"
    if result_path.exists() and not replace:
        raise ValueError("transfer/transfer_result.json already exists; pass --replace to record a repeat")
    payload = {"schema": RESULT_SCHEMA, "criteria_sha": sha_file(criteria_path), "arms": arms}
    atomic_text(result_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    for arm in arms:
        state = "passed as predicted" if arm["pass"] else "did not match its prediction"
        print(f"{arm['kind']}: criterion {arm['criterion']['op']} -> met={arm['met']}; {state}")
    if failed:
        print(f"recorded a failing arm ({', '.join(failed)}); it blocks Verified mastery until a new case passes")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, text in (("plan", "transfer/plan.json"), ("check", "transfer/observations.json")):
        command = sub.add_parser(name)
        command.add_argument("source", type=Path, nargs="?", default=Path(text))
        command.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv[1:])
    try:
        root = find_lab_root()
        if root != Path.cwd().resolve():
            raise ValueError("run this command from the lab root (the directory with PREDICTIONS.md)")
        if not (root / "transfer").is_dir():
            raise ValueError("the lab has no transfer/ directory")
        source = args.source if args.source.is_absolute() else root / args.source
        if args.cmd == "plan":
            return plan(source, root, args.replace)
        return check(source, root, args.replace)
    except (OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

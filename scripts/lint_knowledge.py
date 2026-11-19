#!/usr/bin/env python3
"""Check a topic lab's format and evidence provenance, not the truth of its conclusions.

Run with: python scripts/lint_knowledge.py . [--json] [--anchor HASH]
Legacy run ledgers are readable; only schema-2-only ledgers support a pinned chain head.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

from prediction import binding
from transfer import evaluate, normalize_arm

STATES = {"verified", "documented-only", "blocked", "impossible", "untested"}
TAGS = ("MEASURED", "SOURCE", "INFERRED", "UNVERIFIED")
META = {"complete.md", "findings.md", "predictions.md", "predictions.jsonl", "runs.jsonl",
        "replay.json", "manifest.json", "state.json"}
MEASUREMENT = re.compile(r'\[MEASURED n=(\d+), conditions=(.+?), evidence=([^,\]]+), expect="([^"]*)"\]')
TAG_HINT = re.compile(r"\[(measured|source|inferred|unverified|observed|verified|tested)(?=\]|\s|:)", re.I)
SECRET_PATTERNS = {
    "bearer": r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}",
    "basic": r"\bBasic\s+[A-Za-z0-9+/=]{20,}",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.",
    "credential-value": r"\b(?:access_token|refresh_token|client_secret|api_key|password)\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=~-]{8,}",
    "provider-key": r"\b(?:sk-proj-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{20,}|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[A-Za-z0-9_-]{30,})",
    "private-key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def fingerprint(data: object) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def sections(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            character = marker[1][0]
            if fence is None:
                fence = character
            elif fence == character:
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r"^##\s+(?:\d+\.\s*)?(.+?)\s*$", line)
        if heading:
            current = result.setdefault(heading[1].lower(), [])
        else:
            current.append(line)
    return result


def rows(lines: list[str]) -> list[list[str]]:
    data = []
    for line in lines:
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            if any(cells) and not all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                data.append(cells)
    return data[1:]


def tagged(line: str) -> bool:
    return any(f"[{tag}]" in line for tag in TAGS[1:]) or bool(MEASUREMENT.search(line))


def not_run(lines: list[str]) -> bool:
    return any(re.match(r"^\s*(?:-\s*)?Not run:\s+[^<\s]", line, re.I) for line in lines)


def epoch_ns(value: str) -> int:
    return round(datetime.fromisoformat(value).timestamp() * 1_000_000_000)


class Lint:
    def __init__(self, root: Path, anchor: str | None):
        self.root = root
        self.anchor = anchor
        self.findings: list[dict] = []
        self.advisories: list[dict] = []
        self.runs: list[dict] = []
        self.predictions: dict[int, dict] = {}
        self.produced: dict[str, dict] = {}
        self.status = ""

    def flag(self, check: str, message: str, where: str = "") -> None:
        self.findings.append({"check": check, "message": message, "where": where})

    def advisory(self, check: str, message: str, where: str = "") -> None:
        """Readable limitation that does not fail the report by itself."""
        self.advisories.append({"check": check, "message": message, "where": where})

    def objects(self, name: str, check: str):
        path = self.root / name
        if not path.is_file():
            return
        if path.resolve() != path:
            self.flag(check, f"{name} may not be a link")
            return
        for number, line in enumerate(read(path).split("\n"), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            where = f"{name}:{number}"
            if not isinstance(row, dict):
                self.flag(check, "expected a JSON object", where)
            else:
                yield row, where

    def load(self) -> None:
        for row, where in self.objects("predictions.jsonl", "L8"):
            pid = row.get("id")
            if type(pid) is not int or pid < 1 or pid in self.predictions or not isinstance(row.get("text"), str):
                self.flag("L8", "invalid or duplicate prediction", where)
            else:
                self.predictions[pid] = row
        previous = ""
        legacy = False
        for item, where in self.objects("runs.jsonl", "L15"):
            modern = item.get("schema") == 2
            legacy |= not modern
            ignored = {"hash"} if modern else {"prev_hash", "hash"}
            data = {key: value for key, value in item.items() if key not in ignored}
            if item.get("id") != len(self.runs) + 1 or item.get("prev_hash") != previous \
                    or item.get("hash") != fingerprint(data):
                self.flag("L15", "run ID or hash chain does not match", where)
            previous = item.get("hash", "")
            self.runs.append(item)
            if modern:
                args = item.get("argv")
                if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args) \
                        or item.get("cmd_hash") != fingerprint(args):
                    self.flag("L15", "argument list does not match its hash", where)
                self.check_prediction(item, where)
            output = item.get("out")
            if not isinstance(output, dict):
                continue
            changed = item.get("changed") if modern else None
            if modern and (not isinstance(changed, list) or not all(isinstance(name, str) for name in changed)):
                self.flag("L15", "invalid changed-evidence list", where)
                continue
            for name, meta in output.items():
                if not isinstance(meta, dict):
                    continue
                if modern:
                    made = name in changed
                else:
                    modified, started = meta.get("mtime_ns"), item.get("started_ns")
                    made = type(modified) is int and type(started) is int and modified >= started
                if made:
                    self.produced[name] = {"sha": meta.get("sha"), "exit": item.get("exit")}
        if self.anchor and (not self.runs or legacy or previous != self.anchor):
            self.flag("L15", "chain head does not match the anchor, or the ledger uses legacy seals")

    def check_prediction(self, run: dict, where: str) -> None:
        pid = run.get("prediction_id")
        pred = self.predictions.get(pid) if type(pid) is int else None
        try:
            if not pred or pred.get("cancelled_at"):
                raise ValueError
            if run.get("schema") == 2:
                start = run["started_ns"]
                written = pred["written_ns"] if "written_ns" in pred else epoch_ns(pred["at"])
                first = next(row for row in self.runs if row.get("prediction_id") == pid)
                if type(start) is not int or type(written) is not int or written >= start \
                        or run.get("prediction_sha") != binding(pred) or pred.get("used_by") != first["id"] \
                        or (run["id"] != first["id"] and run.get("replication") is not True):
                    raise ValueError
            elif datetime.fromisoformat(pred["at"]) > datetime.fromisoformat(run["at"]):
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError, StopIteration):
            self.flag("L8", "prediction is missing, edited, not consumed, or not earlier than the run", where)

    def evidence(self, name: str) -> Path | None:
        parts = PurePosixPath(name).parts
        if len(parts) < 2 or parts[0] not in {"out", "transfer"} or ".." in parts or "\\" in name \
                or ":" in name or parts[-1].lower() in META:
            return None
        path = self.root / name
        return path if path.resolve() == path and path.is_file() else None

    def produced_path(self, name: str) -> Path | None:
        path = self.evidence(name)
        record = self.produced.get(name, {})
        if path and record.get("exit") == 0 and hashlib.sha256(path.read_bytes()).hexdigest() == record.get("sha"):
            return path
        return None

    def coverage(self, lines: list[str]) -> None:
        data = rows(lines)
        if not data:
            self.flag("L4", "coverage needs at least one core question")
        for row in data:
            state = row[2].replace("*", "").replace("`", "").strip() if len(row) > 2 else ""
            label = re.split(r"[\s(—]", state, maxsplit=1)[0]
            if label not in STATES:
                self.flag("L4", "use a canonical coverage status")
            if self.status == "mastered" and label != "verified":
                self.flag("L3", "mastery requires every core row to be verified")
            if label == "untested" and not self.partial:
                self.flag("L5", "untested coverage requires a Partial status")
            if label == "verified":
                refs = re.findall(r"`([^`]+)`", row[3]) if len(row) > 3 else []
                if not any(self.produced_path(ref) for ref in refs):
                    self.flag("L12", "verified row lacks unchanged evidence from a successful recorded run")

    def tags(self, text: str) -> None:
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("> LEGEND:"):
                continue
            where = f"COMPLETE.md:{number}"
            for mark in TAG_HINT.finditer(line):
                label = mark[1]
                rest = line[mark.start():]
                if label == "MEASURED":
                    found = MEASUREMENT.match(rest)
                    if not found or int(found[1]) < 1 or found[2].strip() in {"", "-", "...", "…"} or not found[4].strip():
                        self.flag("L6", "malformed measurement tag", where)
                        continue
                    path = self.produced_path(found[3].strip().strip("`"))
                    if not path or found[4] not in read(path):
                        self.flag("L7", "measurement literal missing or evidence is not from a successful recorded run", where)
                elif label not in TAGS or not rest.startswith(f"[{label}]"):
                    self.flag("L6", "non-canonical evidence tag", where)

    def prediction_table(self, lines: list[str]) -> None:
        data = rows(lines)
        if not data:
            if self.runs or self.status != "documented" or not not_run(lines):
                self.flag("L8", "prediction table needs rows or a specific Not run explanation")
            return
        ids = set()
        for row in data:
            match = re.fullmatch(r"P(\d+)", row[0].strip("`*"))
            if match:
                ids.add(int(match[1]))
            else:
                self.flag("L8", "prediction table row must begin with a P-ID")
        for pid in ids:
            matching = [item for item in self.runs if item.get("prediction_id") == pid]
            if not matching:
                self.flag("L8", f"P{pid} was not used by a recorded run")
            for item in matching:
                if item.get("schema") != 2:
                    self.check_prediction(item, f"P{pid}")
        if any(type(item.get("prediction_id")) is not int or item["prediction_id"] not in ids for item in self.runs):
            self.flag("L8", "a run is missing from the prediction table")

    def transfer(self, explanation: list[str]) -> None:
        path = self.evidence("transfer/transfer_result.json")
        if not path:
            if self.status != "documented" or not not_run(explanation):
                self.flag("L16", "missing transfer result or a specific Not run explanation")
            return
        try:
            payload = json.loads(read(path))
        except ValueError:
            self.flag("L16", "transfer result is not valid JSON")
            return
        if isinstance(payload, list):
            self.legacy_transfer(payload)
        elif isinstance(payload, dict):
            self.computed_transfer(payload)
        else:
            self.flag("L16", "transfer result must be an object written by scripts/transfer.py")

    def legacy_transfer(self, arms: list) -> None:
        """Keep old labs readable; a list of declared verdicts cannot be recomputed."""
        seen = set()
        for index, arm in enumerate(arms, 1):
            where = f"transfer_result.json:{index}"
            if not isinstance(arm, dict):
                self.flag("L16", "transfer arm must be an object", where)
                continue
            label = arm.get("arm")
            kind = arm.get("kind") or (label.split("/")[0] if isinstance(label, str) else "")
            if kind not in ("positive", "negative"):
                self.flag("L16", "each arm must specify positive or negative", where)
                continue
            seen.add(kind)
            if any(arm.get(key) is None for key in ("expected", "observed")) or type(arm.get("pass")) is not bool:
                self.flag("L16", "legacy arms need expected, observed and a boolean pass", where)
            elif arm["pass"] is False and self.status != "mastered":
                reason, ref = arm.get("reason"), arm.get("evidence")
                if not isinstance(reason, str) or not reason.strip() or not isinstance(ref, str) or not self.evidence(ref):
                    self.flag("L16", "failed arms must cite a reason and existing local evidence", where)
        if seen != {"positive", "negative"}:
            self.flag("L16", "transfer needs positive and negative arms")
        self.advisory("L16", "legacy transfer result holds declared verdicts and no predeclared criterion, so "
                             "pass/fail cannot be recomputed; re-verify with scripts/transfer.py plan and check")
        if self.status == "mastered":
            self.flag("L3", "Verified mastery needs the criterion-based transfer record; the legacy list cannot support it")

    def computed_transfer(self, result: dict) -> None:
        """Recompute both verdicts from the predeclared criteria and the observed values."""
        arms = result.get("arms")
        if result.get("schema") != 2 or not isinstance(arms, list) or not arms:
            self.flag("L16", "new-format transfer result needs schema 2 and a nonempty arms list")
            return
        maker = next((run for run in reversed(self.runs)
                      if "transfer/transfer_result.json" in run.get("changed", [])), None)
        if maker is None or maker.get("exit") != 0:
            self.flag("L13", "transfer result must be written by a successful recorded run")
            return
        criteria_path = self.evidence("transfer/criteria.json")
        stated = result.get("criteria_sha")
        if not criteria_path or not isinstance(stated, str) \
                or hashlib.sha256(criteria_path.read_bytes()).hexdigest() != stated:
            self.flag("L16", "result must point at the existing transfer/criteria.json it was computed from")
            return
        snapshot = maker.get("out") if isinstance(maker.get("out"), dict) else {}
        meta = snapshot.get("transfer/criteria.json")
        if not isinstance(meta, dict) or meta.get("sha") != stated:
            self.flag("L16", "criteria must be present when the recorded transfer run starts")
        elif "transfer/criteria.json" in maker.get("changed", []):
            self.flag("L16", "criteria changed during the transfer run instead of being written before it")
        try:
            criteria = json.loads(read(criteria_path))
        except ValueError:
            criteria = None
        planned: dict[str, dict] = {}
        for number, arm in enumerate(criteria.get("arms", []) if isinstance(criteria, dict) else [], 1):
            try:
                entry = normalize_arm(arm, f"criteria.json arm {number}")
            except ValueError as exc:
                self.flag("L16", str(exc))
                continue
            planned[entry["kind"]] = entry
        written = criteria.get("written_ns") if isinstance(criteria, dict) else None
        started = maker.get("started_ns")
        if type(written) is not int or type(started) is not int or written >= started:
            self.flag("L16", "criteria were not written before the transfer run")
        seen: set[str] = set()
        failed: list[str] = []
        for index, arm in enumerate(arms, 1):
            where = f"transfer_result.json:arm {index}"
            kind = arm.get("kind")
            if not isinstance(arm, dict) or kind not in ("positive", "negative"):
                self.flag("L16", "each arm needs a positive or negative kind", where)
                continue
            seen.add(kind)
            planned_arm = planned.get(kind)
            if planned_arm is None:
                self.flag("L16", "this arm has no predeclared criterion", where)
                continue
            if any(arm.get(key) != planned_arm[key] for key in ("case", "expect", "criterion")):
                self.flag("L16", "the arm differs from the predeclared case, expectation or criterion", where)
                continue
            observed = arm.get("observed")
            if observed is None:
                self.flag("L16", "the arm has no observed result", where)
                continue
            if self.produced_path(arm.get("evidence")) is None:
                self.flag("L16", "the arm's evidence is missing or was not saved by a successful run", where)
            met = evaluate(planned_arm["criterion"], observed)
            expected_pass = met == (planned_arm["expect"] == "met")
            if type(arm.get("pass")) is not bool:
                self.flag("L16", "the arm needs a boolean pass computed by the checker", where)
            elif arm["pass"] != expected_pass:
                self.flag("L16", f"pass contradicts the recorded observation and criterion "
                                 f"(computed {str(expected_pass).lower()})", where)
            if arm.get("met") is not None and arm["met"] is not met:
                self.flag("L16", "the recorded criterion outcome does not match the observation", where)
            if not expected_pass:
                failed.append(kind)
                if self.status != "mastered":
                    reason = arm.get("reason")
                    if not isinstance(reason, str) or not reason.strip():
                        self.flag("L16", "a failed arm needs a nonempty reason", where)
        if seen != {"positive", "negative"}:
            self.flag("L16", "transfer needs both a positive and a negative arm")
        if self.status == "mastered":
            if failed or seen != {"positive", "negative"}:
                self.flag("L3", "Verified mastery needs both arms computed as passing")
            elif self.produced_path("transfer/transfer_result.json") is None:
                self.flag("L13", "mastery requires transfer evidence from a successful recorded run")
        elif failed:
            self.advisory("L16", "a transfer arm did not pass; the report stays Documented, not mastered")

    def digest(self) -> None:
        """A reusable hand-off summary must be structured and point at its evidence."""
        path = self.root / "DIGEST.md"
        if not path.exists():
            return
        if path.resolve() != path or not path.is_file():
            self.flag("L19", "DIGEST.md must be a local regular file")
            return
        text = read(path)
        headings = sections(text)
        for key in ("practical rules", "pitfalls", "experiment conditions", "unverified"):
            if not any(name.startswith(key) for name in headings):
                self.flag("L19", f"DIGEST.md needs a '{key}' section")
        refs = re.findall(r"`([^`\s]+)`", text) + re.findall(r"\]\(([^)\s]+)\)", text)
        local = [ref.split("#")[0] for ref in refs
                 if ref.split("#")[0] in ("COMPLETE.md", "FINDINGS.md") or ref.startswith(("out/", "transfer/"))]
        if not local:
            self.flag("L19", "DIGEST.md must link its rules to COMPLETE.md or the lab's evidence files")
        for ref in local:
            if ref == "COMPLETE.md":
                continue
            if self.evidence(ref) is None:
                self.flag("L19", "DIGEST.md cites a missing local evidence path", ref)

    def secrets(self) -> None:
        files = [self.root / name for name in ("COMPLETE.md", "FINDINGS.md", "PREDICTIONS.md",
                                                "predictions.jsonl", "runs.jsonl")]
        for part in ("out", "transfer"):
            for directory, folders, names in os.walk(self.root / part, followlinks=False):
                base = Path(directory)
                folders[:] = [name for name in folders if (base / name).resolve() == base / name
                              and name != "__pycache__"]
                files.extend(base / name for name in names)
        for path in files:
            if path.resolve() != path or not path.is_file():
                continue
            text = read(path)
            for kind, pattern in SECRET_PATTERNS.items():
                if re.search(pattern, text, re.I):
                    self.flag("L9", f"possible {kind}; inspect privately, value suppressed", path.relative_to(self.root).as_posix())

    def run(self) -> None:
        complete, log = self.root / "COMPLETE.md", self.root / "FINDINGS.md"
        for path in (complete, log):
            if not path.is_file() or path.resolve() != path:
                self.flag("L1", f"missing or linked {path.name}")
        if not complete.is_file() or complete.resolve() != complete:
            return
        self.load()
        text = read(complete)
        content = sections(text)
        status = [line.strip().lstrip("- ").replace("*", "") for line in content.get("status", [])]
        choices = [label for label, phrase in (("mastered", "Verified mastery"), ("documented", "Documented, not mastered"))
                   if any(re.match(re.escape(phrase) + r"(?:\W|$)", line) for line in status)]
        if len(choices) == 1:
            self.status = choices[0]
        else:
            self.flag("L2", "state either Verified mastery or Documented, not mastered in Status")
        self.partial = any(line.startswith("Partial:") for line in status)
        if self.status == "mastered" and self.partial:
            self.flag("L3", "mastery cannot be partial")
        if not self.runs and (self.status != "documented" or not not_run(content.get("prediction table", []))):
            self.flag("L14", "no recorded runs and no documented Not run explanation")
        self.coverage(content.get("coverage table", []))
        self.tags(text)
        self.prediction_table(content.get("prediction table", []))
        transfer = next((lines for key, lines in content.items() if key.startswith("transfer test")), [])
        self.transfer(transfer)
        for line in content.get("tl;dr", []):
            if re.match(r"^\s*(?:\d+\.|[-*])\s+", line) and not tagged(line):
                self.flag("L17", "TL;DR item without an evidence tag")
        if "tl;dr" not in content:
            self.flag("L17", "missing TL;DR section")
        for title, lines in content.items():
            if re.match(r"^(?:results?|observations?)(?:\W|$)", title):
                for row in rows(lines):
                    if not tagged(" ".join(row)):
                        self.flag("L17", "result row without an evidence tag")
        self.digest()
        self.secrets()
        if log.is_file() and log.resolve() == log and len(read(log).splitlines()) < 15:
            self.flag("L10", "FINDINGS.md looks too short to be an audit trail")
        if (self.root / "replay.json").exists() and "replay" not in text.lower():
            self.flag("L18", "reference does not mention the retained replay")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("--anchor")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    lint = Lint(args.lab.resolve(), args.anchor)
    lint.run()
    if args.json:
        print(json.dumps(lint.findings, indent=2, ensure_ascii=True))
        for item in lint.advisories:
            print(f"advisory {item['check']}: {item['message']}", file=sys.stderr)
        return int(bool(lint.findings))
    for item in lint.findings:
        where = f" ({item['where']})" if item["where"] else ""
        print(f"{item['check']}: {item['message']}{where}")
    for item in lint.advisories:
        where = f" ({item['where']})" if item["where"] else ""
        print(f"advisory {item['check']}: {item['message']}{where}", file=sys.stderr)
    if lint.findings:
        print(f"lint: {len(lint.findings)} finding(s), {len(lint.advisories)} advisory note(s)")
    else:
        print(f"lint: clean (structure and provenance only), {len(lint.advisories)} advisory note(s)")
    return int(bool(lint.findings))


if __name__ == "__main__":
    raise SystemExit(main())

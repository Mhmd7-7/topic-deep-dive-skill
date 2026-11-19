#!/usr/bin/env python3
"""Exercise the installed/extracted skill in throwaway directories. No credentials or network."""
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

SKILL = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
       "TOPIC_TEST_MARKER": "synthetic-test-value"}
PROBE = '''import json
import os
import sys
from pathlib import Path
assert os.getenv("TOPIC_TEST_MARKER") is None
record = {"args": sys.argv[1:], "result": "known output"}
Path("out", os.environ["TOPIC_LAB_RUN_ID"] + ".json").write_text(json.dumps(record), encoding="utf-8")
'''
BLOCKED = '''# Untested fixture

## 0. Status

**Documented, not mastered.**
Partial: item 1 needs a fixture unavailable in this case.

## 1. TL;DR

- [UNVERIFIED] A fixture is needed.

## 4. Coverage table

| # | Question | Status | Evidence |
|---|---|---|---|
| 1 | Fixture-dependent behavior | blocked | Provide a synthetic fixture |

## 5. Transfer test

Not run: the fixture is not available.

## 6. Prediction table

Not run: the fixture is not available, so no command was recorded.
'''

ORACLE = [["a,b", "tail"]]
NAIVE = [["a", "b", "tail"]]

TRANSFER_PROBE = '''import json
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import transfer

NAIVE_SUCCEEDS = __NAIVE__
CRASH = __CRASH__
observed = {"positive": __POSITIVE__, "negative": __NEGATIVE__}
if NAIVE_SUCCEEDS:
    observed["negative"] = __POSITIVE__
entries = {}
for kind, rows in observed.items():
    path = "out/" + kind + ".json"
    Path(path).write_text(json.dumps({"rows": rows}), encoding="utf-8")
    entries[kind] = {"observed": {"rows": rows}, "evidence": path}
Path("transfer/observations.json").write_text(json.dumps(entries), encoding="utf-8")
transfer.check(Path("transfer/observations.json"), Path.cwd(), replace=True)
sys.exit(1 if CRASH else 0)
'''

REFERENCE = '''# Transfer case — reference

> Scope: synthetic quoted-comma fixture only
> Environment: CPython synthetic test, no service or account
> Budget: one recorded run
> LEGEND: [SOURCE] source · [MEASURED n=1, conditions=..., evidence=out/..., expect="..."] observation · [INFERRED] deduction · [UNVERIFIED] gap.

## 0. Status

**__STATUS__**

## 1. TL;DR

- [MEASURED n=1, conditions=quoted comma fixture, evidence=out/positive.json, expect="a,b"] __TLDR__

## 2. Mental model and sources

[SOURCE] Synthetic fixture written for this check; it stands in for an oracle supplied by a primary source.

## 3. Results

| Case | Result | Script |
|---|---|---|
| Quoted comma | [MEASURED n=1, conditions=same fixture, evidence=out/positive.json, expect="a,b"] __ROW__ | `probe.py` |

## 4. Coverage table

| # | Question / capability | Status | Evidence / next action |
|---|---|---|---|
| 1 | Quoted comma | verified | `out/positive.json` |

## 5. Transfer test

__TRANSFER__

## 6. Prediction table

| ID | Prediction before run | Observed result and run ID | Matched? Lesson? |
|---|---|---|---|
| P1 | __PREDICTION__ | Run 1 recorded both arms. | __VERDICT__ |

## 7. Reproduction and restoration

Run `python scripts/run_log.py -- python probe.py` from the lab root. Nothing outside the lab changed.

## 8. Open questions

- [UNVERIFIED] Other dialects and malformed inputs were not tested here.
'''

FINDINGS = '''# Transfer case — working log

## Before the first experiment

- Objective: check that transfer verdicts come from a predeclared criterion.
- Scope: one synthetic fixture, one recorded run.
- Budget: one run.
- Sources: synthetic oracle only.
- Hypothesis: the quoted comma stays in one field.

## Chronological entries

- Run 1: the probe wrote both observations and asked the helper for verdicts.

## Coverage table

| # | Question | Status | Evidence |
|---|---|---|---|
| 1 | Quoted comma | verified | `out/positive.json` |

## Closeout

- Criteria were recorded before the run; the helper computed both verdicts.
- Nothing outside the lab changed and no account was touched.
- Manual review: the fixture is synthetic and safe to share.
'''


def call(cwd, *args, code=0):
    """Run a helper and assert its exit status; raise with the captured streams."""
    process = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, env=ENV,
                             text=True, encoding="utf-8", capture_output=True, timeout=60)
    assert process.returncode == code, (args, process.returncode, process.stdout, process.stderr)
    return process


def lab_for(scratch, name, *topic):
    project = Path(scratch) / name / "project"
    project.mkdir(parents=True)
    call(project, SKILL / "scripts" / "init_lab.py", *topic, "--slug", "case")
    return project / "tools" / "case-lab"


def write_transfer_inputs(lab, *, naive_succeeds=False, crash=False):
    plan = {"arms": [
        {"kind": "positive", "case": "quoted comma kept in one field", "expect": "met",
         "criterion": {"op": "equals", "value": {"rows": ORACLE}}},
        {"kind": "negative", "case": "naive comma split of the same fixture", "expect": "unmet",
         "criterion": {"op": "equals", "value": {"rows": ORACLE}}},
    ]}
    (lab / "transfer" / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    probe = (TRANSFER_PROBE.replace("__NAIVE__", repr(naive_succeeds))
             .replace("__CRASH__", repr(crash))
             .replace("__POSITIVE__", repr(ORACLE)).replace("__NEGATIVE__", repr(NAIVE)))
    (lab / "probe.py").write_text(probe, encoding="utf-8")
    call(lab, "scripts/transfer.py", "plan", "transfer/plan.json")


def write_reference(lab, *, status="Verified mastery", arabic=False):
    text = REFERENCE
    replacements = {
        "__STATUS__": status,
        "__TLDR__": "The quoted comma stayed inside one field." if not arabic
        else "الفاصلة داخل علامات الاقتباس بقيت ضمن حقل واحد.",
        "__ROW__": "kept" if not arabic else "بقي كما هو",
        "__TRANSFER__": (
            "Both arms were judged by the criterion stored in `transfer/criteria.json`; "
            "`scripts/transfer.py` computed the verdicts instead of trusting a declared pass."
            if not arabic else
            "طُبّق نفس المعيار المسجّل مسبقًا في `transfer/criteria.json` على الحالتين، "
            "وحسب `scripts/transfer.py` الحكم بدل الاعتماد على تصريح السكربت."),
        "__PREDICTION__": "Both arms follow the predeclared criterion." if not arabic
        else "الحالتان تتبعان المعيار المسجّل مسبقًا.",
        "__VERDICT__": "Matched" if not arabic else "مطابق",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    (lab / "COMPLETE.md").write_text(text, encoding="utf-8")
    (lab / "FINDINGS.md").write_text(FINDINGS, encoding="utf-8")


def recorded_transfer_lab(scratch, name, *, naive_succeeds=False, crash=False, arabic=False,
                          status="Verified mastery"):
    lab = lab_for(scratch, name, "Transfer case")
    write_transfer_inputs(lab, naive_succeeds=naive_succeeds, crash=crash)
    call(lab, "scripts/prediction.py", "add", "Both arms will match the predeclared criterion.")
    call(lab, "scripts/run_log.py", "--", sys.executable, "probe.py",
         code=0 if not crash else 1)
    write_reference(lab, status=status, arabic=arabic)
    return lab


def core_tests(scratch):
    lab = lab_for(scratch, "core", "Test caf\u00e9")
    call(lab.parents[1], SKILL / "scripts" / "init_lab.py", "Do not replace", "--slug", "case", code=2)
    assert (lab / "FINDINGS.md").read_text(encoding="utf-8").startswith("# Test caf\u00e9")
    (lab / "COMPLETE.md").write_text(BLOCKED, encoding="utf-8")
    call(lab, "scripts/lint_knowledge.py", ".")
    (lab / "probe.py").write_text(PROBE, encoding="utf-8")
    command = ("--replay-safe", "--", sys.executable, "probe.py", "argument with spaces", "--", "")
    call(lab, "scripts/run_log.py", *command, code=2)
    call(lab, "scripts/prediction.py", "add", "Unused assumption")
    call(lab, "scripts/prediction.py", "add", "A second prediction cannot be open", code=2)
    call(lab, "scripts/prediction.py", "cancel", "replace unused assumption")
    call(lab, "scripts/prediction.py", "add", "Expected literal arguments and known output")
    (lab / "out" / ".ENV-example").write_text("synthetic metadata", encoding="utf-8")
    call(lab, "scripts/run_log.py", *command)
    call(lab, "scripts/run_log.py", "--allow-replication", *command)
    call(lab, "scripts/prediction.py", "add", "Same arguments under a named alternate condition")
    call(lab, "scripts/run_log.py", "--case", "variation", *command)
    ledger = [json.loads(line) for line in (lab / "runs.jsonl").read_text(encoding="utf-8").split("\n") if line]
    assert [run["prediction_id"] for run in ledger] == [2, 2, 3]
    assert ledger[2]["case"] == "variation" and ledger[1]["replication"]
    assert all(set(run["changed"]) == {f"out/{index}.json"} for index, run in enumerate(ledger, 1))
    assert json.loads((lab / "out" / "1.json").read_bytes())["args"] == ["argument with spaces", "--", ""]
    assert call(lab, "scripts/run_log.py", "seal").stdout.strip() == ledger[-1]["hash"]
    call(lab, "scripts/run_log.py", "replay", "--id", "1")
    assert json.loads((lab / "replay.json").read_bytes())["matches"] is True
    (lab / "probe.py").write_text(PROBE + '\nPath("out/extra.txt").write_text("extra")\n', encoding="utf-8")
    call(lab, "scripts/run_log.py", "replay", "--id", "1", code=1)
    assert not (lab / "out" / "extra.txt").exists()
    assert json.loads((lab / "replay.json").read_bytes())["changed_paths_match"] is False
    call(lab, "scripts/manifest.py")
    assert "out/.ENV-example" not in json.loads((lab / "manifest.json").read_bytes())["files"]


def transfer_tests(scratch):
    """The four required cases plus the legacy record and a digest."""
    lab = recorded_transfer_lab(scratch, "matching")
    result = json.loads((lab / "transfer" / "transfer_result.json").read_text(encoding="utf-8"))
    assert result["schema"] == 2 and [arm["pass"] for arm in result["arms"]] == [True, True]
    call(lab, "scripts/lint_knowledge.py", ".")

    arabic = recorded_transfer_lab(scratch, "arabic", arabic=True)
    call(arabic, "scripts/lint_knowledge.py", ".")

    contradicted = recorded_transfer_lab(scratch, "contradicted")
    path = contradicted / "transfer" / "transfer_result.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["arms"][0].update(observed={"rows": NAIVE}, met=True, **{"pass": True})
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    refused = call(contradicted, "scripts/lint_knowledge.py", ".", code=1)
    assert "contradicts" in refused.stdout, refused.stdout

    naive = recorded_transfer_lab(scratch, "naive", naive_succeeds=True)
    refused = call(naive, "scripts/lint_knowledge.py", ".", code=1)
    assert "both arms computed as passing" in refused.stdout, refused.stdout

    crashed = recorded_transfer_lab(scratch, "crashed", crash=True)
    refused = call(crashed, "scripts/lint_knowledge.py", ".", code=1)
    assert "successful recorded run" in refused.stdout, refused.stdout

    legacy = lab_for(scratch, "legacy", "Legacy case")
    arms = [{"kind": "positive", "expected": {"rows": ORACLE}, "observed": {"rows": ORACLE}, "pass": True},
            {"kind": "negative", "expected": {"rows": NAIVE}, "observed": {"rows": NAIVE}, "pass": True}]
    (legacy / "transfer" / "transfer_result.json").write_text(json.dumps(arms, indent=2), encoding="utf-8")
    (legacy / "probe.py").write_text(
        'import json\nfrom pathlib import Path\nPath("out/positive.json").write_text('
        'json.dumps({"rows": [["a,b", "tail"]]}), encoding="utf-8")\n', encoding="utf-8")
    call(legacy, "scripts/prediction.py", "add", "Legacy evidence stays readable.")
    call(legacy, "scripts/run_log.py", "--", sys.executable, "probe.py")
    write_reference(legacy, status="Documented, not mastered")
    readable = call(legacy, "scripts/lint_knowledge.py", ".")
    assert "legacy transfer result" in readable.stderr, readable.stderr
    write_reference(legacy, status="Verified mastery")
    refused = call(legacy, "scripts/lint_knowledge.py", ".", code=1)
    assert "legacy list cannot support it" in refused.stdout, refused.stdout

    digest = recorded_transfer_lab(scratch, "digest")
    good = """# Hand-off digest

## Practical rules

1. Keep quoted commas inside one field — evidence: `out/positive.json`.

## Pitfalls

- Splitting on commas breaks quoted rows — evidence: `out/negative.json`.

## Experiment conditions

- Synthetic CPython fixture — evidence: `transfer/criteria.json`.

## Unverified

- Other dialects — see [`COMPLETE.md`](COMPLETE.md).
"""
    (digest / "DIGEST.md").write_text(good, encoding="utf-8")
    call(digest, "scripts/lint_knowledge.py", ".")
    (digest / "DIGEST.md").write_text(good.replace("`out/negative.json`", "`out/missing.json`"),
                                      encoding="utf-8")
    refused = call(digest, "scripts/lint_knowledge.py", ".", code=1)
    assert "missing local evidence path" in refused.stdout, refused.stdout


def main():
    with TemporaryDirectory(prefix="deep-dive-smoke-") as scratch:
        core_tests(scratch)
        transfer_tests(scratch)
    print("Skill smoke: init, blocked report, prediction, argv, variation, replication, seal, replay, "
          "manifest, transfer criteria, computed verdicts, contradictions, crashed runs, legacy records, "
          "and digest checks passed.")


if __name__ == "__main__":
    main()

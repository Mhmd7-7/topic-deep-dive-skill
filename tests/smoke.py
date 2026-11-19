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


def call(cwd, *args, code=0):
    process = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, env=ENV,
                             text=True, encoding="utf-8", capture_output=True, timeout=30)
    assert process.returncode == code, (args, process.returncode, process.stdout, process.stderr)
    return process.stdout.strip()


def main():
    with TemporaryDirectory(prefix="deep-dive-smoke-") as scratch:
        project = Path(scratch) / "project with spaces"
        project.mkdir()
        init = SKILL / "scripts" / "init_lab.py"
        call(project, init, "Test café", "--slug", "smoke")
        call(project, init, "Do not replace", "--slug", "smoke", code=2)
        lab = project / "tools" / "smoke-lab"
        assert (lab / "FINDINGS.md").read_text(encoding="utf-8").startswith("# Test café")
        predict = "scripts/prediction.py"
        runner = "scripts/run_log.py"
        lint = "scripts/lint_knowledge.py"
        (lab / "COMPLETE.md").write_text(BLOCKED, encoding="utf-8")
        call(lab, lint, ".")
        (lab / "probe.py").write_text(PROBE, encoding="utf-8")
        command = ("--replay-safe", "--", sys.executable, "probe.py", "argument with spaces", "--", "")
        call(lab, runner, *command, code=2)
        call(lab, predict, "add", "Unused assumption")
        call(lab, predict, "add", "A second prediction cannot be open", code=2)
        call(lab, predict, "cancel", "replace unused assumption")
        call(lab, predict, "add", "Expected literal arguments and known output — café")
        (lab / "out" / ".ENV-example").write_text("synthetic metadata", encoding="utf-8")
        call(lab, runner, *command)
        call(lab, runner, "--allow-replication", *command)
        call(lab, predict, "add", "Same arguments under a named alternate condition")
        call(lab, runner, "--case", "variation", *command)
        ledger = [json.loads(line) for line in (lab / "runs.jsonl").read_text(encoding="utf-8").split("\n") if line]
        assert [run["prediction_id"] for run in ledger] == [2, 2, 3]
        assert ledger[2]["case"] == "variation" and ledger[1]["replication"]
        assert all(set(run["changed"]) == {f"out/{index}.json"} for index, run in enumerate(ledger, 1))
        assert json.loads((lab / "out" / "1.json").read_bytes())["args"] == ["argument with spaces", "--", ""]
        assert call(lab, runner, "seal") == ledger[-1]["hash"]
        call(lab, runner, "replay", "--id", "1")
        assert json.loads((lab / "replay.json").read_bytes())["matches"] is True
        (lab / "probe.py").write_text(PROBE + '\nPath("out/extra.txt").write_text("extra")\n', encoding="utf-8")
        call(lab, runner, "replay", "--id", "1", code=1)
        assert not (lab / "out" / "extra.txt").exists()
        assert json.loads((lab / "replay.json").read_bytes())["changed_paths_match"] is False
        call(lab, "scripts/manifest.py")
        assert "out/.ENV-example" not in json.loads((lab / "manifest.json").read_bytes())["files"]
    print("Skill smoke: init, blocked report, prediction, argv, variation, replication, seal, replay, and manifest passed.")


if __name__ == "__main__":
    main()

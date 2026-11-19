#!/usr/bin/env python3
"""Create a portable lab for a new topic. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
HELPERS = ("prediction.py", "run_log.py", "transfer.py", "lint_knowledge.py", "manifest.py")
TEMPLATES = {
    "REFERENCE_TEMPLATE.md": "COMPLETE.md",
    "FINDINGS_TEMPLATE.md": "FINDINGS.md",
    "LAB_GUIDE.md": "LAB.md",
}


def create(topic: str, slug: str, project: Path) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 64:
        raise ValueError("--slug must use lowercase ASCII letters, digits and hyphens (max 64)")
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise ValueError("--project must be an existing directory")
    tools = project / "tools"
    if tools.resolve() != tools:
        raise ValueError("project tools/ must be a real local directory, not a link")
    texts = {output: (SKILL / "templates" / source).read_text(encoding="utf-8")
             for source, output in TEMPLATES.items()}
    helpers = {name: (SKILL / "scripts" / name) for name in HELPERS}
    if not all(path.is_file() for path in helpers.values()):
        raise ValueError("skill is missing one or more bundled helper scripts")

    tools.mkdir(exist_ok=True)
    lab = tools / f"{slug}-lab"
    if lab.exists() or lab.is_symlink():
        raise ValueError(f"lab already exists; no files replaced: {lab}")
    lab.mkdir(exist_ok=False)
    for folder in ("out", "transfer", "scripts"):
        (lab / folder).mkdir()
    for filename, text in texts.items():
        (lab / filename).write_text(text.replace("{{TOPIC}}", topic), encoding="utf-8")
    for filename, source in helpers.items():
        shutil.copyfile(source, lab / "scripts" / filename)
    (lab / "PREDICTIONS.md").write_text("# Predictions\n\nNo predictions yet.\n", encoding="utf-8")
    (lab / ".gitignore").write_text("__pycache__/\n*.pyc\n.env*\n.private/\nstate.json\n", encoding="utf-8")
    # The target directory did not exist before initialization: there were no prior lab files.
    (lab / "manifest.json").write_text(json.dumps({"schema": 1, "baseline": {}, "files": {}},
                                                  indent=2) + "\n", encoding="utf-8")
    return lab


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", help="human-readable topic name; Unicode is allowed")
    parser.add_argument("--slug", help="directory name stem; required for names without ASCII letters/digits")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    topic = args.topic.strip()
    if not topic or len(topic) > 200 or any(ord(ch) < 32 for ch in topic):
        parser.error("provide a non-empty single-line topic name (max 200 characters)")
    slug = args.slug or re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    try:
        lab = create(topic, slug, args.project)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Created {lab}")
    print("Fill in FINDINGS.md before recording any experiment. See LAB.md for the workflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# topic-deep-dive

A reusable skill for **read → predict → experiment → verify a new case → document**. It works from a new workspace without Spotify, Minecraft, a particular SDK, or a prior conversation.

## Ask for it

> Use `topic-deep-dive` to study `<topic>`. Focus on `<questions>`. Test it locally when safe and deliver an evidence-backed reference plus the runnable scripts.

## Install or use it manually

Install the whole `topic-deep-dive` folder in your client's skills directory, so `SKILL.md`, `templates/`, `references/`, and `scripts/` stay together. Back up an existing version before replacing it. In DeepSeek Harness the user-level location is normally `~/.dsh/skills/topic-deep-dive/`. Enable or reload the skill catalog if the client does not pick up changes in the current session.

The helpers require Python 3.10+ and no extra packages. From the target project, run:

```text
python <skill-dir>/scripts/init_lab.py "My topic" --slug my-topic --project .
```

The initializer creates `tools/my-topic-lab/` and refuses to replace an existing lab. Read the generated `LAB.md` and fill in the scope and budget before the first experiment. You get a working log, a reference template, helper scripts, and local folders for safe observations and transfer tests. Run local helpers from the lab, not from the skill directory.

Read [`SKILL.md`](SKILL.md) for the full workflow. The transfer step uses `scripts/transfer.py`: record the criterion and the predicted outcome in `transfer/plan.json` **before** running, then let the helper compute each arm's verdict from the saved observation. The checker recomputes those verdicts from the stored criteria; it verifies evidence linkage, the transfer arithmetic and selected formatting/coverage rules, but not scientific correctness, the quality of the criterion, or access permissions. An untested API claim is not counted as a live result. The initialized lab is not a security sandbox, and reviewed offline replay is opt-in.

When the knowledge is handed to another AI or packed for reuse, add `DIGEST.md` from [`templates/DIGEST_TEMPLATE.md`](templates/DIGEST_TEMPLATE.md); the checker requires its four sections and that every cited evidence path exists.

To check an extracted copy without a service or account, run `python tests/smoke.py` from the skill directory. It creates throwaway labs and checks initiation, prediction rules, argument passing, replay, inventory, computed transfer verdicts (including rejected contradictions and crashed runs), legacy record handling, and digest validation.

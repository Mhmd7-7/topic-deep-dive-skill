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

Read [`SKILL.md`](SKILL.md) for the full workflow. The checker verifies evidence linkage and selected formatting/coverage rules, not scientific correctness or access permissions. An untested API claim is not counted as a live result. The initialized lab is not a security sandbox, and reviewed offline replay is opt-in.

To check an extracted copy without a service or account, run `python tests/smoke.py` from the skill directory. It creates throwaway labs and checks initiation, prediction rules, argument passing, replay, and inventory.

# Running the {{TOPIC}} lab

Work from this directory. The helpers use Python 3.10+ and its standard library; the topic may have other prerequisites. The lab is a workspace, not a sandbox.

1. Fill in the scope, numbered questions, initial hypotheses, permissions and budget in `FINDINGS.md` before the first probe.
2. Write a short probe. Have it save an observed, safe, UTF-8 artifact to a fresh path in `out/` or `transfer/`; the recorder hashes output but does not save or print command stdout/stderr. When repeating, the child environment's `TOPIC_LAB_RUN_ID` can distinguish the evidence filenames. Do not put credentials or private data in the lab or on the command line.
3. Keep one prediction open. For example (replace the command and outcome with the actual probe):

   ```text
   python scripts/prediction.py add "the parser will return two fields from the quoted row"
   python scripts/run_log.py -- python probe.py quoted
   python scripts/prediction.py status
   ```

   Use `prediction.py cancel "reason"` to close an unused prediction without erasing its history. Use `run_log.py --allow-replication -- <original command>` only under the same conditions. To run the same arguments under different conditions, use `run_log.py --case <variant-name> -- <command>` with a fresh prediction. The runner preserves the argument list it receives; the caller's shell still performs its normal parsing before the runner sees it. Run commands sequentially within a single lab.
4. Record the observed result, including mismatches, in `FINDINGS.md`. Write the two-arm new-case check under `transfer/` and have it emit `transfer/transfer_result.json`. If a study is blocked before a run or transfer, keep `Not run:` with a specific explanation instead of making evidence up.
5. Complete `COMPLETE.md`, then run `python scripts/lint_knowledge.py .` and `python scripts/manifest.py`. Lint is not proof of correctness; inspect the artifacts and independently check a key result.

Optional: mark only a reviewed, offline command using lab-relative inputs and **fresh** outputs with `--replay-safe` before `--`. Both that recording and its replay use a reduced child environment. `python scripts/run_log.py replay --id N` runs it in a temporary copy of the current lab (without that run's products) and compares exit code, stdout/stderr hashes and evidence changes. This is not a sandbox or restoration of the original machine state. Inspect the code first and never replay live actions. Use `python scripts/run_log.py seal` to retain a new-format ledger head outside the lab, and `python scripts/lint_knowledge.py . --anchor HASH` to check that head; historical ledgers remain readable without a seal.

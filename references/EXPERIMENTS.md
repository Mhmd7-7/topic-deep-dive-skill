# Pick an experiment that fits the topic

| Topic | Useful first experiment | Variation / failure | New-case demonstration |
|---|---|---|---|
| Web API | One documented read with the smallest required scope; check the status and exact response fields | Empty, missing scope or delayed state on an authorized test account; simulate rate responses without generating load | Authenticate by consent, perform a scoped task, and confirm resulting state separately |
| CLI or tool | Tiny fixture, exact arguments, output and exit code | Empty input, paths with spaces, invalid option, or another installed version | Run the tool on a distinct fixture; independently compare its output to known data |
| Library or file format | Minimal parse/serialize case; save intermediate bytes and decoded values | Unicode, missing vs empty value, quoting/line endings, one intentionally malformed local input | Parse a new fixture and compare full structured values; try the naive method against that same expected result |
| Stateful UI or system | Note the initial state, trigger one authorized action, then observe the new state | Verify first/last, cancellation or timing with a disposable fixture | A user-visible small task with an explicit read-back and rollback check |

For a benign live API, don't confuse a success status with completed work. If a command is accepted, poll sparingly within the budget and confirm the expected identifier or state. An allowed, empty response doesn't prove a broad absence. An observed error on one account/device/version isn't a universal rule.

Write sanitized evidence such as `out/pagination.json` or `out/strict-error.txt` immediately. Keep the expected result in the prediction ledger, not passed off as actual output. If a redaction obscures the relevant fact, record stable fixture aliases or a minimal tested invariant instead of publishing sensitive data. When exact bytes are sensitive, use synthetic fixtures rather than storing them.

An expected domain error is a successful experiment if observed and saved. A probe crash is not. Any experiment needing unapproved access, destructive changes, unsafe tests, or a missing runtime stays blocked or documented-only.

If migrating an old chat or a dated notebook, keep original dates and distinguish what it actually recorded from assumptions. Do not fabricate new provenance. Re-run only what is safe and necessary with new predictions. Redact old credentials, identifiers, and private replies before sharing anything.

# P07-5 — Weekly v1 Status Refresh

**Version:** 1.0
**Owner:** YouWard lane
**Review cadence:** Weekly
**Status:** BUILDING — branch-only, first dry run pending

## 0. Go / No-Go Gate

| Gate | Result | Evidence |
|---|---|---|
| Recurrence | PASS | Weekly official-source refresh prevents live v1 status decay. |
| Verifiable output | PASS | Receipt counts, HTML diff, fixtures, P44 result, and Git commit are machine-checkable. |
| Bounded cost | PASS | One GitHub Actions job, weekly, 45-minute timeout, 199 fixed records. |
| Tools available | PASS | Python standard library, GitHub Actions, repository secret webhook. |
| Review bandwidth | PASS | One Slack line per run; circuit breaker asks for human review only above 20%. |
| Pattern selection | PASS | Deterministic maintenance loop. Loss-function development is N/A. |

## 1. Purpose

Keep the 199-record live v1 page current without changing its product shape or allowing transient source failures to manufacture lifecycle claims.

Success means:
- every weekly run evaluates exactly 199 existing rows;
- only status cells and evidence attributes can differ;
- receipts reconcile to 199;
- failed fetches never create an open verdict;
- systemic changes halt before commit.

Failure means:
- row count or immutable row content changes;
- a source failure flips a record open;
- a second consecutive source failure does not become unverified;
- more than 20% of statuses change without a human clearance receipt;
- a page or captured workflow log fails P44;
- a live commit occurs without the required activation gate.

## 2. Scope

### In scope
- index.html v1 status cell and data-evidence refreshes.
- Official-source reads using the v4 Grants.gov, USA.gov challenge, and FBI resolvers.
- Weekly GitHub Actions execution.
- One-line #youward receipts.
- Dry-run artifacts, deterministic fixtures, P44 scans.

### Out of scope
- v2 corpus or adapters.
- Adding, removing, reordering, or redesigning v1 records.
- Editing titles, URLs, classes, publishers, amounts, deadlines, CSS, or JavaScript.
- Calendar creation.
- Mini cron or gateway automation.
- Deployment or push to main before Stephen’s S→A ruling.

## 3. Inputs and Outputs

### Inputs
- index.html with exactly 199 record rows.
- Read-only official source endpoints.
- YOUWARD_SLACK_WEBHOOK repository secret.
- Optional manual breaker-clearance receipt.
- Optional manual live S→A approval receipt.

### Outputs
- Candidate index.html with only status/evidence changes.
- status-receipt.json, status-ledger.json, status.diff, and run.log workflow artifacts.
- One Slack receipt line.
- On activated live runs only: one Git commit whose subject is the receipt line.

### State and history
- Dynamic state: each row’s data-evidence, including FETCH_FAILURE_COUNT=N.
- Durable history: Git commits and retained GitHub Actions artifacts.
- The workflow does not mutate a second state file because the executive bound permits only status/evidence changes.

## 4. Allowed and Forbidden Actions

### Allowed
- GET/POST reads required by the existing public resolvers.
- Write a candidate page and audit artifacts.
- Commit only index.html after all brakes pass and live execution is authorized.
- Post one pre-approved receipt line through the repository-secret webhook.

### Forbidden
- Mutating source sites.
- Adding/removing/restructuring records.
- Inferring open from a future date or successful page load.
- Printing, echoing, or persisting the webhook.
- Committing on the first dry run.
- Pushing to main before Stephen’s S→A ruling.
- Running on the Mini.

## 5. Safety Brakes

1. **Exact-record invariant:** abort unless 199 records are found.
2. **Field-scope invariant:** normalize status/evidence before and after every row rewrite; abort if anything else differs.
3. **Two-failure brake:** first fetch failure retains prior status; second consecutive failure sets unverified. Count is stored in evidence.
4. **Never-open-on-failure:** failure handling can only retain the prior state or set unverified.
5. **20% circuit breaker:** 40 or more status changes out of 199 halt before page output/commit. Override requires a manual #youward clearance receipt.
6. **P44 gate:** scan candidate page, captured refresher log, and diff for private paths, OpenClaw fragments, publisherUid, credentials/tokens, emails, and phone numbers.
7. **Activation gate:** scheduled live writes require repository variable STATUS_REFRESH_LIVE_ENABLED=true; manual live writes require an S→A receipt.
8. **Concurrency lock:** only one refresh run at a time; runs are never cancelled mid-flight.
9. **Timeout:** 45 minutes.
10. **No silent failure:** blocked and completed runs post one receipt line; non-receipt infrastructure failures surface as failed Actions runs.

## 6. Optimization / Loss Function

N/A. This loop is deterministic and rule-based. There is no model generation, grader, or optimization target.

## 7. Maker / Verifier

- Maker: scripts/verify-status.py computes candidate state and receipt.
- Verifiers:
  - tests/test_weekly_refresh.py proves two-failure, reset, breaker boundary, and field-scope behavior.
  - scripts/p44-leak-gate.py scans page and captured workflow output.
  - GitHub Actions checks the changed-file allowlist before commit.
- The maker cannot bypass the verifier gates.

## 8. Evaluation and Acceptance

Required before branch dry run:
- fixtures green;
- P44 green on current page;
- Python compile green;
- workflow syntax review;
- exact 199-record invariant;
- branch commit and push only to the feature branch.

Dry-run acceptance:
- manual dispatch;
- candidate diff and reconciled counts;
- one Slack receipt;
- no page commit;
- artifacts retained.

Production activation requires a later Stephen S→A ruling.

## 9. Runtime Contract

- Trigger: Monday 16:00 UTC weekly, plus manual dispatch.
- Scheduled runs remain dry until STATUS_REFRESH_LIVE_ENABLED=true.
- Manual dispatch defaults to dry run.
- A manual live run requires live_approval.
- A breaker override requires breaker_clearance.
- GitHub-hosted runner only; no Mini runtime.

## 10. Receipt Contract

Format:
[YouWard] status refresh YYYY-MM-DD | RESULT | open N / closed N / upcoming N / unverified N | status changes N/199

The four status counts must total 199. RESULT is DRY_RUN, READY_TO_COMMIT, or BLOCKED_CIRCUIT_BREAKER.

## 11. Rollback and Recovery

- Before activation: delete the feature branch.
- After activation: revert the specific status-refresh commit; no record schema migration exists.
- A breaker remains effective on each rerun until the computed delta drops below 20% or a human supplies a #youward clearance receipt.
- Missing webhook secret blocks receipt delivery and therefore blocks DONE.

## 12. Open Questions

- Repository secret YOUWARD_SLACK_WEBHOOK is currently absent and must be configured by a human before the required branch dry run.
- Production activation variable remains deliberately unset pending Stephen’s S→A ruling.

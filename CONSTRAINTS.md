# P07-5 Constraints

- Scope is the 199-record live v1 page only.
- Automated writes are limited to record status cells and data-evidence.
- Official sources are read-only.
- Never infer open from a future date, HTTP success, or fetch failure.
- First consecutive fetch failure retains prior status.
- Second consecutive fetch failure sets unverified.
- Failure count lives inside the evidence string.
- More than 20% status changes blocks commit until human clearance in #youward.
- The Slack webhook is a repository secret and is never logged.
- P44 scans the candidate page and captured workflow output.
- First execution is a manual-dispatch dry run with no commit.
- No push to main, deployment, schedule activation, or publication without Stephen’s S→A.

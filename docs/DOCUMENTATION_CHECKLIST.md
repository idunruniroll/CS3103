# Documentation and evidence checklist

For the current code at `51b0be7`, see [current validation](CURRENT_VALIDATION.md):
51 discovered tests plus two explicit tests passed on Windows on 2026-11-04.
The historical benchmark evidence below predates the live-delivery change;
rerun performance experiments before attributing those metrics to current code.

This checklist reflects the completed Windows validation recorded at `3a12ef7`,
not a new Ubuntu performance run. Previously reported Ubuntu results remain
attributable to `bfa2c46` unless reproduced on a newer commit.

| Item | Current status | Remaining work |
|---|---|---|
| README setup and commands | Present | Confirm remaining two team identities |
| Design and protocol | Present; limits, recovery, timing and test coverage documented | Keep claims aligned with measured workloads |
| Demo script | Present | Rehearse with real browsers and record the required 5-7 minute video |
| Public-test instructions | Present | Restore or reproduce Ubuntu artifacts and verify network cleanup |
| Windows validation report, summary and provenance | Present in `experiments/validation_windows/` | Keep these separate from Ubuntu evidence |
| Ubuntu results at `bfa2c46` | Attribution documented; `experiments/data/` absent here | Restore original CSV/JSON, commands, environment and summary, or reproduce and record the newer tested commit |
| `AI_USAGE.md` | Missing; template only | Complete a team-reviewed account of tools used, a useful suggestion, a rejected/corrected suggestion, and responsibility |
| `CONTRIBUTIONS.md` | Missing; template only | Confirm names, student IDs, actual responsibilities and agreed percentages totaling 100% |
| Root `report.pdf` | Missing | Produce the required 4-5 page report, excluding references/appendices |
| Final submission check | Failed on the three missing files above | Run `python submission_check.py --final` after completing them |

Do not treat template files as completed declarations. The contribution
percentages and full team tool usage require team input; they cannot be inferred
from passing tests or filled in as verified facts by this audit.

The report must cover architecture/protocol, revision and recovery semantics,
backpressure/overload policy, repeated public experiments, before/after comparison,
P50/P95/P99, freshness and final completeness, failures/trade-offs, limitations,
and a short future-work direction. Cite the tested commit and environment for
each result set. Include coverage and recovery evidence where relevant.

## What the completed checks establish

- 48 discovered Python tests, one explicit overload test, and one explicit
  overflow/reconnect integration test passed: 50 Python tests in total.
- Browser logic and syntax checks passed; visual usability and the mandatory
  real-browser demo/video were not verified by those checks.
- T1-T4 and FIFO T3 ran three times on Windows. Adaptive retained 100% of
  generated finals with no duplicate/stale/connection errors in these runs.
- Scale (300 clients) and shared-proxy bandwidth probes ran once each. They
  are exploratory development checks, not repeated Ubuntu networking evidence.
- Reference Ubuntu delay/jitter/loss tests, long-run memory, recovery after
  impairment removal, hidden workloads and individual viva performance remain
  outside what these checks establish.

Read the [validation report](../experiments/validation_windows/VALIDATION.md)
and [summary](../experiments/validation_windows/SUMMARY.md) for numbers, commands
and limitations. A full-mark claim is not supported by public tests alone.

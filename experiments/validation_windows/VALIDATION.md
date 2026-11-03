# Requirement validation - Windows development checks

This is a historical record, predating the individual-final delivery fix at
`51b0be7`. Its batching and test-count descriptions refer to the implementation
measured then. See [current validation](../../docs/CURRENT_VALIDATION.md) for
the latest correctness checks. Benchmark numbers below have not been rerun for
the current live-delivery policy.

These checks use the current working tree at commit
`3a12ef7efc00e72395330e53cdfd51a4bf8ad9cf`, Python 3.10.10 and websockets 16.1.1
on Windows. See `provenance/PROVENANCE.json` for environment details. Added
validation helpers were untracked during execution. Production code and the
supplied measurement programs were not changed.

These are new Windows results. Previously reported Ubuntu experiments remain
attributable to `bfa2c46`; this run does not reproduce Ubuntu tc/netem results.

## Correctness and compatibility

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | 48 tests passed |
| `python -m unittest tests.overload` | 1 test passed; this file is not discovered by the default `test*.py` pattern |
| `python -m experiments.validation_windows.check_overflow_recovery` | Passed: real WebSocket close 1013, reconnect, ordered missed finals only |
| `node experiments/validation_windows/check_browser.cjs` | Passed: replacement, final deduplication, recall, clock offset, pruning, finalized cursor, reconnect timing |
| `node --check` on app.js and all three client/js modules | Passed |
| `python submission_check.py` | Passed: required entry point and WebSocket handshake |
| `python submission_check.py --final` | Failed: AI_USAGE.md, CONTRIBUTIONS.md and root report.pdf are missing |
| `python -m pip check` | Passed |

An additional in-process default-limit exercise accepted 20,000 final captions
and checked the 4,096-final retention cap, 64-active-segment cap, expiry after
91 seconds, 256 pending segments with 16 retained revisions each, preservation
of all 256 pending finals during batching, and 512 remembered delivered segments.
All assertions passed. This was an ad hoc assertion check, not a timing benchmark.

The browser checks use a simulated DOM/socket and controlled clock. They do not
verify visual usability, real browser networking, or the mandatory two-browser
demonstration/video.

## Reproducible commands

Commands below use `python` as shorthand for `.\.venv\Scripts\python.exe` in
PowerShell. No LIVERECALL environment overrides were set for the adaptive tests.

```powershell
python run_demo.py --clients 20 --duration 20 --runs 3 --quiet-server --output-stem experiments/validation_windows/t1
python run_demo.py --clients 100 --duration 40 --runs 3 --quiet-server --output-stem experiments/validation_windows/t2
python run_demo.py --clients 100 --duration 60 --runs 3 --quiet-server --slow-percent 10 --slow-ms 500 --output-stem experiments/validation_windows/t3
python run_demo.py --clients 100 --duration 60 --runs 3 --quiet-server --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 --output-stem experiments/validation_windows/t4
$env:LIVERECALL_POLICY = 'fifo'
python run_demo.py --clients 100 --duration 60 --runs 3 --quiet-server --slow-percent 10 --slow-ms 500 --output-stem experiments/validation_windows/fifo_t3
Remove-Item Env:LIVERECALL_POLICY
python run_demo.py --clients 300 --duration 20 --runs 1 --quiet-server --output-stem experiments/validation_windows/scale300_smoke
```

The comparison was run by a Python subprocess wrapper with the policy supplied
through its child environment. The PowerShell form above is equivalent.

Portable bandwidth probes use the existing shared token-bucket proxy, not tc:

```powershell
python experiments/bandwidth_sim.py --clients 100 --duration 40 --rate-kbit 400 --policy adaptive --output-stem experiments/validation_windows/bw_smoke
python experiments/bandwidth_sim.py --clients 100 --duration 40 --rate-kbit 400 --policy fifo --output-stem experiments/validation_windows/bw_smoke
python experiments/bandwidth_sim.py --clients 100 --duration 40 --rate-kbit 100 --policy adaptive --output-stem experiments/validation_windows/bw_stress
python experiments/bandwidth_sim.py --clients 100 --duration 40 --rate-kbit 100 --policy fifo --output-stem experiments/validation_windows/bw_stress
python experiments/summarise.py experiments/validation_windows --output experiments/validation_windows/SUMMARY.md
```

Bandwidth and 300-client probes have one run each and are exploratory. They are
not the three-run Ubuntu evidence required for reported performance results.
Per-run CSV/JSON files and comparison logs are in this directory; `SUMMARY.md`
contains medians of the available runs. The harness's overall coverage field
includes clients deliberately slowed or disconnected; it is not restricted to
the unaffected population.

## Grading criteria still requiring evidence

- T5 delay/jitter/loss on the reference Ubuntu setup with tc/netem, three runs
  and cleanup verification. Ubuntu WSL is installed and tc is available, but
  `sudo -n true` reported that a password is required. No qdisc was changed.
  WSL is not the reference grading environment.
- A real browser demo of live replacements, local recall, disconnect/recovery,
  late join, and usable status controls, plus the required 5-7 minute video.
- Final submission files, team identities/contributions, and a 4-5 page report
  with repeated Ubuntu measurements, before/after analysis, trade-offs, and
  limitations. Two README member entries remain to be confirmed.
- Hidden workload freshness, constrained-bandwidth behavior, catch-up after
  impairment removal, bursty normal revision coverage, and long-run memory.
  Short local tests cannot establish the hidden-performance score.
- Individual viva performance. Optional ASR is not required for the mandatory
  100 marks and has not been validated here.

The PDF's hidden-performance correctness gate caps that section at 15/30 below
99% final completeness and 5/30 below 95%. Passing public tests does not establish
a hidden-test score or guarantee the highest available mark.

The short Windows working-set sample is saved in `memory_observation.csv`.
It includes launcher and worker PIDs across a server restart, so it must not be
treated as one uninterrupted memory trace or proof of long-run boundedness.

## Measured results

| Workload | Runs | Final completeness | P95 caption age | P99 caption age | Fresh finals <=500ms |
|---|---:|---:|---:|---:|---:|
| t1 | 3 | 100.00% | 6.46 ms | 8.49 ms | 100.00% |
| t2 | 3 | 100.00% | 21.14 ms | 26.02 ms | 100.00% |
| t3 | 3 | 100.00% | 26.17 ms | 3281.82 ms | 96.32% |
| t4 | 3 | 100.00% | 20.99 ms | 25.00 ms | 98.42% |
| fifo_t3 | 3 | 95.00% | 1843.52 ms | 23720.71 ms | 90.00% |
| scale300_smoke | 1 | 100.00% | 62.52 ms | 68.92 ms | 100.00% |
| bw_smoke_adaptive_400k | 1 | 100.00% | 22.54 ms | 34.37 ms | 100.00% |
| bw_smoke_fifo_400k | 1 | 100.00% | 19.77 ms | 33.47 ms | 100.00% |
| bw_stress_adaptive_100k | 1 | 100.00% | 1692.42 ms | 2299.69 ms | 75.53% |
| bw_stress_fifo_100k | 1 | 77.10% | 10384.28 ms | 11550.56 ms | 0.00% |

All measured runs had zero duplicate, stale, invalid nonfinal HISTORY, and connection-error counts. All adaptive runs preserved 100% of generated finals.

T1/T2 normal update coverage was 100%. T3 normal clients received all 20,520 expected revisions in each run; the overall 93.99% coverage includes deliberately slow clients. T3 median normal-client P95 was 20.60 ms and slow-client P95 was 7,543.26 ms. FIFO slow-client P95 was 27,837.84 ms (median), with 95% final completeness.

T4 median recovery P95 was 15.04 ms. Final completeness and zero duplicates support recovery correctness; this timing is the harness HISTORY-response metric, not a browser-render completion measurement.

At 400 kbit/s neither policy experienced meaningful overload. At 100 kbit/s adaptive retained all finals while FIFO delivered only 77.10% by the test end. Adaptive fresh-final ratio was 75.53%, P95 caption age 1.69 seconds, and revision coverage 43.77%; intermediate suppression is expected during overload. These bandwidth probes are single runs and do not replace repeated Ubuntu tc/netem experiments.

Verdict: local correctness and public-load evidence is strong, but the submission is not complete and the highest mark cannot be certified. Prioritize missing deliverables, reference Ubuntu T5/repeated bandwidth and recovery-after-impairment tests, the mandatory visual demo, and slow-client tail/convergence analysis before claiming top performance.

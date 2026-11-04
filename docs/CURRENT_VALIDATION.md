# Current delivery validation

Checked on Windows on 2026-11-04 against production code at `51b0be7`.
Documentation edits do not change runtime behavior.

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | 51 tests passed |
| `python -m unittest tests.overload` | 1 test passed; explicit overflow/1013 component test |
| `python -m experiments.validation_windows.check_overflow_recovery` | 1 test passed; real WebSocket overflow close, reconnect and recovery |

There are 53 Python tests across these three commands. The two explicit tests
are not included in default discovery. On Windows these commands used the
existing `.venv\Scripts\python.exe`; on Ubuntu activate `.venv` first.

The three tests in `tests/test_overload_requirements.py` establish:

- Live finals use individual `CAPTION_UPDATE` frames in normal and congested
  selection; the controlled bandwidth scenario also rejects any live `HISTORY`.
- At 6,000 and 12,000 bytes/s, with 10 finals/s and 40 revisions per segment,
  finals arrive while the source runs. The 6,000-byte/s case starts congested.
  The test checks all finals and the latest unfinished revision within a
  two-second completion bound, coalescing, bounded pending count, and no close.
- An injected clock simulates a one-hour lecture at two finals/s, checking
  bounded retained state, the previous 60 seconds, resume filtering and expiry.

These are representative correctness checks. The bandwidth transport has no
kernel or WebSocket buffering, and the retention simulation is not an RSS
measurement. No new Ubuntu public-load or tc/netem performance measurements
were made during this documentation audit. Older benchmark tables predate the
individual-final delivery change and must be rerun before being attributed to
the current implementation.


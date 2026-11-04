# Current delivery validation

Checked on Windows on 2026-11-04 against `51b0be7` plus the local repeated-source
fix in `liverecall/hub.py`.

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | 52 tests passed |
| `python -m unittest tests.overload` | 1 test passed; explicit overflow/1013 component test |
| `python -m experiments.validation_windows.check_overflow_recovery` | 1 test passed; real WebSocket overflow close, reconnect and recovery |

There are 54 Python tests across these three commands. The two explicit tests
are not included in default discovery. On Windows these commands used the
existing `.venv\Scripts\python.exe`; on Ubuntu activate `.venv` first.

The repeated-source regression (`check_liverecall_repeat.py`) connects to a separately running WebSocket server and maintains one continuous client connection while two sequential caption-source connections transmit updates. The test verifies that segment IDs remain unique and consecutive across both source rounds.

The test does not exercise client disconnection or HISTORY-based recovery. Reconnect behavior is validated separately by `experiments.validation_windows.check_overflow_recovery`, which checks recovery after an overflow-induced disconnect. This separate test does not specifically verify reconnect recovery across sequential caption-source runs.

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
measurement. Subsequent clean Ubuntu T1–T5 experiments are provided in experiments/verify_data.zip. All 27 individual runs reported 100% final-caption completeness with no duplicates, stale messages or connection errors. The exact tested Git revision was not embedded in the experiment records, so these results are not independently attributable to a specific commit. Older benchmark tables predate the
individual-final delivery change and must be rerun before being attributed to
the current implementation.


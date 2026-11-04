# Demo Script (video 5–7 min, live demo in the viva)

Everything uses the submitted `solution_server.py` and browser client with the
deterministic `caption_source.py`. There are no mock-ups.

## Setup (before recording)

Use three separate terminals from the repository root, with `.venv` active in
each. Run the WebSocket server in Terminal 1, the HTTP server in Terminal 2,
and start the caption source in Terminal 3 at 0:30 in the recording sequence.

```bash
source .venv/bin/activate
python solution_server.py --port 8765 --verbose     # T1: shows connect/disconnect lines
python -m http.server 8000 --directory client       # T2
```

Open **Window A** and **Window B** at <http://127.0.0.1:8000>, side by side.
Tick **Show revisions** in Window A.

## Script

| Time | Action | What to point out |
|---|---|---|
| 0:00 | Introduce the architecture (one slide or `docs/DESIGN.md` §1) | source → server → many clients; per-client queues |
| 0:30 | T3: `python caption_source.py --duration 300` | Both windows show "Live" and captions flow |
| 0:45 | Window A, *Show revisions* on | Grey italic "…" row = provisional. It changes rev 1 → 2 → 3 **in place**, then turns final (black). No duplicate lines. |
| 1:30 | Wait at least 60 s of captions, then press **What did I miss?** in Window B | Opens on **30 s** by default. Switch to **15 s** and **60 s**. Note "from local history": no network request (show DevTools → Network → WS, nothing is sent) |
| 2:30 | Window A: **Simulate 5 s disconnect** (or DevTools → Network → Offline for ~5 s) | Status pill shows "Reconnecting…" then "Live". Toast: "Back online: recovered N missed captions". Recovered rows flash. Recall shows "N recovered after a gap". Info panel: resume cursor, reconnect count |
| 3:30 | In Window A run `LiveRecall.app.store` in the console, or scroll | No duplicate finals: each segment appears once, in order |
| 4:00 | Open **Window C** (late joiner) | Toast "Joined late: loaded N recent captions". The 60 s recall works immediately, then live continues |
| 4:45 | Server terminal: `stats …` lines | clients, congested=0, bounded pending/finals, rss |
| 5:15 | Show the saved Ubuntu three-run summary from `experiments/data/SUMMARY.md` | Explain adaptive versus FIFO results and limitations. Attribute measurements to `bfa2c46`; documentation changes do not constitute a new experiment run. |
| 6:00 | Wrap up | Bounded state, overload policy, results table |

Generate the summary before recording:

The live-delivery policy changed at `51b0be7`. Existing benchmark summaries
predate that change; rerun the experiments and cite the new tested commit if
presenting results as measurements of the current code. Historical Ubuntu
commit attribution differs across documents; see
[current validation](CURRENT_VALIDATION.md) before citing an older result.

```bash
python experiments/summarise.py experiments/data --output experiments/data/SUMMARY.md
```

The Ubuntu `experiments/data/` artifacts are absent from this checkout. Restore
the results from `bfa2c46` or reproduce them and record the newer tested commit
before presenting this summary. The Windows summary under
`experiments/validation_windows/` is separate development evidence and must be
labeled accordingly; it cannot stand in for Ubuntu T5 measurements.

## Checklist for the live viva slot

- [ ] venv active, `pip install -r requirements.txt` done
- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] server, http.server and source commands in shell history
- [ ] two browser windows open, a third ready for late join
- [ ] `experiments/data/` results and `SUMMARY.md` available
- [ ] each member knows their modules (`docs/DESIGN.md` §9)

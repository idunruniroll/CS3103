# LiveRecall - CS3103 Assignment 4

LiveRecall distributes a live, revision-based caption stream from
`caption_source.py` to many browser clients over WebSockets. It keeps captions
correct (no stale or duplicate finals), fresh under slow readers and constrained
bandwidth, and recoverable after disconnects and late joins, with bounded server
memory.

```
caption_source.py ──SOURCE_HELLO / CAPTION_UPDATE──▶ solution_server.py ──HISTORY / CAPTION_UPDATE──▶ browsers / load clients
```

## Team members

Confirm the remaining names and student IDs before submission.

| Name | Student ID | Responsibility |
|---|---|---|
| To be confirmed | To be confirmed | Protocol, caption state and bounded history, server entry point |
| To be confirmed | To be confirmed | Per-client queues, semantic coalescing, flow control / backpressure |
| Max Khoo Zheng Ning | A0307430R | Browser client: revision display, recall, reconnect/resume |
| Tan Yi Qian | A0301651U | Experiments (T1–T5, before/after), documentation, report |

## Repository layout

| Path | Contents |
|---|---|
| `solution_server.py` | **Required entry point** (`python solution_server.py --port 8765`) |
| `liverecall/` | Server package: `protocol`, `caption_state`, `semantic_queue`, `flow_control`, `client_channel`, `hub`, `stats` |
| `client/` | Browser client (`index.html`, `app.js`, `css/`, `js/`) |
| `tests/` | Unit and end-to-end tests (standard-library `unittest`) |
| `experiments/` | Scripts for T1–T5, the policy comparison and a portable bandwidth emulator |
| `docs/` | `PROTOCOL.md`, `DESIGN.md`, `DEMO_SCRIPT.md` |
| `report.pdf` | Required 4-5 page technical report at the repository root; currently missing |
| `experiments/validation_windows/` | Windows development results, validation helpers, and recorded provenance |
| starter files | `caption_source.py`, `load_clients.py`, `run_demo.py`, `analyse_results.py`, `network_profiles/`, … (unmodified) |

## Ubuntu setup

Tested target: Ubuntu 22.04/24.04 (Python 3.10+). From a fresh machine:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2 git
git clone https://github.com/idunruniroll/CS3103.git
cd CS3103
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The only server dependency is `websockets`. No cloud APIs, databases or
Internet access are needed.

## Required server

```bash
python solution_server.py --port 8765
```

By default it binds `0.0.0.0` and needs no interactive input. Startup time
depends on the environment.
Every option has a default. The defaults are the submitted configuration:

| Option | Env variable | Default | Meaning |
|---|---|---|---|
| `--policy` | `LIVERECALL_POLICY` | `adaptive` | `adaptive` (submitted), `coalesce`, `fifo` (naive baseline for comparison) |
| `--lag-threshold` | `LIVERECALL_LAG_THRESHOLD` | `0.3` | Extra ping delay in seconds that marks a client as lagging |
| `--slow-interval` | | `0.5` | Base seconds between frames for a congested client |
| `--retention` | | `90` | Maximum retention age; also capped at 4,096 finals; recovery requests limited to 60 s |
| `--max-pending` | | `256` | Adaptive/coalesce pending segment cap before initiating resync |
| `--compression` | `LIVERECALL_COMPRESSION` | `deflate` | WebSocket permessage-deflate on/off |
| `--stats-interval` | `LIVERECALL_STATS_INTERVAL` | `10` | Seconds between `stats …` log lines (0 = off) |
| `--verbose` | | off | Log every client connect/disconnect |

Environment variables exist because `run_demo.py` starts the server with only
`--port`. Example: `LIVERECALL_POLICY=fifo python run_demo.py ...`.

## Browser client

```bash
# terminal 1
python solution_server.py --port 8765
# terminal 2: serve the static client
python -m http.server 8000 --directory client
```

Open <http://127.0.0.1:8000> in two or more tabs or browsers. The client
connects to `ws://<page host>:8765`. To use another server, open
`index.html?server=ws://HOST:PORT` (or `?port=PORT`). Opening
`client/index.html` directly from disk also works.

Client features:

* live captions, with provisional rows (grey, italic, "…") replaced in place by
  newer revisions and the final;
* **What did I miss?** (shortcut **M**) shows 30 s by default, with 15/30/60 s
  views, computed from local history only;
* a connection status pill, automatic reconnect with exponential backoff
  capped at 5 seconds before up to 30% jitter is applied, resume from the
  latest finalized caption, and a toast
  saying how many missed captions were recovered;
* late join loads up to 60 s of recent context, then continues live;
* *Show revisions* displays segment/revision numbers for the demo;
  *Simulate 5 s disconnect* demonstrates recovery.

## Public deterministic tests

Run every command from the repository root inside the venv. The experiment
scripts default `RUNS` to three independent runs; override it with the `RUNS`
environment variable. `run_demo.py` reports the median.

```bash
bash experiments/run_public_tests.sh          # T1..T4, results in experiments/data/
```

which runs these workloads (also adding `--quiet-server`, capturing logs, and printing a summary):

```bash
python run_demo.py --clients 20  --duration 20 --runs 3 --output-stem experiments/data/t1
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem experiments/data/t2
python run_demo.py --clients 100 --duration 60 --runs 3 --slow-percent 10 --slow-ms 500 --output-stem experiments/data/t3
python run_demo.py --clients 100 --duration 60 --runs 3 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 --output-stem experiments/data/t4
```

T5 (network impairment, needs sudo) defaults to 100 clients, 40 seconds per
run, and three runs per profile on the loopback interface (`lo`). Override
these with `CLIENTS`, `DURATION`, `RUNS`, and `IFACE`, respectively:

```bash
bash experiments/run_netem.sh                 # every profile in network_profiles/
bash experiments/run_netem.sh delay_loss      # a single profile
```

Experiment scripts attempt to reset network impairment through cleanup traps,
but cleanup success should be verified.

Before/after comparison (same workload, three server policies):

```bash
bash experiments/compare_policies.sh                    # T3 slow readers
WITH_BANDWIDTH=1 bash experiments/compare_policies.sh   # + 2 Mbit/s tc profile
python experiments/summarise.py experiments/data     # Markdown table of medians
```

The summarizer prints the table but does not automatically write `SUMMARY.md`.
To save it, run:

```bash
python experiments/summarise.py experiments/data --output experiments/data/SUMMARY.md
```

On machines without `tc` (macOS/Windows development),
`experiments/bandwidth_sim.py` puts a token-bucket proxy
(`experiments/bw_proxy.py`) between the load clients and the server. Report
numbers should still come from Ubuntu `tc`. Reported Ubuntu experiment results
remain attributable to commit `bfa2c46`, not automatically to `78888cd` or
subsequent documentation commits. Update that attribution only after
reproducing the experiments on a newer commit.

Unit and end-to-end tests:

```bash
python -m unittest discover -s tests -t .
python -m unittest tests.overload
python -m experiments.validation_windows.check_overflow_recovery
node experiments/validation_windows/check_browser.cjs
```

The recorded validation passed 48 discovered Python tests, the separate
overflow test, and the overflow/reconnect integration test (50 Python tests
in total), plus browser logic and syntax checks. `tests/overload.py` and the
validation integration check are not included in default test discovery.
Node.js is needed only for the optional browser logic check above, not for
server startup or Python tests. Browser logic checks do not replace a visual demo.

See the [validation report](experiments/validation_windows/VALIDATION.md),
[measured summary](experiments/validation_windows/SUMMARY.md), and
[environment provenance](experiments/validation_windows/provenance/PROVENANCE.json).
These Windows results were recorded at `3a12ef7`; T1-T4 and the FIFO T3
comparison each have three runs. The 300-client and proxy-bandwidth probes
have one run each. They do not reproduce Ubuntu T5 or establish hidden-test scores.
Historical Ubuntu result artifacts under `experiments/data/` are not present
in this checkout and must be restored or reproduced before submission.

Submission documentation is still incomplete: `AI_USAGE.md`,
`CONTRIBUTIONS.md`, and root-level `report.pdf` are missing, two team member
entries need confirmation, and the mandatory video/demo remains unverified.
See the [documentation checklist](docs/DOCUMENTATION_CHECKLIST.md).

## Mandatory deterministic application demo

```bash
python solution_server.py --port 8765                  # terminal 1
python -m http.server 8000 --directory client          # terminal 2
python caption_source.py --duration 300                # terminal 3
```

Open two browser windows at <http://127.0.0.1:8000>, then follow
[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md):

1. provisional to final replacement (*Show revisions* on);
2. **What did I miss?** with the 30 s default and the 15/60 s views;
3. *Simulate 5 s disconnect* (or stop the network), then auto-reconnect and
   "recovered N missed captions" with no duplicate rows;
4. open a third window late: "Joined late: loaded N recent captions", then live.

## Design notes

Full details are in [`docs/DESIGN.md`](docs/DESIGN.md) and the protocol is in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md).

* **Revision/deduplication state:** `CaptionState.apply` accepts a revision
  only if it is newer than the latest accepted one for its segment, and rejects
  everything for a finalized segment. Clients repeat the same check
  (`CaptionStore.apply`), so a final is never shown twice.
* **Bounded server history:** the server retains finalized captions for up to
  90 seconds and 4,096 entries, whichever limit is reached first. Recovery
  requests are limited to 60 seconds. Active provisional segments are capped at 64.
* **Reconnect/late join:** `hub.handle_client` builds retained `HISTORY`, queues
  active provisionals and registers the channel without an intervening `await`.
  Reconnecting clients send their latest finalized cursor. Exponential backoff
  is capped at 5 seconds before up to 30% jitter is applied.
* **Per-client buffering:** adaptive and coalesce policies bound pending segments
  to 256, with up to 16 retained revisions per pending segment. FIFO is
  intentionally unbounded. Each client has its own writer task.
* **Backpressure/overload:** adaptive uses outstanding ping age relative to recent
  minimum RTT, alongside transport backlog, to detect possible congestion.
  The 64 KiB threshold is a congestion-detection trigger, not a hard limit on
  transport buffering. Congested delivery drains until a pong or the 10-second
  drain timeout, then paces finals-first frames. On semantic queue overflow,
  the server initiates a resynchronization close (1013). Reconnecting clients
  request retained finals through `HISTORY`.
* **Revision guarantees:** normal delivery aims to preserve revisions, but
  coalescing and batching may suppress intermediate provisional revisions.
* **Malformed messages:** invalid initial handshakes are rejected with 1008.
  Malformed caption updates after a valid source handshake are discarded.
* **Clock skew:** the browser estimates clock offset from observed message
  timing; this is approximate and can be biased by delayed history delivery.
* **Keepalive:** the server configures a 20-second ping interval and 30-second
  timeout; these do not imply an exact disconnect deadline.
* **Trade-offs:** congested clients lose some provisional updates (by design).
  Slow-reader detection may be delayed until the client library's receive
  buffer fills (16 frames by default in Python `websockets`). See the
  validation report for measured tail latency and remaining evidence gaps.

## Optional ASR bonus

Not attempted.

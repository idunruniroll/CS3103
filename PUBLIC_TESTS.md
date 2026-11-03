# Public Tests

Use these tests to diagnose your design. They do not reveal the hidden final workload. For reported results, use **three independent runs** and report the median.

`run_demo.py --runs 3` restarts the server for each run. The older `--repeat` spelling is accepted as an alias, but `--runs` is clearer.

Activate the environment with `source .venv/bin/activate`. The runner starts
its own server, source and clients; leave port 8765 free. Results are printed
and saved as CSV/JSON. For all T1-T4 scenarios and a summary, run:

```bash
bash experiments/run_public_tests.sh
```

Correctness checks for the current live-delivery contract are separate from
performance measurements:

```bash
python -m unittest discover -s tests -t . -v
python -m unittest tests.test_overload_requirements -v
```

The overload tests check individual live `CAPTION_UPDATE` frames, sustained
final delivery under controlled bandwidth, latest provisional delivery, and
60-second recovery over a simulated one-hour lecture. They use an artificial
transport and clock; they do not replace real TCP/network benchmarks.

## T1 - Basic correctness

```bash
python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem t1
```

Look for: final completeness, duplicate/stale state, normal revision coverage, and unexpected connection errors.

## T2 - Public scale

```bash
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2
```

Look for: P50/P95/P99 Caption Age, Fresh Caption Ratio, Fresh Final Caption Ratio, completeness, and coverage.

## T3 - Slow readers

```bash
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --slow-percent 10 --slow-ms 500 --output-stem t3
```

The analyser reports normal and slow clients separately. A useful design goal is that slow readers do not make normal readers stale or cause unbounded resource growth.

Optional memory observation in another terminal:

```bash
python monitor_server.py --match solution_server.py --duration 60 --output t3_memory.csv
```

## T4 - Reconnect

```bash
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
  --output-stem t4
```

Look for: recovery timing, final completeness, and no duplicate/stale final state. A fast empty HISTORY response is not correct recovery; completeness still matters.

## T5 - Network impairment

Ubuntu only. In one terminal:

```bash
sudo ./network_profiles/delay_loss.sh lo
```

Then run, for example:

```bash
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5
```

Always reset afterwards:

```bash
sudo ./network_profiles/reset.sh lo
```

WebSocket runs over TCP. Packet loss is therefore expected to show up mainly as retransmission/head-of-line delay and larger tail latency, not as ordinary application-message loss.

## Before/after comparison

For at least one stress test, compare your final design with an earlier/basic configuration or with a major optimization disabled. Keep the test parameters the same, quantify the difference, and explain the trade-off.

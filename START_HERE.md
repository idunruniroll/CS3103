# CS3103 Assignment 4 - LiveRecall

This checkout contains the implemented server and browser, public test tools,
and development validation. Use [README.md](README.md) for configuration and
the [documentation checklist](docs/DOCUMENTATION_CHECKLIST.md) for remaining
submission deliverables and evidence gaps.

## Implemented features

- required `python solution_server.py --port <port>` startup path;
- WebSocket source/client handshakes and protocol validation;
- bounded finalized history and recovery following `CLIENT_HELLO`;
- independent client writers and bounded semantic queues;
- adaptive congestion detection, provisional coalescing and pacing;
- individual live `CAPTION_UPDATE` frames, with finals bypassing pacing after drain;
- deterministic caption generator;
- scalable simulated clients and CSV logs;
- public metrics and independent-run support;
- browser revision replacement, deduplication, local recall and automatic reconnect;
- Ubuntu `tc/netem` examples.

The optional `fifo` policy remains an intentionally unbounded baseline for
comparison. Passing public tests does not establish hidden-test performance.

## Quick start

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python submission_check.py
```

Basic public experiment:

```bash
python run_demo.py --clients 20 --duration 20 --runs 1
```

For results used in the report, use three independent runs:

```bash
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2
```

See `PUBLIC_TESTS.md` for T1-T5.

Correctness and overload contract tests:

```bash
python -m unittest discover -s tests -t . -v
python -m unittest tests.test_overload_requirements -v
```

## Browser demo

See `DEMO_GUIDE.md`. The browser replaces revisions in place, keeps finalized
captions for local 15/30/60-second recall, and resumes after disconnection.

## Short background references

- `PROTOCOL_EXAMPLES.md` - normal, reconnect, and late-join message flow.
- `NETWORKING_PRIMER.md` - WebSocket/TCP, asyncio, per-client queues, bounded state, and backpressure terminology.

These guides explain mechanics, not the optimal design.

## Submission compatibility

During development:

```bash
python submission_check.py
```

Before submission, after you have created the required final files:

```bash
python submission_check.py --final
```

The instructor reference implementation and hidden evaluator are not included. Do not modify the public measurement logic when reporting the required public-test results.

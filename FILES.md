# Package Contents

- `solution_server.py` - asyncio WebSocket server entry point, configuration and startup.
- `liverecall/` - protocol validation, bounded caption history, per-client semantic queues, adaptive flow control, connection handling and statistics. The optional FIFO comparison policy is intentionally unbounded.
- `caption_source.py` - deterministic revision source; exact-segment and long/demo modes.
- `load_clients.py` - scalable clients with role labels, finalized resume state, and history duplicate/stale checks.
- `run_demo.py` - independent public runs + median summary.
- `analyse_results.py` - correctness/freshness/coverage, slow-reader split, and recovery timing.
- `monitor_server.py` - optional Ubuntu RSS memory observation helper.
- `client/` - browser UI with revision replacement, local recall, bounded caption state and automatic reconnect/recovery.
- `tests/` - protocol, state, queue, flow-control, real-WebSocket and controlled-bandwidth contract tests; `overload.py` is run explicitly rather than by default discovery.
- `docs/` - current protocol, design, demo script and documentation checklist.
- `experiments/` - repeated public-load, network impairment and policy comparison runners; saved validation artifacts identify the implementation measured.
- `network_profiles/` - public `tc/netem` examples.
- `START_HERE.md`, `DEMO_GUIDE.md`, `PUBLIC_TESTS.md`, `PROTOCOL_EXAMPLES.md`, `NETWORKING_PRIMER.md`, `UBUNTU_SETUP.md` - student guides.
- `submission_check.py` - startup/WebSocket compatibility checker; `--final` checks final deliverables.
- `README_TEMPLATE.md`, `AI_USAGE_TEMPLATE.md`, `CONTRIBUTIONS_TEMPLATE.md` - submission templates.
- `bonus_asr/` - optional-only bonus guidance.

---
title: "LiveRecall: Fresh, Correct and Bounded Live-Caption Delivery over WebSockets"
subtitle: "CS3103 Assignment 4 · Team XX"
author: "Member 1 (A0…) · Member 2 (A0…) · Member 3 (A0…) · Member 4 (A0…)"
---

# 1. Problem and goals

A live lecture caption stream consists of *segments*, each with provisional revisions followed by a final caption. Students need the newest revision without duplicate finals, a rolling 15/30/60-second recall view, and recovery after disconnection or late joining. The challenge is preserving low caption age and bounded memory with many concurrent clients, including slow readers and impaired networks. Our policy therefore prioritizes **complete and timely finals**, preserves all revisions for healthy clients, and suppresses obsolete intermediate revisions only when congestion warrants it.

# 2. Architecture and protocol

```text
caption_source.py  →  hub.handle_source  →  CaptionState.apply
                                               │
                                               └→ ClientChannel.offer() × N
                                                     │  independent per-client queue
                                                     └→ FlowController → writer → WebSocket browser
```

`solution_server.py` runs one Python `asyncio` server using the `liverecall/` package. The source handler parses and validates each `CAPTION_UPDATE`, updates session state, and offers the accepted caption to per-client channels without awaiting client sends. Each client has an independent queue and writer, isolating slow readers from the source and other clients. The `fifo` baseline retains all pending revisions; `coalesce` compacts pending revisions without proactive lag detection; `adaptive` combines semantic queues with measured congestion feedback.

The WebSocket protocol uses source `SOURCE_HELLO` and `CAPTION_UPDATE` messages, and browser `CLIENT_HELLO` with an optional final-caption cursor (`last_segment`, `last_revision`) and `history_seconds` (at most 60). The server returns retained finals in segment order in a `HISTORY` response to `CLIENT_HELLO`, then uses individual `CAPTION_UPDATE` frames for all live delivery. Unsolicited mid-stream `HISTORY` is not used. See `docs/PROTOCOL.md` for the field-level contract.

The browser maintains revision-aware caption state and a bounded local history, displays the current live caption, supports 15/30/60-second recall without a fresh server request, and automatically reconnects with a resume cursor after network interruption. The local history window is 90 seconds, providing slack around the maximum 60-second recall request.

# 3. Revision, ordering and recovery

**Revision safety.** `CaptionState.apply` accepts only revisions newer than the latest accepted revision for a segment. Once a segment is finalized, later updates cannot replace it. Server queue delivery tracking and browser-side revision checks independently reject already-delivered, stale or duplicate captions. This prevents an old provisional from overwriting a final even if messages are repeated across reconnection.

**Bounded retention.** Server finalized history is retained for 90 seconds and capped at 4,096 entries; abandoned active provisionals are capped at 64. The per-client semantic queue is bounded at 256 distinct pending segments, with at most 16 retained revisions per pending segment before compaction. Time-based pruning uses the server's monotonic clock rather than trusting the source timestamp.

**Recovery.** A connecting client supplies its last finalized cursor and a requested history window. `HISTORY` contains retained finals later than that cursor; clients without a cursor receive the eligible recent finals. It is followed by current provisional state where applicable. Channel registration and history snapshot preparation avoid an intervening suspension point, eliminating the subscribe/snapshot race. Local recall normally reads browser state only; reconnect and late join use the server's bounded retained history.

# 4. Backpressure and overload control

**Why naive FIFO/coalescing is inadequate.** `await ws.send()` can complete while captions accumulate in WebSocket and operating-system buffers. Waiting for a blocked send is therefore too late to detect an increasing application-to-render delay. In our T3 experiments, the `coalesce` policy without proactive congestion detection behaved almost identically to FIFO.

**Adaptive lag measurement.** The sender uses WebSocket ping/pong progress as a signal of whether a peer has processed preceding transport data. Lag is identified when an outstanding ping exceeds the recent minimum RTT baseline by 0.3 seconds, or when the transport's pending write buffer exceeds 64 KiB. A delayed network alone should not automatically be classified as a slow reader because the baseline incorporates observed RTT.

**Control states.** In normal operation, the writer sends revisions without artificial pacing, subject to queue limits and final priority when at least four finals are pending. Once congested, it collapses superseded provisional revisions; while draining, it avoids adding more traffic behind a lagging client until a pong or the 10-second drain timeout. After draining, finals bypass pacing and are sent individually as `CAPTION_UPDATE`. Provisional-only traffic waits for the pacing interval and the oldest pending caption's one-second hold. The initial paced interval is 0.5 seconds; repeated congestion increases it up to 4 seconds. Probing eventually returns a recovered client to unpaced delivery; repeated lag invokes backoff rather than sustained reflooding.

**Bounded overload fallback.** A semantic queue exceeding its distinct-segment capacity requests resynchronization. The writer closes with code **1013**, reason `resync: reconnect to recover`. Reconnecting clients request retained finals through `HISTORY`; captions older than the retained window are not guaranteed. Both the explicit R11 component test and the real-WebSocket overflow/reconnect integration test passed in the current Windows validation.

# 5. Experimental evaluation

The performance tables in this section are historical and predate the live
delivery fix at `51b0be7`. They have not been rerun with individual live finals
and revised pacing. Their Ubuntu commit attribution (`7385d6d` below) differs
from the `bfa2c46` attribution in README and Windows provenance; original
Ubuntu artifacts are absent here, so that discrepancy remains unresolved.
See [current validation](docs/CURRENT_VALIDATION.md) for the 2026-11-04 Windows
checks: 51 discovered tests plus the explicit overflow and real-WebSocket
overflow/reconnect tests all passed. This supersedes the earlier R11-only
evidence limitation described below.

## 5.1 Methodology and environment

Final performance measurements used **Ubuntu 24.04 LTS**, **Python 3.12.3**, and Git commit **`7385d6d`**. We ran three independent trials per reported scenario and show the median of the per-run metrics, using the supplied public harness and the project's experiment scripts. Caption age is measured in milliseconds; freshness denotes captions received within 500 ms. *Final completeness* counts unique finalized captions received relative to those expected; *normal update coverage* measures received live revisions. Duplicate and stale messages were counted separately. Network impairment was applied with Linux traffic control and cleaned up afterward (`tc qdisc show dev lo` reported `qdisc noqueue`). Ubuntu tests are loopback experiments and should not be construed as measurements over a live campus network.

Separately, the automated suite passed **49/49 tests in 13.650 seconds on Windows**, including history bounds, protocol validation, revision ordering, end-to-end server cases, slow-client isolation, flow-control transitions, semantic queues and a deterministic R11 overflow/1013 unit test. These 49 tests should not be described as having been rerun on Ubuntu without a corresponding test log.

## 5.2 Public scenarios T1–T4 (adaptive; three-run medians)

| Scenario | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final completeness % | Coverage % | Normal P95 ms | Recovery P95 ms | Dup / stale |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| T1: 20 clients | 5.0 | 7.9 | 9.7 | 100.00 | 100.00 | 100.00 | 100.00 | 7.9 | — | 0 / 0 |
| T2: 100 clients | 16.0 | 30.6 | 39.5 | 100.00 | 100.00 | 100.00 | 100.00 | 30.6 | — | 0 / 0 |
| T3: 10% slow readers | 15.5 | 29.9 | 3,364.2 | 97.90 | 95.92 | 100.00 | 94.04 | 27.9 | — | 0 / 0 |
| T4: 20% reconnect | 11.7 | 25.1 | 30.6 | 100.00 | 98.42 | 100.00 | 98.42 | 25.1 | 9.8 | 0 / 0 |

All T1–T4 runs preserved **100% final-caption completeness**. T3's high aggregate P99 reflects the tail of slow readers; the unaffected clients' P95 was 27.9 ms, compared with 30.6 ms for T2. T3 slow readers had P50 **322.6 ms** and P95 **7,526.5 ms**. T4 recovered retained missed finals with a HISTORY-response P95 of **9.8 ms**, and neither duplicate nor stale messages were observed. Fast HISTORY response alone is not a correctness proof; completeness and duplicate counts jointly support the recovery outcome.

## 5.3 Controlled before/after policy comparison: T3

| Policy | Overall P95 ms | P99 ms | Slow P50 ms | Slow P95 ms | Fresh final % | Final completeness % | Coverage % |
|---|---:|---:|---:|---:|---:|---:|---:|
| FIFO baseline | 2,252.7 | 24,017.6 | 14,729.4 | 28,068.8 | 90.00 | 95.13 | 95.18 |
| Coalesce | 2,257.9 | 24,034.0 | 14,728.6 | 28,088.8 | 90.00 | 95.13 | 95.18 |
| **Adaptive** | **28.7** | **3,381.9** | **327.7** | **7,524.6** | **95.92** | **100.00** | **94.04** |

The controlled T3 comparison shows an overall **98.7% reduction in P95 age** with adaptive versus FIFO: (2,252.7 − 28.7) / 2,252.7. Final-caption completeness improved by **4.87 percentage points**, from 95.13% to 100%; fresh-final ratio improved from 90.00% to 95.92%. The principal cost was slightly lower provisional-revision coverage (94.04% versus 95.18%) because the policy intentionally removes obsolete intermediate updates from overloaded clients. Slow-reader P95 remains high (approximately 7.5 seconds), especially during initial detection/drain, so the adaptive mechanism improves but does not eliminate startup tail latency.

A separate bandwidth comparison under its tested bottleneck profile showed **no overload benefit**: FIFO P95 **38.2 ms**, coalesce **38.8 ms**, and adaptive **53.8 ms**, with **100% freshness, completeness and coverage** for all policies (three runs each). This is important counterevidence: adaptive introduces some overhead when clients are already keeping up, and its advantage becomes material under actual congestion rather than every bandwidth cap. We do not substitute the earlier one-run Windows 100-kbit/s stress results for this Ubuntu comparison because the test conditions differ.

## 5.4 T5 network impairment (adaptive; three-run medians)

| Impairment | P50 ms | P95 ms | P99 ms | Fresh % | Fresh final % | Final completeness % | Coverage % | Dup / stale |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2 Mbit/s bandwidth | 28.0 | 53.5 | 61.1 | 100.00 | 100.00 | 100.00 | 100.00 | 0 / 0 |
| 100 ms delay | 210.0 | 259.2 | 280.4 | 100.00 | 100.00 | 100.00 | 100.00 | 0 / 0 |
| 3% loss | 15.6 | 29.7 | 210.0 | 99.93 | 99.78 | 100.00 | 98.48 | 0 / 0 |
| Reordering | 62.0 | 73.9 | 78.1 | 100.00 | 100.00 | 100.00 | 100.00 | 0 / 0 |
| **Combined delay + loss** | **272.8** | **831.8** | **1,054.6** | **80.07** | **62.86** | **99.49** | **55.75** | **0 / 0** |

The combined delay-and-loss profile was the most damaging: freshness fell to 80.07%, fresh-final ratio to 62.86%, and final completeness to **99.49%**. TCP retransmissions and in-order delivery can block later WebSocket frames behind lost data, contributing to the long tails. The results demonstrate good but **not perfect** final delivery under this impairment within the harness observation period. They should not be reported as 100% complete or as zero final loss in all network conditions.

# 6. Discussion, failures and trade-offs

**Normal load and isolation.** T1 and T2 delivered all revisions and finals, without duplicates or stale updates. In T3, normal-client P95 remained close to T2 even while 10% of peers processed frames slowly, supporting the benefit of independent client writers and queues. In T4, disconnected clients recovered retained finals promptly, but some intermediate live revisions were rightly absent because `HISTORY` is finals-oriented.

**Optimization mechanism.** FIFO accumulated stale frames for slow peers and ended with only 95.13% final completeness in the fixed-duration observation window. Coalescing without proactive lag detection scarcely differed from FIFO. Adaptive feedback detected sustained receiver lag, reduced obsolete revision traffic, and preserved final state; its lower coverage is an intentional freshness–completeness trade-off, not evidence that every provisional revision is guaranteed.

**Limitations revealed by T5.** Simple delay increased latency but preserved completeness; combined delay and packet loss produced materially worse tails and 99.49% completeness. A WebSocket over TCP cannot eliminate head-of-line blocking. The 500-ms freshness target is therefore not universally met under severe impairment, and retained-history recovery is bounded by its configured window.

**Implementation issues addressed.** Earlier queue compaction affected healthy clients during bursts; compaction was restricted to congestion (with a per-segment pending-revision bound). Fixed or prematurely restarted probe intervals could reflood slow clients; the flow controller now uses stall-sensitive pacing and probe backoff, with unit tests covering repeated lag and recovery. These engineering changes explain why the adaptive policy is more than simple queue coalescing.

# 7. Limitations and future work

The server uses one process and event loop; very large deployments would require horizontal scaling and cross-worker session state. Receiver lag is inferred from transport progress rather than explicit browser-render acknowledgements, so detection may lag behind large receiver buffers. Adaptive backpressure acts independently per client and does not provide a global fair-share scheduler for shared bottlenecks. Even after detection, initial buffered frames may remain stale; T3 slow-client P95 of about 7.5 seconds demonstrates that limitation. The current Windows validation covers both the R11 overflow close and a real-WebSocket overflow/reconnect/recovery sequence. Performance and recovery after network impairment still require fresh Ubuntu validation.

Future extensions include receiver acknowledgements for more accurate rendered-caption lag, compression or delta encoding of provisional revisions, session sharding across worker processes, coordinated bandwidth allocation for congested cohorts, and integration with a speech-recognition source. A future-project direction is per-student recall summaries, while keeping the present caption transport and consistency guarantees independently testable.

---

**Reproducibility:** Ubuntu 24.04 LTS · Python 3.12.3 · performance commit `7385d6d` · three independent runs/scenario · `experiments/run_public_tests.sh`, `experiments/run_netem.sh`, `experiments/compare_policies.sh` · aggregated by `experiments/summarise.py`. The 49-test unit-suite result was obtained on Windows. Replace the team placeholders above with the actual team information before submission.

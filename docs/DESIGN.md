# LiveRecall Design

## 1. Architecture

```
                    ┌──────────────────────── solution_server.py ─────────────────────────┐
caption_source ───▶ │ hub.handle_source                                                   │
                    │   protocol.caption_from_message   (validate, encode JSON once)      │
                    │   CaptionState.apply              (revision order, final durable)   │
                    │        │ accepted                                                   │
                    │        ▼  for each client: ClientChannel.offer()  (O(1), no await)  │
                    │   ┌─────────────┐  ┌─────────────┐        ┌─────────────┐           │
                    │   │SemanticQueue│  │SemanticQueue│  ...   │SemanticQueue│           │
                    │   │FlowController│ │FlowController│       │FlowController│          │
                    │   │writer task  │  │writer task  │        │writer task  │           │
                    │   └──────┬──────┘  └──────┬──────┘        └──────┬──────┘           │
                    └──────────┼────────────────┼──────────────────────┼──────────────────┘
                               ▼                ▼                      ▼
                           client A          client B (slow)        client N
```

| Module | Role | Bounded by |
|---|---|---|
| `liverecall/protocol.py` | Parse/validate/encode messages. Each caption is encoded once and the string is shared by all clients. | – |
| `liverecall/caption_state.py` | Authoritative revision state and the recovery window | 90 s **and** 4096 finals; 64 active segments |
| `liverecall/semantic_queue.py` | Per-client pending revisions grouped by segment | 16 revisions/segment, 256 segments |
| `liverecall/flow_control.py` | Lag detection and the congested-mode state machine (pure logic, unit-tested) | 32 RTT samples |
| `liverecall/client_channel.py` | One writer task per client: chooses the next frame and sends pings | – |
| `liverecall/hub.py` | Handshakes, HISTORY construction, fan-out | 16 sessions |
| `liverecall/stats.py` | `stats clients=… congested=… pending=… rss_mb=…` every 10 s | – |

## 2. Correctness invariants

1. **An older revision never overwrites a newer one.** Enforced three times:
   the server's `CaptionState.apply` drops it, the client's `SemanticQueue`
   drops anything at or below what it already delivered (`mark_delivered`),
   and the browser's `CaptionStore.apply` ignores it.
2. **A final is never overwritten and never shown twice.** Final segments are
   rejected server-side, and also after they leave the window (via
   `_evicted_floor`). The browser keeps finals for up to 90 s and 1000 segments, plus a
   `prunedFloor`. HISTORY excludes the client's cursor.
3. **No gap between HISTORY and live.** `hub.handle_client` builds HISTORY,
   queues the active provisional and registers the channel with no `await`
   in between. asyncio is single-threaded, so no update interleaves.
4. **Coalescing preserves finals.** On semantic queue overflow, the server
   initiates a resynchronization close (1013). Reconnecting clients request
   retained finals through `HISTORY`, subject to retention and recovery limits.

Adaptive and coalesce policies bound pending segments to 256, with up to 16
retained revisions per pending segment. FIFO is intentionally unbounded.
The server retains finalized captions for up to 90 seconds and 4,096 entries,
whichever limit is reached first. Recovery requests are limited to 60 seconds.

The 4,096-entry cap must be sized for the supported final-caption rate: it
cannot preserve a complete 60-second window if more than 4,096 finals arrive
within that window. The fixed bound is not a guarantee for arbitrary source
rates. Disconnections beyond retained history cannot recover older captions.

## 3. Why the naive design fails

`await ws.send()` only blocks once the **receiver library's** queue (Python
`websockets` buffers 16 frames by default), the client's kernel receive
buffer, the server's send buffer and the transport buffer are all full. With
roughly 150-byte compressed captions that is hundreds of messages. A FIFO
design therefore notices nothing until a slow reader is many seconds behind,
and then keeps delivering stale revisions in order. Measured on T3, FIFO
slow-reader P50 is about 15 s and P95 about 28 s.

## 4. Lag detection: ping as an application-level ACK

Adaptive uses outstanding ping age relative to recent minimum RTT, alongside
transport backlog, to detect possible congestion. After sending a caption
frame, the adaptive writer sends a WebSocket ping (at most one
outstanding, tagged with a sequence number). A peer can only answer after it
has read every byte in front of the ping. So:

* fast client: pong in about 1 ms, so it stays in NORMAL mode;
* bandwidth bottleneck: pong delayed by the queueing delay;
* slow reader: once its library queue is full it stops reading, and the pong
  stalls for seconds.

`lagging = ping age > baseline_rtt + 0.3 s` (the baseline is the minimum of
the last 32 RTTs, so pure network delay such as netem 120 ms is not lag), or
more than 64 KiB stuck in the transport buffer. The 64 KiB threshold is a
congestion-detection trigger, not a hard limit on transport buffering.

## 5. Congested-mode state machine (`flow_control.py`)

```
            lag                         pong (drain done)
  NORMAL ─────────▶ CONGESTED/DRAIN ─────────────────────▶ CONGESTED/PACE
    ▲                       ▲                                 │      │
    │ probe survives 15 s   └──── lag again (interval ×2) ────┘      │
    │                                                                │
    └──────── PROBE (NORMAL) ◀──── lag-free for probe_wait ──────────┘
                 │ lag within 15 s → CONGESTED, probe backoff ×2
```

* **DRAIN:** send nothing until the outstanding ping is answered or the
  10-second drain timeout expires. A pong indicates transport progress; the
  application may still have captions waiting to be displayed.
* **PACE:** provisional-only traffic waits for `interval` (0.5 s base, doubled on renewed
  lag up to 4 s, shrunk ×0.9 on clean pongs). Frame choice in
  `ClientChannel._next_frame`:
  1. one pending final as a `CAPTION_UPDATE`, bypassing the pacing interval
     after drain mode ends; repeat for remaining finals;
  2. otherwise the newest provisional of a pending segment, but only after
     the oldest pending caption has waited `provisional_hold` = 1 s. Most provisionals are superseded
     within a second, so a congested client is not spent on them, but a
     long sentence still updates.
  The queue is `collapse()`d first, so superseded provisionals are dropped.
* **PROBE:** `probe_wait = min(60 s, max(2 s, 10 × worst stall)) × backoff`.
  A single TCP retransmission (stall < 1 s) costs a few seconds of
  coalescing; a slow reader whose drain took 6 s or more waits 60 s. That
  matters because each
  failed probe refills its 16-frame receive buffer. A failed probe doubles
  `backoff` (up to ×8) and a successful one resets it.

Normal delivery aims to preserve revisions, but coalescing and final priority may
suppress intermediate provisional revisions. More than 16 revisions per pending
segment causes coalescing; four pending finals trigger final priority in NORMAL
mode, superseding the provisionals of each final selected. Every live caption
uses an individual `CAPTION_UPDATE`; `HISTORY` is reserved for connection recovery
after `CLIENT_HELLO`. The legacy `batch_*` names configure priority thresholds,
and the legacy live `batches` statistic remains zero.

## 6. Bounded state summary

| State | Bound | Where |
|---|---|---|
| Server final history | 90 s and 4096 entries | `CaptionState._prune` |
| Server active provisionals | 64 segments, and 90 s | `CaptionState.apply/_prune` |
| Per-client semantic pending (`adaptive`/`coalesce`; FIFO is unbounded) | 16 revisions × 256 segments, then resync | `SemanticQueue.offer` |
| Per-client delivered map | 512 segments | `SemanticQueue.mark_delivered` |
| Transport backlog congestion trigger (not a hard buffer limit) | 64 KiB | `FlowConfig.write_buffer_limit` |
| Browser history | Up to 90 s and 1000 segments after periodic pruning; temporary overshoot is possible | `CaptionStore.prune` |
| Sessions | 16 | `ServerConfig.max_sessions` |

## 7. Failure modes and handling

| Situation | Behaviour |
|---|---|
| Invalid initial handshake | Rejected with 1008 |
| Malformed caption update after a valid source handshake | Discarded and counted; unknown message types are ignored |
| Client never sends hello | Closed with 1008 after 5 s |
| Client stops answering pings | Drain gives up after 10 s, then pacing continues; keepalive uses a 20-second ping interval and 30-second timeout; these do not imply an exact disconnect deadline |
| Semantic queue overflow | Initiate resynchronization close 1013; reconnecting clients request retained finals through HISTORY |
| Source reconnects | Same session state continues; stale or duplicate revisions rejected |
| Browser on another machine (clock skew) | Browser estimates clock offset from observed message timing; approximate and potentially biased by delayed history delivery |
| Many simultaneous reconnects | O(window) HISTORY per client; exponential backoff is capped at 5 seconds before up to 30% jitter is applied |

Experiment scripts attempt to reset network impairment through cleanup traps,
but cleanup success should be verified. Reported Ubuntu experiment results
refer to commit `bfa2c46` unless reproduced on a newer commit.

## 8. Known limitations

* A slow reader may not be detectable until its library's receive buffer is
  full (16 frames by default in Python `websockets`). The observed initial
  delay of roughly 8-12 seconds is workload-dependent. After detection,
  adaptive pacing aims to improve freshness without guaranteeing a fixed age.
* Probing a still-slow reader costs one buffer refill, which is why probes are
  rare (60 s or more, doubling). We measured this directly: with a 30 s
  probe, a failed probe late in a 60 s T3 run left slow readers about 8 s
  behind when the run ended, and completeness dropped to 98.8%.
* Lag is detected per client. A shared bottleneck is detected independently by
  each client, which converges but is not an explicit fair-share scheduler.
* Single process, single event loop. Larger deployments may require sharding
  or multiple workers; public tests do not establish capacity at that scale.

## 9. Viva quick reference

| Question | Answer location |
|---|---|
| Why can an older revision never overwrite a newer one? | `CaptionState.apply`, `SemanticQueue.offer`, `CaptionStore.apply` (§2) |
| What happens on reconnect after 10 s offline? | `hub.handle_client` → `CaptionState.history_since(cursor, 60)` (§3, PROTOCOL §3) |
| Where is per-client buffering, and how is it bounded? | `SemanticQueue` (16 × 256), `ClientChannel.offer` |
| Why does P95/P99 rise under loss even though TCP is reliable? | Retransmission timeout (≥ 200 ms) plus head-of-line blocking: later frames wait behind the lost segment |
| What happens when a client reads slower than captions are produced? | §3 to §5: lag detected, drain, paced provisionals and individual priority finals |
| Which provisionals can safely be dropped? | Any provisional superseded by a newer revision or the final of its segment (`collapse`, `pop_final`) |
| What if bandwidth is halved? | Ping age or backlog may trigger congestion; provisional traffic is coalesced and paced, while finals bypass pacing after draining. Completeness still depends on sufficient final-stream capacity and retained recovery state. |
| Show the overload policy | `flow_control.py` (`update`, `send_delay`, `probe_wait`), `client_channel.py` (`_pump`, `_hold_time`, `_next_frame`) |

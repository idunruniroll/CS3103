# LiveRecall Protocol

All messages are UTF-8 JSON objects in WebSocket text frames. The required
compatibility interface (assignment §4) is implemented exactly. Unknown
message types and unknown fields after a valid handshake are ignored. Invalid
initial handshakes are rejected with 1008. Malformed caption updates after a
valid source handshake are discarded.

## 1. Messages

### Source → server

| Message | Fields | Server behaviour |
|---|---|---|
| `SOURCE_HELLO` | `type`, `session` | First message on a source connection. Selects the session (default `L1`). |
| `CAPTION_UPDATE` | `type`, `session`, `segment` (int ≥ 1), `revision` (int ≥ 1), `source_ts` (finite number, Unix seconds), `final` (bool), `text` (string) | Validated, then applied to the session's caption state (§2). Accepted updates are offered to every client channel. Extra fields (e.g. a test-phase label) are ignored and not forwarded. |
| `SOURCE_DONE` | `type`, … | Logged, not forwarded. |

### Client → server

| Message | Fields | Server behaviour |
|---|---|---|
| `CLIENT_HELLO` | `type`, `client_id`, `session`, `last_segment`, `last_revision`, `history_seconds` | First message on a client connection. Answered with `HISTORY` (§3). Invalid cursor values are treated as `0/0`. `history_seconds` is clamped to 0–60 (default 30). |

Clients send nothing else. The server keeps reading so close frames and pongs
are processed.

### Server → client

| Message | Fields | Meaning |
|---|---|---|
| `HISTORY` | `type`, `items: [CAPTION_UPDATE…]` | Finalized captions only, ordered oldest to newest, never including a final the client already reported. |
| `CAPTION_UPDATE` | as above | A live revision. |

A first message that is not valid JSON, not a known hello, or not received
within 5 s gets close code **1008**.

## 2. Revision semantics (server)

For each segment the server keeps the latest accepted revision:

* `revision` ≤ latest accepted revision of that segment: **stale**, dropped.
* Segment already final (or older than the bounded window): **finalized**,
  dropped. A final is durable state, so nothing overwrites it.
* Otherwise **accepted**. If `final=true`, it moves to the bounded final
  history.

Nothing assumes a fixed number of revisions per segment.

## 3. Resume, late join and HISTORY

On `CLIENT_HELLO(last_segment=S, last_revision=R, history_seconds=H)`:

1. `items` = every retained final accepted by the server in the last `H` seconds whose
   `(segment, revision)` is greater than `(S, R)`, sorted by segment.
2. After `HISTORY`, the server sends the latest provisional revision of every
   still-active segment newer than `S`, so a late joiner immediately sees the
   sentence in progress.
3. The client's channel is registered in the same event-loop step as 1–2. No
   update can be accepted between "history built" and "live delivery starts",
   so there are no gaps and no duplicates.

`(S, R)` must be the latest **finalized** caption the client holds, not the
latest provisional it saw. The browser and `load_clients.py` both do this.
A new client uses `0/0`. The browser asks for `history_seconds=60` to populate
recall with available retained finals. The server retains finalized captions
for up to 90 seconds and 4,096 entries, whichever limit is reached first.
Recovery requests are limited to 60 seconds.

The browser estimates clock offset from observed message timing; this is
approximate and can be biased by delayed history delivery. Exponential backoff
is capped at 5 seconds before up to 30% jitter is applied.

## 4. Live delivery

`HISTORY` is sent only in response to the initial `CLIENT_HELLO` on each
connection, including reconnects and late joins. Every live revision, including
every final, uses its own `CAPTION_UPDATE` frame. There are no unsolicited
mid-stream `HISTORY` batches.

When congested, or when at least four finals are pending, the writer selects
one pending final at a time in segment order and removes its superseded
provisionals. The legacy configuration names `batch_normal`,
`batch_congested`, and `batch_threshold` remain in the code; the threshold
now selects final priority rather than wire batching. The legacy `batches`
statistics field stays zero for live delivery.

## 5. Delivery under overload

* Each client has its own queue and writer. The source never waits for a client.
* Adaptive and coalesce policies bound pending segments to 256, with up to
  16 retained revisions per pending segment. FIFO is intentionally unbounded.
* Normal delivery aims to preserve revisions, but coalescing and final priority may
  suppress intermediate provisional revisions.
* Adaptive uses outstanding ping age relative to recent minimum RTT, alongside
  transport backlog, to detect possible congestion. Ping age above baseline RTT
  + 0.3 seconds or transport backlog above 64 KiB triggers congestion.
  The 64 KiB threshold is a congestion-detection trigger, not a hard limit on
  transport buffering.
* During drain mode, the writer waits for a pong or the 10-second drain timeout.
  After draining, pending finals bypass the pacing interval and are sent as
  individual `CAPTION_UPDATE` frames, subject to transport backpressure.
  Provisional-only traffic is paced at a base interval of 0.5 seconds, backing
  off to at most 4 seconds, and waits until the oldest pending caption has
  waited 1 second. Superseded provisional revisions are coalesced away.
* On semantic queue overflow, the server initiates a resynchronization close
  (1013). Reconnecting clients request retained finals through `HISTORY`.
* The server configures a 20-second ping interval and 30-second timeout; these
  do not imply an exact disconnect deadline.

See [`DESIGN.md`](DESIGN.md) for the state machine.

## 6. Example exchanges

Normal connection:

```text
C→S CLIENT_HELLO(last_segment=0,last_revision=0,history_seconds=60)
S→C HISTORY(items=[])
S→C CAPTION_UPDATE(seg=1,rev=1,final=false,"TCP provides")
S→C CAPTION_UPDATE(seg=1,rev=2,final=false,"TCP provides reliable byte")
S→C CAPTION_UPDATE(seg=1,rev=3,final=true,"TCP provides reliable byte stream delivery …")
```

Reconnect after missing segments 39–45 while segment 46 is in progress:

```text
C→S CLIENT_HELLO(last_segment=38,last_revision=3,history_seconds=60)
S→C HISTORY(items=[39/3 … 45/3])            # finals only, oldest first
S→C CAPTION_UPDATE(seg=46,rev=2,final=false) # active segment
S→C CAPTION_UPDATE(seg=46,rev=3,final=true)  # live continues
```

A congested client during a burst:

```text
S→C CAPTION_UPDATE(seg=51,rev=3,final=true)  # individual live finals
S→C CAPTION_UPDATE(seg=52,rev=3,final=true)
S→C CAPTION_UPDATE(seg=53,rev=3,final=true)
S→C CAPTION_UPDATE(seg=54,rev=2,final=false) # only after waiting 1 s; rev 1 coalesced away
```

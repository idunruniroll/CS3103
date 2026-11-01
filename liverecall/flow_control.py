"""Per-client lag detection and congested-mode pacing.

Why this exists
---------------
TCP and the WebSocket libraries buffer a lot of data. A slow reader (or a
bandwidth bottleneck) does not make ``await ws.send()`` block until the
client library's receive queue, both kernel socket buffers and the server's
transport buffer are all full; by then many stale revisions are queued in
front of the newest caption. Waiting for ``send()`` to block is far too late
to start coalescing.

Signal
------
After sending a caption frame the channel sends a WebSocket ping (at most one
outstanding). A peer answers a ping only after it has read every byte in
front of it, so the ping's age measures how far behind the receiver (or the
path) is. A ping unanswered for longer than ``baseline RTT + lag_threshold``
means "lagging". A large transport write buffer is treated the same way.

Note on receiver libraries: a client library may keep reading from the socket
(and answering pings) until its own message queue fills; Python
``websockets`` buffers 16 frames by default. Lag therefore becomes visible
once that local buffer is full, which is why CONGESTED mode first drains.

Policy (a small state machine)
------------------------------
NORMAL     every revision is sent as soon as the writer is free, so clients
           that keep up receive full revision coverage.
CONGESTED  entered when lag is detected.
           1. DRAIN: send nothing until the outstanding ping is answered,
              i.e. until the client has worked through its backlog.
           2. PACE: at most one frame per ``interval``. Finals go first (all
              pending finals batched into one frame); the newest provisional
              revision is sent only if it has waited ``provisional_hold``
              seconds, so a congested client is not spent on revisions that
              are about to be replaced, yet a long segment still updates.
           Lag detected again doubles the interval (multiplicative back-off);
           clean pongs shrink it back towards the base interval.
PROBE      after a lag-free wait the channel tries NORMAL again. The wait is
           proportional to how long the drain stalled (``probe_factor``,
           between ``min_probe_after`` and ``probe_after``), so a transient
           blip (e.g. one TCP retransmission) ends after a few seconds while
           a truly slow reader stays paced for a minute or more. If lag returns within ``probe_confirm``
           seconds the probe failed and the next wait doubles. This is how a
           client whose network/reader has recovered returns to full-update
           behaviour.

This module is pure logic with an injected clock so that it can be unit
tested without sockets.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

NORMAL = "normal"
CONGESTED = "congested"


@dataclass
class FlowConfig:
    adaptive: bool = True
    lag_threshold: float = 0.3          # s of extra ping delay that means lag
    write_buffer_limit: int = 64 * 1024  # bytes queued in the transport
    slow_interval: float = 0.5          # base s between frames when CONGESTED
    max_slow_interval: float = 4.0
    provisional_hold: float = 1.0       # min wait before a provisional is sent
    drain_timeout: float = 10.0         # give up waiting for a pong after this
    probe_after: float = 60.0           # max lag-free s in CONGESTED before probing
    min_probe_after: float = 2.0
    probe_factor: float = 10.0          # probe wait = factor x observed stall
    max_probe_backoff: int = 8          # failed probes multiply the wait up to this
    probe_confirm: float = 15.0         # s a probe must survive to succeed
    batch_normal: int = 4               # pending finals that trigger batching
    batch_congested: int = 2
    rtt_samples: int = 32


class FlowController:
    def __init__(self, config: FlowConfig, now: float) -> None:
        self.cfg = config
        self.mode = NORMAL
        self.interval = config.slow_interval
        self.next_send_at = now
        self.draining = False
        self.drain_started = now
        self.probe_backoff = 1
        self.probe_at = math.inf
        self.episode_stall = 0.0  # worst drain stall since entering CONGESTED
        self.probing_since: float | None = None
        self.ping_sent_at: float | None = None
        self._rtts: deque[float] = deque(maxlen=config.rtt_samples)
        self.congestion_events = 0

    # ------------------------------------------------------------- ping/pong
    @property
    def baseline_rtt(self) -> float:
        return min(self._rtts) if self._rtts else 0.0

    @property
    def ping_outstanding(self) -> bool:
        return self.ping_sent_at is not None

    @property
    def congested(self) -> bool:
        return self.mode == CONGESTED

    def on_ping_sent(self, now: float) -> None:
        self.ping_sent_at = now

    def on_pong(self, now: float) -> None:
        if self.ping_sent_at is None:
            return
        rtt = now - self.ping_sent_at
        lagged = rtt > self.baseline_rtt + self.cfg.lag_threshold
        self.ping_sent_at = None
        self._rtts.append(rtt)
        if self.draining:
            self._finish_drain(now, stall=rtt)
        elif self.mode == CONGESTED and not lagged:
            self.interval = max(self.cfg.slow_interval, self.interval * 0.9)

    def lagging(self, now: float, write_backlog: int = 0) -> bool:
        if write_backlog > self.cfg.write_buffer_limit:
            return True
        return (self.ping_sent_at is not None
                and now - self.ping_sent_at > self.baseline_rtt + self.cfg.lag_threshold)

    # --------------------------------------------------------- state machine
    def update(self, now: float, write_backlog: int = 0) -> None:
        if not self.cfg.adaptive:
            return
        lag = self.lagging(now, write_backlog)
        if self.mode == NORMAL:
            if lag:
                self._enter_congested(now)
            elif (self.probing_since is not None
                  and now - self.probing_since >= self.cfg.probe_confirm):
                # Probe survived: the client really has recovered.
                self.probing_since = None
                self.probe_backoff = 1
            return

        if self.draining and now - self.drain_started >= self.cfg.drain_timeout:
            # The peer is not answering pings; stop waiting for this one and
            # fall back to plain pacing (a fresh ping follows the next frame).
            self.ping_sent_at = None
            self._finish_drain(now, stall=self.cfg.drain_timeout)
            lag = self.lagging(now, write_backlog)
        if lag and not self.draining:
            # Still overloaded even at the paced rate: back off further.
            self.interval = min(self.cfg.max_slow_interval, self.interval * 2)
            self.congestion_events += 1
            self._start_drain(now)
        elif not lag and not self.draining and now >= self.probe_at:
            self.mode = NORMAL
            self.probing_since = now
            self.probe_at = math.inf

    def _enter_congested(self, now: float) -> None:
        if self.probing_since is not None:
            # Lag came back during a probe: wait longer before the next one.
            self.probe_backoff = min(self.cfg.max_probe_backoff, self.probe_backoff * 2)
            self.probing_since = None
        self.mode = CONGESTED
        self.congestion_events += 1
        self.interval = self.cfg.slow_interval
        self.episode_stall = 0.0
        self._start_drain(now)

    def _start_drain(self, now: float) -> None:
        self.draining = True
        self.drain_started = now
        self.probe_at = math.inf

    def _finish_drain(self, now: float, stall: float) -> None:
        # Leave one interval for whatever is still in the client's own
        # buffer, then pace. The probe clock starts only once drained.
        self.draining = False
        self.next_send_at = max(self.next_send_at, now + self.interval)
        # A short re-stall while already paced must not shorten the wait
        # earned by the severe stall that started this episode.
        self.episode_stall = max(self.episode_stall, stall)
        self.probe_at = now + self.probe_wait(self.episode_stall)

    def probe_wait(self, stall: float) -> float:
        """How long to stay CONGESTED after a drain that took ``stall`` s.

        Proportional to the severity of the lag: one retransmission on a
        lossy link (stall well under a second) costs only a few seconds of
        coalescing, while a genuinely slow reader (multi-second stall) is
        left alone for ``probe_after`` seconds: every failed probe refills
        its receive buffer (~16 frames, ~8 s of stale captions at 500 ms per
        message), which costs far more than the provisional revisions it
        would have gained.
        """
        cfg = self.cfg
        base = min(cfg.probe_after, max(cfg.min_probe_after, cfg.probe_factor * stall))
        return base * self.probe_backoff

    # ------------------------------------------------------------ scheduling
    def send_delay(self, now: float) -> float:
        """Seconds until the next frame may be sent (0 means send now)."""
        if self.mode == NORMAL or not self.cfg.adaptive:
            return 0.0
        if self.draining:
            return max(0.01, self.cfg.drain_timeout - (now - self.drain_started))
        return max(0.0, self.next_send_at - now)

    def on_frame_sent(self, now: float) -> None:
        if self.mode == CONGESTED:
            self.next_send_at = now + self.interval

    @property
    def batch_threshold(self) -> int:
        if self.mode == CONGESTED:
            return self.cfg.batch_congested
        return self.cfg.batch_normal

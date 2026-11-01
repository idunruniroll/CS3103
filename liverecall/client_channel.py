"""One outbound channel per connected client.

The source handler never awaits a client. It calls ``offer()``, which is a
constant-time dictionary update plus an event set. Each client has its own
writer task (``run``) that drains its own queue, so a slow or stalled client
can only delay itself.

Policies (``--policy``):
    adaptive  SemanticQueue + FlowController (default, the graded design):
              full revisions while the client keeps up, coalescing + paced
              batches once lag is detected
    coalesce  SemanticQueue always collapsed, no lag detection: coalescing
              happens only when revisions pile up behind a blocked send()
    fifo      FifoQueue, no coalescing, no flow control (naive baseline)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from websockets.exceptions import ConnectionClosed

from .flow_control import FlowConfig, FlowController
from .protocol import Caption, encode_history
from .semantic_queue import DROPPED, OVERFLOW, FifoQueue, SemanticQueue

log = logging.getLogger("liverecall.channel")

POLICIES = ("adaptive", "coalesce", "fifo")


class ClientChannel:
    def __init__(self, ws: Any, client_id: Any, policy: str,
                 flow_config: FlowConfig, max_pending: int) -> None:
        if policy not in POLICIES:
            raise ValueError(f"unknown policy {policy!r}")
        self.ws = ws
        self.client_id = client_id
        self.policy = policy
        self._loop = asyncio.get_running_loop()
        self.queue = FifoQueue() if policy == "fifo" else SemanticQueue(max_pending)
        self.adaptive = policy == "adaptive" and flow_config.adaptive
        cfg = flow_config if self.adaptive else FlowConfig(adaptive=False)
        self.flow = FlowController(cfg, self._loop.time())
        self._wake = asyncio.Event()
        self._resync = False
        self._ping_seq = 0

        self.frames_sent = 0
        self.captions_sent = 0
        self.batches_sent = 0

    # ------------------------------------------------------------ producer
    def offer(self, caption: Caption) -> None:
        """Called by the source handler for every accepted caption."""
        result = self.queue.offer(caption, self._loop.time())
        if result == DROPPED:
            return
        if result == OVERFLOW:
            self._resync = True
        self._wake.set()

    def mark_delivered(self, captions: Iterable[Caption]) -> None:
        for caption in captions:
            self.queue.mark_delivered(caption)

    # ------------------------------------------------------------ consumer
    async def run(self, initial_frames: list[str]) -> None:
        try:
            for frame in initial_frames:
                await self.ws.send(frame)
                self.frames_sent += 1
            await self._pump()
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:  # never let one client kill the server
            log.exception("writer for client %s failed", self.client_id)
            await self.ws.close(1011, "internal error")

    async def _pump(self) -> None:
        loop = self._loop
        flow = self.flow
        while True:
            if self._resync:
                # The client is hopelessly behind; a reconnect + HISTORY
                # recovers it with bounded memory instead of a growing queue.
                log.info("client %s too far behind: forcing resync", self.client_id)
                await self.ws.close(1013, "resync: reconnect to recover")
                return
            if not len(self.queue):
                self._wake.clear()
                await self._wake.wait()
                continue

            now = loop.time()
            flow.update(now, self._write_backlog())
            if flow.congested or self.policy == "coalesce":
                # The client cannot keep up (or the plain coalescing policy
                # is selected): drop superseded revisions before choosing.
                self.queue.collapse()
            delay = flow.send_delay(now)
            if delay <= 0:
                delay = self._hold_time(now)
            if delay > 0:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), delay)
                except asyncio.TimeoutError:
                    pass
                continue

            frame, count, batched = self._next_frame()
            await self.ws.send(frame)
            now = loop.time()
            flow.on_frame_sent(now)
            self.frames_sent += 1
            self.captions_sent += count
            self.batches_sent += batched
            if self.adaptive and not flow.ping_outstanding:
                await self._send_ping(now)

    def _hold_time(self, now: float) -> float:
        """While congested, how long to keep holding provisional-only state.

        A congested client gets finals immediately, but a provisional revision
        only once it has waited ``provisional_hold`` seconds: most provisional
        revisions are superseded (and coalesced away) before then.
        """
        if not self.flow.congested or self.queue.finals_pending:
            return 0.0
        return self.flow.cfg.provisional_hold - self.queue.oldest_wait(now)

    def _next_frame(self) -> tuple[str, int, int]:
        """Pick the most useful frame to send next."""
        finals_pending = self.queue.finals_pending
        if finals_pending and (self.flow.congested
                               or finals_pending >= self.flow.batch_threshold):
            finals = self.queue.pop_finals()
            self.mark_delivered(finals)
            if len(finals) == 1:
                return finals[0].wire, 1, 0
            # Several finals are waiting: deliver them all in one HISTORY
            # frame. The receiver pays per-frame cost once, not per caption.
            return encode_history(finals), len(finals), 1
        caption = self.queue.pop()
        self.queue.mark_delivered(caption)
        return caption.wire, 1, 0

    def _write_backlog(self) -> int:
        transport = getattr(self.ws, "transport", None)
        if transport is None:
            return 0
        try:
            return transport.get_write_buffer_size()
        except Exception:
            return 0

    async def _send_ping(self, now: float) -> None:
        self._ping_seq += 1
        self.flow.on_ping_sent(now)
        waiter = await self.ws.ping(self._ping_seq.to_bytes(8, "big"))
        waiter.add_done_callback(self._on_pong)

    def _on_pong(self, fut: asyncio.Future) -> None:
        if fut.cancelled() or fut.exception() is not None:
            return
        self.flow.on_pong(self._loop.time())
        self._wake.set()

    # --------------------------------------------------------------- stats
    @property
    def congested(self) -> bool:
        return self.flow.congested

    @property
    def pending(self) -> int:
        return len(self.queue)

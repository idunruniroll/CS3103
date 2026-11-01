"""WebSocket connection handling for caption sources and clients.

Each session owns its caption state and client channels. A new client gets its
history and any current provisional caption before it starts receiving live
updates.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from websockets.exceptions import ConnectionClosed

from .caption_state import ACCEPTED, CaptionState
from .client_channel import ClientChannel
from .flow_control import FlowConfig
from .protocol import (
    DEFAULT_SESSION,
    ProtocolError,
    caption_from_message,
    encode_history,
    parse_client_hello,
    parse_json,
)

log = logging.getLogger("liverecall.hub")


@dataclass
class ServerConfig:
    policy: str = "adaptive"
    retention_seconds: float = 90.0
    max_pending: int = 256
    hello_timeout: float = 5.0
    max_sessions: int = 16
    flow: FlowConfig = field(default_factory=FlowConfig)


class Session:
    def __init__(self, name: str, config: ServerConfig) -> None:
        self.name = name
        self.state = CaptionState(retention_seconds=config.retention_seconds)
        self.channels: set[ClientChannel] = set()


class LiveRecallHub:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.sessions: dict[str, Session] = {}
        self.totals = {
            "invalid_messages": 0,
            "client_connections": 0,
            "frames_sent": 0,
            "captions_sent": 0,
            "batches_sent": 0,
            "coalesced": 0,
            "congestion_events": 0,
        }

    def session(self, name: str) -> Session | None:
        session = self.sessions.get(name)
        if session is None and len(self.sessions) < self.config.max_sessions:
            session = self.sessions[name] = Session(name, self.config)
        return session

    def channels(self) -> list[ClientChannel]:
        return [ch for s in self.sessions.values() for ch in s.channels]

    async def handler(self, ws: Any) -> None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=self.config.hello_timeout)
            hello = parse_json(raw)
        except (asyncio.TimeoutError, ProtocolError):
            await ws.close(1008, "expected SOURCE_HELLO or CLIENT_HELLO")
            return
        except ConnectionClosed:
            return

        kind = hello.get("type")
        if kind == "SOURCE_HELLO":
            await self.handle_source(ws, hello)
        elif kind == "CLIENT_HELLO":
            await self.handle_client(ws, hello)
        else:
            await ws.close(1008, "expected SOURCE_HELLO or CLIENT_HELLO")

    async def handle_source(self, ws: Any, hello: dict[str, Any]) -> None:
        name = hello.get("session")
        if not isinstance(name, str):
            name = DEFAULT_SESSION
        session = self.session(name)
        if session is None:
            await ws.close(1013, "too many sessions")
            return
        log.info("source connected: session=%s", name)
        state = session.state
        try:
            async for raw in ws:
                try:
                    msg = parse_json(raw)
                except ProtocolError:
                    self.totals["invalid_messages"] += 1
                    continue
                kind = msg.get("type")
                if kind == "CAPTION_UPDATE":
                    try:
                        caption = caption_from_message(msg, name)
                    except ProtocolError:
                        self.totals["invalid_messages"] += 1
                        continue
                    if caption.session != name:
                        continue
                    if state.apply(caption) == ACCEPTED:
                        for channel in session.channels:
                            channel.offer(caption)
                elif kind == "SOURCE_DONE":
                    log.info("source done: session=%s", name)
                # Ignore unknown messages so newer clients do not break us.
        except ConnectionClosed:
            pass
        finally:
            log.info("source disconnected: session=%s", name)

    async def handle_client(self, ws: Any, raw_hello: dict[str, Any]) -> None:
        hello = parse_client_hello(raw_hello)
        session = self.session(hello.session)
        if session is None:
            await ws.close(1013, "too many sessions")
            return

        channel = ClientChannel(ws, hello.client_id, self.config.policy,
                                self.config.flow, self.config.max_pending)

        # Do this without yielding so a caption cannot land between the
        # history snapshot and channel registration.
        history = session.state.history_since(
            hello.last_segment, hello.last_revision, hello.history_seconds)
        channel.mark_delivered(history)
        initial = [encode_history(history)]
        for caption in session.state.active_captions():
            if caption.segment > hello.last_segment:
                initial.append(caption.wire)
                channel.queue.mark_delivered(caption)
        session.channels.add(channel)
        self.totals["client_connections"] += 1
        log.debug("client connected: id=%s session=%s cursor=%s/%s history=%d",
                  hello.client_id, session.name, hello.last_segment,
                  hello.last_revision, len(history))
        writer = asyncio.create_task(channel.run(initial))
        try:
            # Keep receiving so close frames and pongs are handled promptly.
            async for _ in ws:
                pass
        except ConnectionClosed:
            pass
        finally:
            session.channels.discard(channel)
            writer.cancel()
            try:
                await writer
            except (asyncio.CancelledError, ConnectionClosed):
                pass
            self._absorb(channel)
            log.debug("client disconnected: id=%s", hello.client_id)

    def _absorb(self, channel: ClientChannel) -> None:
        t = self.totals
        t["frames_sent"] += channel.frames_sent
        t["captions_sent"] += channel.captions_sent
        t["batches_sent"] += channel.batches_sent
        t["coalesced"] += channel.queue.coalesced
        t["congestion_events"] += channel.flow.congestion_events

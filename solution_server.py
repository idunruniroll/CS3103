#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall naive working baseline.

This starter is intentionally useful but incomplete. It provides the required
CLI and a basic WebSocket broadcaster so that caption_source.py -> server ->
browser/load clients works on day one.

It DOES NOT implement the graded networking mechanisms:
  - revision-state management or deduplication
  - recent-history recovery or late-join recovery
  - bounded per-client application queues
  - slow-client isolation
  - semantic coalescing / backpressure
  - constrained-bandwidth overload handling

Required evaluator command:
    python solution_server.py --port 8765

Teams should replace or substantially extend the implementation while keeping
this command-line interface and the protocol in the assignment specification.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from collections import deque
import time
import websockets

# Naive global set of currently connected student clients.
# There is deliberately no per-client queue or recovery state here.
CLIENTS: set[Any] = set()

# store recent finalised for recovery
HISTORY_SECONDS = 70 # slighltly longer than 60s to account for network delay

# each item is a complete CAPTION_UPDATE msg
FINAL_HISTORY = deque()

# latest revision for the currently active segment
ACTIVE_SEGMENT = None

def prune_history():
    """remove finalised capttions outside the retention window"""
    cutoff = time.time() - HISTORY_SECONDS
    while FINAL_HISTORY and FINAL_HISTORY[0]["source_ts"] < cutoff:
        FINAL_HISTORY.popleft()

def accept_caption(msg):
    """validate a caption update and update the server's state"""
    global ACTIVE_SEGMENT

    segment = msg.get("segment")
    revision = msg.get("revision")
    source_ts = msg.get("source_ts")
    is_final = msg.get("final")

    if (type(segment) is not int or segment <= 0
        or type(revision) is not int or revision <= 0
        or not isinstance(source_ts, (int, float))
        or type(is_final) is not bool
        or not isinstance(msg.get("text"), str)):
        return False

    prune_history()

    # ignore stale/dup updates to recent finalised segments
    if any(c["segment"] == segment for c in FINAL_HISTORY):
        return False

    if ACTIVE_SEGMENT is not None:
        active_id = ACTIVE_SEGMENT["segment"]

        # the supplised src emits successive segment numbers
        if segment < active_id:
            return False

        if segment == active_id:
            if revision <= ACTIVE_SEGMENT["revision"]:
                return False
            if ACTIVE_SEGMENT["final"]:
                return False

    ACTIVE_SEGMENT = msg

    if is_final:
        FINAL_HISTORY.append(msg)
        ACTIVE_SEGMENT = None
        prune_history()

        print(
            f"Stored final segment {segment}, "
            f"history size={len(FINAL_HISTORY)}",
            flush=True
        )

    return True

def build_history(hello):
    """build incremental history for connecting a client"""
    prune_history()

    last_segment = hello.get("last_segment", 0)
    last_revision = hello.get("last_revision", 0)
    seconds = hello.get("history_seconds", 30)

    if type(last_segment) is not int or last_segment < 0:
        last_segment = 0

    if type(last_revision) is not int or last_revision < 0:
        last_revision = 0

    if type(seconds) is not int:
        seconds = 30

    seconds = max(0, min(seconds, 60))
    cutoff = time.time() - seconds

    items = [caption for caption in FINAL_HISTORY
             if caption["source_ts"] >= cutoff
             and (caption["segment"] > last_segment
                  or (caption["segment"] == last_segment
                      and caption["revision"] > last_revision))]

    items.sort(key=lambda c: (c["segment"], c["revision"]))
    return {"type": "HISTORY", "items": items}


async def broadcast_naively(raw_message: str) -> None:
    """Send one message directly to every connected client.

    This is intentionally a naive baseline. The source handler waits for all
    sends to complete. Under pressure, this design may accumulate delay and is
    not the target architecture for the assignment.
    """
    if not CLIENTS:
        return

    snapshot = list(CLIENTS)
    results = await asyncio.gather(
        *(client.send(raw_message) for client in snapshot),
        return_exceptions=True,
    )
    for client, result in zip(snapshot, results):
        if isinstance(result, Exception):
            CLIENTS.discard(client)


async def handle_source(ws, hello: dict[str, Any]) -> None:
    session = hello.get("session")
    print(f"source connected: session={session}", flush=True)

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "CAPTION_UPDATE":
                # Baseline behavior: forward exactly what was received.
                # No history, state, validation, coalescing, or bounded queues.
                if msg.get("session") != session:
                    continue
                if accept_caption(msg):
                    await broadcast_naively(raw)
            elif msg_type == "SOURCE_DONE":
                # Test-control message. The specification does not require it
                # to be forwarded to clients.
                print("source finished", flush=True)
            else:
                # Forward compatibility: ignore fields/messages this baseline
                # doesn't understand rather than crashing.
                continue
    finally:
        print("source disconnected", flush=True)


async def handle_client(ws, hello: dict[str, Any]) -> None:
    client_id = hello.get("client_id")

    # The baseline has no stored recovery state. Sending an empty HISTORY makes
    # the connection behavior visible and keeps the starter easy to inspect.
    # Students must implement correct HISTORY semantics for the assignment.
    # Register before sending history so live updates arriving
    # during connection setup are not silently missed.
    CLIENTS.add(ws)

    try:
        history = build_history(hello)
        await ws.send(json.dumps(history))

        print(
            f"client {client_id}: sent {len(history['items'])} recovery captions",
            flush=True
        )
    except Exception:
        CLIENTS.discard(ws)
        raise
    print(f"client connected: id={client_id}; clients={len(CLIENTS)}", flush=True)
    try:
        # Student clients normally don't send further messages after hello.
        # Keep the WebSocket open until the client disconnects.
        async for _ in ws:
            pass
    finally:
        CLIENTS.discard(ws)
        print(f"client disconnected: id={client_id}; clients={len(CLIENTS)}", flush=True)


async def handler(ws) -> None:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(code=1008, reason="Expected a valid hello message")
        return

    msg_type = hello.get("type")
    if msg_type == "SOURCE_HELLO":
        await handle_source(ws, hello)
    elif msg_type == "CLIENT_HELLO":
        await handle_client(ws, hello)
    else:
        await ws.close(code=1008, reason="Expected SOURCE_HELLO or CLIENT_HELLO")


async def main_async(port: int) -> None:
    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=20,
    ):
        print(f"LiveRecall baseline listening on ws://0.0.0.0:{port}", flush=True)
        await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

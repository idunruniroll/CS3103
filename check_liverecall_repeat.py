#!/usr/bin/env python3
"""End-to-end check: two sequential caption sources, one unchanged server/client.

Start the server separately, then run from the repository root:
    python check_liverecall_repeat.py

Uses the standard SOURCE_HELLO / CAPTION_UPDATE / SOURCE_DONE protocol and does
not alter the instructor's caption_source.py or the performance test harness.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets


async def transmit_round(uri: str, session: str, round_number: int, count: int) -> None:
    async with websockets.connect(uri) as source:
        await source.send(json.dumps({"type": "SOURCE_HELLO", "session": session}))
        for segment in range(1, count + 1):
            for revision in (1, 2):
                final = revision == 2
                event = {
                    "type": "CAPTION_UPDATE",
                    "session": session,
                    "segment": segment,
                    "revision": revision,
                    "source_ts": time.time(),
                    "final": final,
                    "text": f"repeat-smoke round={round_number} segment={segment} " +
                            ("final" if final else "provisional"),
                }
                await source.send(json.dumps(event))
                await asyncio.sleep(0.035)
        await source.send(json.dumps({
            "type": "SOURCE_DONE", "session": session, "source_ts": time.time(),
            "segments": count,
        }))
        await asyncio.sleep(0.15)


async def read_finals(client, round_number: int, count: int) -> list[dict]:
    finals = []
    deadline = asyncio.get_running_loop().time() + 8
    while len(finals) < count:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"Only {len(finals)}/{count} finals from round {round_number}")
        frame = json.loads(await asyncio.wait_for(client.recv(), timeout=remaining))
        if frame.get("type") != "CAPTION_UPDATE" or not frame.get("final"):
            continue
        if frame.get("text", "").startswith(f"repeat-smoke round={round_number} "):
            finals.append(frame)
    return finals


async def check(uri: str, session: str, count: int) -> None:
    async with websockets.connect(uri) as client:
        await client.send(json.dumps({
            "type": "CLIENT_HELLO", "client_id": "repeat-smoke-test",
            "session": session, "last_segment": 0, "last_revision": 0,
            "history_seconds": 0,
        }))
        first = json.loads(await asyncio.wait_for(client.recv(), timeout=3))
        assert first["type"] == "HISTORY", f"Expected HISTORY, got {first}"
        results = []
        for round_number in (1, 2):
            await transmit_round(uri, session, round_number, count)
            received = await read_finals(client, round_number, count)
            segments = [c["segment"] for c in received]
            print(f"Round {round_number} final IDs: {segments}")
            assert segments == list(range(segments[0], segments[0] + count)), (
                f"Nonconsecutive IDs in round {round_number}: {segments}"
            )
            results.extend(received)
        segments = [c["segment"] for c in results]
        assert len(set(segments)) == 2 * count, "Duplicate IDs across source runs"
        assert segments == list(range(segments[0], segments[0] + 2 * count)), (
            f"IDs did not continue across source runs: {segments}"
        )
        print("PASS: second caption source accepted; clients stayed connected; IDs unique.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="ws://127.0.0.1:8765")
    parser.add_argument("--session", default="L1")
    parser.add_argument("--segments", type=int, default=3)
    args = parser.parse_args()
    if args.segments <= 0:
        parser.error("--segments must be positive")
    asyncio.run(check(args.uri, args.session, args.segments))


if __name__ == "__main__":
    main()

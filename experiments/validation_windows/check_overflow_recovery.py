"""Deterministic integration check using a real WebSocket close and reconnect.

Run from the repository root with python -m experiments.validation_windows.check_overflow_recovery.
The synchronous offers force queue overflow independently of TCP buffer sizes.
"""
import asyncio
import json
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from liverecall.hub import LiveRecallHub, ServerConfig
from tests.helpers import cap


class OverflowRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_close_and_incremental_recovery(self):
        hub = LiveRecallHub(ServerConfig(max_pending=2))
        hello = {"type": "CLIENT_HELLO", "client_id": 1, "session": "L1",
                 "last_segment": 0, "last_revision": 0, "history_seconds": 60}
        async with serve(hub.handler, "127.0.0.1", 0) as server:
            uri = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            session = hub.session("L1")
            session.state.apply(cap(1, 1, final=True))
            async with connect(uri) as client:
                await client.send(json.dumps(hello))
                first = json.loads(await asyncio.wait_for(client.recv(), 2))
                self.assertEqual([c["segment"] for c in first["items"]], [1])
                channel = hub.channels()[0]
                for segment in (2, 3, 4):
                    caption = cap(segment, 1, final=True)
                    session.state.apply(caption)
                    channel.offer(caption)
                self.assertEqual(channel.queue.segments_pending, 2)
                self.assertTrue(channel._resync)
                await asyncio.wait_for(client.wait_closed(), 2)
                self.assertEqual(client.close_code, 1013)
            hello.update(last_segment=1, last_revision=1)
            async with connect(uri) as resumed:
                await resumed.send(json.dumps(hello))
                history = json.loads(await asyncio.wait_for(resumed.recv(), 2))
                self.assertEqual(history["type"], "HISTORY")
                self.assertEqual([c["segment"] for c in history["items"]], [2, 3, 4])
                self.assertTrue(all(c["final"] for c in history["items"]))


if __name__ == "__main__":
    unittest.main()

"""End-to-end tests: real WebSocket server, source and clients in-process."""

import asyncio
import json
import time
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from liverecall.flow_control import FlowConfig
from liverecall.hub import LiveRecallHub, ServerConfig


def update(seg, rev, final, text=None):
    return json.dumps({
        "type": "CAPTION_UPDATE", "session": "L1", "segment": seg,
        "revision": rev, "source_ts": time.time(), "final": final,
        "text": text or f"s{seg}r{rev}", "phase": "test",
    })


def hello(last_segment=0, last_revision=0, seconds=60):
    return json.dumps({
        "type": "CLIENT_HELLO", "client_id": 1, "session": "L1",
        "last_segment": last_segment, "last_revision": last_revision,
        "history_seconds": seconds,
    })


class ServerTestCase(unittest.IsolatedAsyncioTestCase):
    policy = "adaptive"

    async def asyncSetUp(self):
        self.hub = LiveRecallHub(ServerConfig(
            policy=self.policy, flow=FlowConfig(lag_threshold=0.3)))
        self.server = await serve(self.hub.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.uri = f"ws://127.0.0.1:{port}"
        self.source = await connect(self.uri)
        await self.source.send(json.dumps({"type": "SOURCE_HELLO", "session": "L1"}))

    async def asyncTearDown(self):
        await self.source.close()
        self.server.close()
        await self.server.wait_closed()

    async def publish(self, seg, revisions=3):
        for rev in range(1, revisions + 1):
            await self.source.send(update(seg, rev, rev == revisions))

    async def settle(self):
        await asyncio.sleep(0.15)


async def collect(ws, until_segment_final, timeout=5.0):
    """Receive until the final of `until_segment_final` arrives."""
    got = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
        if msg["type"] == "HISTORY":
            got.extend(("H", i["segment"], i["revision"], i["final"]) for i in msg["items"])
            if any(i["segment"] == until_segment_final for i in msg["items"]):
                return got
        else:
            got.append(("L", msg["segment"], msg["revision"], msg["final"]))
            if msg["segment"] == until_segment_final and msg["final"]:
                return got
    raise AssertionError(f"timed out; got {got}")


class ProtocolBehaviourTest(ServerTestCase):
    async def test_restarted_source_keeps_client_and_resume_cursors(self):
        from check_liverecall_repeat import check

        await asyncio.wait_for(check(self.uri, "L1", 3), timeout=15)
        self.assertEqual(self.hub.sessions["L1"].highest_segment, 6)
        async with connect(self.uri) as client:
            await client.send(hello(last_segment=3, last_revision=2))
            history = json.loads(await asyncio.wait_for(client.recv(), timeout=3))
        self.assertEqual([item["segment"] for item in history["items"]], [4, 5, 6])

    async def test_live_revisions_and_stale_updates(self):
        async with connect(self.uri) as client:
            await client.send(hello())
            first = json.loads(await client.recv())
            self.assertEqual(first, {"type": "HISTORY", "items": []})
            await self.publish(1)
            await self.source.send(update(1, 2, False))   # stale after final
            await self.publish(2)
            got = await collect(client, 2)
        self.assertEqual(got, [("L", 1, 1, False), ("L", 1, 2, False), ("L", 1, 3, True),
                               ("L", 2, 1, False), ("L", 2, 2, False), ("L", 2, 3, True)])

    async def test_late_join_gets_history_then_live(self):
        for seg in range(1, 6):
            await self.publish(seg)
        await self.source.send(update(6, 1, False))
        await self.settle()
        async with connect(self.uri) as client:
            await client.send(hello())
            history = json.loads(await client.recv())
            self.assertEqual([i["segment"] for i in history["items"]], [1, 2, 3, 4, 5])
            self.assertTrue(all(i["final"] for i in history["items"]))
            active = json.loads(await client.recv())
            self.assertEqual((active["segment"], active["revision"]), (6, 1))
            await self.source.send(update(6, 2, True))
            live = json.loads(await client.recv())
            self.assertEqual((live["segment"], live["revision"], live["final"]), (6, 2, True))

    async def test_resume_returns_only_missed_finals(self):
        for seg in range(1, 11):
            await self.publish(seg)
        await self.settle()
        async with connect(self.uri) as client:
            await client.send(hello(last_segment=7, last_revision=3))
            history = json.loads(await client.recv())
        self.assertEqual([i["segment"] for i in history["items"]], [8, 9, 10])

    async def test_bad_hello_is_rejected_without_crashing(self):
        async with connect(self.uri) as bad:
            await bad.send("not json")
            await bad.wait_closed()
        self.assertEqual(bad.close_code, 1008)
        async with connect(self.uri) as good:   # server still serving
            await good.send(hello())
            self.assertEqual(json.loads(await good.recv())["type"], "HISTORY")


class SlowClientTest(ServerTestCase):
    async def test_stalled_client_does_not_delay_others_and_stays_bounded(self):
        stalled = await connect(self.uri, max_queue=4)
        await stalled.send(hello())
        normal = await connect(self.uri)
        await normal.send(hello())
        self.assertEqual(json.loads(await normal.recv())["type"], "HISTORY")
        await self.settle()

        received = []

        async def reader():
            async for raw in normal:
                msg = json.loads(raw)
                received.append((time.time(), msg))
                if msg.get("segment") == 60 and msg.get("final"):
                    return

        task = asyncio.create_task(reader())
        for seg in range(1, 61):
            await self.publish(seg, revisions=4)
            await asyncio.sleep(0.01)
        await asyncio.wait_for(task, 10)

        # A normal client should receive every revision promptly.
        live = [m for _, m in received if m["type"] == "CAPTION_UPDATE"]
        self.assertEqual(len(live), 240)
        ages = [t - m["source_ts"] for t, m in received if m["type"] == "CAPTION_UPDATE"]
        self.assertLess(max(ages), 0.5)

        # A stalled client should stay bounded and enter congested mode.
        await asyncio.sleep(0.5)
        channels = self.hub.channels()
        stalled_channel = max(channels, key=lambda ch: ch.pending)
        self.assertLessEqual(stalled_channel.pending, 60)
        self.assertTrue(stalled_channel.congested)
        await stalled.close()
        await normal.close()


if __name__ == "__main__":
    unittest.main()

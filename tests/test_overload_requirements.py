"""Contract tests for the clarified overload requirements.

Run: python -m unittest tests.test_overload_requirements -v
These use a controlled transport rather than OS-dependent socket buffers.
They are representative scenarios, not a reproduction of hidden parameters.
"""

import asyncio
import json
import unittest

from liverecall.caption_state import CaptionState
from liverecall.client_channel import ClientChannel
from liverecall.flow_control import FlowConfig
from tests.helpers import FakeClock, cap


class LimitedTransport:
    """A reader with finite byte capacity and no hidden outbound queue."""

    def __init__(self, bytes_per_second):
        self.bytes_per_second = bytes_per_second
        self.received = []
        self.closed = None

    async def send(self, frame):
        await asyncio.sleep(len(frame.encode("utf-8")) / self.bytes_per_second)
        self.received.append(json.loads(frame))

    async def ping(self, payload):
        pong = asyncio.get_running_loop().create_future()
        pong.set_result(None)
        return pong

    async def close(self, code, reason):
        self.closed = (code, reason)


def captions(messages):
    # Count finals independently of the separate frame-type contract test.
    return [item for msg in messages
            for item in (msg["items"] if msg["type"] == "HISTORY" else [msg])]


class LiveDeliveryContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_finals_never_use_unsolicited_history(self):
        for congested in (False, True):
            with self.subTest(congested=congested):
                channel = ClientChannel(LimitedTransport(10000), "test", "adaptive",
                                        FlowConfig(), 32)
                if congested:
                    channel.flow.update(channel._loop.time(), 100000)
                for seg in range(1, 7):
                    channel.offer(cap(seg, 1))
                    channel.offer(cap(seg, 2, final=True))
                delivered = []
                while channel.pending:
                    frame, _, _ = channel._next_frame()
                    msg = json.loads(frame)
                    self.assertEqual(msg["type"], "CAPTION_UPDATE",
                                     "Live delivery must not batch finals into HISTORY")
                    delivered.append(msg)
                self.assertEqual({m["segment"] for m in delivered if m["final"]},
                                 set(range(1, 7)))

    async def test_bandwidth_suppresses_revisions_but_delivers_finals_during_source(self):
        # 10 finals/s fit easily; 400 full revisions/s exceed this byte rate.
        for bandwidth in (6000, 12000):
            with self.subTest(bytes_per_second=bandwidth):
                ws = LimitedTransport(bandwidth)
                channel = ClientChannel(ws, "slow", "adaptive", FlowConfig(), 32)
                if bandwidth == 6000:
                    # Model a reader that has drained a previous backlog but
                    # remains congested. Finals must exceed the 2 frames/s
                    # provisional pacing limit without HISTORY batching.
                    now = channel._loop.time()
                    channel.flow.on_ping_sent(now - 0.4)
                    channel.flow.update(now)
                    channel.flow.on_pong(now)
                    self.assertTrue(channel.congested)
                writer = asyncio.create_task(channel.run([]))
                peak_pending = 0
                try:
                    for seg in range(1, 21):
                        for rev in range(1, 41):
                            channel.offer(cap(seg, rev, final=rev == 40))
                            peak_pending = max(peak_pending, channel.pending)
                        await asyncio.sleep(0.1)
                        if seg == 10:
                            live_finals = {m["segment"] for m in captions(ws.received)
                                           if m["final"]}
                            self.assertTrue(set(range(1, 8)) <= live_finals,
                                            "Finals must arrive while the source is running")
                    # Latest useful state must also reach a client without a final.
                    for rev in range(1, 41):
                        channel.offer(cap(21, rev))
                    async def complete():
                        while True:
                            got = captions(ws.received)
                            finals = {m["segment"] for m in got if m["final"]}
                            latest = any(m["segment"] == 21 and m["revision"] == 40
                                         for m in got)
                            if finals == set(range(1, 21)) and latest:
                                return
                            await asyncio.sleep(0.01)
                    await asyncio.wait_for(complete(), timeout=2.0)
                    self.assertIsNone(ws.closed, "Client with sufficient final capacity closed")
                    self.assertTrue(all(m["type"] == "CAPTION_UPDATE"
                                        for m in ws.received))
                    self.assertLessEqual(peak_pending, 32 * 16)
                    self.assertGreater(channel.queue.coalesced, 0)
                    self.assertLess(len(captions(ws.received)), 20 * 40)
                finally:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)


class RetentionContractTest(unittest.TestCase):
    def test_long_lecture_retains_previous_60_seconds_and_resume_cursor(self):
        clock = FakeClock()
        state = CaptionState(clock=clock)
        for seg in range(1, 7201):
            state.apply(cap(seg, 2, final=True))
            clock.advance(0.5)
            self.assertLessEqual(state.snapshot()["finals_retained"], 181)
        self.assertEqual([c.segment for c in state.history_since(0, 0, 60)],
                         list(range(7081, 7201)))
        self.assertEqual([c.segment for c in state.history_since(7190, 2, 60)],
                         list(range(7191, 7201)))
        clock.advance(91)
        self.assertEqual(state.history_since(0, 0, 60), [])


if __name__ == "__main__":
    unittest.main()

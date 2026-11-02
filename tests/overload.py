
import asyncio
import json
import time
import unittest

from liverecall.client_channel import ClientChannel
from liverecall.flow_control import FlowConfig
from liverecall.protocol import Caption


class BlockedWebSocket:
    def __init__(self):
        self.send_started = asyncio.Event()
        self.allow_send = asyncio.Event()
        self.close_code = None
        self.close_reason = None

    async def send(self, frame):
        self.send_started.set()
        await self.allow_send.wait()

    async def close(self, code, reason):
        self.close_code = code
        self.close_reason = reason


class TestR11Overload(unittest.IsolatedAsyncioTestCase):

    async def test_overflow_triggers_1013(self):
        ws = BlockedWebSocket()

        channel = ClientChannel(
            ws=ws,
            client_id="r11-test",
            policy="adaptive",
            flow_config=FlowConfig(),
            max_pending=2,
        )

        writer = asyncio.create_task(
            channel.run([
                json.dumps({"type": "HISTORY", "items": []})
            ])
        )

        await asyncio.wait_for(ws.send_started.wait(), 2)

        try:
            # Use the same Caption constructor as your
            # existing protocol tests.
            def caption(segment):
                msg = {
                    "type": "CAPTION_UPDATE",
                    "session": "L1",
                    "segment": segment,
                    "revision": 1,
                    "source_ts": time.time(),
                    "final": True,
                    "text": f"Final caption {segment}",
                }

                return Caption(
                    session="L1",
                    segment=segment,
                    revision=1,
                    source_ts=msg["source_ts"],
                    final=True,
                    text=msg["text"],
                    wire=json.dumps(msg),
                )

            channel.offer(caption(1))
            channel.offer(caption(2))
            channel.offer(caption(3))

            self.assertTrue(
                channel._resync,
                "Queue overflow should request resync"
            )

            ws.allow_send.set()
            await asyncio.wait_for(writer, 2)

            self.assertEqual(ws.close_code, 1013)
            self.assertIn("resync", ws.close_reason)

        finally:
            ws.allow_send.set()
            if not writer.done():
                writer.cancel()
                await asyncio.gather(
                    writer, return_exceptions=True
                )


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from liverecall.protocol import (
    ProtocolError,
    caption_from_message,
    encode_history,
    parse_client_hello,
    parse_json,
)


def update(**overrides):
    msg = {
        "type": "CAPTION_UPDATE",
        "session": "L1",
        "segment": 42,
        "revision": 3,
        "source_ts": 1760000000.123,
        "final": True,
        "text": "TCP uses cumulative acknowledgements.",
    }
    msg.update(overrides)
    return msg


class CaptionParsingTest(unittest.TestCase):
    def test_valid_update_round_trips(self):
        c = caption_from_message(update(), "L1")
        self.assertEqual((c.segment, c.revision, c.final), (42, 3, True))
        wire = json.loads(c.wire)
        self.assertEqual(wire["type"], "CAPTION_UPDATE")
        self.assertEqual(wire["text"], "TCP uses cumulative acknowledgements.")

    def test_unknown_fields_are_ignored_and_not_forwarded(self):
        c = caption_from_message(update(phase="T3", extra={"x": 1}), "L1")
        self.assertNotIn("phase", json.loads(c.wire))

    def test_missing_session_uses_source_session(self):
        msg = update()
        del msg["session"]
        self.assertEqual(caption_from_message(msg, "L1").session, "L1")

    def test_rejects_bad_fields(self):
        bad = [
            update(segment=0),
            update(segment="3"),
            update(revision=-1),
            update(revision=True),      # bool is not an int here
            update(final="true"),
            update(source_ts=float("nan")),
            update(text=None),
        ]
        for msg in bad:
            with self.subTest(msg=msg), self.assertRaises(ProtocolError):
                caption_from_message(msg, "L1")

    def test_parse_json_rejects_non_objects(self):
        with self.assertRaises(ProtocolError):
            parse_json("[1, 2]")
        with self.assertRaises(ProtocolError):
            parse_json("{not json")
        self.assertEqual(parse_json(b'{"type":"X"}'), {"type": "X"})


class ClientHelloTest(unittest.TestCase):
    def test_defaults(self):
        hello = parse_client_hello({"type": "CLIENT_HELLO"})
        self.assertEqual((hello.last_segment, hello.last_revision), (0, 0))
        self.assertEqual(hello.history_seconds, 30)
        self.assertEqual(hello.session, "L1")

    def test_history_seconds_is_clamped(self):
        self.assertEqual(parse_client_hello({"history_seconds": 600}).history_seconds, 60)
        self.assertEqual(parse_client_hello({"history_seconds": -5}).history_seconds, 0)

    def test_bad_cursor_means_no_previous_state(self):
        hello = parse_client_hello({"last_segment": "38", "last_revision": 3})
        self.assertEqual((hello.last_segment, hello.last_revision), (0, 0))


class HistoryEncodingTest(unittest.TestCase):
    def test_history_frame_is_valid_json(self):
        items = [caption_from_message(update(segment=s), "L1") for s in (1, 2)]
        frame = json.loads(encode_history(items))
        self.assertEqual(frame["type"], "HISTORY")
        self.assertEqual([i["segment"] for i in frame["items"]], [1, 2])
        self.assertEqual(json.loads(encode_history([])), {"type": "HISTORY", "items": []})


if __name__ == "__main__":
    unittest.main()

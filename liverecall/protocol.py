"""LiveRecall wire protocol helpers.

Implements the compatibility interface from assignment section 4:

    SOURCE_HELLO   source -> server   {"type", "session"}
    CAPTION_UPDATE source -> server -> client
                   {"type", "session", "segment", "revision", "source_ts",
                    "final", "text"}
    SOURCE_DONE    source -> server   (test control, not forwarded)
    CLIENT_HELLO   client -> server   {"type", "client_id", "session",
                    "last_segment", "last_revision", "history_seconds"}
    HISTORY        server -> client   {"type", "items": [CAPTION_UPDATE, ...]}

Every accepted caption is encoded to JSON exactly once (``Caption.wire``) and
that string is shared by every client queue, so fan-out cost does not include
per-client serialisation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_SESSION = "L1"
DEFAULT_HISTORY_SECONDS = 30
MAX_HISTORY_SECONDS = 60

_COMPACT = (",", ":")


class ProtocolError(ValueError):
    """Raised when a message cannot be interpreted."""


def _is_int(value: Any) -> bool:
    # bool is a subclass of int in Python; True must not be accepted as 1.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (_is_int(value) or isinstance(value, float)) and math.isfinite(value)


@dataclass(frozen=True)
class Caption:
    """One accepted caption revision.

    ``wire`` is the canonical CAPTION_UPDATE JSON text sent to clients. Extra
    source fields (e.g. a test-phase label) are intentionally dropped so that
    clients only receive the documented fields.
    """

    session: str
    segment: int
    revision: int
    source_ts: float
    final: bool
    text: str
    wire: str

    @property
    def key(self) -> tuple[int, int]:
        return (self.segment, self.revision)


def parse_json(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("message is not UTF-8") from exc
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("message is not valid JSON") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a JSON object")
    return msg


def encode_caption(session: str, segment: int, revision: int, source_ts: float,
                   final: bool, text: str) -> str:
    return json.dumps(
        {
            "type": "CAPTION_UPDATE",
            "session": session,
            "segment": segment,
            "revision": revision,
            "source_ts": source_ts,
            "final": final,
            "text": text,
        },
        separators=_COMPACT,
        ensure_ascii=False,
    )


def caption_from_message(msg: dict[str, Any], default_session: str) -> Caption:
    """Validate a CAPTION_UPDATE from the source and build a Caption.

    Unknown fields are ignored. Missing/ill-typed required fields raise
    ProtocolError so the caller can drop the message without crashing.
    """
    segment = msg.get("segment")
    revision = msg.get("revision")
    source_ts = msg.get("source_ts")
    final = msg.get("final")
    text = msg.get("text")
    session = msg.get("session", default_session)

    if not _is_int(segment) or segment <= 0:
        raise ProtocolError("segment must be a positive integer")
    if not _is_int(revision) or revision <= 0:
        raise ProtocolError("revision must be a positive integer")
    if not _is_number(source_ts):
        raise ProtocolError("source_ts must be a finite number")
    if not isinstance(final, bool):
        raise ProtocolError("final must be a boolean")
    if not isinstance(text, str):
        raise ProtocolError("text must be a string")
    if not isinstance(session, str):
        raise ProtocolError("session must be a string")

    source_ts = float(source_ts)
    return Caption(
        session=session,
        segment=segment,
        revision=revision,
        source_ts=source_ts,
        final=final,
        text=text,
        wire=encode_caption(session, segment, revision, source_ts, final, text),
    )


@dataclass(frozen=True)
class ClientHello:
    client_id: Any
    session: str
    last_segment: int
    last_revision: int
    history_seconds: int


def parse_client_hello(msg: dict[str, Any]) -> ClientHello:
    """Parse CLIENT_HELLO leniently.

    A malformed resume cursor is treated as "no previous state" rather than
    rejecting the client: sending a little extra history is safer than
    refusing service, and clients deduplicate finals anyway.
    """
    last_segment = msg.get("last_segment", 0)
    last_revision = msg.get("last_revision", 0)
    seconds = msg.get("history_seconds", DEFAULT_HISTORY_SECONDS)
    session = msg.get("session", DEFAULT_SESSION)

    if not _is_int(last_segment) or last_segment < 0:
        last_segment, last_revision = 0, 0
    if not _is_int(last_revision) or last_revision < 0:
        last_revision = 0
    if not _is_number(seconds):
        seconds = DEFAULT_HISTORY_SECONDS
    seconds = int(max(0, min(MAX_HISTORY_SECONDS, seconds)))
    if not isinstance(session, str):
        session = DEFAULT_SESSION

    return ClientHello(
        client_id=msg.get("client_id"),
        session=session,
        last_segment=last_segment,
        last_revision=last_revision,
        history_seconds=seconds,
    )


def encode_history(captions: Iterable[Caption]) -> str:
    """Build a HISTORY frame from pre-encoded captions (oldest first)."""
    return '{"type":"HISTORY","items":[' + ",".join(c.wire for c in captions) + "]}"

"""Shared helpers for the unit tests."""

from liverecall.protocol import Caption, encode_caption


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def cap(segment: int, revision: int, final: bool = False, text: str | None = None,
        source_ts: float = 1760000000.0) -> Caption:
    text = text if text is not None else f"segment {segment} revision {revision}"
    return Caption(
        session="L1",
        segment=segment,
        revision=revision,
        source_ts=source_ts,
        final=final,
        text=text,
        wire=encode_caption("L1", segment, revision, source_ts, final, text),
    )

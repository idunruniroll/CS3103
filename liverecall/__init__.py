"""LiveRecall server package.

Module map (each module is small and independently testable):

    protocol.py        wire-format parsing/validation/encoding
    caption_state.py   authoritative revision state + bounded final history
    semantic_queue.py  per-client pending captions with revision coalescing
    flow_control.py    lag detection and congested-mode pacing (pure logic)
    client_channel.py  one writer task per client: queue + flow control + socket
    hub.py             connection handling and fan-out from source to clients
    stats.py           periodic server statistics for experiments/debugging

The required evaluator entry point is ../solution_server.py.
"""

__all__ = [
    "protocol",
    "caption_state",
    "semantic_queue",
    "flow_control",
    "client_channel",
    "hub",
    "stats",
]

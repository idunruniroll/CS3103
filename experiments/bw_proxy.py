#!/usr/bin/env python3
"""Portable bandwidth bottleneck for LiveRecall experiments.

    clients --> bw_proxy (listen port) --> solution_server (target port)

All server->client bytes of all connections share ONE token bucket, like a
single constrained link. Client->server bytes (hellos, pongs) are forwarded
unshaped but still queue behind nothing, which matches a downlink bottleneck.

The proxy reads at most one chunk per connection ahead of the bucket, so the
backlog builds in TCP socket buffers and the server experiences genuine
backpressure (as with `tc tbf` on Linux).

This exists so the constrained-bandwidth behaviour can be developed on any
OS. Report numbers must still come from `tc` on Ubuntu
(network_profiles/bandwidth_2mbit.sh), which is the grading environment.

    python experiments/bw_proxy.py --listen 8766 --target 8765 --rate-kbit 500
"""

from __future__ import annotations

import argparse
import asyncio
import time


class TokenBucket:
    def __init__(self, rate_bytes: float, burst_bytes: int) -> None:
        self.rate = rate_bytes
        self.burst = burst_bytes
        self.tokens = float(burst_bytes)
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()  # FIFO across connections
        self.bytes_total = 0

    async def consume(self, n: int) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= n:
                    self.tokens -= n
                    self.bytes_total += n
                    return
                await asyncio.sleep((n - self.tokens) / self.rate)


async def pipe(reader, writer, bucket: TokenBucket | None, chunk: int) -> None:
    try:
        while data := await reader.read(chunk):
            if bucket is not None:
                await bucket.consume(len(data))
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main_async(args) -> None:
    bucket = TokenBucket(args.rate_kbit * 1000 / 8, args.burst_bytes)

    async def handle(client_reader, client_writer):
        try:
            server_reader, server_writer = await asyncio.open_connection(
                args.target_host, args.target)
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            pipe(client_reader, server_writer, None, 65536),
            pipe(server_reader, client_writer, bucket, args.chunk),
        )

    server = await asyncio.start_server(handle, "127.0.0.1", args.listen)
    print(f"bw_proxy :{args.listen} -> :{args.target} at {args.rate_kbit} kbit/s", flush=True)
    async with server:
        if args.duration:
            await asyncio.sleep(args.duration)
        else:
            await asyncio.Future()
    print(f"bw_proxy forwarded {bucket.bytes_total / 1000:.1f} kB downstream", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--listen", type=int, default=8766)
    p.add_argument("--target", type=int, default=8765)
    p.add_argument("--target-host", default="127.0.0.1")
    p.add_argument("--rate-kbit", type=float, default=500)
    p.add_argument("--burst-bytes", type=int, default=4000)
    p.add_argument("--chunk", type=int, default=1400)
    p.add_argument("--duration", type=float, default=0)
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

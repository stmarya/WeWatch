"""Small signaling load smoke test.

This is intentionally not a replacement for a full WebRTC/SFU load test.
It measures connection and join behavior before media load is introduced.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import time

import socketio


def connect_one(base_url: str, index: int, join_token: str = "") -> tuple[bool, float, str]:
    client = socketio.Client(reconnection=False, logger=False, engineio_logger=False)
    joined = False
    error = ""
    started = time.perf_counter()

    @client.on("participants_update")
    def on_join(_data):
        nonlocal joined
        joined = True

    @client.on("join_rejected")
    def on_rejected(data):
        nonlocal error
        error = data.get("reason", "join rejected")

    try:
        client.connect(base_url, transports=["websocket"], wait_timeout=10)
        client.emit(
            "join",
            {
                "role": "client",
                "identity": f"load-test-{index}",
                "name": f"Load Test {index}",
                "mic": False,
                "cam": False,
                "join_token": join_token,
            },
        )
        deadline = time.time() + 10
        while not joined and not error and time.time() < deadline:
            time.sleep(0.01)
        return joined, time.perf_counter() - started, error
    except Exception as exc:
        return False, time.perf_counter() - started, str(exc)
    finally:
        client.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:5001")
    parser.add_argument(
        "--join-token",
        default="",
        help="Short-lived client join token when WEBRTC_REQUIRE_JOIN_TOKEN=true",
    )
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    args = parser.parse_args()
    if args.count < 1 or args.count > 1000:
        parser.error("--count must be between 1 and 1000")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, args.count)) as pool:
        results = list(
            pool.map(
                lambda i: connect_one(args.url, i, args.join_token),
                range(args.count),
            )
        )
    successes = [duration for ok, duration, _ in results if ok]
    errors = [error for ok, _, error in results if not ok]
    print(f"attempted={len(results)} success={len(successes)} failed={len(errors)}")
    if successes:
        print(f"join_seconds_avg={sum(successes) / len(successes):.3f}")
        print(f"join_seconds_max={max(successes):.3f}")
    if errors:
        print("sample_error=", errors[0])
    raise SystemExit(0 if len(successes) == len(results) else 1)


if __name__ == "__main__":
    main()
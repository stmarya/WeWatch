"""Measure signaling join capacity before media load is introduced.

For token-enforced rooms, pass --admin-token so the tool mints a unique
short-lived token for every load-test identity. A single --join-token is only
valid for the identity it was issued to.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
from pathlib import Path

import requests
import socketio


def _get_join_token(base_url: str, index: int, admin_token: str, timeout: float) -> str:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/room-token",
        headers={"X-Admin-Token": admin_token},
        json={
            "identity": f"load-test-{index}",
            "name": f"Load Test {index}",
            "role": "client",
            "ttl": 300,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    token = response.json().get("join_token")
    if not token:
        raise RuntimeError("room-token response did not contain join_token")
    return token


def connect_one(
    base_url: str,
    index: int,
    join_token: str = "",
    admin_token: str = "",
    connect_timeout: float = 10,
    join_timeout: float = 10,
) -> tuple[bool, float, str]:
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
        error = (
            data.get("reason", "join rejected")
            if isinstance(data, dict)
            else "join rejected"
        )

    try:
        if admin_token:
            join_token = _get_join_token(base_url, index, admin_token, connect_timeout)
        client.connect(
            base_url,
            transports=["websocket"],
            wait_timeout=connect_timeout,
        )
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
        deadline = time.time() + join_timeout
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
        help="One short-lived token for its matching identity; use --admin-token for batches",
    )
    parser.add_argument(
        "--admin-token",
        default=os.getenv("WEBRTC_ADMIN_TOKEN", ""),
        help="Admin token used to mint one token per load-test identity",
    )
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--connect-timeout", type=float, default=10)
    parser.add_argument("--join-timeout", type=float, default=10)
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.count < 1 or args.count > 1000:
        parser.error("--count must be between 1 and 1000")
    if args.workers < 1:
        parser.error("--workers must be positive")
    if not 0 < args.min_success_rate <= 1:
        parser.error("--min-success-rate must be between 0 and 1")
    if args.admin_token and args.join_token:
        parser.error("use either --admin-token or --join-token, not both")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.workers, args.count)
    ) as pool:
        results = list(
            pool.map(
                lambda i: connect_one(
                    args.url,
                    i,
                    args.join_token,
                    args.admin_token,
                    args.connect_timeout,
                    args.join_timeout,
                ),
                range(args.count),
            )
        )

    successes = [duration for ok, duration, _ in results if ok]
    errors = [error for ok, _, error in results if not ok]
    success_rate = len(successes) / len(results)
    print(f"attempted={len(results)} success={len(successes)} failed={len(errors)}")
    if successes:
        ordered = sorted(successes)
        p50 = ordered[int(0.50 * (len(ordered) - 1))]
        p95 = ordered[int(0.95 * (len(ordered) - 1))]
        print(f"join_seconds_avg={sum(successes) / len(successes):.3f}")
        print(f"join_seconds_p50={p50:.3f}")
        print(f"join_seconds_p95={p95:.3f}")
        print(f"join_seconds_max={max(successes):.3f}")
    if errors:
        print("sample_error=", errors[0])

    summary = {
        "attempted": len(results),
        "success": len(successes),
        "failed": len(errors),
        "success_rate": success_rate,
        "join_seconds_avg": sum(successes) / len(successes) if successes else None,
        "join_seconds_max": max(successes) if successes else None,
        "errors": errors[:10],
        "elapsed_seconds": time.perf_counter() - started,
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    raise SystemExit(0 if success_rate >= args.min_success_rate else 1)


if __name__ == "__main__":
    main()
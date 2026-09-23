#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from utils import TIGHTVNC, connect  # noqa: E402

from vncdotool import api  # noqa: E402


def log(message: str) -> None:
    print(f"[keep-warm {time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=float, default=0.0)
    parser.add_argument("--max-seconds", type=float, default=1200.0)
    args = parser.parse_args()

    began = time.monotonic()
    client = connect(TIGHTVNC, timeout=30.0)
    client.refreshScreen(incremental=False)
    client.timeout = max(args.poll, 1.0)
    log(f"connected to {TIGHTVNC.name}:{TIGHTVNC.port} poll={args.poll}s max={args.max_seconds}s")
    polls = answered = 0
    try:
        while time.monotonic() - began < args.max_seconds:
            if args.poll <= 0:
                time.sleep(1.0)
                continue
            polls += 1
            asked = time.monotonic()
            try:
                client.refreshScreen(incremental=True)
                answered += 1
            except Exception:  # noqa: BLE001
                pass
            time.sleep(max(0.0, args.poll - (time.monotonic() - asked)))
            if polls % 30 == 0:
                log(f"polls={polls} answered={answered}")
        log(f"max lifetime reached after {time.monotonic() - began:.0f}s")
    finally:
        log(f"exiting polls={polls} answered={answered}")
        try:
            client.disconnect()
        finally:
            api.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

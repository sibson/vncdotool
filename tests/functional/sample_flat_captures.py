#!/usr/bin/env python3
"""Diagnostic only (diag/tightvnc-flat-wire): how often a fresh capture is flat.

Takes N captures of every server in a group, each through its own `vncdo`
process, round-robin across the servers, and prints one line per sample, a
per-server summary, and the wire trail of the first flat captures. Always
exits 0.

Usage: sample_flat_captures.py [os|docker|all] [N]
       sample_flat_captures.py tightvnc
"""

import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from utils import (  # noqa: E402
    VNCServer,
    _terminate,
    capture_screenshot,
    connect,
    distinct_colours,
    has_expected_content,
    print_wire_summary,
    probe_context,
    select_servers,
)

from vncdotool import api  # noqa: E402

DEFAULT_SAMPLES = 20
TRAILS_PER_SERVER = 2


class Sample(NamedTuple):
    server: str
    index: int
    offset: float
    gap: Optional[float]
    duration: float
    flat: bool
    colour: Optional[str]
    colours: Optional[int]
    size: Optional[tuple]
    error: Optional[str]
    wire_log: Path


def take_sample(
    server: VNCServer, index: int, start: float, previous_end: Optional[float], tmp: Path
) -> Sample:
    png = tmp / f"{server.name}-{index:02d}.png"
    wire_log = tmp / f"{server.name}-{index:02d}.wire.log"
    began = time.monotonic()
    gap = None if previous_end is None else began - previous_end
    colours = size = colour = error = None
    flat = False
    try:
        with probe_context(server) as env:
            capture_screenshot(server, png, env=env, wire_log=wire_log)
        with Image.open(png) as image:
            colours = distinct_colours(image)
            size = image.size
            flat = not has_expected_content(server, colours)
            if flat:
                colour = "%02x%02x%02x" % image.convert("RGB").getpixel((0, 0))
    except Exception as exc:  # noqa: BLE001 - a failed capture is a data point too
        lines = str(exc).strip().splitlines() or [""]
        error = f"{type(exc).__name__}: {lines[0]}" + (f" ... {lines[-1]}" if len(lines) > 1 else "")
    return Sample(
        server.name, index, began - start, gap, time.monotonic() - began,
        flat, colour, colours, size, error, wire_log,
    )


def describe(sample: Sample) -> str:
    gap = "-" if sample.gap is None else f"{sample.gap:.2f}s"
    head = (
        f"[sample] {sample.server:<12} #{sample.index:02d} t=+{sample.offset:6.1f}s "
        f"gap={gap:>6} dur={sample.duration:5.2f}s"
    )
    if sample.error:
        return f"{head} ERROR {sample.error}"
    size = "x".join(str(n) for n in sample.size) if sample.size else "?"
    if sample.flat:
        return f"{head} FLAT {sample.colour} {size}"
    colours = ">256" if sample.colours is None else str(sample.colours)
    return f"{head} ok {colours} colours {size}"


FAST_SAMPLES = 40
SLOW_SAMPLES = 10
SLOW_SLEEP = 5.0
REASK_MAX_CONNECTIONS = 60
REASK_BLACK_FIRSTS = 6
REASK_CALL_TIMEOUT = 8.0
REASK_POLL_SECONDS = 15.0
REASK_POLL_INTERVAL = 0.5


def flat_colour(server: VNCServer, image: Image.Image) -> Optional[str]:
    if has_expected_content(server, distinct_colours(image)):
        return None
    return "%02x%02x%02x" % image.convert("RGB").getpixel((0, 0))


def summarise_count_vs_time(label: str, taken: List[Sample]) -> None:
    flats = [s for s in taken if s.flat]
    offsets = [round(s.offset, 1) for s in flats]
    print(
        f"[phaseA {label}] N={len(taken)} flat={len(flats)} errors={sum(1 for s in taken if s.error)} "
        f"colours={sorted({s.colour for s in flats})} indices={[s.index for s in flats]} "
        f"t={offsets} dt={[round(b - a, 1) for a, b in zip(offsets, offsets[1:])]} "
        f"index_steps={[b.index - a.index for a, b in zip(flats, flats[1:])]}",
        flush=True,
    )


def phase_count_vs_time(server: VNCServer, tmp: Path, start: float) -> List[Sample]:
    print(
        f"[phaseA] {server.name}: {FAST_SAMPLES} back-to-back, then {SLOW_SAMPLES} with "
        f"{SLOW_SLEEP}s sleeps; index counts every {server.name} connection this script made",
        flush=True,
    )
    fast: List[Sample] = []
    slow: List[Sample] = []
    previous_end: Optional[float] = None
    for index in range(FAST_SAMPLES + SLOW_SAMPLES):
        if index >= FAST_SAMPLES:
            time.sleep(SLOW_SLEEP)
        sample = take_sample(server, index, start, previous_end, tmp)
        previous_end = time.monotonic()
        (fast if index < FAST_SAMPLES else slow).append(sample)
        print(describe(sample).replace("[sample]", "[phaseA]"), flush=True)
    summarise_count_vs_time("fast", fast)
    summarise_count_vs_time("slow", slow)
    summarise_count_vs_time("all", fast + slow)
    for sample in [s for s in fast + slow if s.flat][:1]:
        print_wire_summary(server, sample.wire_log, f"phaseA-{sample.index:02d}")
    return fast + slow


def capture_frame(client, incremental: bool) -> Image.Image:
    buffer = io.BytesIO()
    client.captureScreen(buffer, incremental, format="PNG")
    buffer.seek(0)
    return Image.open(buffer)


def timed_frame(client, server: VNCServer, incremental: bool, began: float) -> str:
    try:
        colour = flat_colour(server, capture_frame(client, incremental))
    except Exception as exc:  # noqa: BLE001 - a timeout is a data point too
        return f"{'inc' if incremental else 'full'}@{time.monotonic() - began:.2f}s:{type(exc).__name__}({exc})"
    state = f"FLAT {colour}" if colour else "ok"
    return f"{'inc' if incremental else 'full'}@{time.monotonic() - began:.2f}s:{state}"


def reask(client, server: VNCServer, incremental_first: bool) -> List[str]:
    began = time.monotonic()
    trail = [timed_frame(client, server, incremental_first, began)]
    if "Error(" in trail[0]:
        return trail + ["abandoned"]
    while not trail[-1].endswith(":ok") and time.monotonic() - began < REASK_POLL_SECONDS:
        time.sleep(REASK_POLL_INTERVAL)
        trail.append(timed_frame(client, server, False, began))
    return trail


def phase_same_connection(server: VNCServer, first_index: int, start: float) -> None:
    print(
        f"[phaseB] {server.name}: one library connection per sample, re-asking on the same "
        f"connection after a flat first frame; stop at {REASK_BLACK_FIRSTS} flat firsts "
        f"or {REASK_MAX_CONNECTIONS} connections",
        flush=True,
    )
    results = []
    for n in range(REASK_MAX_CONNECTIONS):
        index = first_index + n
        offset = time.monotonic() - start
        try:
            client = connect(server, timeout=REASK_CALL_TIMEOUT)
            first = flat_colour(server, capture_frame(client, False))
        except Exception as exc:  # noqa: BLE001 - a failed connection is a data point too
            print(f"[phaseB] #{index:02d} t=+{offset:6.1f}s ERROR {type(exc).__name__}: {exc}", flush=True)
            continue
        if first is None:
            print(f"[phaseB] #{index:02d} t=+{offset:6.1f}s first ok", flush=True)
            results.append((index, None, []))
        else:
            incremental_first = sum(1 for r in results if r[1]) % 2 == 1
            trail = reask(client, server, incremental_first)
            first_ok = next((step for step in trail if step.endswith(":ok")), "never")
            print(
                f"[phaseB] #{index:02d} t=+{offset:6.1f}s first FLAT {first} reask {' '.join(trail[:2])} "
                f"requests={len(trail)} first_ok={first_ok} last={trail[-1]}",
                flush=True,
            )
            results.append((index, first, trail))
        try:
            client.disconnect()
        except Exception as exc:  # noqa: BLE001
            print(f"[phaseB] #{index:02d} disconnect {type(exc).__name__}: {exc}", flush=True)
        if sum(1 for r in results if r[1]) >= REASK_BLACK_FIRSTS:
            break
    black = [r for r in results if r[1]]
    print(
        f"[phaseB summary] connections={len(results)} flat_first={len(black)} "
        f"indices={[r[0] for r in black]}",
        flush=True,
    )
    for index, colour, trail in black:
        first_ok = next((step for step in trail if step.endswith(":ok")), "never")
        print(
            f"[phaseB summary] #{index:02d} {colour}: first re-ask={trail[0]} "
            f"requests={len(trail)} first_ok={first_ok}",
            flush=True,
        )
    api.shutdown()


def main_tightvnc() -> int:
    server = next(s for s in select_servers("os") if s.name == "tightvnc")
    with tempfile.TemporaryDirectory() as tmpdir:
        start = time.monotonic()
        taken = phase_count_vs_time(server, Path(tmpdir), start)
        phase_same_connection(server, len(taken), start)
        print(f"[sample] done in {time.monotonic() - start:.1f}s", flush=True)
    return 0


KEEP_WARM_SAMPLES = 30
KEEP_WARM_SETTLE = 2.0


def start_keep_warm(log_path: Path, poll: float) -> subprocess.Popen:
    argv = [sys.executable, str(_HERE / "keep_warm.py"), "--poll", str(poll), "--max-seconds", "600"]
    with open(log_path, "w") as out:
        process = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT)
    time.sleep(KEEP_WARM_SETTLE)
    return process


def stop_keep_warm(label: str, process: subprocess.Popen, log_path: Path) -> None:
    alive = process.poll() is None
    _terminate(process)
    print(f"[{label}] keep-warm alive_at_end={alive} exit={process.returncode}", flush=True)
    for line in log_path.read_text(errors="replace").splitlines()[-15:]:
        print(f"[{label}]   {line}", flush=True)


def run_phase(label: str, server: VNCServer, tmp: Path, start: float) -> List[Sample]:
    taken: List[Sample] = []
    previous_end: Optional[float] = None
    for index in range(KEEP_WARM_SAMPLES):
        sample = take_sample(server, index, start, previous_end, tmp / label)
        previous_end = time.monotonic()
        taken.append(sample)
        print(describe(sample).replace("[sample]", f"[{label}]"), flush=True)
    return taken


def summarise_phase(label: str, taken: List[Sample]) -> str:
    flats = [s for s in taken if s.flat]
    return (
        f"[summary {label}] N={len(taken)} flat={len(flats)} errors={sum(1 for s in taken if s.error)} "
        f"colours={sorted({s.colour for s in flats})} indices={[s.index for s in flats]}"
    )


def main_keep_warm() -> int:
    server = next(s for s in select_servers("os") if s.name == "tightvnc")
    summaries: List[str] = []
    poll_for_tests = "0"
    taken: List[Sample] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        start = time.monotonic()
        phases = [("phase1-cold", None), ("phase2-idle", 0.0), ("phase3-poll1s", 1.0)]
        for label, poll in phases:
            if label == "phase3-poll1s" and not any(s.flat for s in taken):
                print("[phase3-poll1s] skipped: phase2 had no flat captures", flush=True)
                break
            (tmp / label).mkdir()
            print(f"[{label}] {KEEP_WARM_SAMPLES} back-to-back vncdo captures, keep-warm poll={poll}", flush=True)
            keep_warm = None if poll is None else start_keep_warm(tmp / f"{label}.keep-warm.log", poll)
            try:
                taken = run_phase(label, server, tmp, start)
            finally:
                if keep_warm is not None:
                    stop_keep_warm(label, keep_warm, tmp / f"{label}.keep-warm.log")
            summaries.append(summarise_phase(label, taken))
            print(summaries[-1], flush=True)
            for sample in [s for s in taken if s.flat][:1]:
                print_wire_summary(server, sample.wire_log, f"{label}-{sample.index:02d}")
            if poll:
                poll_for_tests = str(poll)
        print(f"[sample] done in {time.monotonic() - start:.1f}s", flush=True)
    for line in summaries:
        print(line, flush=True)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as env:
            env.write(f"KEEP_WARM_POLL={poll_for_tests}\n")
    print(f"[sample] keep-warm for the functional tests: poll={poll_for_tests}", flush=True)
    return 0


def main(argv: List[str]) -> int:
    group = argv[1] if len(argv) > 1 else "os"
    if group == "tightvnc":
        return main_tightvnc()
    if group == "keepwarm":
        return main_keep_warm()
    count = int(argv[2]) if len(argv) > 2 else DEFAULT_SAMPLES
    servers = select_servers(group)
    print(f"[sample] {count} captures each of {[s.name for s in servers]}, round-robin", flush=True)

    samples: Dict[str, List[Sample]] = {server.name: [] for server in servers}
    previous_end: Dict[str, Optional[float]] = {server.name: None for server in servers}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        start = time.monotonic()
        for index in range(count):
            for server in servers:
                sample = take_sample(server, index, start, previous_end[server.name], tmp)
                previous_end[server.name] = time.monotonic()
                samples[server.name].append(sample)
                print(describe(sample), flush=True)

        print(f"[sample] done in {time.monotonic() - start:.1f}s", flush=True)
        for server in servers:
            taken = samples[server.name]
            flats = [s for s in taken if s.flat]
            errors = [s for s in taken if s.error]
            print(
                f"[summary] {server.name}: N={len(taken)} flat={len(flats)} errors={len(errors)} "
                f"colours={sorted({s.colour for s in flats})} "
                f"indices={[s.index for s in flats]} "
                f"t={[round(s.offset, 1) for s in flats]} "
                f"gaps={[None if s.gap is None else round(s.gap, 2) for s in flats]}",
                flush=True,
            )
        for server in servers:
            for sample in [s for s in samples[server.name] if s.flat][:TRAILS_PER_SERVER]:
                print_wire_summary(server, sample.wire_log, f"sample-{sample.index:02d}")
    return 0


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception:  # noqa: BLE001 - diagnostic step must never fail the job
        traceback.print_exc(file=sys.stdout)
    sys.exit(0)

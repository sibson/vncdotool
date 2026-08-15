"""Event-sink checks: did the client's input actually arrive.

Two sinks, two questions: vncev answers "what did the client put on the
wire", the x11vnc container's `xev -root` answers "did the server turn
that into a real X event". Both are polled through `docker compose logs`,
the only handle either sink offers.
"""

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List
from unittest import TestCase

from .vncservers import DOCKER_SERVERS, HOST, VNCEV, port_open, run_vncdo

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "tests" / "servers" / "docker-compose.yml"

X11VNC = next(s for s in DOCKER_SERVERS if s.name == "x11vnc")

LOG_POLL_INTERVAL = 0.5
LOG_POLL_DEADLINE = 15.0


def _docker_compose_available() -> bool:
    return shutil.which("docker") is not None


def _compose_logs(service: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "logs", service],
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    return result.stdout + result.stderr


def wait_for_log_line(
    service: str, needle_patterns: List[str], deadline: float = LOG_POLL_DEADLINE, offset: int = 0
) -> str:
    """Poll `docker compose logs <service>` until every pattern has matched, or give up.

    `offset` is a character position into the accumulated log, so a line
    left over from an earlier test can't satisfy this one's assertion.
    Returns the log text past that offset.
    """
    remaining = set(needle_patterns)
    end = time.monotonic() + deadline
    logs = ""
    while time.monotonic() < end:
        logs = _compose_logs(service)[offset:]
        remaining = {p for p in remaining if not re.search(p, logs, re.MULTILINE)}
        if not remaining:
            return logs
        time.sleep(LOG_POLL_INTERVAL)
    return logs


class TestVncevSink(TestCase):
    """Client conformance: what vncev saw the client actually send."""

    def setUp(self) -> None:
        if not _docker_compose_available():
            self.skipTest("docker not available")
        if not port_open(HOST, VNCEV.port):
            self.skipTest(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )

    def test_keypress_seen_by_vncev(self) -> None:
        offset = len(_compose_logs("vncev"))
        result = run_vncdo(VNCEV, "key", "x")
        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

        # Asserting on 0x78 rather than the keysym name: vncev's name lookup
        # needs a readable keysym.h in its cwd, which the container lacks.
        logs = wait_for_log_line("vncev", [r"down:.*\(0x78\)", r"up:.*\(0x78\)"], offset=offset)
        down = re.search(r"down:.*\(0x78\)", logs)
        up = re.search(r"up:.*\(0x78\)", logs)
        self.assertIsNotNone(down, f"no keydown seen in vncev logs:\n{logs}")
        self.assertIsNotNone(up, f"no keyup seen in vncev logs:\n{logs}")
        self.assertLess(down.start(), up.start(), f"keyup seen before keydown in vncev logs:\n{logs}")

    def test_special_keys_seen_by_vncev(self) -> None:
        """A named key, a function key, and a modifier combo reach the wire
        with the keysyms KEYMAP says they should.

        Wire-level only. Whether a server then turns those keysyms into the
        right input is a separate, layout-sensitive question -- see the
        design doc's "Special keys across servers" TODO.
        """
        offset = len(_compose_logs("vncev"))
        result = run_vncdo(VNCEV, "key", "enter", "key", "f1", "key", "ctrl-c")
        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

        # enter, f1, ctrl, c
        keysyms = ["0xff0d", "0xffbe", "0xffe3", "0x63"]
        patterns = [rf"down:.*\({k}\)" for k in keysyms]
        logs = wait_for_log_line("vncev", patterns, offset=offset)
        for keysym in keysyms:
            self.assertRegex(logs, rf"down:.*\({keysym}\)", f"no keydown for {keysym}:\n{logs}")
            self.assertRegex(logs, rf"up:.*\({keysym}\)", f"no keyup for {keysym}:\n{logs}")

        # The modifier has to wrap the key it modifies, or the combo is
        # three unrelated keystrokes as far as the server is concerned.
        ctrl_down = re.search(r"down:.*\(0xffe3\)", logs)
        c_down = re.search(r"down:.*\(0x63\)", logs)
        ctrl_up = re.search(r"up:.*\(0xffe3\)", logs)
        self.assertLess(ctrl_down.start(), c_down.start(), f"ctrl pressed after c:\n{logs}")
        self.assertLess(c_down.start(), ctrl_up.start(), f"ctrl released before c:\n{logs}")

    def test_mousemove_seen_by_vncev(self) -> None:
        offset = len(_compose_logs("vncev"))
        result = run_vncdo(VNCEV, "move", "10", "20", "click", "1")
        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

        logs = wait_for_log_line("vncev", [r"Ptr: mouse button mask 0x1 at 10,20"], offset=offset)
        self.assertRegex(
            logs,
            r"Ptr: mouse button mask 0x1 at 10,20",
            f"no matching pointer event seen in vncev logs:\n{logs}",
        )


def _sink_alive(service: str, pattern: str) -> bool:
    """Is the container's event sink process still running?

    A sink that died leaves the container serving VNC quite happily, so
    nothing else in the suite notices; asking the container directly is
    the only way to tell "the event never arrived" from "nothing was
    listening for it".
    """
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", service, "pgrep", "-f", pattern],
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    return result.returncode == 0


class TestX11SideSink(TestCase):
    """Server processing: did x11vnc's X display see a real X event.

    Relies on the window-manager-less Xvfb display leaving focus on the
    root window xev listens on, which no window manager is there to steal.
    """

    def setUp(self) -> None:
        if not _docker_compose_available():
            self.skipTest("docker not available")
        if not port_open(HOST, X11VNC.port):
            self.skipTest(
                f"x11vnc not reachable on {HOST}:{X11VNC.port} -- start the servers first "
                "with `make servers-up`"
            )
        # Fail as the infrastructure problem it is. Without this the symptom
        # of a dead sink is an assertion about a keypress, pointing at
        # vncdotool for something vncdotool did not do.
        self.assertTrue(
            _sink_alive("x11vnc", "xev -root"),
            "x11vnc's xev sink is not running, so no event can be observed no matter what "
            "the client sends. Check `docker compose logs x11vnc` for why it exited.",
        )

    def test_keypress_seen_by_xev(self) -> None:
        offset = len(_compose_logs("x11vnc"))
        result = run_vncdo(X11VNC, "key", "x")
        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

        logs = wait_for_log_line("x11vnc", [r"xev: KeyPress event"], offset=offset)
        self.assertRegex(
            logs,
            r"xev: KeyPress event",
            f"no KeyPress seen in x11vnc's xev log:\n{logs}",
        )

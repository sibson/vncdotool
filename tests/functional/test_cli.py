"""CLI-surface checks against the Docker Compose test fleet.

The smoke grid in vncservers.py covers the happy path per server; these
are the checks about vncdo's own behaviour, kept in one place rather than
duplicated per server.
"""

from unittest import TestCase

from .vncservers import (
    DOCKER_SERVERS,
    PNG_MAGIC,
    HOST,
    port_open,
    run_vncdo,
    screenshot_dir,
)

# The one fleet server with a password, so the only one that can prove a
# wrong password is rejected rather than ignored.
_SERVER = next(s for s in DOCKER_SERVERS if s.name == "tigervnc-auth")


class TestCLI(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, _SERVER.port):
            self.skipTest(
                f"tigervnc-auth not reachable on {HOST}:{_SERVER.port} -- "
                "start the servers first with `make servers-up`"
            )

    def test_bad_password_exits_nonzero(self) -> None:
        """A rejected VNC-password auth attempt exits non-zero, not hangs."""
        wrong = _SERVER._replace(password="not-the-password")
        result = run_vncdo(wrong, "pause", "0")
        self.assertNotEqual(
            result.returncode,
            0,
            f"vncdo exited 0 against a wrong password, stderr:\n{result.stderr}",
        )

    def test_unknown_command_exits_nonzero(self) -> None:
        """An unrecognised command is a parse error, not a hang or a crash."""
        result = run_vncdo(_SERVER, "not-a-real-command")
        self.assertNotEqual(
            result.returncode,
            0,
            f"vncdo exited 0 for an unknown command, stderr:\n{result.stderr}",
        )

    def test_nocursor_capture_succeeds(self) -> None:
        """--nocursor is accepted and still produces a valid capture."""
        png = screenshot_dir() / f"{_SERVER.name}-nocursor.png"
        result = run_vncdo(_SERVER, "--nocursor", "move", "10", "10", "capture", str(png))
        self.assertEqual(
            result.returncode,
            0,
            f"vncdo --nocursor exited {result.returncode}, stderr:\n{result.stderr}",
        )
        data = png.read_bytes()
        self.assertEqual(data[:8], PNG_MAGIC, "--nocursor capture is not a valid PNG")

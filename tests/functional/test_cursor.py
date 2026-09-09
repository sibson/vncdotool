"""A capture does not contain the mouse pointer, checked per server.

Every server gets its own case rather than one test looping the fleet, so a
server that starts painting the pointer names itself in the failure.

x11vnc carries the `--localcursor` case: of the servers running a scene
player it is the only one answering the Cursor pseudo-encoding with a real
shape, 18x18. libvncserver-example sends one too, at 32x32. tigervnc, its
VeNCrypt variants and selenoid answer a degenerate 0x0 rectangle, which means
hide the pointer (RFC 6143 7.6.1); wayvnc, qemu and qemu-tls answer nothing
at all. On any of those `--localcursor` has no shape to draw.
"""

from typing import Dict, Optional, Tuple
from unittest import TestCase

from PIL import Image, ImageChops

from .utils import (
    QEMU_TLS,
    QEMU_TLS_CA,
    TCP_SERVERS,
    WEBSOCKET_SERVERS,
    FleetTestCase,
    VNCServer,
    X11VNC,
    absent_server_skips,
    os_servers,
    run_vncdo,
    screenshot_dir,
    server_is_up,
)

NEAR = (20, 20)
FAR = (150, 120)
# Comfortably over the largest shape the fleet sends, libvncserver's 32x32.
CURSOR_EXTENT = 48

Box = Tuple[int, int, int, int]


class CursorFreeCapture:
    """Shared body, parameterized per server by _register().

    Deliberately not a TestCase, or `unittest discover` would collect this
    shared base as its own serverless case.
    """

    server: VNCServer

    def env(self) -> Optional[Dict[str, str]]:
        if self.server is not QEMU_TLS:
            return None
        # SSL_CERT_FILE is how OpenSSL, and so Twisted's platform trust, is
        # pointed at a private CA. There is no vncdotool option that skips
        # verification.
        if not QEMU_TLS_CA.exists():
            self.fail(f"{self.server.name} has not written {QEMU_TLS_CA}")
        return {"SSL_CERT_FILE": str(QEMU_TLS_CA)}

    def at(self, tag: str, position: Tuple[int, int], *flags: str) -> Image.Image:
        png = screenshot_dir() / f"{self.server.name}-cursor-{tag}.png"
        args = (*flags, "move", str(position[0]), str(position[1]), "pause", "0.5")
        result = run_vncdo(self.server, *args, "capture", str(png), env=self.env())
        self.assertEqual(
            result.returncode, 0,
            f"{self.server.name}: `vncdo {' '.join(args)}` exited "
            f"{result.returncode}, stderr:\n{result.stderr}",
        )
        with Image.open(png) as image:
            return image.convert("RGB").copy()

    def test_capture_does_not_depend_on_where_the_pointer_is(self) -> None:
        """Neither pointer position leaves a mark on a capture.

        Only the neighbourhood of each position is compared. A painted
        pointer lands there and nowhere else, so a clock or a blinking text
        cursor elsewhere on the screen cannot be mistaken for one -- and
        unlike calibrating against the screen's own churn, this does not
        depend on catching that churn mid-blink.
        """
        near = self.at("near", NEAR)
        far = self.at("far", FAR)

        for label, position in (("near", NEAR), ("far", FAR)):
            box = self.around(position, near.size)
            difference = ImageChops.difference(near.crop(box), far.crop(box))
            self.assertIsNone(
                difference.getbbox(),
                f"{self.server.name}: the capture changed around the {label} "
                f"pointer position {position} (region {box}) when the pointer "
                f"moved between {NEAR} and {FAR}. The server is painting it "
                "into the framebuffer despite being offered Cursor.",
            )

    @staticmethod
    def around(position: Tuple[int, int], size: Tuple[int, int]) -> Box:
        """A box big enough for any cursor drawn at `position`.

        A shape is drawn at the pointer minus its hotspot, so it reaches
        above and left of the position as well as below and right.
        """
        x, y = position
        width, height = size
        return (
            max(0, x - CURSOR_EXTENT), max(0, y - CURSOR_EXTENT),
            min(width, x + CURSOR_EXTENT), min(height, y + CURSOR_EXTENT),
        )


class NativeGating:
    """setUp for a server CI sets up rather than compose.

    Not a TestCase either, for the same reason as CursorFreeCapture.
    """

    server: VNCServer

    def setUp(self) -> None:
        if server_is_up(self.server):
            return
        unreachable = f"{self.server.name} not reachable -- {self.server.how_to_start}"
        if absent_server_skips(self.server):
            self.skipTest(unreachable)
        self.fail(unreachable)


class TestLocalCursor(CursorFreeCapture, FleetTestCase):
    server = X11VNC

    def test_localcursor_composites_a_decoded_cursor(self) -> None:
        """--localcursor draws a shape the default discards, at the pointer."""
        without = self.at("plain", NEAR)
        with_cursor = self.at("localcursor", NEAR, "--localcursor")

        bbox = ImageChops.difference(without, with_cursor).getbbox()
        self.assertIsNotNone(
            bbox,
            "--localcursor capture is pixel-identical to the default at the "
            "same pointer position; no cursor was decoded and composited",
        )
        # NEAR plus slack for the cursor's own extent and hotspot offset.
        left, top, _, _ = bbox
        self.assertLess(left, NEAR[0] + 32, f"diff region {bbox} is not near the pointer")
        self.assertLess(top, NEAR[1] + 32, f"diff region {bbox} is not near the pointer")


def _add(namespace: Dict[str, object], bases: Tuple[type, ...], server: VNCServer) -> None:
    name = "TestCursorFree_" + server.name.replace("-", "_")
    namespace[name] = type(
        name,
        bases,
        {"server": server, "__module__": namespace.get("__name__", __name__)},
    )


def _register(namespace: Dict[str, object]) -> None:
    for server in TCP_SERVERS + WEBSOCKET_SERVERS:
        _add(namespace, (CursorFreeCapture, FleetTestCase), server)
    for server in os_servers():
        _add(namespace, (CursorFreeCapture, NativeGating, TestCase), server)


_register(globals())

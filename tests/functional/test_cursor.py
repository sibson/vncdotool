"""A capture does not contain the mouse pointer, checked per fleet server.

Every server gets its own case rather than one test looping the fleet, so a
server that starts painting the pointer names itself in the failure. The
OS-hosted servers get the same body through `CursorPositionIndependent`,
opted into `register_server_tests()` for any server not in
`CURSOR_TESTED_SERVERS` below -- which is what the os-servers workflow runs.

x11vnc carries the `--localcursor` case: of the servers running a scene
player it is the only one answering the Cursor pseudo-encoding with a real
shape, 18x18. libvncserver-example sends one too, at 32x32. tigervnc, its
VeNCrypt variants and selenoid answer a degenerate 0x0 rectangle, which means
hide the pointer (RFC 6143 7.6.1); wayvnc, qemu and qemu-tls answer nothing
at all. On any of those `--localcursor` has no shape to draw.
"""

from typing import Dict, Optional, Tuple

from PIL import Image, ImageChops

from .utils import (
    BLANK_FRACTION,
    CURSOR_FAR,
    CURSOR_NEAR,
    CURSOR_TESTED_SERVERS,
    QEMU_TLS,
    QEMU_TLS_CA,
    CursorShapeOffered,
    FleetTestCase,
    VNCServer,
    X11VNC,
    assert_pointer_matches_expectation,
    blank_fraction,
    run_vncdo,
    screenshot_dir,
)


class CaptureHelper:
    """`at()`/`env()`, shared by CursorFreeCapture and TestLocalCursor's own cases.

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
            capture = image.convert("RGB").copy()

        if self.server.has_pointer:
            blank = blank_fraction(capture)
            self.assertLess(
                blank, BLANK_FRACTION,
                f"{self.server.name}: the {tag} capture is {blank:.0%} one "
                "colour, so the desktop had not painted and nothing about the "
                f"pointer can be read off it. See {png}.",
            )
        return capture


class CursorFreeCapture(CaptureHelper):
    """Adds the pointer-independence case, parameterized per server by _register()."""

    def test_capture_does_not_depend_on_where_the_pointer_is(self) -> None:
        """Neither pointer position leaves a mark on a capture."""
        assert_pointer_matches_expectation(
            self, self.server,
            {"near": self.at("near", CURSOR_NEAR), "far": self.at("far", CURSOR_FAR)},
        )


class TestLocalCursor(CaptureHelper, FleetTestCase):
    """x11vnc's `--localcursor` cases. Its pointer-independence case is
    TestCursorFree_x11vnc, registered below -- not repeated here.
    """

    server = X11VNC

    def test_localcursor_matches_the_server_side_render(self) -> None:
        """The client composite is the server's own render, pixel for pixel.

        `--cursor server` is the only way to obtain the server's render, and
        the only reason this can be asserted at all.
        """
        server_drawn = self.at("servercursor", CURSOR_NEAR, "--cursor", "server")
        client_drawn = self.at("localcursor", CURSOR_NEAR, "--cursor", "local")

        self.assertIsNone(
            ImageChops.difference(server_drawn, client_drawn).getbbox(),
            "--cursor local does not reproduce what --cursor server captured",
        )

    def test_localcursor_composites_a_decoded_cursor(self) -> None:
        """--localcursor draws a shape the default discards, at the pointer."""
        without = self.at("plain", CURSOR_NEAR)
        with_cursor = self.at("localcursor", CURSOR_NEAR, "--localcursor")

        bbox = ImageChops.difference(without, with_cursor).getbbox()
        self.assertIsNotNone(
            bbox,
            "--localcursor capture is pixel-identical to the default at the "
            "same pointer position; no cursor was decoded and composited",
        )
        # CURSOR_NEAR plus slack for the cursor's extent and hotspot offset.
        left, top, _, _ = bbox
        self.assertLess(left, CURSOR_NEAR[0] + 32, f"diff region {bbox} is not near the pointer")
        self.assertLess(top, CURSOR_NEAR[1] + 32, f"diff region {bbox} is not near the pointer")


def _register(namespace: Dict[str, object]) -> None:
    for server in CURSOR_TESTED_SERVERS:
        name = "TestCursorFree_" + server.name.replace("-", "_")
        bases: Tuple[type, ...] = (CursorFreeCapture, FleetTestCase)
        if server.has_pointer:
            bases = (CursorShapeOffered,) + bases
        namespace[name] = type(
            name,
            bases,
            {"server": server, "__module__": namespace.get("__name__", __name__)},
        )


_register(globals())

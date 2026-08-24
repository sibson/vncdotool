"""Mid-session desktop resize: the case specs/decoder-architecture.md's
scene-catalogue testing cannot reach, since the scene player has no way to
make a server change geometry (see "Deferred" in decoder-goldens.md and
"Testing" in decoder-architecture.md).

libvncserver-example is the one fleet server that can: its ``dokey()``
(examples/example.c, LibVNCServer 0.9.14, matching this repo's pinned
``LIBVNCSERVER_VERSION``) handles ``XK_Up``/``XK_Down`` by calling
``rfbNewFramebuffer()``, cycling 640x480 -> 800x600 -> 1024x768 and back.
There is no signal, stdin, or xrandr path -- only those two keysyms, which
``vncdotool.keys.KEYMAP`` maps "up"/"down" onto exactly.

The cycle position is a static variable in the server process, not
per-connection state, so a container a previous run already resized reports
its current size at the next connection's ServerInit. Two Downs floor it at
640x480 regardless of where it started (at most two steps between any of
the three sizes), making the floor -- and everything that follows it --
independent of connection order.
"""

from unittest import TestCase

from PIL import Image

from .utils import HOST, LIBVNCSERVER_EXAMPLE, port_open, run_vncdo, screenshot_dir

FLOOR_SIZE = (640, 480)
RESIZED_SIZE = (800, 600)


class TestDesktopResize(TestCase):

    def setUp(self) -> None:
        if not port_open(HOST, LIBVNCSERVER_EXAMPLE.port):
            self.fail(
                f"{LIBVNCSERVER_EXAMPLE.name} not reachable on {HOST}:{LIBVNCSERVER_EXAMPLE.port} -- "
                f"{LIBVNCSERVER_EXAMPLE.how_to_start}"
            )

    def test_mid_session_resize_is_decoded(self) -> None:
        """Floor the server's geometry, capture it, grow it one step, capture
        again: each capture's size is the server's actual PSEUDO_DESKTOP_SIZE
        rectangle decoded and applied to the client's framebuffer, not the
        size ServerInit negotiated at connect time.
        """
        floor_png = screenshot_dir() / f"{LIBVNCSERVER_EXAMPLE.name}-resize-floor.png"
        resized_png = screenshot_dir() / f"{LIBVNCSERVER_EXAMPLE.name}-resize-grown.png"

        result = run_vncdo(
            LIBVNCSERVER_EXAMPLE,
            "key", "down",
            "key", "down",
            "pause", "0.5",
            "capture", str(floor_png),
            "key", "up",
            "pause", "0.5",
            "capture", str(resized_png),
        )
        self.assertEqual(
            result.returncode, 0,
            f"{LIBVNCSERVER_EXAMPLE.name}: vncdo exited {result.returncode}, stderr:\n{result.stderr}",
        )

        with Image.open(floor_png) as image:
            self.assertEqual(
                image.size, FLOOR_SIZE,
                f"{LIBVNCSERVER_EXAMPLE.name}: two Downs did not floor the framebuffer at {FLOOR_SIZE}",
            )

        with Image.open(resized_png) as image:
            self.assertEqual(
                image.size, RESIZED_SIZE,
                f"{LIBVNCSERVER_EXAMPLE.name}: one Up from the floor did not grow the framebuffer to {RESIZED_SIZE}",
            )

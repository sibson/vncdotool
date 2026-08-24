"""Mid-session desktop resize: the case specs/decoder-architecture.md's
scene-catalogue testing cannot reach, since the scene player has no way to
make a server change geometry (see "Deferred" in decoder-goldens.md and
"Testing" in decoder-architecture.md).

libvncserver-example resizes only in response to ``XK_Up``/``XK_Down``
(examples/example.c, LibVNCServer 0.9.14); no signal, stdin, or xrandr path
exists.

The cycle position is a static variable in the server process, not
per-connection state, so a container a previous run already resized reports
its current size at the next connection's ServerInit.
"""

from unittest import TestCase

from PIL import Image

from .utils import HOST, LIBVNCSERVER_EXAMPLE, distinct_colours, has_expected_content, port_open, run_vncdo, screenshot_dir

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
        """Each capture's size reflects the server's actual PSEUDO_DESKTOP_SIZE
        rectangle decoded onto the client's framebuffer, not the size
        ServerInit negotiated at connect time.
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
            colours = distinct_colours(image)

        self.assertTrue(
            has_expected_content(LIBVNCSERVER_EXAMPLE, colours),
            f"{LIBVNCSERVER_EXAMPLE.name}: floor capture is a single flat colour, no screen content was decoded",
        )

        with Image.open(resized_png) as image:
            self.assertEqual(
                image.size, RESIZED_SIZE,
                f"{LIBVNCSERVER_EXAMPLE.name}: one Up from the floor did not grow the framebuffer to {RESIZED_SIZE}",
            )
            colours = distinct_colours(image)

        self.assertTrue(
            has_expected_content(LIBVNCSERVER_EXAMPLE, colours),
            f"{LIBVNCSERVER_EXAMPLE.name}: resized capture is a single flat colour, no screen content was decoded",
        )

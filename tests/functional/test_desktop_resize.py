from unittest import TestCase

from PIL import Image

from .utils import (
    HOST,
    LIBVNCSERVER_EXAMPLE,
    TIGERVNC_RESIZE,
    distinct_colours,
    has_expected_content,
    port_open,
    run_vncdo,
    screenshot_dir,
)

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


class TestClientInitiatedResize(TestCase):
    """TigerVNC's Xvnc is the fleet's only server that grants SetDesktopSize;
    libvncserver advertises ExtendedDesktopSize and then denies every request
    to change the layout.
    """

    SERVER = TIGERVNC_RESIZE
    # Whatever a run leaves behind is what the next one starts from, so no
    # other test may read this server's geometry.
    GROWN = (320, 240)
    SHRUNK = (288, 216)

    def setUp(self) -> None:
        if not port_open(HOST, self.SERVER.port):
            self.fail(
                f"{self.SERVER.name} not reachable on {HOST}:{self.SERVER.port} -- "
                f"{self.SERVER.how_to_start}"
            )

    def resize_to(self, size: tuple, png_name: str) -> Image.Image:
        png = screenshot_dir() / png_name
        result = run_vncdo(
            self.SERVER,
            "resize", str(size[0]), str(size[1]),
            "capture", str(png),
        )
        self.assertEqual(
            result.returncode, 0,
            f"{self.SERVER.name}: vncdo exited {result.returncode}, stderr:\n{result.stderr}",
        )
        return Image.open(png)

    def test_resize_changes_the_framebuffer_the_server_serves(self) -> None:
        with self.resize_to(self.GROWN, "tigervnc-setdesktopsize-grown.png") as image:
            self.assertEqual(image.size, self.GROWN)

        with self.resize_to(self.SHRUNK, "tigervnc-setdesktopsize-shrunk.png") as image:
            self.assertEqual(image.size, self.SHRUNK)
            self.assertTrue(
                has_expected_content(self.SERVER, distinct_colours(image)),
                f"{self.SERVER.name}: capture after a resize is a single flat colour",
            )

    def test_a_refusing_server_reports_it_rather_than_going_quiet(self) -> None:
        if not port_open(HOST, LIBVNCSERVER_EXAMPLE.port):
            self.fail(
                f"{LIBVNCSERVER_EXAMPLE.name} not reachable on {HOST}:{LIBVNCSERVER_EXAMPLE.port} -- "
                f"{LIBVNCSERVER_EXAMPLE.how_to_start}"
            )
        result = run_vncdo(LIBVNCSERVER_EXAMPLE, "resize", "320", "240")

        self.assertNotEqual(
            result.returncode, 0,
            f"{LIBVNCSERVER_EXAMPLE.name}: vncdo reported a resize it did not get:\n"
            f"{result.stdout}",
        )
        self.assertIn("resize", result.stderr.lower())

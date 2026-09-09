"""x11vnc is the only fleet server exercised here: it answers the Cursor
pseudo-encoding with a real 18x18 rectangle, and composites the pointer into
the framebuffer for any client that does not ask for one. tigervnc answers
with a degenerate 0x0 rectangle and never paints.
"""

from unittest import TestCase

from PIL import Image, ImageChops

from .utils import HOST, X11VNC, port_open, run_vncdo, screenshot_dir

CURSOR_POS = (50, 50)
FAR_POS = (200, 150)


class TestCursor(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, X11VNC.port):
            self.fail(
                f"x11vnc not reachable on {HOST}:{X11VNC.port} -- "
                "start the servers first with `make servers-up`"
            )

    def capture(self, name: str, *args: str) -> Image.Image:
        png = screenshot_dir() / f"x11vnc-{name}.png"
        result = run_vncdo(X11VNC, *args, "capture", str(png))
        self.assertEqual(result.returncode, 0, f"vncdo {args} failed: {result.stderr}")
        with Image.open(png) as image:
            return image.convert("RGB")

    def test_capture_does_not_depend_on_where_the_pointer_is(self) -> None:
        """The default keeps the pointer out of a capture on a server that
        would otherwise paint it in."""
        near = self.capture("pointer-near", "move", *map(str, CURSOR_POS))
        far = self.capture("pointer-far", "move", *map(str, FAR_POS))

        bbox = ImageChops.difference(near, far).getbbox()
        self.assertIsNone(
            bbox,
            f"captures differ across {bbox} with only the pointer moved; "
            "x11vnc is still painting it into the framebuffer",
        )

    def test_localcursor_composites_a_decoded_cursor(self) -> None:
        """--localcursor draws a decoded cursor the default discards."""
        x, y = map(str, CURSOR_POS)
        without = self.capture("nocursor", "move", x, y)
        with_cursor = self.capture("localcursor", "--localcursor", "move", x, y)

        bbox = ImageChops.difference(without, with_cursor).getbbox()
        self.assertIsNotNone(
            bbox,
            "--localcursor capture is pixel-identical to the default at the "
            "same pointer position; no cursor was decoded and composited",
        )
        # The differing region should sit at the pointer, not somewhere
        # coincidental -- CURSOR_POS plus a little slack for the cursor's
        # own extent and hotspot offset.
        left, top, _, _ = bbox
        self.assertLess(left, CURSOR_POS[0] + 32, f"diff region {bbox} is not near the pointer")
        self.assertLess(top, CURSOR_POS[1] + 32, f"diff region {bbox} is not near the pointer")

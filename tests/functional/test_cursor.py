"""``--localcursor`` decodes a live Cursor pseudo-encoding rectangle.

x11vnc is the only fleet server exercised here: it answers the Cursor
pseudo-encoding with a real 18x18 rectangle. tigervnc answers with a
degenerate 0x0 rectangle instead, which decodes to no pixels and would pass
this test whether or not CursorDecoder (vncdotool/decoders/cursor.py) ever
ran.
"""

from unittest import TestCase

from PIL import Image, ImageChops

from .imagediff import assert_images_match
from .utils import HOST, X11VNC, port_open, run_vncdo, screenshot_dir

CURSOR_POS = (50, 50)


class TestLocalCursor(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, X11VNC.port):
            self.fail(
                f"x11vnc not reachable on {HOST}:{X11VNC.port} -- "
                "start the servers first with `make servers-up`"
            )

    def test_localcursor_composites_a_decoded_cursor(self) -> None:
        """Two captures at the same pointer position, --nocursor against
        --localcursor: both negotiate the Cursor pseudo-encoding, so x11vnc
        excludes its own server-side cursor from the pixel data either way
        (a plain capture with neither flag would already have that baked
        in, making it useless as a contrast here). --nocursor then discards
        the decoded cursor while --localcursor pastes it onto the
        framebuffer, so a live decode shows up as a pixel difference right
        at the pointer position.
        """
        x, y = str(CURSOR_POS[0]), str(CURSOR_POS[1])
        nocursor_png = screenshot_dir() / "x11vnc-nocursor.png"
        localcursor_png = screenshot_dir() / "x11vnc-localcursor.png"

        nocursor = run_vncdo(X11VNC, "--nocursor", "move", x, y, "capture", str(nocursor_png))
        self.assertEqual(nocursor.returncode, 0, f"vncdo --nocursor failed: {nocursor.stderr}")

        localcursor = run_vncdo(X11VNC, "--localcursor", "move", x, y, "capture", str(localcursor_png))
        self.assertEqual(localcursor.returncode, 0, f"vncdo --localcursor failed: {localcursor.stderr}")

        with Image.open(nocursor_png) as without, Image.open(localcursor_png) as with_cursor:
            diff = ImageChops.difference(without.convert("RGB"), with_cursor.convert("RGB"))
            bbox = diff.getbbox()
            self.assertIsNotNone(
                bbox,
                "--localcursor capture is pixel-identical to --nocursor at the same "
                "pointer position; no cursor was decoded and composited",
            )
            # The differing region should sit at the pointer, not somewhere
            # coincidental -- CURSOR_POS plus a little slack for the cursor's
            # own extent and hotspot offset.
            left, top, right, bottom = bbox
            self.assertLess(left, CURSOR_POS[0] + 32, f"diff region {bbox} is not near the pointer")
            self.assertLess(top, CURSOR_POS[1] + 32, f"diff region {bbox} is not near the pointer")

    def test_localcursor_matches_the_server_side_render(self) -> None:
        """The client-side composite should look like what x11vnc renders itself.

        A plain capture (no flags) gets x11vnc's own cursor baked into the
        pixel data server-side. --localcursor gets none of that -- x11vnc
        excludes the cursor once the encoding is negotiated -- and instead
        composites the decoded image back on the client. The two should
        still land on the same pixels: this is the check that CursorDecoder
        didn't just receive bytes, but decoded and placed them correctly.
        """
        x, y = str(CURSOR_POS[0]), str(CURSOR_POS[1])
        default_png = screenshot_dir() / "x11vnc-default.png"
        localcursor_png = screenshot_dir() / "x11vnc-localcursor-vs-default.png"

        default = run_vncdo(X11VNC, "move", x, y, "capture", str(default_png))
        self.assertEqual(default.returncode, 0, f"vncdo failed: {default.stderr}")

        localcursor = run_vncdo(X11VNC, "--localcursor", "move", x, y, "capture", str(localcursor_png))
        self.assertEqual(localcursor.returncode, 0, f"vncdo --localcursor failed: {localcursor.stderr}")

        with Image.open(default_png) as oracle, Image.open(localcursor_png) as captured:
            assert_images_match(
                self,
                captured,
                oracle,
                label="x11vnc-localcursor-vs-server-render",
                message="client-side cursor composite does not match x11vnc's own server-side render",
            )

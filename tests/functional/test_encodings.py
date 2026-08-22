"""Tier 2: each selectable encoding, live, against the same oracle images.

The offline half is tests/unit/test_decoders.py, whose bytes come from the
specification. This half catches what a hand-built fixture cannot:
negotiation, rectangle ordering, and whether a real server's idea of the
encoding matches ours. See specs/decoder-goldens.md.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from vncdotool import decoders

from .vncservers import HOST, TIGERVNC, port_open, run_vncdo

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"

# tigervnc answers a request for CoRRE with Raw (see the fleet encoding
# support table in specs/decoder-architecture.md), so offering it proves the
# fallback renders, not that CoRRE does.
EMITTED_BY_TIGERVNC = {"raw", "rre", "hextile"}


class TestEncodings(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")

    def _capture(self, encodings: str, key: str) -> tuple[Image.Image, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            result = run_vncdo(
                TIGERVNC, "-v", "--encodings", encodings,
                "key", key, "pause", "0.3", "capture", str(path),
            )
            if result.returncode != 0:
                self.fail(f"vncdo --encodings {encodings} failed ({result.returncode}): {result.stderr}")
            return Image.open(path).convert("RGB").copy(), result.stderr

    def test_every_encoding_renders_the_scene_it_was_shown(self) -> None:
        for name in sorted(decoders.ENCODING_NAMES):
            for key in ("0", "s"):
                with self.subTest(encoding=name, scene=key):
                    screen, _ = self._capture(name, key)
                    oracle = Image.open(SCENES_DIR / f"{key}.png").convert("RGB")
                    self.assertEqual(screen.size, oracle.size)
                    self.assertEqual(
                        screen.tobytes(), oracle.tobytes(),
                        f"{name} does not render the image the server was shown",
                    )

    def test_the_server_really_emits_the_encoding_we_asked_for(self) -> None:
        """Without this the test above passes on a server that answered every
        request with Raw, which proves only that Raw still works.
        """
        for name in sorted(EMITTED_BY_TIGERVNC):
            with self.subTest(encoding=name):
                _, log = self._capture(name, "s")
                wanted = decoders.ENCODING_NAMES[name]
                self.assertIn(
                    repr(wanted), log,
                    f"no {wanted!r} rectangle arrived; tigervnc answered with something else",
                )

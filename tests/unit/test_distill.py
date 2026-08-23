"""Slicing a recorded server stream into labelled golden steps."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from struct import pack

from PIL import Image

from tests.goldens import distill, scenes
from vncdotool import pixelformat, rfb
from vncdotool.const import AuthTypes, Encoding, MsgS2C

PIXEL_FORMAT = rfb.PixelFormat()
SIZE = (16, 16)


def handshake_bytes(pixel_format: rfb.PixelFormat = PIXEL_FORMAT) -> bytes:
    """RFB 3.3, no auth, ServerInit -- what vnclog records before any update."""
    return b"RFB 003.003\n" + pack("!I", AuthTypes.NONE) + pack(
        "!HH16sI", SIZE[0], SIZE[1], pixel_format.to_bytes(), len(b"golden")
    ) + b"golden"


def raw_update(image: Image.Image) -> bytes:
    header = pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, 1)
    rectangle = pack("!HHHHi", 0, 0, SIZE[0], SIZE[1], Encoding.RAW)
    return header + rectangle + image.convert("RGB").tobytes("raw", "RGBX")


def screen(key: str) -> Image.Image:
    image = Image.new("RGB", SIZE, (10, 20, 30))
    scenes.stamp_patch(image, key)
    return image


class TestSplit(unittest.TestCase):
    def test_init_stops_at_the_first_update(self) -> None:
        init, _ = distill.split(handshake_bytes() + raw_update(screen("0")), None)
        self.assertEqual(init, handshake_bytes())

    def test_one_step_per_update(self) -> None:
        stream = handshake_bytes() + raw_update(screen("0")) + raw_update(screen("s"))
        _, steps = distill.split(stream, None)
        self.assertEqual([step.index for step in steps], [1, 2])

    def test_a_scene_split_across_updates_is_one_step(self) -> None:
        # A server may answer one key with several updates, and the driver
        # polls for them, so the patch rather than the framing says where a
        # scene ends.
        first, second = raw_update(screen("0")), raw_update(screen("s"))
        stream = handshake_bytes() + first + raw_update(screen("0")) + second
        _, steps = distill.split(stream, None)
        self.assertEqual([step.key for step in steps], ["0", "s"])
        self.assertEqual(steps[0].data, first + raw_update(screen("0")))
        self.assertEqual(steps[1].data, second)

    def test_steps_are_labelled_by_the_patch(self) -> None:
        stream = handshake_bytes() + raw_update(screen("0")) + raw_update(screen("d"))
        _, steps = distill.split(stream, None)
        self.assertEqual([step.key for step in steps], ["0", "d"])

    def test_a_step_holds_exactly_its_own_update_bytes(self) -> None:
        first, second = raw_update(screen("0")), raw_update(screen("s"))
        _, steps = distill.split(handshake_bytes() + first + second, None)
        self.assertEqual([step.data for step in steps], [first, second])

    def test_an_unstamped_frame_has_no_key(self) -> None:
        _, steps = distill.split(handshake_bytes() + raw_update(Image.new("RGB", SIZE, (1, 2, 3))), None)
        self.assertIsNone(steps[0].key)

    def test_the_requested_format_reads_the_bytes_the_server_sent(self) -> None:
        stream = handshake_bytes(pixelformat.PIXEL_FORMATS["bgrx8888"]) + raw_update(screen("s"))
        _, steps = distill.split(stream, "rgbx8888")
        self.assertEqual([step.key for step in steps], ["s"])


class TestWriteFixture(unittest.TestCase):
    def test_writes_one_pair_per_step_plus_conditions(self) -> None:
        stream = handshake_bytes() + raw_update(screen("0")) + raw_update(screen("s"))
        init, steps = distill.split(stream, None)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "fixture"
            distill.write_fixture(directory, init, steps, {"server": "tigervnc"})
            self.assertEqual(gzip.decompress((directory / "init.bin.gz").read_bytes()), init)
            self.assertTrue((directory / "step-01-0.bin.gz").exists())
            self.assertTrue((directory / "step-02-s.bin.gz").exists())
            self.assertEqual(
                json.loads((directory / "conditions.json").read_text())["server"], "tigervnc"
            )


if __name__ == "__main__":
    unittest.main()

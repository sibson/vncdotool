"""Turn a vnclog capture archive into a golden fixture directory.

The recorded server stream is fed to a real client one byte at a time, so
the boundary between two FramebufferUpdates is exactly where the client
finished one and asked for the next, rather than somewhere a second parser
of the wire believes it to be.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from PIL import Image

from tests.goldens import scenes
from vncdotool import client, pixelformat


@dataclass
class Step:
    index: int
    key: Optional[str]
    data: bytes
    screen: Optional[Image.Image] = None


class _Recorder(client.VNCDoToolClient):
    """A client that notes how far the stream had been read at each boundary.

    ``consumed`` is set before every byte is handed over, so a hook firing
    inside ``dataReceived`` sees the offset of the byte that completed the
    message.
    """

    def __init__(self) -> None:
        super().__init__()
        self.update_ends: List[int] = []
        self.init_end: Optional[int] = None
        self.consumed = 0
        self.abort_reason: Optional[str] = None

    def vncConnectionMade(self) -> None:
        super().vncConnectionMade()
        self.init_end = self.consumed

    def vncProtocolError(self, reason: str) -> None:
        # The error reaches a mocked factory and goes nowhere, so it is kept
        # here for `split` to raise on.
        self.abort_reason = reason
        super().vncProtocolError(reason)

    def commitUpdate(self, rectangles: Optional[list] = None) -> None:
        super().commitUpdate(rectangles)
        self.update_ends.append(self.consumed)

    def split(self, s2c: bytes) -> Tuple[bytes, List[Step]]:
        screens: List[Optional[Image.Image]] = []
        for offset in range(len(s2c)):
            self.consumed = offset + 1
            self.dataReceived(s2c[offset:offset + 1])
            if len(self.update_ends) > len(screens):
                screens.append(self.screen.copy() if self.screen else None)

        if self.abort_reason is not None:
            raise ValueError(
                f"the recorded stream stopped decoding after {len(self.update_ends)} "
                f"updates: {self.abort_reason}"
            )

        if self.init_end is None:
            raise ValueError("stream carries no ServerInit; it is not a whole recorded session")

        steps: List[Step] = []
        start = self.init_end
        pending = b""
        for end, screen in zip(self.update_ends, screens):
            pending += s2c[start:end]
            start = end
            if screen is None:
                continue
            key = scenes.read_patch(screen)
            if steps and key == steps[-1].key:
                steps[-1].data += pending
                steps[-1].screen = screen
            else:
                steps.append(Step(index=len(steps) + 1, key=key, data=pending, screen=screen))
            pending = b""
        if pending and steps:
            steps[-1].data += pending
        return s2c[: self.init_end], steps


def _make_client(pixel_format: str, jpeg_quality: Optional[int] = None) -> _Recorder:
    """SetPixelFormat and SetEncodings are client-to-server (RFC 6143 sections
    7.5.1 and 7.5.2), so the s2c stream being replayed never says the server
    switched layouts, nor which encodings were asked for. The recorder has to
    be told both: otherwise it unpacks the bytes as ServerInit announced them
    and permutes every channel, and it refuses the JPEG rectangles the capture
    itself requested.
    """
    recorder = _Recorder()
    recorder.requested_pixel_format = pixelformat.PIXEL_FORMATS[pixel_format]
    recorder.requested_jpeg_quality = jpeg_quality
    recorder.transport = mock.Mock()
    recorder.factory = mock.Mock()
    recorder.factory.shared = 0
    recorder.factory.password = None
    recorder.factory.nocursor = False
    recorder.factory.pseudocursor = False
    recorder.factory.pseudodesktop = False
    recorder.factory.last_rect = False
    recorder.factory.qemu_extended_key = False
    return recorder


def split(
    s2c: bytes, pixel_format: str, jpeg_quality: Optional[int] = None
) -> Tuple[bytes, List[Step]]:
    return _make_client(pixel_format, jpeg_quality).split(s2c)


_NUMBER_ARRAY = re.compile(r"\[\s+((?:-?\d+,\s+)*-?\d+)\s+\]")


def render_conditions(conditions: Dict[str, Any]) -> str:
    """Indented, but with arrays of numbers on one line: a geometry or a
    per-channel tolerance reads as a row, not as a column of digits.
    """
    indented = json.dumps(conditions, indent=2, sort_keys=True)
    return _NUMBER_ARRAY.sub(lambda m: "[" + " ".join(m.group(1).split()) + "]", indented) + "\n"


def write_fixture(directory: Path, init: bytes, steps: List[Step], conditions: Dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "init.bin.gz").write_bytes(gzip.compress(init))
    for step in steps:
        stem = f"step-{step.index:02d}-{step.key or 'unknown'}"
        (directory / f"{stem}.bin.gz").write_bytes(gzip.compress(step.data))
    (directory / "conditions.json").write_text(render_conditions(conditions))

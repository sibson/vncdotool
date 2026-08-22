"""Turn a vnclog capture archive into a golden fixture directory.

The recorded server stream is fed to a real client one byte at a time, so
the boundary between two FramebufferUpdates is exactly where the client
finished one and asked for the next, rather than somewhere a second parser
of the wire believes it to be.
"""
from __future__ import annotations

import gzip
import json
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

    def vncConnectionMade(self) -> None:
        super().vncConnectionMade()
        self.init_end = self.consumed

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

        if self.init_end is None:
            raise ValueError("stream carries no ServerInit; it is not a whole recorded session")

        steps: List[Step] = []
        start = self.init_end
        # A driver polling for a scene draws empty updates in reply, and a
        # scene can arrive across several. The patch says where one ends;
        # every byte between still belongs to a step, so the stream a
        # fixture replays is the stream that was recorded.
        pending = b""
        for end, screen in zip(self.update_ends, screens):
            pending += s2c[start:end]
            start = end
            if screen is None:
                continue
            key = scenes.read_patch(screen)
            if steps and key == steps[-1].key:
                steps[-1].data += pending
            else:
                steps.append(Step(index=len(steps) + 1, key=key, data=pending))
            pending = b""
        if pending and steps:
            steps[-1].data += pending
        return s2c[: self.init_end], steps


def _make_client(pixel_format: Optional[str]) -> _Recorder:
    """``pixel_format`` is what the capturing client asked the server for.

    `SetPixelFormat` is client-to-server (:rfc:`6143` §7.5.1), so it is not in
    the s2c stream being replayed: without being told, the recorder unpacks
    the bytes in whatever format ServerInit announced and every channel comes
    out permuted.
    """
    recorder = _Recorder()
    if pixel_format is not None:
        recorder.requested_pixel_format = pixelformat.PIXEL_FORMATS[pixel_format]
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


def split(s2c: bytes, pixel_format: Optional[str]) -> Tuple[bytes, List[Step]]:
    return _make_client(pixel_format).split(s2c)


def write_fixture(directory: Path, init: bytes, steps: List[Step], conditions: Dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "init.bin.gz").write_bytes(gzip.compress(init))
    for step in steps:
        stem = f"step-{step.index:02d}-{step.key or 'unknown'}"
        (directory / f"{stem}.bin.gz").write_bytes(gzip.compress(step.data))
    (directory / "conditions.json").write_text(json.dumps(conditions, indent=2, sort_keys=True) + "\n")

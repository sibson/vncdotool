"""Turn a vnclog capture archive into a golden fixture directory.

The recorded server stream is fed to a real client one byte at a time, so
the boundary between two FramebufferUpdates is exactly where the client
finished one and asked for the next -- no second parser of the wire, and
the byte-at-a-time feed doubles as the segmentation property the decoder
pump has to satisfy anyway.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from PIL import Image

from tests.servers import scenes
from vncdotool import client


@dataclass
class Step:
    index: int
    key: Optional[str]
    data: bytes
    screen: Image.Image


class _Recorder(client.VNCDoToolClient):
    """A client that notes how far the stream had been read at each boundary.

    ``consumed`` is set by the caller before every byte is handed over, so a
    hook firing inside ``dataReceived`` sees the offset of the byte that
    completed the message.
    """

    def __init__(self) -> None:
        super().__init__()
        self.update_ends: List[int] = []
        self.init_end: Optional[int] = None
        self.consumed = 0

    def vncConnectionMade(self) -> None:
        # ServerInit's block only carries the fixed fields; the server name
        # that follows it is read separately, and this is the callback that
        # fires once that name has also been consumed.
        super().vncConnectionMade()
        self.init_end = self.consumed

    def commitUpdate(self, rectangles: Optional[list] = None) -> None:
        super().commitUpdate(rectangles)
        self.update_ends.append(self.consumed)


def _make_client() -> _Recorder:
    recorder = _Recorder()
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


def split(s2c: bytes) -> Tuple[bytes, List[Step]]:
    recorder = _make_client()
    screens: List[Image.Image] = []
    for offset in range(len(s2c)):
        recorder.consumed = offset + 1
        recorder.dataReceived(s2c[offset:offset + 1])
        if len(recorder.update_ends) > len(screens):
            assert recorder.screen is not None
            screens.append(recorder.screen.copy())

    if recorder.init_end is None:
        raise ValueError("stream carries no ServerInit; it is not a whole recorded session")

    steps: List[Step] = []
    start = recorder.init_end
    for index, (end, screen) in enumerate(zip(recorder.update_ends, screens), start=1):
        steps.append(Step(index=index, key=scenes.read_patch(screen), data=s2c[start:end], screen=screen))
        start = end
    return s2c[: recorder.init_end], steps


def write_fixture(directory: Path, init: bytes, steps: List[Step], conditions: Dict[str, Any]) -> None:
    """Write a fixture directory: init bytes, one bytes+PNG pair per step, conditions.

    The PNG here is what our own decoder produced from the step's bytes, so
    it is a debug artifact, not the oracle -- capture.py overwrites it with
    the scene app's own PNG once the fixture is written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "init.bin.gz").write_bytes(gzip.compress(init))
    for step in steps:
        stem = f"step-{step.index:02d}-{step.key or 'unknown'}"
        (directory / f"{stem}.bin.gz").write_bytes(gzip.compress(step.data))
        step.screen.save(directory / f"{stem}.png")
    (directory / "conditions.json").write_text(json.dumps(conditions, indent=2, sort_keys=True) + "\n")

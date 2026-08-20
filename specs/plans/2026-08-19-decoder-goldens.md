# Decoder Golden Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture per-encoding wire bytes from a real VNC server under screen changes we chose, and replay them into the decoder as offline unit tests with an oracle that is not our own decoder.

**Architecture:** A fullscreen X app inside the fleet containers paints scenes selected by keypress and writes the exact buffer it pushed as an oracle PNG. `vnclog` records the session; a distiller slices the recorded server stream on FramebufferUpdate framing, labels each step by a keysym patch decoded from the frame, and writes a fixture directory. A unit test replays those bytes through a client on a mocked transport.

**Tech Stack:** Python 3.10+, stdlib `unittest`, PIL, `python3-xlib` (in-container only), Docker Compose, Twisted (never started in unit tests).

**Spec:** `specs/decoder-goldens.md`. Read it before Task 1.

## Global Constraints

- Tests are stdlib `unittest`, never pytest. Unit suite: `make test` (`python -m unittest discover tests/unit`).
- No unit test may start the Twisted reactor. Drive protocol classes with `mock.Mock()` transports — see `tests/unit/test_decoder_bugs.py`.
- Functional tests fail loudly (`self.fail`) when a server is down; they never `skipTest`.
- Lint is `flake8 --count --statistics vncdotool tests`, line length 127, `extend-ignore = E203`. No black, no isort.
- Comments carry only what the reader cannot get from the code, the language, the library docs or the RFB specs. One or two lines is the norm. Nothing about the change itself — that is commit-message material.
- Anything touching the wire is checked against RFC 6143 or rfbproto, not inferred from surrounding code.
- Golden capture geometry is **256x192**. Scene keys are `0 s d x g p c f`.
- Every user-visible change gets a `CHANGELOG.rst` entry under the current `(UNRELEASED)` heading as `- <description> (@author, #NNN)`. Test-only scaffolding is not user-visible.
- Commit after each task. Do not push.

## File Structure

| File | Responsibility |
|---|---|
| `tests/servers/__init__.py` (create) | Makes the container-side modules importable from the unit suite. |
| `tests/servers/scenes.py` (create) | Pure scene functions: prior screen image → new screen image. Keysym patch encode/decode. No X, no I/O. |
| `tests/servers/scene_app.py` (create) | X plumbing: fullscreen window, keypress loop, `put_image`, oracle PNG writing. Imports `scenes`. |
| `tests/servers/Dockerfile` (modify) | Base stage gains `python3`, `python3-xlib`, `python3-pil`; copies the two modules. |
| `tests/servers/tigervnc-entrypoint.sh`, `x11vnc-entrypoint.sh` (modify) | Launch `scene_app.py` instead of `draw-content.sh`. |
| `tests/servers/draw-content.sh` (delete, Task 2) | Superseded. |
| `tests/servers/docker-compose.yml` (modify) | New `tigervnc-golden` service at 256x192, port 5936. |
| `tests/functional/vncservers.py` (modify) | `TIGERVNC_GOLDEN` descriptor. |
| `tests/functional/test_scene_app.py` (create) | Fleet smoke: a scene key changes the screen; the patch says which key. |
| `tests/goldens/__init__.py`, `distill.py` (create) | Archive → fixture directory. Offline, no reactor. |
| `tests/goldens/capture.py` (create) | Drives the fleet + vnclog + vncdo, then calls the distiller. Manual, via `make goldens`. |
| `tests/unit/test_scenes.py` (create) | Scene determinism, patch round-trip. |
| `tests/unit/test_distill.py` (create) | Slicing and labelling, from synthetic streams. |
| `tests/unit/test_goldens.py` (create) | Replays every committed fixture. |
| `tests/unit/fixtures/goldens/tigervnc-raw-rgb888/` (create, Task 5) | The first fixture. |

---

### Task 1: Pure scenes and the keysym patch

**Files:**
- Create: `tests/servers/__init__.py`, `tests/servers/scenes.py`
- Test: `tests/unit/test_scenes.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SIZE: tuple[int, int]` = `(256, 192)`
  - `PATCH_ORIGIN: tuple[int, int]`, `PATCH_SIZE: int`
  - `base() -> PIL.Image.Image` — RGB, deterministic, not flat
  - `SCENES: dict[str, Callable[[Image.Image], Image.Image]]` keyed by `"0"`, `"s"`, `"d"`, `"x"`, `"g"`, `"p"`, `"c"`, `"f"`
  - `apply(key: str, screen: Image.Image) -> Image.Image` — runs the scene then stamps the patch
  - `stamp_patch(image: Image.Image, key: str) -> None`
  - `read_patch(image: Image.Image) -> str | None`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_scenes.py`:

```python
"""The scene generator, which runs in the fleet containers and offline here."""
from __future__ import annotations

import unittest

from tests.servers import scenes


class TestScenes(unittest.TestCase):
    def test_base_is_not_flat(self) -> None:
        # A flat screen is indistinguishable from "no update arrived".
        self.assertGreater(len(scenes.base().getcolors(maxcolors=4096) or []), 1)

    def test_base_is_the_declared_size(self) -> None:
        self.assertEqual(scenes.base().size, scenes.SIZE)

    def test_every_key_is_deterministic(self) -> None:
        for key in scenes.SCENES:
            with self.subTest(key=key):
                first = scenes.apply(key, scenes.base())
                second = scenes.apply(key, scenes.base())
                self.assertEqual(first.tobytes(), second.tobytes())

    def test_scenes_depend_on_the_prior_screen(self) -> None:
        # An update is a delta, so "c" scrolling a solid screen and "c"
        # scrolling a dense one must not produce the same result.
        solid = scenes.apply("s", scenes.base())
        dense = scenes.apply("d", scenes.base())
        self.assertNotEqual(
            scenes.apply("c", solid).tobytes(),
            scenes.apply("c", dense).tobytes(),
        )

    def test_patch_round_trips_for_every_key(self) -> None:
        for key in scenes.SCENES:
            with self.subTest(key=key):
                self.assertEqual(scenes.read_patch(scenes.apply(key, scenes.base())), key)

    def test_read_patch_rejects_an_unstamped_screen(self) -> None:
        self.assertIsNone(scenes.read_patch(scenes.base()))

    def test_reset_returns_the_base_screen(self) -> None:
        stamped = scenes.apply("0", scenes.apply("d", scenes.base()))
        expected = scenes.base()
        scenes.stamp_patch(expected, "0")
        self.assertEqual(stamped.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run python -m unittest tests.unit.test_scenes -v
```

Expected: `ModuleNotFoundError: No module named 'tests.servers'`.

- [ ] **Step 3: Create the package marker**

`tests/servers/__init__.py`:

```python
"""Modules shared between the fleet container images and the test suite."""
```

- [ ] **Step 4: Write `tests/servers/scenes.py`**

```python
"""Screen content for golden capture, as pure functions of the prior screen.

Runs both inside the fleet containers (via scene_app.py) and offline in the
unit suite, so it must import nothing X-specific.

Every scene is a deterministic function of the screen it is handed: an
update is a delta, so what a decoder sees depends on what was there before.
"""
from __future__ import annotations

import random
from typing import Callable, Dict, Optional

from PIL import Image, ImageDraw

SIZE = (256, 192)

# The patch is how a distilled step learns which key produced it: the
# archive keeps the two stream directions apart, so a key event in the
# client stream cannot be aligned against an offset in the server's.
PATCH_ORIGIN = (0, 0)
PATCH_SIZE = 8
_PATCH_GREEN = 0x5A
_PATCH_BLUE = 0xA5


def _seeded(key: str) -> random.Random:
    return random.Random(f"vncdotool-scene-{key}")


def base() -> Image.Image:
    image = Image.new("RGB", SIZE, (24, 24, 32))
    draw = ImageDraw.Draw(image)
    width, height = SIZE
    draw.rectangle([16, 16, width - 17, height - 17], outline=(200, 200, 40), width=2)
    draw.line([0, 0, width - 1, height - 1], fill=(180, 40, 40), width=1)
    draw.line([0, height - 1, width - 1, 0], fill=(40, 180, 60), width=1)
    return image


def _reset(screen: Image.Image) -> Image.Image:
    return base()


def _solid(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    ImageDraw.Draw(image).rectangle([32, 32, 223, 159], fill=(0, 96, 192))
    return image


def _dense(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    rng = _seeded("d")
    noise = Image.new("RGB", (192, 128))
    noise.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(192 * 128)])
    image.paste(noise, (32, 32))
    return image


def _scattered(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    draw = ImageDraw.Draw(image)
    rng = _seeded("x")
    for _ in range(64):
        x = rng.randrange(SIZE[0] - 8)
        y = rng.randrange(SIZE[1] - 8)
        draw.rectangle([x, y, x + 5, y + 5], fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    return image


def _gradient(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    width, height = SIZE
    gradient = Image.new("RGB", (width, height))
    gradient.putdata(
        [
            (x * 255 // (width - 1), y * 255 // (height - 1), 255 - (x * 255 // (width - 1)))
            for y in range(height)
            for x in range(width)
        ]
    )
    image.paste(gradient, (0, 0))
    return image


def _palette(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    draw = ImageDraw.Draw(image)
    two = [(0, 0, 0), (255, 255, 255)]
    four = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    sixteen = [(v * 17, (15 - v) * 17, (v * 7) % 256) for v in range(16)]
    for band, colours in enumerate((two, four, sixteen)):
        top = 16 + band * 56
        for index, colour in enumerate(colours):
            step = 224 // len(colours)
            left = 16 + index * step
            draw.rectangle([left, top, left + step - 1, top + 47], fill=colour)
    return image


def _scroll(screen: Image.Image) -> Image.Image:
    """Move a region up, which is what makes a server emit CopyRect at all."""
    image = screen.copy()
    region = image.crop((0, 32, SIZE[0], SIZE[1]))
    image.paste(region, (0, 16))
    return image


def _full(screen: Image.Image) -> Image.Image:
    rng = _seeded("f")
    return Image.new("RGB", SIZE, (rng.randrange(64, 256), rng.randrange(64, 256), rng.randrange(64, 256)))


SCENES: Dict[str, Callable[[Image.Image], Image.Image]] = {
    "0": _reset,
    "s": _solid,
    "d": _dense,
    "x": _scattered,
    "g": _gradient,
    "p": _palette,
    "c": _scroll,
    "f": _full,
}


def stamp_patch(image: Image.Image, key: str) -> None:
    left, top = PATCH_ORIGIN
    colour = (ord(key), _PATCH_GREEN, _PATCH_BLUE)
    ImageDraw.Draw(image).rectangle([left, top, left + PATCH_SIZE - 1, top + PATCH_SIZE - 1], fill=colour)


def read_patch(image: Image.Image) -> Optional[str]:
    left, top = PATCH_ORIGIN
    red, green, blue = image.convert("RGB").getpixel((left + PATCH_SIZE // 2, top + PATCH_SIZE // 2))
    if (green, blue) != (_PATCH_GREEN, _PATCH_BLUE):
        return None
    key = chr(red)
    return key if key in SCENES else None


def apply(key: str, screen: Image.Image) -> Image.Image:
    image = SCENES[key](screen)
    stamp_patch(image, key)
    return image
```

- [ ] **Step 5: Run the tests**

```bash
uv run python -m unittest tests.unit.test_scenes -v
```

Expected: 7 tests, all pass. If `test_scenes_depend_on_the_prior_screen` fails, the scroll scene is copying a region that is identical in both inputs — widen the crop, do not weaken the test.

- [ ] **Step 6: Lint**

```bash
uv run flake8 --count --statistics vncdotool tests
```

Expected: `0`.

- [ ] **Step 7: Commit**

```bash
git add tests/servers/__init__.py tests/servers/scenes.py tests/unit/test_scenes.py
```

```bash
git commit -m "test(goldens): add the pure scene generator and keysym patch"
```

---

### Task 2: The scene app in the fleet

**Files:**
- Create: `tests/servers/scene_app.py`, `tests/functional/test_scene_app.py`
- Modify: `tests/servers/Dockerfile`, `tests/servers/tigervnc-entrypoint.sh`, `tests/servers/x11vnc-entrypoint.sh`, `tests/servers/docker-compose.yml`, `tests/functional/vncservers.py`
- Delete: `tests/servers/draw-content.sh`

**Interfaces:**
- Consumes: `tests/servers/scenes.py` (`SIZE`, `apply`, `base`, `stamp_patch`, `read_patch`).
- Produces: `TIGERVNC_GOLDEN: VNCServer` in `vncservers.py` (name `tigervnc-golden`, port 5936, size `(256, 192)`); oracle PNGs written inside the container to `$SCENE_ORACLE_DIR` (default `/oracles`) as `oracle-<NN>-<key>.png`, `NN` a 1-based counter of applied keys.

- [ ] **Step 1: Write the failing functional test**

`tests/functional/test_scene_app.py`:

```python
"""The in-container scene app, exercised through a real server."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from tests.servers import scenes

from .vncservers import TIGERVNC_GOLDEN, port_open, HOST, run_vncdo


class TestSceneApp(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC_GOLDEN.port):
            self.fail(f"{TIGERVNC_GOLDEN.name} is not listening on {TIGERVNC_GOLDEN.port}; {TIGERVNC_GOLDEN.how_to_start}")

    def _capture(self, *args: str) -> Image.Image:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            result = run_vncdo(TIGERVNC_GOLDEN, *args, "capture", str(path))
            if result.returncode != 0:
                self.fail(f"vncdo failed ({result.returncode}): {result.stderr}")
            return Image.open(path).copy()

    def test_serves_the_golden_geometry(self) -> None:
        self.assertEqual(self._capture("key", "0").size, scenes.SIZE)

    def test_a_scene_key_changes_the_screen(self) -> None:
        reset = self._capture("key", "0")
        solid = self._capture("key", "s")
        self.assertNotEqual(reset.tobytes(), solid.tobytes())

    def test_the_patch_names_the_key_that_was_pressed(self) -> None:
        for key in ("0", "s", "d", "g"):
            with self.subTest(key=key):
                self.assertEqual(scenes.read_patch(self._capture("key", key)), key)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run python -m unittest tests.functional.test_scene_app -v
```

Expected: `ImportError` on `TIGERVNC_GOLDEN`.

- [ ] **Step 3: Write `tests/servers/scene_app.py`**

```python
#!/usr/bin/env python3
"""Fullscreen X client that paints a scene per keypress, for golden capture.

Runs inside the fleet containers. Scenes are composed in memory and pushed
whole with PutImage, so what reaches the X framebuffer is a buffer this
process holds rather than the result of a rendering stack -- that buffer,
saved as a PNG, is the oracle a golden fixture is checked against.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image
from Xlib import X, XK, display

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.servers import scenes  # noqa: E402

ORACLE_DIR = Path(os.environ.get("SCENE_ORACLE_DIR", "/oracles"))
# PutImage carries the whole request in one X message; splitting into bands
# keeps every request well inside the server's maximum request length.
BAND_ROWS = 32


def _to_zpixmap(image: Image.Image) -> bytes:
    """Depth-24 ZPixmap data: B, G, R, pad per pixel on an LSBFirst server."""
    return image.convert("RGB").tobytes("raw", "BGRX")


class SceneApp:
    def __init__(self) -> None:
        self.display = display.Display()
        if self.display.info.image_byte_order != 0:
            raise SystemExit("scene_app: X server is not LSBFirst; ZPixmap byte order would be wrong")
        screen = self.display.screen()
        width, height = scenes.SIZE
        self.window = screen.root.create_window(
            0, 0, width, height, 0, screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=screen.black_pixel,
            override_redirect=True,
            event_mask=X.KeyPressMask | X.ExposureMask,
        )
        self.gc = self.window.create_gc()
        self.window.map()
        self.display.set_input_focus(self.window, X.RevertToParent, X.CurrentTime)
        self.screen_image = scenes.base()
        scenes.stamp_patch(self.screen_image, "0")
        self.applied = 0
        ORACLE_DIR.mkdir(parents=True, exist_ok=True)
        self.paint()
        self.write_oracle("0")

    def paint(self) -> None:
        width, height = scenes.SIZE
        data = _to_zpixmap(self.screen_image)
        stride = width * 4
        for top in range(0, height, BAND_ROWS):
            rows = min(BAND_ROWS, height - top)
            self.window.put_image(
                self.gc, 0, top, width, rows, X.ZPixmap, self.display.screen().root_depth, 0,
                data[top * stride:(top + rows) * stride],
            )
        self.display.flush()

    def write_oracle(self, key: str) -> None:
        self.applied += 1
        self.screen_image.save(ORACLE_DIR / f"oracle-{self.applied:02d}-{key}.png")

    def handle_key(self, keycode: int) -> None:
        keysym = self.display.keycode_to_keysym(keycode, 0)
        key = XK.keysym_to_string(keysym)
        if key not in scenes.SCENES:
            return
        self.screen_image = scenes.apply(key, self.screen_image)
        self.paint()
        self.write_oracle(key)

    def run(self) -> None:
        while True:
            event = self.display.next_event()
            if event.type == X.Expose:
                self.paint()
            elif event.type == X.KeyPress:
                self.handle_key(event.detail)


if __name__ == "__main__":
    SceneApp().run()
```

- [ ] **Step 4: Teach the base image about it**

In `tests/servers/Dockerfile`, in the `base` stage: add `python3`, `python3-xlib` and `python3-pil` to the `apt-get install` list, and replace the two `draw-content.sh` lines with:

```dockerfile
COPY __init__.py /tests/servers/__init__.py
COPY scenes.py /tests/servers/scenes.py
COPY scene_app.py /tests/servers/scene_app.py
```

`scene_app.py` inserts three parents of its own path onto `sys.path`, so the in-image layout must keep `tests/servers/` — hence the paths above.

Update the base stage's comment: it currently says the stage holds "an X client to draw so captures aren't pure black". It now holds the scene app, which draws the base screen at start-up and repaints on a keypress.

- [ ] **Step 5: Launch it from both X entrypoints**

In `tests/servers/tigervnc-entrypoint.sh` replace:

```sh
DISPLAY=:0 /draw-content.sh &
```

with:

```sh
DISPLAY=:0 python3 /tests/servers/scene_app.py &
```

Make the same replacement in `tests/servers/x11vnc-entrypoint.sh`, and drop `/tmp/draw-content-ready` from its `rm -f` line.

In `tigervnc-entrypoint.sh`, take the geometry from the environment so one image serves both the normal and the golden service:

```sh
Xvnc :0 \
    "$@" \
    -rfbport 5900 \
    -geometry "${VNC_GEOMETRY:-1024x768}" \
```

- [ ] **Step 6: Delete the superseded script**

```bash
git rm tests/servers/draw-content.sh
```

- [ ] **Step 7: Add the golden service**

In `tests/servers/docker-compose.yml`, after the `tigervnc-auth` service:

```yaml
  # Golden-fixture capture: a small framebuffer keeps a committed Raw
  # update to tens of kilobytes rather than megabytes.
  tigervnc-golden:
    build:
      context: .
      target: tigervnc
    image: vncdotool-test-tigervnc
    environment:
      VNC_GEOMETRY: 256x192
    ports:
      - "127.0.0.1:5936:5900"
```

- [ ] **Step 8: Describe it to the suite**

In `tests/functional/vncservers.py`, after `X11VNC`:

```python
# Small framebuffer, for golden capture; see specs/decoder-goldens.md.
TIGERVNC_GOLDEN = VNCServer("tigervnc-golden", 5936, size=(256, 192))
```

and add `TIGERVNC_GOLDEN` to `DOCKER_SERVERS`.

- [ ] **Step 9: Rebuild the fleet and run the functional test**

```bash
make servers-up
```

```bash
uv run python -m unittest tests.functional.test_scene_app -v
```

Expected: 3 tests pass. A failure in `test_the_patch_names_the_key_that_was_pressed` with `None` means the key never reached the app — check `docker compose -f tests/servers/docker-compose.yml logs tigervnc-golden` for a Python traceback before touching the test.

- [ ] **Step 10: Check nothing else regressed**

```bash
make test-servers
```

Expected: the existing per-server grid passes, including the new `tigervnc-golden` member.

- [ ] **Step 11: Lint and commit**

```bash
uv run flake8 --count --statistics vncdotool tests
```

```bash
git add tests/servers tests/functional/test_scene_app.py tests/functional/vncservers.py tests/servers/docker-compose.yml
```

```bash
git commit -m "test(goldens): paint scenes on keypress inside the X fleet servers"
```

---

### Task 3: The distiller

**Files:**
- Create: `tests/goldens/__init__.py`, `tests/goldens/distill.py`
- Test: `tests/unit/test_distill.py`

**Interfaces:**
- Consumes: `vncdotool.client.VNCDoToolClient`, `tests/servers/scenes.read_patch`.
- Produces:
  - `@dataclass class Step: index: int; key: str | None; data: bytes; screen: Image.Image`
  - `split(s2c: bytes) -> tuple[bytes, list[Step]]` — returns the bytes up to the first FramebufferUpdate (the handshake and ServerInit) and one `Step` per update
  - `write_fixture(directory: Path, init: bytes, steps: list[Step], conditions: dict) -> None`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_distill.py`:

```python
"""Slicing a recorded server stream into labelled golden steps."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from struct import pack

from PIL import Image

from tests.goldens import distill
from tests.servers import scenes
from vncdotool import rfb
from vncdotool.const import AuthTypes, Encoding, MsgS2C

PIXEL_FORMAT = rfb.PixelFormat()
SIZE = (16, 16)


def handshake_bytes() -> bytes:
    """RFB 3.3, no auth, ServerInit -- what vnclog records before any update."""
    return b"RFB 003.003\n" + pack("!I", AuthTypes.NONE) + pack(
        "!HH16sI", SIZE[0], SIZE[1], PIXEL_FORMAT.to_bytes(), len(b"golden")
    ) + b"golden"


def raw_update(image: Image.Image) -> bytes:
    """One FramebufferUpdate carrying the whole screen as a Raw rectangle."""
    header = pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, 1)
    rectangle = pack("!HHHHi", 0, 0, SIZE[0], SIZE[1], Encoding.RAW)
    return header + rectangle + image.convert("RGB").tobytes("raw", "RGBX")


def screen(key: str) -> Image.Image:
    image = Image.new("RGB", SIZE, (10, 20, 30))
    scenes.stamp_patch(image, key)
    return image


class TestSplit(unittest.TestCase):
    def test_init_stops_at_the_first_update(self) -> None:
        init, _ = distill.split(handshake_bytes() + raw_update(screen("0")))
        self.assertEqual(init, handshake_bytes())

    def test_one_step_per_update(self) -> None:
        stream = handshake_bytes() + raw_update(screen("0")) + raw_update(screen("s"))
        _, steps = distill.split(stream)
        self.assertEqual([step.index for step in steps], [1, 2])

    def test_steps_are_labelled_by_the_patch(self) -> None:
        stream = handshake_bytes() + raw_update(screen("0")) + raw_update(screen("d"))
        _, steps = distill.split(stream)
        self.assertEqual([step.key for step in steps], ["0", "d"])

    def test_a_step_holds_exactly_its_own_update_bytes(self) -> None:
        first, second = raw_update(screen("0")), raw_update(screen("s"))
        _, steps = distill.split(handshake_bytes() + first + second)
        self.assertEqual([step.data for step in steps], [first, second])

    def test_an_unstamped_frame_has_no_key(self) -> None:
        _, steps = distill.split(handshake_bytes() + raw_update(Image.new("RGB", SIZE, (1, 2, 3))))
        self.assertIsNone(steps[0].key)


class TestWriteFixture(unittest.TestCase):
    def test_writes_one_pair_per_step_plus_conditions(self) -> None:
        stream = handshake_bytes() + raw_update(screen("0")) + raw_update(screen("s"))
        init, steps = distill.split(stream)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "fixture"
            distill.write_fixture(directory, init, steps, {"server": "tigervnc-golden"})
            self.assertEqual(gzip.decompress((directory / "init.bin.gz").read_bytes()), init)
            self.assertTrue((directory / "step-01-0.bin.gz").exists())
            self.assertTrue((directory / "step-02-s.png").exists())
            self.assertEqual(
                json.loads((directory / "conditions.json").read_text())["server"], "tigervnc-golden"
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run python -m unittest tests.unit.test_distill -v
```

Expected: `ModuleNotFoundError: No module named 'tests.goldens'`.

- [ ] **Step 3: Write `tests/goldens/__init__.py`**

```python
"""Golden-fixture capture and distillation. See specs/decoder-goldens.md."""
```

- [ ] **Step 4: Write `tests/goldens/distill.py`**

```python
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

    def _handleServerInit(self, block: bytes) -> None:
        super()._handleServerInit(block)
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
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "init.bin.gz").write_bytes(gzip.compress(init))
    for step in steps:
        stem = f"step-{step.index:02d}-{step.key or 'unknown'}"
        (directory / f"{stem}.bin.gz").write_bytes(gzip.compress(step.data))
        step.screen.save(directory / f"{stem}.png")
    (directory / "conditions.json").write_text(json.dumps(conditions, indent=2, sort_keys=True) + "\n")
```

- [ ] **Step 5: Run the tests**

```bash
uv run python -m unittest tests.unit.test_distill -v
```

Expected: 6 tests pass. If `_handleServerInit` turns out to have a different name or signature on `VNCDoToolClient`, read `vncdotool/rfb.py` and hook the real one — the boundary must come from the client that parsed the message, never from re-parsing the handshake here, whose shape varies with the negotiated version.

- [ ] **Step 6: Confirm the oracle PNG in a fixture is the decoded frame, not the truth**

The `screen` on a `Step` comes out of our own decoder, so it is a debug artifact. Add this to `distill.py` under `write_fixture`'s docstring line, no more than two lines, in your own words: the PNG written here is what our decoder produced, and the capture harness overwrites it with the scene app's oracle.

- [ ] **Step 7: Lint and commit**

```bash
uv run flake8 --count --statistics vncdotool tests
```

```bash
git add tests/goldens tests/unit/test_distill.py
```

```bash
git commit -m "test(goldens): distill a recorded stream into labelled steps"
```

---

### Task 4: The capture harness

**Files:**
- Create: `tests/goldens/capture.py`
- Modify: `tests/servers/servers.mk`, `Makefile` (help text)

**Interfaces:**
- Consumes: `tests/goldens/distill.split`, `distill.write_fixture`, `tests/functional/vncservers.py` (`TIGERVNC_GOLDEN`, `VNCLOG`, `VNCDO`, `HOST`), `tests/servers/scenes.SCENES`.
- Produces: `tests/unit/fixtures/goldens/<server>-<encoding>-<format>/`, written by `make goldens`.

- [ ] **Step 1: Write `tests/goldens/capture.py`**

```python
"""Capture a golden fixture from a running fleet server. Manual: `make goldens`.

Never runs in CI. CI runs the fixtures this writes.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.functional.vncservers import HOST, TIGERVNC_GOLDEN, VNCDO, VNCLOG  # noqa: E402
from tests.goldens import distill  # noqa: E402
from tests.servers import scenes  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "goldens"
PROXY_PORT = 5999
PROXY_STARTUP_DEADLINE = 10.0
CAPTURE_DEADLINE = 60.0
SCENE_ORDER = ["0", "s", "d", "x", "g", "p", "c", "f"]


def scene_script(directory: Path) -> Path:
    """The .vdo that drives the scenes -- it travels inside the archive."""
    lines = []
    for index, key in enumerate(SCENE_ORDER, start=1):
        lines.append(f"key {key}")
        lines.append(f"capture {directory}/driver-{index:02d}-{key}.png")
    path = directory / "scene.vdo"
    path.write_text("\n".join(lines) + "\n")
    return path


def image_digest(service: str) -> str:
    """Which image this fixture came from, so it can be rebuilt years later."""
    result = subprocess.run(
        ["docker", "compose", "-f", "tests/servers/docker-compose.yml", "images", "--format", "json", service],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def container_oracles(service: str, into: Path) -> dict:
    """Copy the scene app's own PNGs out of the container: the real oracle."""
    subprocess.run(
        ["docker", "compose", "-f", "tests/servers/docker-compose.yml", "cp",
         f"{service}:/oracles/.", str(into)],
        check=True,
    )
    return {path.name.split("-")[2].removesuffix(".png"): path for path in sorted(into.glob("oracle-*.png"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="tigervnc-raw-rgb888", help="fixture directory name")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        archive = work / "capture.zip"
        proxy = subprocess.Popen(
            [VNCLOG, "-s", f"{HOST}::{TIGERVNC_GOLDEN.port}", "--listen", str(PROXY_PORT),
             "--capture-raw", str(archive)],
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
        )
        deadline = time.monotonic() + PROXY_STARTUP_DEADLINE
        while time.monotonic() < deadline:
            if "accepting connections" in (proxy.stderr.readline() or ""):
                break
        else:
            proxy.kill()
            raise SystemExit("vnclog never listened")

        subprocess.run([VNCDO, "-s", f"{HOST}::{PROXY_PORT}", str(scene_script(work))], check=True,
                       timeout=CAPTURE_DEADLINE)
        proxy.wait(timeout=CAPTURE_DEADLINE)

        with zipfile.ZipFile(archive) as zipped:
            s2c = zipped.read("s2c.bin")
            meta = zipped.read("meta.json").decode()

        init, steps = distill.split(s2c)
        oracles = container_oracles(f"{TIGERVNC_GOLDEN.name}", work / "oracles")

        directory = FIXTURE_ROOT / args.name
        if directory.exists():
            shutil.rmtree(directory)
        conditions = {
            "server": TIGERVNC_GOLDEN.name,
            "image_digest": image_digest(TIGERVNC_GOLDEN.name),
            "meta": meta,
            "scene_order": SCENE_ORDER,
            "scene_script": scene_script(work).read_text(),
            "geometry": list(scenes.SIZE),
            "tolerance": 0,
        }
        distill.write_fixture(directory, init, steps, conditions)

        for step in steps:
            if step.key is None:
                raise SystemExit(f"step {step.index} carries no keysym patch; capture is unusable")
            oracle = oracles.get(step.key)
            if oracle is None:
                raise SystemExit(f"no oracle PNG for key {step.key!r}")
            Image.open(oracle).save(directory / f"step-{step.index:02d}-{step.key}.png")

        print(f"wrote {directory} ({len(steps)} steps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add the make target**

In `tests/servers/servers.mk`:

```make
# Capture golden decoder fixtures from the running fleet. Manual, never CI:
# CI replays the fixtures this writes. See specs/decoder-goldens.md.
.PHONY: goldens
goldens:
	uv run python tests/goldens/capture.py
```

and a line in the `Makefile` help block:

```make
	@echo "goldens:	capture decoder golden fixtures from the fleet"
```

- [ ] **Step 3: Run it against the live fleet**

```bash
make servers-up
```

```bash
make goldens
```

Expected: `wrote .../tigervnc-raw-rgb888 (8 steps)`. If it exits with "step N carries no keysym patch", the server sent an update the scene app had not painted yet — add `pause 0.5` after each `key` line in `scene_script` and rerun. If a step count above 8 appears, that is a server sending more than one update per key and is fine; the labels stay correct.

- [ ] **Step 4: Check the fixture's size before committing it**

```bash
du -sh tests/unit/fixtures/goldens/tigervnc-raw-rgb888
```

Expected: under 1MB. If it is larger, the geometry is not being honoured — check `VNC_GEOMETRY` reached Xvnc rather than compressing harder.

- [ ] **Step 5: Commit the harness and the fixture**

```bash
git add tests/goldens/capture.py tests/servers/servers.mk Makefile tests/unit/fixtures/goldens
```

```bash
git commit -m "test(goldens): capture the first Raw fixture from tigervnc"
```

---

### Task 5: The golden test

**Files:**
- Create: `tests/unit/test_goldens.py`
- Modify: `specs/decoder-goldens.md` (status line only)

**Interfaces:**
- Consumes: the fixture directories from Task 4, `vncdotool.client.VNCDoToolClient`.
- Produces: nothing further.

- [ ] **Step 1: Write the test**

`tests/unit/test_goldens.py`:

```python
"""Replay committed decoder goldens. No fleet, no network, no reactor.

Capture these with `make goldens`; see specs/decoder-goldens.md.
"""
from __future__ import annotations

import gzip
import json
import unittest
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock

from PIL import Image

from vncdotool import client

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "goldens"


def fixtures() -> List[Path]:
    return sorted(path for path in FIXTURE_ROOT.iterdir() if (path / "conditions.json").exists())


def make_client() -> client.VNCDoToolClient:
    cli = client.VNCDoToolClient()
    cli.transport = mock.Mock()
    cli.factory = mock.Mock()
    cli.factory.shared = 0
    cli.factory.password = None
    cli.factory.nocursor = False
    cli.factory.pseudocursor = False
    cli.factory.pseudodesktop = False
    cli.factory.last_rect = False
    cli.factory.qemu_extended_key = False
    return cli


def first_difference(actual: Image.Image, expected: Image.Image, tolerance: int) -> Optional[Tuple[int, int, tuple, tuple]]:
    left, right = actual.convert("RGB"), expected.convert("RGB")
    if left.size != right.size:
        raise AssertionError(f"decoded {left.size}, expected {right.size}")
    width, _ = left.size
    for index, (got, want) in enumerate(zip(left.getdata(), right.getdata())):
        if any(abs(a - b) > tolerance for a, b in zip(got, want)):
            return index % width, index // width, got, want
    return None


class TestGoldens(unittest.TestCase):
    def test_at_least_one_fixture_is_committed(self) -> None:
        self.assertTrue(fixtures(), f"no golden fixtures under {FIXTURE_ROOT}; capture one with `make goldens`")

    def test_every_fixture_decodes_to_its_oracle(self) -> None:
        for fixture in fixtures():
            with self.subTest(fixture=fixture.name):
                conditions = json.loads((fixture / "conditions.json").read_text())
                tolerance = conditions["tolerance"]
                cli = make_client()
                cli.dataReceived(gzip.decompress((fixture / "init.bin.gz").read_bytes()))
                for step in sorted(fixture.glob("step-*.bin.gz")):
                    cli.dataReceived(gzip.decompress(step.read_bytes()))
                    expected = Image.open(step.with_suffix("").with_suffix(".png"))
                    self.assertIsNotNone(cli.screen, f"{step.name}: no framebuffer after the update")
                    difference = first_difference(cli.screen, expected, tolerance)
                    if difference is not None:
                        x, y, got, want = difference
                        self.fail(f"{fixture.name} {step.name}: pixel ({x},{y}) decoded {got}, expected {want}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

```bash
uv run python -m unittest tests.unit.test_goldens -v
```

Expected: both tests pass against the fixture from Task 4. A pixel mismatch here is a real finding — the oracle came from the scene app, not from our decoder — so investigate before adjusting anything. Serve the capture back with `vncdo-replay --server` to see it in a viewer.

- [ ] **Step 3: Run the whole unit suite**

```bash
make test
```

Expected: all green, no reactor started.

- [ ] **Step 4: Mark the spec built**

In `specs/decoder-goldens.md`, change the status line from `Status: draft.` to `Status: scaffold built; Raw at 32bpp against tigervnc. Later matrix values are TDD entry points, see Phasing.`

- [ ] **Step 5: Lint and commit**

```bash
uv run flake8 --count --statistics vncdotool tests
```

```bash
git add tests/unit/test_goldens.py specs/decoder-goldens.md
```

```bash
git commit -m "test(goldens): replay committed fixtures against their oracle"
```

---

## What this plan deliberately does not build

Named so they are not mistaken for oversights: `vncdo --pixel-format`, `--encodings`, the second and later fixtures in the matrix, cross-format equality assertions, the reduced-depth tolerance oracle, x11vnc capture, and the libvncserver pnm-server. Each is a TDD entry point once the scaffold is green — see the Phasing section of `specs/decoder-goldens.md`.

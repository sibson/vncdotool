# Decoder Golden Fixtures — Design

Status: draft. Builds the fixture half of
[testing-framework.md](testing-framework.md) Phase 2 and the capture half of
[decoder-architecture.md](decoder-architecture.md) Phase 0. Read the
screen-change section of the testing framework first: it establishes that no
fleet server can be scripted into a screen change today, which is the gap this
design fills.

## Problem

Decoder goldens need wire bytes from a real server, produced by screen changes
we chose, verified against something that is not our own decoder. Today none of
those three exist: `draw-content.sh` paints once at start-up, nothing can ask a
fleet server for a particular update, and the only image we could compare
against is one our decoder produced.

## What reproducible means here

The committed fixture bytes are the reproducible artifact. They replay into the
decoder identically on any machine, with no fleet, no network and no reactor,
for as long as they sit in the repository.

A capture *run* only has to be re-derivable and labelled. It records the
conditions that produced it so a person can rebuild an equivalent fixture when
an image updates, re-verify it against the oracle, and commit the replacement.
Nothing needs a byte-identical rerun, which is what lets the fixture source be a
server we do not control.

The high-order bit is exercising the decoders with many values in a way that is
reproducible and debuggable. Everything below serves that; where a choice made
the matrix bigger without making a decoder better exercised, it was cut.

## The scene-app

`tests/servers/scene_app.py`: a fullscreen X client using `python3-xlib`, no
toolkit and no fonts. It composes each scene into an in-memory RGB buffer and
pushes it with `XPutImage`, so what reaches the X framebuffer is a buffer we
hold rather than the outcome of a rendering stack. It replaces
`draw-content.sh` in the `tigervnc` and `x11vnc` images;
`libvncserver-example` has no X server and stays out of golden capture.

Keys select behaviour. There is no step counter and no notion of "next", so a
dropped or mistranslated keysym cannot silently shift every later fixture into
the wrong label — the c2s stream names the scene that was asked for.

| Key | Draws | Exercises |
|---|---|---|
| `0` | reset to a known base screen | isolation between cases |
| `s` | large solid fill | RRE fill path, ZRLE single-colour palette |
| `d` | dense pseudo-random detail | raw-tile fallback, worst-case bandwidth |
| `x` | many small scattered rects | many-rectangle updates, decode ordering |
| `g` | smooth gradient | quantization under reduced-depth formats |
| `p` | 2, 4 and 16-colour regions | ZRLE packed-palette branches |
| `c` | scroll a region by N pixels | CopyRect, if the server emits one |
| `f` | full-screen repaint | single large rect, encoder size chunking |

Keys stay plain lowercase letters and digits. The key classes with server
translation quirks are the subject of the KEYMAP issues, and the scene driver
must not depend on the thing under investigation elsewhere.

Scenes are not stateless and should not be: an update is a delta against
whatever was on screen, so `d` after `s` and `d` after `x` are different wire
bytes, and CopyRect exists only because of prior content. `0` makes any case
reachable in isolation.

Each key also paints a small patch encoding the keysym actually received. It is
fontless, it costs one harmless rect, and it turns a dropped key into a wrong
patch rather than a mislabelled fixture. It is not merely a check: it is how
distillation labels a step at all, since the frame carries it and the c2s
stream cannot be aligned against s2c.

The base screen is non-black so the existing screenshot smoke tests, which only
assert that a capture is not flat, stay green.

Golden capture runs at **256x192**. Raw at 1024x768 is 3MB per full-screen
update, which the repository should not carry; at 256x192 it is 192KB, about
40KB gzipped. The fleet's normal geometry is unchanged — the golden entrypoint
sets its own.

## Driving

The scene is a `vncdo` script:

    key 0
    key s
    capture step-02-s.png
    key d
    capture step-03-d.png

`capture` forces a FramebufferUpdateRequest and blocks until the update
arrives, so each scene produces at least one update rather than being folded
into a neighbour's. The PNGs it writes are debug artifacts, never oracles: they
came out of our own decoder.

## Capture

`vnclog` unchanged, in one-shot mode, writing its existing archive. Three
things make it the right recorder rather than a new one:

- It already runs a full `VNCDoToolClient` as an observer on the s2c stream
  (`loggingproxy.py:190`), parsing rectangles and tallying the encoding the
  server really used. Rect-level slicing is a hook on an object that already
  does the work.
- The c2s stream is the conditions record. `SetPixelFormat`, `SetEncodings` and
  every scene key are in it verbatim, as the bytes the server received.
- The archive already carries `session.vdo`, so the recipe travels with the
  capture, and `vncdo-replay --server` can serve those exact bytes back at a
  real viewer when a golden fails.

Auth stripping is irrelevant here: golden capture targets no-auth servers.

## Distillation

`tests/goldens/distill.py` feeds `s2c.bin` into a `VNCDoToolClient` subclass on
a `NullTransport`, recording each FramebufferUpdate's raw bytes and the
encoding actually used. It adds no wire parser and starts no reactor.

Steps are cut on FramebufferUpdate framing and labelled by the keysym patch
decoded from each frame. The c2s key events cannot do the cutting: the archive
stores the two directions as separate members with no interleaving, so a c2s
offset locates nothing in s2c. The patch travels *in* the frame, which is the
property that makes it the label — and it also absorbs a server that answers
one key with two updates, since both frames carry the same patch.

## Fixture layout

A fixture is a whole capture session, not a single update:

    tests/unit/fixtures/goldens/tigervnc-raw-rgb888/
      init.bin.gz                            # ServerInit onward
      step-01-0.bin.gz   step-01-0.png
      step-02-s.bin.gz   step-02-s.png
      ...
      conditions.json

Session-level is the only granularity that can test R7, the decoder
architecture's strict-ordering requirement. ZRLE uses a single
zlib stream per connection, so rectangles must decode strictly in order across
updates; a fixture holding one update cannot exercise that, and neither can it
exercise CopyRect, which is a function of the previous framebuffer. It also
pushes far more pixels through the decoder per fixture.

Steps are separate files rather than offsets into one blob: ordering is the
filename, there is no offset format to version, and each step can be inspected
alone. `init.bin` is replayed first so the client initializes from the same
ServerInit the capture ran against.

Flat directory names, one level. At full build-out (below) there are fifteen of
them, and `ls goldens | grep zrle` should answer "what covers ZRLE" without
opening anything.

## conditions.json

Written by the harness from what happened, never from what was intended:
compose service and image digest, the server version string from ServerInit,
the negotiated PixelFormat fields, the encoding the server actually used,
geometry, the driving `.vdo`, vncdotool version, scene-app source hash, capture
date, and the source archive's filename. Per-channel comparison tolerance lives
here too — zero today, non-zero when reduced-depth formats land.

## Oracles

Ground truth is the buffer the scene-app pushed to X, saved as a PNG on a
shared volume by the drawing side. It is independent of our decoder and of our
reading of the specification.

At reduced depth the server quantizes, so a decoded frame will not equal that
buffer, and modelling the rounding ourselves would put our reading of the spec
back into the oracle. Two checks are used together, because they fail on
different things and share one capture run:

- **Source with tolerance.** Compare against the oracle allowing per-channel
  error bounded by the format's step. This bounds the server's rounding without
  modelling it, and still catches channel swaps, wrong shifts, endianness
  errors and colour-map misindexing — the whole defect class R3, decoder output
  not depending on the negotiated format, is about.
- **Cross-format self-consistency.** Decode the same scene at every format and
  assert the canonical outputs agree within tolerance. This is R3 stated
  directly, and needs no external truth, but a decoder wrong the same way at
  every depth passes it.

Both are deferred until a second format exists. Today's tolerance is zero.

## The unit test

`tests/unit/test_goldens.py` walks the fixture tree, one subtest per fixture:
replay `init.bin`, then each step in order, through one client on a mocked
transport, asserting the framebuffer against that step's oracle within the
recorded tolerance. No fleet, no network, no reactor.

Failure reports the fixture, the step and its key, the rect index, and the
first differing pixel with coordinates and both values, and writes the decoded
frame beside the expected one. When the bytes themselves are in doubt, the
source archive replays through `vncdo-replay --server`.

`make goldens` — bring the fleet up, run vnclog, drive the script, distill,
write fixtures — is a manual target. It never runs in CI; the committed
fixtures do.

## The matrix

Axes are crossed only where they interact.

- Raw x 4 pixel formats, 4 fixtures
- 5 further encodings x 32bpp, 5 fixtures
- ZRLE and Tight x the 3 non-default formats, 6 fixtures

Fifteen fixtures at full build-out, one today. Each carries every scene in the
catalogue, so the scene axis multiplies steps rather than fixtures.

The full cross is not needed. The pixel-format axis tests pixel plumbing, which
Raw exercises as well as anything; the scene axis tests rect logic, which one
format exercises as well as anything. The exception is CPIXEL: ZRLE and Tight
do not use the ordinary pixel layout, and CPIXEL's byte width depends on the
negotiated format (RFC 6143 §7.7.6). Testing them only at 32bpp exercises the
one case where CPIXEL and pixel coincide — and that is precisely where the
known ZRLE hardcoded-layout defect lives.

**Servers.** TigerVNC is primary. x11vnc is not a second copy of everything: it
is there because CoRRE comes only from x11vnc and Tight only from TigerVNC, per
the measured table in `decoder-architecture.md`, plus a small sanity subset
where its polling differ produces messier rect patterns than Xvnc's damage
tracking.

## Phasing

The scaffold lands at today's single pixel format and Raw alone. Every later
axis value is then a TDD entry point: extend the matrix, watch capture fail for
a missing feature, build the feature.

1. scene-app, golden geometry, fleet wiring. Proven by one functional test:
   pressing `s` changes the screen.
2. Distiller, fixture format, `make goldens`. Commit `tigervnc-raw-rgb888`.
3. `test_goldens.py` green against it.

Then: adding `rgb565` to the matrix fails for want of a flag, which builds
`vncdo --pixel-format`. Adding RRE fails for want of encoding selection, which
builds `--encodings` (decoder Phase 3). Each decoder phase adds its encoding
the same way.

## Deferred

Recorded so they are not rediscovered as new ideas.

- The **pnm-server** — a libvncserver example that declares its own rects — and
  the rect pathologies that need it (hundreds of tiny rects, mid-session
  resize).
- **Cross-format equality** and the **tolerance oracle**, both of which need a
  second format to exist.
- **CopyRect**, which appears only if Xvnc turns the scene-app's scroll into
  one. We find out by reading a capture, not by asserting it in advance.

## Risks

- x11vnc polls and coalesces, so one key may produce more than one update. The
  distiller records everything between key events rather than assuming one
  update, and the fixture keeps whatever arrived.
- The scene-app is stepped through the keyboard path, so a server that
  mishandles a plain letter stalls a capture. The keysym patch makes that
  visible in the bytes; if it ever becomes a real obstacle, the escape is a
  fifo poked by `docker exec`, at the cost of losing the c2s step boundaries.

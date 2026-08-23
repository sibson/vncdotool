# Decoder Golden Fixtures — Design

Status: scaffold built; Raw at 32bpp against tigervnc. Later matrix values are
TDD entry points, see Phasing. Builds the fixture half of
[testing-framework.md](testing-framework.md) Phase 2 and the capture half of
[decoder-architecture.md](decoder-architecture.md) Phase 0.

## Problem

Decoder goldens need wire bytes from a real server, produced by screen changes
we chose, verified against something that is not our own decoder. The fleet
offered none of the three: `draw-content.sh` painted once at start-up, nothing
could ask a server for a particular update, and the only image to compare
against was one our own decoder had produced.

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

## The scene player

`tests/goldens/scene_player.py`: a fullscreen X client using `python3-xlib`, no
toolkit and no fonts. A keypress selects one of the committed PNGs in the
adjacent `tests/goldens/scenes/` and it goes to the X framebuffer whole, via
`XPutImage`, so what the server sees is a file in the repository rather than
the outcome of a rendering stack. It replaces `draw-content.sh` in the
`tigervnc` and `x11vnc` images; `libvncserver-example` has no X server and
stays out of golden capture.

The scenes themselves are generated offline by `tests/goldens/scenes.py`'s own
`main()`, from the same pure functions the unit suite covers. Committing the
images rather than drawing them in the container is what lets the same file be
both what was displayed and what a golden is checked against.

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

Every scene image carries a small patch encoding its own key. It is fontless,
it costs one harmless rect, and it turns a dropped key into a wrong patch
rather than a mislabelled fixture. It is not merely a check: it is how
distillation labels a step at all, since the frame carries it and the c2s
stream cannot be aligned against s2c.

The base screen is non-black so the existing screenshot smoke tests, which only
assert that a capture is not flat, stay green.

The `tigervnc` service serves **256x192**. Raw at 1024x768 is 3MB per
full-screen update, which the repository should not carry; at 256x192 it is
192KB, about 40KB gzipped. Nothing else in the fleet needs a large desktop, so
this is the one service's geometry rather than a second service beside it.

## Driving

The scene is `tests/goldens/scene.vdo`, a committed `vncdo` script:

    key 0
    expect scenes/0.png 0
    key s
    expect scenes/s.png 0

`expect` polls with incremental FramebufferUpdateRequests until the screen
matches, so the driver waits on the scene arriving rather than on a duration.
The player repaints on its own X event loop, and a fixed delay would be both a
guess at how long that takes and, when wrong, a fixture labelled by the
previous image's patch. A scene that never arrives now fails the capture
naming the image it waited for.

It compares histograms rather than pixels, which is enough to sequence on; the
pixel-exact comparison is the golden test's job, against the same file.

## Capture

`vnclog` unchanged, in one-shot mode, writing its existing archive. Three
things make it the right recorder rather than a new one:

- It already runs a full `VNCDoToolClient` as an observer on the s2c stream
  (`VNCLoggingClient`), parsing rectangles and tallying the encoding the
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

Steps are cut where the keysym patch changes, not on FramebufferUpdate
framing: a driver polling for a scene draws empty updates in reply, and a
server may spread one scene over several. Every byte between two patches still
belongs to the step, so what a fixture replays is what was recorded.

The c2s key events cannot do the cutting: the archive stores the two
directions as separate members with no interleaving, so a c2s offset locates
nothing in s2c. The patch travels *in* the frame, which is what makes it the
label.

## Fixture layout

A fixture is a whole capture session, not a single update:

    tests/unit/fixtures/goldens/tigervnc-raw-bgrx8888/
      init.bin.gz          # ServerInit onward
      step-01-0.bin.gz     # the key names the scene, and so the oracle
      step-02-s.bin.gz
      ...
      conditions.json

A fixture holds no images. The step filename ends in the scene key, and the
oracle is `tests/goldens/scenes/<key>.png` — the same file the server was
shown, so there is nothing to keep in sync.

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

`--pixel-format` is required, so `pixel_format` always names a format rather
than recording "the server's own". Nothing on the wire would correct it — the
server never acknowledges `SetPixelFormat` — so a fixture that does not say
what it asked for cannot be replayed at the format its pixels are in.

Written by the harness from what happened, never from what was intended: the
compose service, the geometry, and vnclog's own `meta` — protocol version,
security types, the encodings the server actually used, and the capture
timestamp. Per-channel comparison tolerance
lives here too: zero today, non-zero when reduced-depth formats land.

The driving script is not copied in. `session.vdo` inside the capture archive
already is it, and a second copy is a second thing to keep true.

## Oracles

Ground truth is the committed PNG the scene player pushed to X. It is
independent of our decoder and of our reading of the specification, and it
needs no copying out of a container: the file the test compares against is the
file the server was shown.

At reduced depth the server quantizes, so a decoded frame will not equal that
image, and modelling the rounding ourselves would put our reading of the spec
back into the oracle. The comparison instead allows per-channel error bounded
by the format's step, which bounds the server's rounding without modelling it
and still catches channel swaps, wrong shifts, endianness errors and colour-map
misindexing — the whole defect class R3, the framebuffer not depending on the
negotiated format, is about. Every fixture is checked this way at the format it
was captured at, and that is where R3 is checked.

The tolerance waits on a reduced-depth format: every format captured so far is
32bpp truecolour, which is why it is zero.

**Cross-format self-consistency** — decode one scene at two formats, assert the
framebuffers agree — is not used, though it reads like R3 stated directly. It
cannot fail alone: every fixture is pinned to the PNG, so one member of a pair
equals the PNG exactly and comparing the other against it is the comparison
above at a looser bound. Reduced depth does not change that. The version with
independent power — quantize the PNG onto the reduced grid, demand exact
equality — is the rounding model this section rejects.

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

Fifteen fixtures at full build-out, four today. Each carries every scene in the
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

1. scene player, golden geometry, fleet wiring. Proven by one functional test:
   pressing `s` changes the screen.
2. Distiller, fixture format, `make goldens`. Commit `tigervnc-raw-bgrx8888`.
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
- The **tolerance oracle**, which needs a reduced-depth format to exist.
- **CopyRect**, which appears only if Xvnc turns the scene player's scroll into
  one. We find out by reading a capture, not by asserting it in advance.

## Risks

- x11vnc polls and coalesces, so one key may produce more than one update. The
  distiller records everything between key events rather than assuming one
  update, and the fixture keeps whatever arrived.
- The scene player is stepped through the keyboard path, so a server that
  mishandles a plain letter stalls a capture. The keysym patch makes that
  visible in the bytes; if it ever becomes a real obstacle, the escape is a
  fifo poked by `docker exec`, at the cost of losing the c2s step boundaries.

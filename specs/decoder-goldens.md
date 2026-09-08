# Decoder Golden Fixtures: Design

Status: scaffold built; Raw at 32bpp against tigervnc. Later matrix values are
TDD entry points, see Phasing. Builds the fixture half of
[testing-framework.md](testing-framework.md) Phase 2 and the capture half of
[decoder-architecture.md](decoder-architecture.md) Phase 0.

## Problem

Decoder goldens need wire bytes from a real server, produced by deliberately
chosen screen changes, and verified against something other than the decoder
itself. The fleet offered none of the three: `draw-content.sh` painted once at
start-up, nothing could ask a server for a particular update, and the only
image to compare against was one the decoder itself had produced.

## What reproducible means here

The committed fixture bytes are the reproducible artifact. They replay into the
decoder identically on any machine, with no fleet, no network and no reactor,
for as long as they sit in the repository.

A capture *run* only has to be re-derivable and labelled. It records the
conditions that produced it so a person can rebuild an equivalent fixture when
an image updates, re-verify it against the oracle, and commit the replacement.
Nothing needs a byte-identical rerun, which is what lets the fixture source be a
server outside vncdotool's control.

The high-order bit is exercising the decoders with many values in a way that is
reproducible and debuggable. Everything below serves that; where a choice made
the matrix bigger without making a decoder better exercised, it was cut.

## The scene player

`tests/goldens/scene_player.py`: a fullscreen X client using `python3-xlib`, no
toolkit and no fonts. A keypress selects one of the committed PNGs in the
adjacent `tests/goldens/scenes/` and it goes to the X framebuffer whole, via
`XPutImage`, so what the server sees is a file in the repository rather than
the outcome of a rendering stack. It runs in the `tigervnc`, `x11vnc` and
`wayvnc` images, the last through Xwayland. `libvncserver-example` has no X
server and stays out of golden capture.

The scenes themselves are generated offline by `tests/goldens/scenes.py`'s own
`main()`, from the same pure functions the unit suite covers. Committing the
images rather than drawing them in the container is what lets the same file be
both what was displayed and what a golden is checked against.

Keys select behaviour. There is no step counter and no notion of "next," so a
dropped or mistranslated keysym cannot silently shift every later fixture into
the wrong label: the c2s stream names the scene that was asked for.

| Key | Draws | Exercises |
|---|---|---|
| `0` | reset to a known base screen | isolation between cases |
| `s` | large solid fill | RRE fill path, ZRLE single-color palette |
| `d` | dense pseudo-random detail | raw-tile fallback, worst-case bandwidth |
| `x` | many small scattered rects | many-rectangle updates, decode ordering |
| `g` | smooth gradient | quantization under reduced-depth formats |
| `p` | 2, 4 and 16-color regions | ZRLE packed-palette branches |
| `c` | scroll a region by N pixels | CopyRect, if the server emits one |
| `f` | full-screen repaint | single large rect, encoder size chunking |

Keys stay plain lowercase letters and digits. The key classes with server
translation quirks are the subject of the KEYMAP issues, and the scene driver
must not depend on the thing under investigation elsewhere.

Scenes are not stateless and should not be: an update is a delta against
whatever was on screen, so `d` after `s` and `d` after `x` are different wire
bytes, and CopyRect exists only because of prior content. `0` makes any case
reachable in isolation.

Every scene image carries a small patch naming its own key. It costs one
harmless rect, and it turns a dropped key into a wrong patch rather than a
mislabelled fixture. It is not merely a check: it is how distillation labels a
step at all, since the frame carries it and the c2s stream cannot be aligned
against s2c.

The patch is the key's glyph, drawn from a 5x7 table in `scenes.py` at four
pixels a cell, black on white, in a 26x34 box at the center of the frame.
`read_patch` samples one pixel per cell, thresholds it, and matches the
bitmap against the table whole: a frame either carries a glyph or does not,
with no tolerance anywhere.

The table is literal rather than rendered because Pillow's default font is an
implementation detail that has changed shape across releases, and a fixture
labelled by a rendered glyph would be invalidated by an upgrade. The glyphs
are the uppercase forms (5x7 lowercase needs descenders for `g` and `p`),
so the player folds an incoming keysym to lower case and `C` and `c` select
the same scene.

Black and white are what make this hold at any depth. They are every
channel's extremes, and a pixel format reproduces its extremes exactly
however few bits it keeps, so the patch reaches the client unquantized at
rgb565 as much as at rgbx8888. The earlier patch instead carried the key as
`ord(key)` in the red channel, which assumed an 8-bit red without saying so:
at rgb565 `c`, `d`, `f` and `g` (99, 100, 102 and 103) landed on one 5-bit
value, and a step could only be narrowed to a set of keys and then guessed at
by which scene the frame most resembled.

The base screen is non-black so the existing screenshot smoke tests, which only
assert that a capture is not flat, stay green.

The `tigervnc` service serves **256x192**. Raw at 1024x768 is 3 MB per
full-screen update, which the repository should not carry; at 256x192 it is
192 KB, about 40 KB gzipped. Nothing else in the fleet needs a large desktop, so
this is the one service's geometry rather than a second service beside it.

## Driving

The scene is `tests/goldens/scene.vdo`, a committed `vncdo` script:

    key 0
    expect scenes/0.png
    key s
    expect scenes/s.png

`expect` polls with incremental FramebufferUpdateRequests until the screen
matches, so the driver waits on the scene arriving rather than on a duration.
The player repaints on its own X event loop, and a fixed delay would be both a
guess at how long that takes and, when wrong, a fixture labelled by the
previous image's patch. A scene that never arrives now fails the capture
naming the image it waited for.

It compares histograms rather than pixels, which is enough to sequence on; the
pixel-exact comparison is the golden test's job, against the same file.

At a reduced depth that histogram can never equal the scene PNG's, so `expect`
also matches when every pixel is within the negotiated format's per-channel
tolerance. `client.py` reads the tolerance off `self.pixel_format`, so nothing
is written down in `scene.vdo` and every `expect` in the wild gains the same
fix: at 8 bits per channel the tolerance is zero and the new condition is
exact equality, which the old one already implied.

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
oracle is `tests/goldens/scenes/<key>.png`, the same file the server was
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
than recording "the server's own." Nothing on the wire would correct it: the
server never acknowledges `SetPixelFormat`, so a fixture that does not say
what it asked for cannot be replayed at the format its pixels are in.

Written by the harness from what happened, never from what was intended: the
compose service, the geometry, and vnclog's own `meta` (protocol version,
security types, the encodings the server actually used, and the capture
timestamp). The comparison tolerance lives here too, as the three per-channel
bounds `pixelformat.channel_tolerance` computes from the requested format:
`[0, 0, 0]` at 32bpp, `[7, 3, 7]` at rgb565.

The driving script is not copied in. `session.vdo` inside the capture archive
already is it, and a second copy is a second thing to keep true.

## Oracles

Ground truth is the committed PNG the scene player pushed to X. It is
independent of the decoder under test and of any reading of the specification,
and it needs no copying out of a container: the file the test compares against
is the file the server was shown.

At reduced depth the server quantizes, so a decoded frame does not equal that
image, and modelling the rounding independently would put a particular reading
of the spec back into the oracle. The comparison instead allows per-channel
error bounded by the format's step, which bounds the server's rounding without
modelling it and still catches channel swaps, wrong shifts, endianness errors
and color-map misindexing: the whole defect class R3, the framebuffer not
depending on the negotiated format, is about. Every fixture is checked this way at the format it
was captured at, and that is where R3 is checked.

The bound is `pixelformat.channel_tolerance`, and it falls out of the format
rather than being tuned per fixture: a channel of *n* bits reaches only every
2**(8-n)th 8-bit value, so an 8-bit value sits at most `255 >> n` short of one
the channel can reach. It is per channel, not one number, because rgb565's
6-bit green permits half the error its 5-bit red and blue do, and a single
scalar of 7 would accept twice the green error the format can produce.

The one place the tolerance is computed is `pixelformat.py`. `capture.py`
records it, `test_goldens.py` compares within it, and the scene driver and
distiller below use the same call, so no fixture carries a number someone
chose.

**A lossy encoding breaks that derivation, and says so in the fixture.** A
Tight rectangle captured with `--jpeg-quality` is JPEG, whose error has
nothing to do with the format's quantization step and is much the larger of
the two at 32bpp, where the step is zero. Widening `channel_tolerance` to
accommodate it would loosen every other fixture at the same time and destroy
the property that the number falls out of the format, so the two are separate
fields: `tolerance_kind` is `format-quantization` or `jpeg-lossy`, and
`test_goldens.py` requires one of them and re-derives the first from the
format, so a chosen number cannot be filed under the computed one.

The lossy bound is not a per-channel triple at all. Nothing in the wire format
implies one, and a per-channel maximum stops separating a correct frame from a
wrong one as soon as the quality drops: at level 5 the correct scene sits 229
away while the nearest wrong scene sits at 180. A `jpeg-lossy` fixture records
a fuzz and a blur instead: the perceived-difference bound of
[expect-matching.md](expect-matching.md), which holds from level 9 to level 0,
and `test_goldens.py` reads whichever pair of numbers the kind calls for.

The recorded fuzz is measured from the capture itself: the furthest any of its
own frames landed from its scene, plus a margin of 4 for the decode drifting
under another libjpeg. It is deliberately not the bound the driver ran under,
which has to be wide enough for the worst quality level anyone captures and so
asserts almost nothing about the frames in front of it. Level 9 records 6 and
level 5 records 19, against the 64 they were driven at.

A measured bound could still be one that nothing can fail, so it is checked by
mutation rather than asserted: swapping red and blue in the JPEG path fails the
level-9 fixture at 72 against its 6 and the level-5 fixture at 56 against its
19.

The quality level is recorded too, because how far a frame may sit from its
oracle depends on it: at level 9 the worst frame is 1 from its scene, at level
5 it is 14, at level 0 it is 46, against a nearest wrong scene of 87.

The keysym patch keeps a per-channel triple, which is a different question:
whether a flat 48x48 block still reads back as the value that was stamped on
it. It does, at every quality level tigervnc offers.

**Cross-format self-consistency** (decode one scene at two formats, assert the
framebuffers agree) is not used, though it reads like R3 stated directly. It
cannot fail alone: every fixture is pinned to the PNG, so one member of a pair
equals the PNG exactly and comparing the other against it is the comparison
described earlier at a looser bound. Reduced depth does not change that. The
version with independent power (quantize the PNG onto the reduced grid, demand
exact equality) is the rounding model this section rejects.

## The unit test

`tests/unit/test_goldens.py` walks the fixture tree, one subtest per fixture:
replay `init.bin`, then each step in order, through one client on a mocked
transport, asserting the framebuffer against that step's oracle within the
recorded tolerance. No fleet, no network, no reactor.

Failure reports the fixture, the step and its key, the rect index, and the
first differing pixel with coordinates and both values, and writes the decoded
frame beside the expected one. When the bytes themselves are in doubt, the
source archive replays through `vncdo-replay --server`.

`make goldens` (bring the fleet up, run vnclog, drive the script, distill,
write fixtures) is a manual target. It never runs in CI; the committed
fixtures do.

## The matrix

Axes are crossed only where they interact.

- Raw x 4 pixel formats, 4 fixtures
- 5 further encodings x 32bpp, 5 fixtures
- ZRLE and Tight x the 3 non-default formats, 6 fixtures
- Tight x JPEG quality levels 9 and 5, 2 fixtures: level 9 is the only quality
  tigervnc encodes without chroma subsampling, so level 5 is what exercises a
  genuinely lossy encoding

Seventeen fixtures at full build-out, twelve today. Each carries every scene in the
catalogue, so the scene axis multiplies steps rather than fixtures.

The full cross is not needed. The pixel-format axis tests pixel plumbing, which
Raw exercises as well as anything; the scene axis tests rect logic, which one
format exercises as well as anything. The exception is CPIXEL: ZRLE and Tight
do not use the ordinary pixel layout, and CPIXEL's byte width depends on the
negotiated format (RFC 6143 §7.7.6). Testing them only at 32bpp exercises the
one case where CPIXEL and pixel coincide, and that is precisely where the
known ZRLE hardcoded-layout defect lives.

**Servers.** TigerVNC is primary. x11vnc is not a second copy of everything: it
is there because it is the only server in the fleet that emits CoRRE, plus a
small sanity subset where its polling differ produces messier rect patterns than
Xvnc's damage tracking. `x11vnc-corre-bgrx8888` is the only fixture in the tree
holding real CoRRE rectangles.

x11vnc paints the X cursor into the framebuffer unless the client asks for the
Cursor pseudo-encoding, and at the scene geometry the pointer rests on the
scene rather than beside it. Its capture therefore runs `--nocursor`, which
puts a cursor rectangle in the fixture that a replaying client has to discard
the same way: `conditions.json` records `nocursor` for that, alongside the
pixel format and the JPEG quality, and for the same reason.

wayvnc displays the scenes too -- Debian's sway spawns Xwayland on the first X
connection, so the same X scene player reaches a wlroots framebuffer, and
`seat seat0 hide_cursor` keeps sway's own pointer out of the capture. It is not
a golden source yet: `vnclog` reaches its upstream through
`command.add_standard_options`, which carries no TLS options, and wayvnc offers
VeNCrypt and nothing else. The live encoding and pixel-format grids in
`tests/functional/` drive it directly and do cover it. neatvnc, behind it,
implements Raw, ZRLE and Tight and answers every other request with Raw, so
three of the seven encodings the grid offers are its own and the rest exercise
the fallback.

Which encoding a server really used is read off `vncdo -v -v`, which names the
encoding of every rectangle it receives.

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

- The **pnm-server** (a libvncserver example that declares its own rects) and
  the rect pathologies that need it (hundreds of tiny rects, mid-session
  resize).
- **CopyRect**, which appears only if Xvnc turns the scene player's scroll into
  one. That is found out by reading a capture, not by asserting it in advance.
- **One large, complex scene**, on a service serving more than 256x192. Every
  scene here is small and synthetic, so none of them says whether a photograph
  at a desktop size decodes correctly, and encoders choose differently at that
  size. The cost is the reason it is deferred rather than done: fixture size
  scales with area, so the 3.1 MB of committed goldens becomes about 12 MB at
  512x384 and 50 MB at 1024x768, against a 22 MB repository.

## Risks

- x11vnc polls and coalesces, so one key may produce more than one update. The
  distiller records everything between key events rather than assuming one
  update, and the fixture keeps whatever arrived.
- The scene player is stepped through the keyboard path, so a server that
  mishandles a plain letter stalls a capture. The keysym patch makes that
  visible in the bytes; if it ever becomes a real obstacle, the escape is a
  fifo poked by `docker exec`, at the cost of losing the c2s step boundaries.

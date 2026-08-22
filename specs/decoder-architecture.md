# Pluggable Decoders

`vncdotool/rfb.py` is 1229 lines and roughly half of it decodes encodings. Every
encoding we add makes that worse, and Tight is the one users ask for (#264).
This document proposes an architecture that moves decoders out of `rfb.py`,
makes each one testable, and lays out the order to build it in.

## Only Raw works today

`VNCDoToolClient.vncConnectionMade` offers the server `[RAW]` plus the pseudo-encodings, there is no
CLI flag to change that (#167, #168), and a server may only use an encoding the
client asked for. So CopyRect, RRE, CoRRE, Hextile and ZRLE are unreachable in
normal use. They are compiled, not run.

This shapes everything below:

- The migration is far lower risk than the file size suggests. Only Raw and the
  pseudo-encodings have behaviour worth preserving.
- Their known defects — CoRRE's missing `f` prefix and `sz`/`end` loop bound,
  CopyRect's docstring-only `copyRectangle` stub, ZRLE's hardcoded pixel layout
  — cost users nothing today and fixing them in isolation wins nothing. The win
  arrives only when an encoding becomes selectable.
- Therefore selectable encodings, not bug fixes, is the milestone that makes
  this work user-visible.

## The problem is not file size

Decoders are continuation-passing state machines. `expect(handler, size, *args)`
parks a callback until N bytes arrive, so a decoder needing bytes in several
steps splits across several methods and threads its state through every hop as
arguments. Hextile is six mutually recursive `_handleDecodeHextile*` methods
passing `(bg, color, x, y, width, height, tx, ty)` between them.

The consequence is that a decoder cannot be driven without an `RFBClient` and a
working `expect`, so nothing gets tested, so the unreachable code above rotted
undisturbed. Splitting the file without changing the interface preserves all of
that. The interface is the design decision; file layout follows.

## Requirements

Stated independently of how. Each design decision should trace to one.

**Functional**

- **R1** Adding an encoding touches new files plus one registry entry; `rfb.py`
  is unchanged. This is the motivating requirement.
- **R2** Every decoder is unit-testable with no reactor, no transport, no
  server, and no `RFBClient`.
- **R3** The framebuffer a client sees does not depend on the pixel format the
  server negotiated. Stated over the framebuffer rather than over decoder
  output, because decoders emit the layout they were sent and name it; the
  format-independence is the client's paste, and the goldens' cross-format
  comparison is what checks it. Servers that ignore `SetPixelFormat` cause #90
  and #275.
- **R4** The user can choose which encodings are offered (#167, #168). Without
  this, every encoding except Raw is dead code and none of it can be tested
  end-to-end.
- **R5** Raw and the pseudo-encodings — the only paths in live use — behave
  exactly as they do today. The other encodings are carried across as-is,
  bug-for-bug, with no claim that they work; they are not in use, so there is no
  behaviour to regress.
- **R6** Malformed, oversized or unsupported input produces a diagnosed error
  and a closed connection, never an indefinite wait and never an unhandled
  `MemoryError` (#322, #284, #262, #146).
- **R7** Per-connection decoder state is isolated per connection and reset on
  reconnect, and rectangles are decoded strictly in order. RFC 6143 §7.7.6: "A
  single zlib 'stream' object is used for a given RFB protocol connection, so
  that ZRLE rectangles must be encoded and decoded strictly in order." The
  ordering half permanently rules out decoding rectangles concurrently.

**Non-functional**

- **N1** Raw's render time does not regress, measured. Raw is the only valid
  before-and-after baseline, being the only encoding in use.
- **N2** Each encoding added after Raw demonstrates fewer bytes over the wire
  than Raw on the content class it is designed for, and no render-time
  regression against Raw on any content class. The qualifier is not a hedge:
  RRE expands on dense detail and only wins on flat regions, so a flat "beats
  Raw everywhere" bar would fail an encoding that is working exactly as
  specified. What must hold everywhere is the render-time half.

**Inherited constraints**

- **C1** No unit test starts the Twisted reactor (`CLAUDE.md`).
- **C2** Anything touching the wire is checked against RFC 6143 or rfbproto, not
  inferred from surrounding code (`CLAUDE.md`).
- **C3** `flake8 --count --statistics vncdotool tests` is clean.
- **C4** Every user-visible fix gets a `CHANGELOG.rst` entry under
  `(UNRELEASED)`.
- **C5** Functional tests fail loudly rather than skipping when the fleet is
  down.

R2 and C1 are one requirement from two directions: today the prohibition is
discipline, and R2 makes it structural.

## Decoders are generators

A decoder yields the number of bytes it wants and receives them back:

```python
class RawDecoder:
    def decode(self, target: RectBuffer, pf: PixelFormat) -> Iterator[int]:
        data = yield target.width * target.height * pf.bypp
        target.blit(0, 0, target.width, target.height, data)
```

`RFBClient` keeps one adapter — the pump — that drives the generator against
`expect`: send it bytes, take the yielded count, park with `expect`, repeat until
`StopIteration`.

Hextile and ZRLE become nested loops rather than callback chains. A unit test is
bytes in, buffer out: no Twisted, no transport, no reactor. The per-rectangle
cost is one generator plus a few `send()` calls, not per-pixel; Raw stays a
single yield.

Byte-starvation stops being a decoder concern entirely. The pump satisfies each
yielded count in full before resuming, so a decoder never observes a partial
buffer and cannot get segmentation wrong. That is a property of the pump, tested
once at the pump, not a per-decoder obligation.

Two alternatives rejected. Keeping continuation-passing and merely moving methods
into decoder classes is a file split dressed as an architecture: the tangle
survives and decoders still reach into `client.bypp`, `client._zlib_stream` and
`client._doConnection`. Handing a decoder the whole buffer and letting it raise
`NeedMoreData(n)` to be re-run works until zlib — ZRLE and Tight streams live for
the whole connection and cannot be replayed.

## Two decoder base classes

Not every encoding produces pixels. A decoder subclasses whichever of these
describes what it produces:

| Base class | Produces | Method it overrides | Encodings |
|---|---|---|---|
| `PixelDecoder` | fills a `RectBuffer` the pump allocates and pastes | `decodePixels` | Raw, RRE, CoRRE, Hextile, ZRLE, Tight |
| `ClientDecoder` | calls `copyRectangle` or `updateCursor` | `decodeForClient` | CopyRect, Cursor |

Both are nominal base classes under one `Decoder`, which defines both methods and
raises `NotImplementedError` for the one a given subclass does not use.
Structural typing cannot express this: the two take different arguments but
`Protocol` matching compares method names, so every `PixelDecoder` satisfies
`ClientDecoder` and the pump has to guess from the methods an object carries.

The pseudo-encodings — DesktopSize, LastRect, QEMU extended key — are still on
`rfb.py`'s own path and get their base class in phase 5, when there is a real one
to design against. They consume no payload, which is a difference in arguments
rather than in what they do to the client: DesktopSize resizes the framebuffer
much as CopyRect writes to it. Whether that earns a third base class or is just a
`ClientDecoder` whose generator returns without yielding is a question for the
phase that migrates them.

Each decoder class also names the encoding-type it decodes (RFC 6143 §7.6.1) as
`ENCODING`, and the registry is built from a list of classes rather than a
hand-written mapping, so a key cannot drift from the class it points at.

### Which pump path a decoder takes is resolved once per connection

`for_connection()` runs at connect time, so that is where each decoder is paired
with the pump path its base class implies. A rectangle then costs one dict lookup
and a call through a bound method — no `isinstance`, no probing for methods, and
no tag to keep in step with the class hierarchy.

Decoders depend on nothing from `rfb.py`: the pump keeps `_rectBuffer`,
`_pumpBlock` and `_doConnection` to itself, and the entry points that use them —
`_pumpPixels` and `_pumpForClient` — live with the pump rather than on the
decoder.

There is no separate sink object. The pump calls the existing client callbacks —
`updateRectangle`, `copyRectangle`, `updateCursor` — which is the vocabulary the
codebase already uses.

CopyRect reads four bytes and no pixel data; it is a framebuffer-to-framebuffer
blit needing the screen, not a rect buffer. Cursor produces an image and a mask,
not a framebuffer rectangle. Collapsing either into "fills a buffer" would mean
inventing a fake buffer or reading the framebuffer back.

Cursor is otherwise an ordinary decoder. Its payload is `width * height` pixel
values followed by a bitmask of left-to-right, top-to-bottom scanlines, each
padded to a whole number of bytes — `floor((width + 7) / 8)` — with the most
significant bit of each byte representing the leftmost pixel and a 1-bit meaning
the corresponding cursor pixel is valid.

The genuine special cases are the pseudo-encodings phase 5 migrates: `LastRect`
mutates the rectangle loop counter, and the QEMU extended key encoding mutates
`negotiated_encodings` and removes the entry it just appended to `rectanglePos`.

## Pixel format is shared, not per-decoder

Almost nothing about pixel format varies between decoders, so it lives once in
`vncdotool/pixelformat.py`: the negotiated PIXEL width and its Pillow raw mode,
CPIXEL's three-byte rule and its two placements (RFC 6143 §7.7.5), TPIXEL's
narrower and differently-ordered one (rfbproto §Tight), and colour-map
indirection. [pixel-format.md](pixel-format.md) is the design.

ZRLE's `cpixel()` in `rfb.py` gets both CPIXEL cases wrong in one line: `next(i), next(i),
next(i)` implements the low placement, silently mis-decodes the high one, and
appends a fabricated fourth byte.

What varies per decoder is pixel *layout in the stream* — palettes, RLE runs,
subrect coordinates. That is decoding, not formatting.

### Decoders emit the bytes they were sent, and say what they are

A decoder returns pixel bytes in whatever layout it produced them, tagged with
the `PixelFormat` that describes it. `client.py` resolves that to a Pillow raw
mode and materializes each rectangle with one `Image.frombytes(..., "raw",
mode)`. Most decoders tag the negotiated format; Tight's JPEG and TPIXEL tag
24 bpp RGB, a colour-mapped decoder tags the colour-mapped format.

The tag is a `PixelFormat`, not a Pillow mode string: decoders implement a
specification written in shifts and maxima, so Pillow stays in `client.py` and
in `pixelformat.raw_mode`, and a decoder unit test needs no rendering library
(R2).

So a decoder never interprets a pixel. A background colour, a Hextile
foreground, a ZRLE palette entry are opaque `bypp`-sized byte strings and a fill
is one repeated — no shifts, no masks, no endianness, so that class of bug
cannot be written. `client.PF2IM` goes with it: a computed raw
mode covers every layout Pillow can unpack, which is the bound this accepts.

[pixel-format.md](pixel-format.md) has the module, the coverage, and what
happens for a layout Pillow cannot unpack. Pixel format still comes early in the
build order: every decoder's output contract depends on it.

Cursor keeps its `(image, mask)` shape rather than folding the mask into alpha.
Folding would move bit-unpacking and interleaving into the decoder to save
`client.py` one attribute.

## One paste per rectangle

Decoders fill a rect-sized buffer and the pump makes a single `updateRectangle`
call, rather than one call per tile.

Today each tile becomes an `Image.frombytes` plus a `screen.paste`: for a
1920x1080 update that is roughly 8,100 PIL round-trips for Hextile's 16x16 tiles
and 510 for ZRLE's 64x64 tiles. Single paste makes both one. The replacement cost
is stride arithmetic concentrated in one shared helper:

```python
class RectBuffer:
    def blit(self, x, y, w, h, pixels) -> None: ...
    def fill(self, x, y, w, h, color) -> None: ...
```

The readability gain is larger than the code saved. **Decoders stop seeing screen
coordinates.** ZRLE's tile walk currently carries `tx`/`ty` in absolute screen
space and wraps with `tx += 64; if tx >= x + width: tx = x; ty += 64`; every tile
decoder repeats a variant and each is its own off-by-one opportunity. Against a
rect buffer the coordinates are rect-local and only the pump knows where the
rectangle lands.

Tests improve correspondingly: one expected byte array replaces an ordered log of
callbacks with absolute coordinates, which is a test that breaks when tile
iteration order changes even though the rendered result is identical.

The buffer is `w*h*bypp` — 8.3MB for full-screen 1080p at the 32 bpp every
measured server sends — and is sized from
server-declared dimensions, so the pump validates those against
`MAX_DESKTOP_SIZE` before allocating. That is R6, not a separate concern: an
unhandled `MemoryError` is as undiagnosed a failure as an indefinite wait. The
pump owns the buffer and reuses a high-water-mark allocation across rectangles;
the client must not retain it, which `Image.frombytes` satisfies by copying.

Nothing paints until a rectangle completes. vncdotool has no live viewer, so this
costs nothing today.

## Errors, not hangs

The protocol layer's response to malformed data is to wait forever (#322, #284,
#262, #146). The pump gives one place to catch a `DecodeError` and turn it into a
diagnosed disconnect. This is a larger user-facing win than the split itself.

## Module layout

```
vncdotool/pixelformat.py         PixelFormat, its Pillow raw mode, CPIXEL/TPIXEL widths
vncdotool/decoders/__init__.py   registry, built from the decoder classes
vncdotool/decoders/base.py       Decoder, PixelDecoder, ClientDecoder
vncdotool/decoders/buffer.py     RectBuffer
vncdotool/decoders/errors.py     DecodeError
vncdotool/decoders/{raw,rre,corre,hextile,zrle,cursor}.py
vncdotool/decoders/control.py    DesktopSize, LastRect, QEMU extended key
vncdotool/rfb.py                 negotiation, auth, message framing, the pump
```

`SUPPORTED_ENCODINGS` stops being the set literal in `RFBClient` and derives
from the registry, filterable per connection, which is R4. It is also what makes
R1's zero-line `rfb.py` diff possible. Registering an encoding means adding a
module beside the other decoders and naming its class in the list that
`decoders/__init__.py` builds `DECODERS` from; nothing tells `rfb.py` the
encoding exists.

Third-party decoder plugins via entry points are out of scope. Nobody ships
out-of-tree VNC encodings; the registry is a dict.

## Subclass compatibility: find out before deciding

`api.connect(..., factory_class=...)` and `RFBFactory.protocol` are a supported
extension point, so `CustomClient(VNCDoToolClient)` subclasses *may* exist. We
have no evidence that any do. Building compatibility machinery for a population
we cannot observe is speculative, and so is breaking it silently.

Two hooks change:

- `updateRectangle` gains the raw mode its bytes are in, and is called once per
  rectangle instead of once per tile. The bytes stay in the server's format for
  every encoding in use today, so a subclass that reads them with the session's
  format still reads them correctly; what changes is that the format now
  travels with the data rather than being assumed.
- `fillRectangle` stops being called, because decoders fill a rect buffer
  instead. Its docstring actively invites overriding it "for better
  performance", so a subclass that did so silently stops being invoked.

`copyRectangle`, `updateCursor` and the remaining hooks are unaffected. Anything
named `_handleDecode*` is private and disappears without replacement.

So Phase -1 ships a **survey, not a deprecation**, and ships it publicly before
anything else changes. At that point nothing has changed yet, so the warning
cannot say a method is no longer called — it says the contract will change, and
asks the reader to say so on a tracking issue:

```python
_CHANGING_HOOKS = ("fillRectangle", "updateRectangle")

def __init_subclass__(cls, **kwargs) -> None:
    super().__init_subclass__(**kwargs)
    for name in _CHANGING_HOOKS:
        if not getattr(cls, name).__module__.startswith("vncdotool."):
            warnings.warn(f"...will change in a future release; please comment "
                          f"on <issue url> if you rely on it", FutureWarning,
                          stacklevel=2)
```

Testing `__module__` rather than comparing against `RFBClient.<method>` keeps our
own subclasses quiet — `VNCDoToolClient` overrides `updateRectangle` and
`updateCursor`, and `loggingproxy` subclasses that in turn — with no allowlist to
maintain. Only the two changing hooks are listed: warning on unaffected ones
trains users to filter the category wholesale. The category is `FutureWarning`,
not `DeprecationWarning`, because the latter is hidden by default outside
`__main__`, which would leave a mechanism that looks implemented and does
nothing. `FutureWarning` is not in the default filter list either, so it falls
through to the `default` action and prints once per source location rather than
once per call.

Class-definition time beats connect time: it fires for a subclass that is never
connected, and `stacklevel` points at the definition. A decorator on the base
method cannot work, since an overridden method means the base is never invoked —
which is the failure mode being detected.

`self.image_mode` is the one break `__init_subclass__` cannot see, since reading
an attribute overrides nothing. It becomes a property that warns on access and
returns the mode the negotiated format resolves to, which stays truthful under
the new design for as long as one session has one format; `setImageMode` becomes
a warning no-op.

**This machinery is temporary.** Once the contracts have actually changed the
warnings are false, and they are removed. If the survey turns up nobody, they are
removed having cost one release. If it turns up someone, we have a named user to
design compatibility with rather than a hypothetical one.

## Build order

**Phase -1 — survey release.** The `__init_subclass__` warning, the `image_mode`
property, and a tracking issue. No other change. Ship it and wait.
*Done when:* released publicly and enough time has passed to hear from users.
This is the only phase whose completion is measured in elapsed time rather than
code, and the only one that gates on information we do not have.

**Phase 0 — capture tooling and harness.** A `DecoderTestCase` driving a decoder
with no reactor, and the capture tooling described under Testing. Discharges R2,
C1.

**Phase 1 — pixel format.** `pixelformat.py`: a negotiated format resolved to a
Pillow raw mode, both CPIXEL placements, TPIXEL's narrower rule, and the
`--pixel-format` flag that makes a second format reachable. `PF2IM` removed.
Designed in [pixel-format.md](pixel-format.md).
*Done when:* the same scene, captured at two negotiated formats, decodes to the
same framebuffer within the reduced format's quantization. Discharges R3 for
those two; colour map and the formats Pillow cannot unpack follow with the
servers that need them. This comes before any decoder migrates so no decoder is
written twice.

**Phase 2 — pump, Raw, CopyRect.** The pump lands with `DecodeError` handling and
`MAX_DESKTOP_SIZE` validation. Raw and CopyRect move; everything else stays on
the existing path behind the registry.
*Done when:* the functional suite is green, the pump's segmentation test passes,
and Raw has a recorded render-time baseline. Discharges R6, R7, N1; establishes
R1's shape.

**Phase 3 — selectable encodings, proven on the two simplest.** `--encodings`
lands, and RRE and CoRRE are migrated and verified end-to-end against the fleet.
They are the simplest decoders we have — a subrectangle count, a background
pixel, then a flat list of coloured subrectangles — and CoRRE is RRE with U8
coordinates in place of U16, so the pair shares almost all its code. That makes
them the cheapest possible second exercise of the registry path, which is the
point: prove the architecture before investing in a hard decoder.

This phase is an architecture proof, not a user win. RRE and CoRRE are rarely
any server's preferred encoding and their bandwidth advantage is narrow. The
user-visible payoff starts at Phase 4.

The encoding probe lands here too, as a loop over the new flag, filling in the
UltraVNC and Screen Sharing columns of the support table above. Whether it stays
in CI or runs once and leaves its results in that table is the same question the
pixel-format probe answered by leaving: a measurement that only moves when a
runner image does is a record, not a test.

*Done when:* both render identically to Raw against every fleet server that
supports them, and `--encodings` can select them. Discharges R4.

**Phase 4 — Hextile.** The first phase with a user-visible result: Hextile is
near-universally supported and wins substantially on real screen content.
*Done when:* it renders identically to Raw against every fleet server and meets
N2.

**Phase 5 — ZRLE, Cursor, and the control encodings.** ZRLE carries the largest
bandwidth win and the CPIXEL defect we now understand precisely, which is why it
comes after the architecture is proven rather than before. Its fix happens here,
as part of proving the encoding rather than as a standalone repair to
unreachable code.
*Done when:* no `_handleDecode*` remains in `rfb.py` and every migrated encoding
meets N2. Discharges R5.

**Phase 6 — Tight.** A new encoding as new files plus tests.
*Done when:* it is added with a zero-line diff to `rfb.py`. The one line that
registers it goes in `decoders/__init__.py`, and `Encoding.TIGHT` already exists
in `const.py`, so `rfb.py` and `const.py` are both untouched. That is the test of
R1: today the same change edits `RFBClient.SUPPORTED_ENCODINGS`, and if it still
does, the architecture did not deliver what it exists for.
`libvncserver-example` falls back to Raw when asked for Tight, so its oracle
comes from `tigervnc` and `x11vnc`.

TRLE is **not** in this plan. No server in the fleet emits it (see Fleet
encoding support), so under the captured-fixture rule it cannot be tested at
all. Building it would mean either adding a server that speaks it or
hand-assembling fixtures from the specification, which is the practice this
design rejects. Revisit only if a real user asks for it, and then start by
finding a server that emits it.

Phase -1 can ship immediately and runs concurrently with Phases 0 and 1, which
touch no client callback. It must land publicly before Phase 2, which is where
`updateRectangle`'s contract first changes.

## Fleet encoding support

Because fixtures must come from a real server, an encoding no fleet server emits
cannot be tested, and therefore cannot be built. Measured by offering each server
exactly one encoding and reading back the encoding it actually used:

| Encoding | tigervnc | x11vnc | libvncserver-example | ultravnc | screen-sharing |
|---|---|---|---|---|---|
| RRE | yes | yes | yes | ? | ? |
| CoRRE | no [1] | yes [1] | yes | ? | ? |
| Hextile | yes | yes | yes | ? | ? |
| ZRLE | yes | yes | yes | ? | ? |
| Tight | yes | no | — see below | ? | ? |
| TRLE | no | no | no | ? | ? |

A "no" means the server answered a request for that encoding with Raw.

[1] Measured 2026-08-22 against `tigervnc-standalone-server 1.12.0+dfsg-8`
(Debian bookworm, the fleet image) with a socket-level RFB 3.8 probe that
offered CoRRE and nothing else, then asked for the full screen and three
sub-regions: every rectangle came back Raw. The same probe against x11vnc
returned CoRRE, so it can see a CoRRE rectangle when one arrives, and offering
RRE alone to tigervnc returned RRE, so tigervnc is not answering everything
with Raw. Upstream agrees: `EncodeManager::supported()` in TigerVNC 1.12.0
(`common/rfb/EncodeManager.cxx`) accepts Raw, RRE, Hextile, ZRLE and Tight and
nothing else. Every other cell predates this pass and remains uncited.

**The two Tier 2 columns are unmeasured**, and they are the servers users run.
That matters most for Tight, the encoding this whole document exists for (#264):
UltraVNC is the likeliest server in the fleet to speak it, and nothing here
knows whether it does. Both already authenticate in CI (`os-servers.yml`), so
the probe is what is missing, not access.

Read these asymmetrically. A "yes" is proof: the server really emitted that
encoding. A "no" is strong evidence but not certainty, because servers choose
per-rectangle and the probe reads only the first rectangle of a full-screen
update — a server could in principle pick Raw for that one rectangle while
supporting the encoding elsewhere. Do not delete an encoding on a "no" alone.
The tigervnc CoRRE "no" is the exception: [1] read four separate updates and
found upstream source saying the same thing.

Consequences already folded into the build order: RRE is universal, so Phase 3
is safe; CoRRE survives on two of three servers, TigerVNC having dropped it;
Hextile and ZRLE are universal; TRLE is emitted by nothing and is therefore out
of scope entirely.

The probe is not in the repository — the table came from a throwaway that no
longer exists, which is why two columns are blank. Building it waits for Phase 3
rather than being Phase 0 tooling: `--encodings` lands there, so the probe is
then a loop over a flag instead of a script reaching into `client.encoding`, and
Phase 3 is also the first phase whose scope the missing columns could change.
Until then the matrix is three servers nobody runs, and it drifts as their
images update.

## Testing

Fixtures are **captured from real servers**, never hand-assembled from the
specification. Hand-built bytes encode our reading of the spec, so a
misunderstanding produces a fixture and a decoder that agree with each other and
with nothing else — the test then pins the misunderstanding. This is the same
trap as reading goldens off the implementation.

**Capture tooling (Phase 0), built.** `loggingproxy.py` sits between client and
server at the byte level, which is the right place to record, and `vnclog
--capture-raw` is the recorder. A scene player pushes committed PNGs to a fleet
server's X framebuffer on keypress; the capture is distilled into per-step
fixtures under `tests/unit/fixtures/goldens/`.

**The oracle is the committed PNG the server was shown**, not a Raw replay. An
earlier revision proposed replaying each script with Raw negotiated and treating
that render as ground truth, which makes the oracle a second capture — subject
to the same server, the same session, and its own decode. Comparing against the
file that was displayed removes the server from the oracle entirely, and there
is nothing to keep in sync because the fixture names the scene and the scene is
the file. [decoder-goldens.md](decoder-goldens.md) has the scene source, the
capture path, the fixture format and the matrix.

**Tier 1 — unit, offline.** Captured wire bytes into the decoder, compare the
resulting framebuffer against the scene PNG. Fast, no fleet, no reactor. The
comparison is on the framebuffer after the client's paste, which is what makes
it hold across captures from servers that negotiated different formats.

**Tier 2 — live, against the fleet.** Force `--encodings` to one encoding, drive
the same scene script, compare the captured screen to the same PNGs. Catches
everything the capture missed: negotiation, ordering, zlib stream continuity
across rectangles.

**Tier 3 — screen-change stress.** Fixtures are only as good as the screen
changes that produced them, and a decoder that passes Tier 1 and Tier 2 on a
blank-ish screen has been barely tested. The scene catalogue in
[decoder-goldens.md](decoder-goldens.md) is this tier: solid fills for RRE and
ZRLE's single-colour palette, dense detail for raw-tile fallback, scattered
rects for ordering and R7's stream continuity, a scrolled region for CopyRect —
the one encoding whose correctness depends on prior framebuffer contents.

Mid-session desktop resize is the case the catalogue cannot reach, since the
scene player cannot make a server change geometry; it is deferred there with the
libvncserver example that could.

**Segmentation.** One test at the pump feeding a capture one byte at a time and
asserting identical output. Because the pump satisfies every yielded byte count
in full, this is a property of the pump and does not need repeating per decoder.

## Benchmark

Two distinct measurements, because only Raw has a past to regress against.

**Raw, before and after (N1).** Decode a captured Raw frame N times with no
Twisted in the loop, recorded before Phase 2 and after. This is the only
regression test the migration can have.

**Each new encoding (N2).** Two numbers against Raw on identical screen content:
bytes over the wire, which should drop substantially, and render time, which must
not regress. The bandwidth number is the reason users want these encodings; the
render-time number is what stops us shipping one that trades their bandwidth for
their latency.

Single paste is expected to help, but that expectation is arithmetic — 8,100 PIL
round-trips becoming one — not measurement. Readability and testability justify
the change on their own; if the benchmark comes back flat we should know it from
a number.

## Protocol validation

C2 requires wire claims to come from the specifications rather than the
surrounding code.

**Verified against RFC 6143:** the CPIXEL rule and its two byte placements; the
single-zlib-stream-per-connection rule and the strict ordering it implies; ZRLE's
64x64 and TRLE's 16x16 tile sizes; the RRE subrectangle layout of a pixel value
followed by four U16 coordinates; ZRLE palette limits of 16 packed and 127
run-length.

**Verified against rfbproto:** the Cursor pseudo-encoding payload — pixel values
followed by a byte-padded, MSB-first scanline bitmask.

**Checked against the implementation while validating:** RRE parses
pixel-then-coordinates correctly (`_handleRRESubRectangles`) and the ZRLE run-length branch
already permits palettes to 127 (`subencoding & 127`). Neither needs changing;
the packed-palette cap of 16 is in the correct branch.

**Verified against rfbproto, since:** Tight's TPIXEL rule — narrower than
CPIXEL, fixed in red-green-blue order — and its four zlib streams; CPIXEL's
tie-break at depth ≤ 16, absent from RFC 6143; and that *bits-per-pixel* must be
8, 16 or 32. Detail in [pixel-format.md](pixel-format.md).

Per `DEVELOP.rst`, rfbproto is a living document with no releases, so any comment
or test depending on its wording cites a commit permalink rather than `master`.

## Deliberate non-goals

- No new encodings before Phase 6. Tight is the motivation, not the first step.
- No changes to authentication, negotiation, or transport.
- No fix for cursor compositing being destructive — `drawCursor` pastes into
  `self.screen` and nothing erases the previous position, so stale pointers
  persist where the server does not resend. Pre-existing, and the boundary
  between decoder and client is drawn so fixing it later touches no decoder.
- No fix for `VNCDoToolClient.updateCursor`, where a zero-width or zero-height cursor sets
  `self.cursor = None` and then falls through to `Image.frombytes` with a zero
  dimension instead of returning. Worth a separate issue; it is a client bug, not
  a decoder one.

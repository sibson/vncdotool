# Tight Encoding — Build Plan

Status: draft, under review. Executes
[decoder-architecture.md](decoder-architecture.md) Phase 6 and the Tight half of
[server-compatibility-plan.md](server-compatibility-plan.md) Phase 2.1. Closes
#264.

## What Phase 6 assumed, and what is actually missing

Phase 6 reads as "a new encoding as new files plus tests", with the registry
already able to carry it. Three things it does not account for turned up on
inspection:

- **TPIXEL does not exist.** Phase 1 delivered CPIXEL and its two placements
  (`pixelformat.cpixel_bytes`, `cpixel_offset`) and nothing else. Tight's
  narrower, fixed-order rule is unbuilt.
- **A decoder's output format is per-decoder, not per-rectangle.** The pump
  calls `decoder.output_format(self.pixel_format)` once per rectangle and sizes
  the `RectBuffer` from the *negotiated* format (`rfb._allocateBuffer`). Tight
  varies within one update: a JPEG rectangle is 24 bpp RGB whatever was
  negotiated, a basic rectangle is TPIXEL. At a 16 bpp negotiated format a JPEG
  rectangle wants more bytes than the buffer holds.
- **Fixtures need a decoder before the decoder can be tested.** Captured
  fixtures are the rule (`decoder-goldens.md`), and distillation drives a real
  client over the s2c stream, so a Tight capture cannot be distilled until Tight
  parses. `vnclog --capture-raw` breaks the cycle: raw bytes first, distilled
  fixtures once the decoder walks them.

## What the wire brief settled

[tight-wire.md](tight-wire.md) is the source, pinned to rfbproto
`152107db63cd34b3536ad8ddf54a0cfc9017a9f9` and cross-read against TigerVNC
1.16.2, TurboVNC 3.3.1 and LibVNCServer. Three findings changed this plan's
scope:

- **JPEG cannot appear in a capture.** rfbproto: with no JPEG quality level
  advertised, JpegCompression is not used. TigerVNC's
  `TightJPEGEncoder::isSupported()` and TurboVNC's `qualityLevel != -1` guards
  agree. Offering encoding 7 alone therefore yields no JPEG rectangle, ever.
- **Nothing emits the gradient filter.** Neither TigerVNC nor TurboVNC writes
  one, and the brief found a real spec ambiguity for non-888 formats that it
  could not settle precisely because no live encoder exists to settle it against.
- **There are four zlib streams and servers use them differently.** TigerVNC
  pins a stream id per rectangle type and never sets a reset bit; TurboVNC
  rotates round-robin. Maintaining only stream 0 passes against one and fails
  against the other.

RFC 6143 does not define Tight at all, so C2's "RFC 6143 or rfbproto" is
rfbproto alone here.

## Decisions

**JPEG is in scope, and Pillow decodes it inside the decoder**, which emits
24 bpp RGB. This is the one place the architecture's "a decoder unit test needs
no rendering library" (R2) does not hold; Pillow is already a hard dependency,
and the alternative — passing JPEG bytes through to `client.py` — changes
`updateRectangle`'s `(bytes, PixelFormat)` contract for every encoding to serve
one.

The decode path is unconditional: nothing in the wire format stops a
non-conforming server from sending `0x9_`, and a client that cannot read it
fails in the field. What is conditional is whether we *invite* JPEG.

**`--jpeg-quality N` offers a quality level; the default offers none.** A
conforming server sends JPEG only to a client that advertised -23..-32, so the
default keeps captures lossless, which is what a screenshot tool should do, and
the flag is what makes a JPEG rectangle capturable at all — which is what makes
the decode path testable rather than dead. Its fixture carries a non-zero
per-channel tolerance in `conditions.json`, the first use of a field
[decoder-goldens.md](decoder-goldens.md) reserved for reduced-depth formats:
JPEG is lossy, so the oracle comparison against the scene PNG cannot be exact.

**The gradient filter raises `DecodeError`, naming what arrived.** No encoder in
the fleet emits one, so no fixture can cover it, and the brief records an
unresolved disagreement between LibVNCServer and TigerVNC about its behaviour at
non-888 formats — precisely because there is no live encoder to settle it
against. Failing loudly beats shipping a branch that is a guess at a spec
ambiguity.

**Whole-rectangle decoders are a third pump path.** A Tight rectangle carries
one compression type covering the whole rectangle, so Tight never writes a
partial rectangle and never needs the shared `RectBuffer`. Its generator returns
`(bytes, PixelFormat)` and the pump hands both straight to `updateRectangle`.
No buffer is allocated, so the format mismatch above cannot arise, and
`output_format` stays a per-decoder answer for the decoders that have one.
Rejected: repacking every pixel into the negotiated layout in the decoder
(per-pixel Python on JPEG rectangles, against N2), and letting `RectBuffer`
change its `bypp` mid-life (mutable shape on a hot shared class, and still
undersized when the output is wider than the negotiated format).

**Decode only, against TigerVNC.** TigerVNC is the only fleet server measured to
emit Tight and it does not require the Tight security type. Everything else is
deferred below.

## Requirements

Inherits R1–R7, N1–N2, C1–C5 from [decoder-architecture.md](decoder-architecture.md).
Phase 6 is specifically the test of **R1**: this lands with a zero-line diff to
`rfb.py`'s encoding tables and `const.py`.

Two additions:

- **T1** Every wire claim cites rfbproto at a pinned commit, per C2. The brief
  built for this work is the source; a decoder comment citing `master` is a bug.
- **T2** The zlib streams are per connection and there are four of them
  (rfbproto §Tight), reset only by the stream-reset bits of a compression
  control byte. `for_connection()` already gives each connection its own decoder
  instance, which is where they live.

## Build order

A stack: each stage is a branch on the one below it, reviewed and merged on its
own, and the next rebases onto what landed. Every stage is green on `make test`,
`flake8 --count --statistics vncdotool tests` and `make typecheck` before it is
offered for review.

**Stage 0 — wire brief. Done**, committed as [tight-wire.md](tight-wire.md).

**Stage 1 — TPIXEL.** `pixelformat.tpixel_bytes` and the 24 bpp RGB output
format a 3-byte TPIXEL implies, with unit tests beside the CPIXEL ones in
`test_pixelformat.py`. The condition is narrow and exact — true colour, 32 bpp,
depth 24, three 8-bit channels — and the byte order is a fixed R, G, B that
ignores the big-endian flag and the channel shifts, which is what makes it
unlike CPIXEL. Touches no decoder.

**Stage 2 — the whole-rectangle pump path.** A `WholeRectDecoder` base beside
`PixelDecoder`, `_pumpFor` dispatching to it, and its own `test_pump.py` cases
including the one-byte-at-a-time segmentation case, since this path does not go
through the existing one. A Tight rectangle carries one compression type for the
whole rectangle, so the decoder returns `(bytes, PixelFormat)` and no
`RectBuffer` is allocated — which is also what keeps a 3-byte TPIXEL rectangle
from being written into a buffer sized for a 4-byte negotiated format. Touches
no decoder; independent of stage 1 in content, stacked on it in git.

**Stage 3 — the decoder, against real bytes.** Registration
(`DECODERS`, `ENCODING_NAMES["tight"]`) lands first so `--encodings tight` can be
offered at all, then `vnclog --capture-raw` against `tigervnc` produces the bytes
the implementation is written against. In order: the control byte and its reset
bits over four independent streams, fill, basic/copy, basic/palette. Gradient
raises `DecodeError`; JPEG is stage 5. Unit tests in
`tests/unit/test_decoder_tight.py`, every case driven from captured bytes.

Framing details that desynchronise the stream rather than merely producing a
wrong image, so each gets a test: the filter byte exists only when bit 6 is set;
palette size is stored minus one; the 12-byte uncompressed threshold is computed
by the decoder from `height * rowSize` and never signalled on the wire; a
2-colour palette packs 1-bit rows padded to a byte boundary. The 2048-pixel width
check exempts Fill, because TigerVNC servers before 1.16.0 sent wider Fill
rectangles and its own decoder exempts them.

**Stage 4 — goldens.** `tests/goldens/capture.py --encoding tight
--pixel-format bgrx8888`, committed as `tigervnc-tight-bgrx8888`, plus the
non-default formats the matrix asks for: TPIXEL width varies with the negotiated
format, and 32 bpp is exactly the case that hides it. `test_goldens.py` walks the
tree and needs no edit.

**Stage 5 — JPEG.** `--jpeg-quality N` offering one of -23..-32, the Pillow
decode path in the decoder, and a `tigervnc-tight-jpeg-bgrx8888` fixture
captured with the flag set and a per-channel tolerance recorded. Also the
grayscale case: TurboVNC under `-subsamp gray` emits 1-component JPEG, so the
decoder converts whatever components arrive to RGB rather than assuming three.
That one has no fixture — no fleet server emits it — so it is a code path we
take on the brief's authority alone, and the PR says so.

**Stage 6 — live and measured.** `"tight"` joins `EMITTED_BY_TIGERVNC` in
`tests/functional/test_encodings.py`; the per-encoding cases generate themselves
from `ENCODING_NAMES`. N2 lands as a bandwidth case in `test_bandwidth.py`
beside Hextile's, plus a render-time comparison against Raw.

**Stage 7 — docs, CHANGELOG, and the R1 check.** `git diff main` over `rfb.py`
and `const.py` across the whole stack is empty. If it is not, the PR says so
rather than quietly carrying the edit: that is the architecture failing the test
Phase 6 exists to be.

## Testing

Tier 1 is `test_goldens.py` against the captured fixture, and per-branch unit
tests in `tests/unit/test_decoder_tight.py` driven from captured bytes — never
from bytes assembled out of the specification, per `decoder-goldens.md`. Tier 2
is `test_encodings.py` against the fleet. Tier 3 is the existing scene
catalogue, which already covers the content classes the filters split on: solid
fills (fill compression), dense detail (JPEG or raw copy), palette regions
(palette filter), gradient (gradient filter).

The scene catalogue was built before Tight was in view. If a filter turns out
unreachable with the scenes we have, the fix is a scene, not a hand-built
fixture.

## Deferred

- **Compression level (-247..-256)**, a hint with no defined per-level meaning.
  Nothing measurable rides on it until someone has a bandwidth complaint.
- **The gradient filter.** No encoder in the fleet emits it, and the brief
  records an unresolved disagreement between LibVNCServer and TigerVNC about how
  it behaves at non-888 formats. Revisit when a server that emits it turns up —
  and start by finding that server, exactly as `decoder-architecture.md` says of
  TRLE.
- **Tight security type 16**, which TightVNC requires before falling back to VNC
  auth (server-compatibility-plan Phase 2.1). Decoding Tight and authenticating
  to TightVNC are separate; this one needs a TightVNC server in the fleet.
- **Tight Encoding Without Zlib (-317)**, which is what makes the `0xA0`/`0xE0`
  control bytes legal. We do not advertise it, so those bytes are a protocol
  error.
- **TightPNG (-260)**. No fleet server emits it, so under the captured-fixture
  rule it cannot be tested.

## Housekeeping found on the way

`RFBClient._UNMIGRATED_ENCODINGS` still lists `Encoding.ZRLE` although
`ZRLEDecoder` is registered; the union with `DECODERS` hides it. One line,
unrelated to Tight, so it travels on its own commit.

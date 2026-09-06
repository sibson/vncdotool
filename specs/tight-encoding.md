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
the decode path testable rather than dead. The level is the RFB quality level
0–9 the wire carries, not a percentage: the protocol has ten values and every
viewer's own control is that same 0–9 scale, so a percentage would invent a
mapping onto ten buckets that no two servers agree on.

Its fixture cannot reuse the reduced-depth tolerance field, as this plan first
assumed. That number is `255 >> channel_width` and bounds the server's
quantization; JPEG error is unrelated to it and much larger, and widening it
would loosen every other fixture at once. The fixture records a separate
`tolerance_kind`, and [decoder-goldens.md](decoder-goldens.md) carries the
bound, where it came from and the mutations that show it can still fail.

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
own, and the next rebases onto what landed. Every stage is green on `make test`
and on `flake8 --count --statistics vncdotool tests`, and adds no new
`make typecheck` error, before it is offered for review.

**Stage 0 — wire brief. Done**, committed as [tight-wire.md](tight-wire.md).

**Stage 1 — TPIXEL. Done.** `pixelformat.tpixel_bytes` and the 24 bpp RGB output
format a 3-byte TPIXEL implies, with unit tests beside the CPIXEL ones in
`test_pixelformat.py`. The condition is narrow and exact — true colour, 32 bpp,
depth 24, three 8-bit channels — and the byte order is a fixed R, G, B that
ignores the big-endian flag and the channel shifts, which is what makes it
unlike CPIXEL. Touches no decoder.

**Stage 2 — the whole-rectangle pump path. Done.** A `WholeRectDecoder` base beside
`PixelDecoder`, `_pumpFor` dispatching to it, and its own `test_pump.py` cases
including the one-byte-at-a-time segmentation case, since this path does not go
through the existing one. A Tight rectangle carries one compression type for the
whole rectangle, so the decoder returns `(bytes, PixelFormat)` and no
`RectBuffer` is allocated — which is also what keeps a 3-byte TPIXEL rectangle
from being written into a buffer sized for a 4-byte negotiated format. Touches
no decoder; independent of stage 1 in content, stacked on it in git.

**Stage 3 — the decoder, against real bytes. Done.** Registration
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

**Stage 4 — goldens. Done.** `tests/goldens/capture.py --encoding tight
--pixel-format bgrx8888`, committed as `tigervnc-tight-bgrx8888`, plus the
non-default formats the matrix asks for: TPIXEL width varies with the negotiated
format, and 32 bpp is exactly the case that hides it. `test_goldens.py` walks the
tree and needs no edit.

**No single scene is the palette scene for Tight**, which the Testing section
below assumed there would be. Palette coverage at bgrx8888 arrives spread across
the catalogue — 24 basic/palette rectangles at palette sizes 2, 3, 4, 5, 8 and
16 — and which rectangles come out palette is a function of the negotiated
format as much as of the content: at rgb565, quantizing to 5/6/5 collapses the
dense and scattered scenes far enough that TigerVNC sends palettes of 37, 40 and
204 colours where at bgrx8888 it sent the same rectangles as a raw copy. Which
filter a fixture reaches is therefore a property of the (scene, format) pair, not
of the scene; the capture is read back afterwards to find out what it got, and
what each one got is recorded in the commit that added it.

**Stage 5 — JPEG. Done.** `--jpeg-quality N` offering one of -23..-32, the
Pillow decode path in the decoder, and a `tigervnc-tight-jpeg-bgrx8888`
fixture captured with the flag set, carrying a lossy-encoding tolerance and
the quality level it was taken at. Also the grayscale case: TurboVNC under
`-subsamp gray` emits 1-component JPEG, so the decoder converts whatever
components arrive to RGB rather than assuming three. That one has no captured
fixture — no fleet server emits it — so its unit case re-encodes a captured
rectangle's own pixels with one component and splices them into that
rectangle's framing, and the PR says the branch is taken on the brief's
authority alone.

Two things the plan had wrong, found here. Offering a quality level *moves*
work off the other branches rather than adding to it: TigerVNC sends JPEG
where it would have sent a full-colour copy rectangle, so the lossy capture
reaches no copy filter, no implicit filter and nothing under the 12-byte
threshold, and it carries its own coverage contract rather than the lossless
one. And `expect` could not sequence a lossy capture at all, which
[expect-matching.md](expect-matching.md) went on to fix.

**Stage 6 — live and measured. Done.** `"tight"` joins `EMITTED_BY_TIGERVNC` in
`tests/functional/test_encodings.py`; the per-encoding cases generate themselves
from `ENCODING_NAMES` and render both scenes byte for byte. N2's bandwidth half
lands as two cases in `test_bandwidth.py`, one per content class, and is met
with room to spare against Raw at 256x192: 820 bytes against 196,899 on flat
regions, 69,174 against 196,803 on dense noise. Tight wins on every scene in
the catalogue, worst case 0.68x on the gradient.

**Render time is recorded, not compared against Raw.** Replaying
`tigervnc-tight-bgrx8888` costs 1446 us over the same 87 rectangles, against
Hextile's 6.4 ms and ZRLE's 31 ms on the same machine. It cost 1773 us until
`_unpalette` stopped expanding palette indices a pixel at a time; what is left is
the per-rectangle pump and zlib, which is where to look next. `bench.jsonl`
carries both rows; N2 asks that it not regress against itself.

Two things the plan had wrong, found here. `TestNegotiation` did not test
negotiation: it searched the client's own log for `repr(Encoding.X)`, which only
the "Offering" line carries, so adding any name to `EMITTED_BY_TIGERVNC` passed.
The witness is `vnclog --capture-raw`'s `encodings_seen`. And `benchmark.py`
replayed every fixture as if it were captured at the server's native format,
which is invisible until a fixture is narrower than four bytes: the rgb565
fixture desynchronised, aborted, and reported 112 us as if it were a win.

**Stage 7 — docs, CHANGELOG, and the R1 check. Done.** `--encodings tight` and
`--jpeg-quality` are documented under Encodings in `docs/usage.rst`, beside the
other flags; the CHANGELOG entries the stages wrote independently are
consolidated.

### The R1 result

`git diff main` across the whole stack, measured per file:

| file | insertions | deletions | which stage |
|---|---|---|---|
| `vncdotool/const.py` | 0 | 0 | — |
| `vncdotool/rfb.py` | 30 | 5 | stage 2 alone |
| `vncdotool/decoders/__init__.py` | 12 | 1 | stages 2 and 3 |

Of the fifteen commits in the stack, exactly one touches `rfb.py` and none
touches `const.py`.

**`const.py` is a literal zero and `rfb.py`'s encoding tables are untouched** —
neither `SUPPORTED_ENCODINGS` nor `_UNMIGRATED_ENCODINGS` appears anywhere in
the stack's `rfb.py` diff, and `Encoding.TIGHT` was already in `const.py`. That
is R1's actual claim, and it holds: **adding the encoding needed no `rfb.py`
edit at all.** Stage 3, which is the encoding, changed three lines in
`decoders/__init__.py` — an import, a `DECODERS` entry, an `ENCODING_NAMES`
entry — and nothing else outside `decoders/`.

**The 30 lines in `rfb.py` are real and are not the encoding.** Every one of
them is stage 2's `_pumpWholeRectangle`: a third pump path, plus threading a
generator's return value out through `_pumpGenerator`'s `on_done`. A pump path
is `rfb.py`'s own subject matter, not an encoding's, and the architecture's
registry claim — "nothing tells `rfb.py` the encoding exists" — survives it
intact. But R1 as written says `rfb.py` is unchanged, and this stack changed it,
so the honest reading is that Phase 6 discharges R1 for *registration* and
leaves open whether R1 also intends to bar new pump shapes. An encoding whose
framing fits neither existing path costs an `rfb.py` edit once, and the next
whole-rectangle encoding will cost none.

### N2, recorded

Stage 6 found N2's render-time half unmet. Re-measured at stage 7 on this
machine (Apple M4 Pro, CPython 3.13.12), `make bench` against each committed
golden, 8 updates x 200 replays, best microseconds:

| fixture | best us | x Raw | rectangles |
|---|---|---|---|
| `tigervnc-raw-bgrx8888` | 576 | 1.00 | 87 |
| `tigervnc-corre-bgrx8888` | 573 | 0.99 | 87 |
| `tigervnc-rre-bgrx8888` | 911 | 1.58 | 87 |
| `tigervnc-tight-bgrx8888` | 1778 | 3.09 | 87 |
| `tigervnc-tight-jpeg-bgrx8888` | 2679 | — | 68 |
| `tigervnc-hextile-bgrx8888` | 6428 | 11.2 | 87 |
| `tigervnc-zrle-bgrx8888` | 31448 | 54.6 | 87 |

The JPEG fixture has no x-Raw column: it is a different capture with 68
rectangles, so it is comparable to the other Tight rows and not to Raw.

These rows are not in `bench.jsonl`: its newest rows are stage 6's and it holds
no Hextile row at all, so this table and the profile below are a stage-7 run
that survives only here. The replacement proposed below would require recording
it.

**Tight fails N2's render-time half, and so does every encoding measured here
except CoRRE**, which alone lands inside the noise against Raw. What the slow
rows share is per-rectangle Python decode work, not decompression: only Tight
and ZRLE decompress at all, and RRE at 1.58x and Hextile at 11.2x reach those
figures without zlib — Hextile's cost is per-subrectangle Python. Hextile and
ZRLE shipped in phases 4 and 5 with N2 stated and unmet at 11x and 55x, so this
is a requirement almost nothing has ever met, not a regression Tight introduced.

The profile says why. Over 20 profiled replays of `tigervnc-tight-bgrx8888`,
0.068 s total: `_unpalette` 0.012 s of self time (the per-pixel Python loop that
expands palette indices), `zlib.Decompress.decompress` 0.010 s, then the pump —
427 `_pumpGenerator` sends per replay of 87 rectangles, against Raw's zero. Raw
is fast because it takes none of these: it enters `_pumpRectangle`, reads
`width * height * bypp` bytes straight off the wire in the negotiated layout, and
pastes them. Its profile has no decoder frame in the top twenty-five at all.
Doing any per-pixel work in Python therefore cannot be free, and a bar measured
against the one encoding that does none asks for exactly that.

### Proposed replacement for N2 — not applied

`decoder-architecture.md` is not edited here: amending a standing architectural
requirement is the repository owner's call. This is the case, for them to accept
or reject.

> **N2** Each encoding added after Raw demonstrates fewer bytes over the wire
> than Raw on the content class it is designed for, measured. Render time is
> measured and recorded in `bench.jsonl` for every encoding at every committed
> pixel format, and no encoding regresses against its own previous recorded
> figure on the same machine; there is no bar against Raw, because Raw does no
> per-pixel work and everything that does is slower than it in Python. An
> encoding whose render time would make a scripted session slower end to end
> than Raw over the same link is the thing to refuse, and that is a wire-time
> and render-time question together, not render time alone.

If the owner prefers to keep an absolute bar, the alternative is to state it as
a budget rather than a comparison — "no encoding costs more than N ms per
full-screen update at 1920x1080" — and to accept that ZRLE fails it today and
needs the `cpixel` loop replaced before it can pass.

## Testing

Tier 1 is `test_goldens.py` against the captured fixture, and per-branch unit
tests in `tests/unit/test_decoder_tight.py` driven from captured bytes — never
from bytes assembled out of the specification, per `decoder-goldens.md`. Tier 2
is `test_encodings.py` against the fleet. Tier 3 is the existing scene
catalogue, which covers the content classes the filters split on: solid fills
(fill compression), dense detail (JPEG or raw copy) and palette regions
(palette filter).

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

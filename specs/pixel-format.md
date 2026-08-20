# Pixel Format — Design

Status: draft, under review. The first slice of
[decoder-architecture.md](decoder-architecture.md) Phase 1, and the `rgb565`
entry point [decoder-goldens.md](decoder-goldens.md) names in its phasing.

## Problem

`client.PF2IM` (`client.py:68`) is a five-entry dict keyed on the whole
`PixelFormat` dataclass, valued with a Pillow raw mode. A format outside those
five raises `LookupError`, and `setImageMode` (`client.py:318-329`) guesses —
`BGR16` if the server announced 3.889, `RGB32` otherwise — sends
`SetPixelFormat`, and assumes it was obeyed. A server that ignores it keeps
sending its own format, decoded as the requested one: #90 and #275.

Nothing can request a format from the command line (#167, #168), so the golden
matrix has one fixture and the pixel plumbing has never run at a second format.

## Scope

The `pixelformat.py` machinery, plus one new negotiated format: `rgb565`. That
discharges R3 for two formats — one scene decoding to the same framebuffer at
both. Colour map, and the layouts Pillow cannot unpack, wait for a server that
needs them.

## What servers actually send

ServerInit read off each running server, not from documentation. Tier 1 locally,
Tier 2 from run
[32386264566](https://github.com/sibson/vncdotool/actions/runs/32386264566):

| Server | ServerInit format | Wire | In `PF2IM`? |
|---|---|---|---|
| tigervnc, x11vnc | 32 bpp, depth 24, LE, max 255, shifts 16/8/0 | BGRX | yes |
| ultravnc (windows-latest) | identical | BGRX | yes |
| screen-sharing (macos-latest) | identical | BGRX | yes |
| libvncserver-example | 32 bpp, **depth 32**, LE, max 255, shifts 0/8/16 | RGBX | **no** |
| vncev | 8 bpp, depth 8, **colour-mapped** | index | **no** |

The two misses are libvncserver's example programs, in the fleet because they
are scriptable, not because anyone runs them. **Every server anyone runs sends
BGRX at 32 bpp, depth 24, little-endian**, and neither Tier 2 job logged a
`Requesting` line, so today's code already reads both natives without
renegotiating.

Three consequences:

- **`PF2IM` misses on `depth`, which does not affect byte layout.**
  libvncserver-example's format *is* the layout `PF2IM` calls `RGBX`, differing
  only by declaring depth 32 — the historical quirk rfbproto warns about — so we
  renegotiate to a format byte-identical to the one already arriving. Computing
  the mode from the fields removes the failure mode.
- **The 3.889 Apple branch never fires against current Screen Sharing**, whose
  native is in `PF2IM` already. It is dropped rather than carried forward; if an
  older ARD server needs it, it returns as a measurement.
- **One dominant native is not a safe assumption.** `PF2IM` was shaped around
  the formats someone had met, and libvncserver-example is a depth declaration
  away from an entry.

## Decoders emit what they were sent

A decoder returns bytes in the layout it produced them, tagged with the Pillow
raw mode that unpacks it. `client.py` materializes each rectangle with one
`Image.frombytes(..., "raw", mode)`. Raw, RRE, CoRRE, Hextile and ZRLE tag the
negotiated format; Tight's JPEG tags `RGB`; a colour-mapped decoder tags `P` and
carries the palette.

Converting inside each decoder to one canonical layout was designed first and
dropped. It materializes every rectangle twice — bytes, image, bytes, image, for
~1.2 ms per 1080p frame of copying — and forces JPEG, TPIXEL and colour map to
produce a layout that then has to be undone.

Tagging means **a decoder never interprets a pixel**. A background colour, a
Hextile foreground, a ZRLE palette entry are opaque `bypp`-sized byte strings,
and a fill is one repeated. No shifts, no masks, no endianness in any decoder,
so that class of bug cannot be written — including the live one, ZRLE's
`cpixel()` reading three bytes least-significant-first and appending `0xFF`
(`rfb.py:820`).

R3 moves with it: stated over the framebuffer, not decoder output, and checked
by the goldens' cross-format comparison.

## Surface

```python
def raw_mode(pixel_format: rfb.PixelFormat) -> str: ...      # raises UnsupportedPixelFormat
def cpixel_bytes(pixel_format: rfb.PixelFormat) -> int: ...  # 3 or bypp
def cpixel_offset(pixel_format: rfb.PixelFormat) -> int: ... # 0 or bypp - 3
```

`raw_mode` ignores `depth` — it does not affect where the channels sit.
`cpixel_bytes` must obey it, since the encoder used the same declaration.

`UnsupportedPixelFormat` rather than a guess, though under the policy below a
caller only reaches it when a server ignores what we asked for.

**CPIXEL** (RFC 6143 §7.7.5) is three bytes when true colour, 32 bpp, depth ≤ 24
and every colour bit sits in either the low or the high three bytes; which
placement is a function of the shifts. rfbproto adds a tie-break the RFC omits:
at depth ≤ 16 both placements fit, and the low three bytes are sent.

**TPIXEL** is narrower and fixed — depth exactly 24, all channels exactly 8
bits, bytes red, green, blue — so a Tight rect tags `RGB` unconditionally. It
arrives with Tight at decoder Phase 6.

This pass writes the CPIXEL functions and their tests; ZRLE keeps its current
bytes until Phase 5, per R5.

## What Pillow can unpack

Probed by feeding known words through each mode:

| Negotiated layout | Pillow raw mode |
|---|---|
| 32 bpp, 8-bit channels, any order or endianness | `RGBX` `BGRX` `XRGB` `XBGR` |
| 24 bpp packed, either order | `RGB` `BGR` |
| 16 bpp 565, 555, 444, either order, **little-endian** | `BGR;16` `RGB;16` `BGR;15` `RGB;15` `RGB;4B` |

`rgb565` is `BGR;16`: `0x00F8` little-endian yields `(255, 0, 0)`, so it is
red-in-the-high-bits 565, matching `PixelFormat(16, 16, False, True, 31, 63, 31,
11, 5, 0)` — the constant `client.py` calls `BGR16`.

Four layouts fall outside: **big-endian 16 bpp** (big-endian 32 bpp is another
byte permutation, covered); **channel widths outside 8/8/8, 5/6/5, 5/5/5,
4/4/4**; **non-byte-aligned shifts at 32 bpp**; and **colour-mapped**, which is
`P` plus `putpalette` rather than a raw mode.

None needs a converter, because none is reachable while a server honours
`SetPixelFormat` — an unreadable native means we ask for `bgrx8888`. A converter
is for a server that sends an exotic native *and* ignores the request, which no
capture has shown. Measured for whenever one does: a 2^16-entry lookup table
converts a 1080p frame in 23.7 ms, per-pixel Python in 160 ms.

## Negotiation

`setImageMode`, `PF2IM` and the `image_mode` property all go; its
`FutureWarning` shipped in 1.4 (#385) and this is 2.0.

The replacement runs at `vncConnectionMade`, before the first
`FramebufferUpdateRequest`. Required, not tidy: rfbproto states a client **must
not** have an outstanding request when it sends `SetPixelFormat`, since the next
update would be undecidable between formats. There is no acknowledgement and no
fence, so `--pixel-format` is connect-time only — a later switch needs the
request drained or the Fence pseudo-encoding, which we do not implement.

1. `--pixel-format NAME` given: send it.
2. Otherwise, if `raw_mode` resolves the native: send nothing.
3. Otherwise: request `rgbx8888`.

Sending nothing is both the default and, for every measured server, the whole
policy. rfbproto is explicit that absent a `SetPixelFormat` the server sends its
ServerInit format, and that servers **must support** the message while clients
need not send one. #90 and #275 are servers that keep sending native after being
asked otherwise; a client that never asked cannot be bitten by them. Step 3 has
no measured caller.

Nothing detects a server ignoring the request — the protocol offers no way. What
changes is that an unreadable native is a diagnosed error rather than a silent
guess.

A colour-mapped request leaves the map empty until `SetColourMapEntries`
arrives, whatever the server set before; that lands with the colour-map slice.

## Command line

    vncdo --pixel-format rgb565 capture screen.png

Names from a registry, not a ten-field tuple: `bgrx8888`, `rgbx8888`, `rgb565`.
Channel order as the bytes arrive, per-channel widths, `x` for a pad byte —
naming the pad because it distinguishes the 32 bpp formats every server sends
from the 24 bpp ones the specification does not allow. Fixtures use the same
vocabulary, which is why `tigervnc-raw-rgb888` became `tigervnc-raw-bgrx8888`:
a fixture is named for the format it holds, never for how that format was
chosen.

Every requestable name is 8, 16 or 32 bpp, all the specification permits. The
24 bpp modes stay reachable by `raw_mode` and out of the registry — reading one
is tolerance for an out-of-spec server, never something we ask for.

`api.connect` gains a `pixel_format=` keyword taking the same names. `vnclog`
gets no flag: the client negotiates, the proxy records what it saw.

## Testing

**Unit.** `raw_mode` over a table of formats, including pairs differing only by
`depth` and only by endianness, plus `UnsupportedPixelFormat` for the four
uncovered layouts. Then, per mode, known bytes through `Image.frombytes` to
known RGB pixels — the mode string is a claim about Pillow, and that is the
claim that can be wrong. CPIXEL gets both placements, the depth ≤ 16 tie-break,
and the negative cases falling back to PIXEL width.

**Negotiation.** Mocked transport asserting the `SetPixelFormat` bytes, or their
absence, which is step 2 and the case a test would otherwise skip.

**Golden.** A second fixture, `tigervnc-raw-rgb565`, from `make goldens`. Its
oracle is the same committed scene PNG, so tolerance stops being zero: the bound
is the format's own step, 255/31 for the 5-bit channels and 255/63 for the
6-bit, rounded up, which covers truncation and round-to-nearest alike without
modelling either. Two fixtures then allow the cross-format check — decode both,
assert the framebuffers agree — which is R3 as restated.

`conditions.json` grows the pixel format, both the ServerInit one and any we
requested. They are different facts and the interesting fixtures are where they
differ.

**Functional.** One fleet case: `--pixel-format rgb565` capture is not flat.

**Capture script.** `scene.vdo` steps with `expect scenes/X.png 0`, a histogram
RMS of exactly zero, which `rgb565` can never reach — every step would poll
until the capture hung rather than failed. The driving script becomes
per-format, `make goldens` supplying the maxrms; `session.vdo` in the archive
records which ran.

## Phasing

1. `pixelformat.py`, the registry, unit tests. No call sites change.
2. `client.py` resolves the mode per rectangle; `PF2IM`, `setImageMode`,
   `image_mode` go. BGRX behaviour unchanged (R5).
3. `--pixel-format`, the policy, the `api.connect` keyword.
4. Capture `tigervnc-raw-rgb565`; tolerance and the cross-format check in
   `test_goldens.py`; the fleet case.

## Validated against the specs

C2. Read from a local rfbproto clone (`DEVELOP.rst` says where) and RFC 6143.

- **Format fields** (rfbproto §ServerInit, RFC 6143 §7.4): bpp must be 8, 16 or
  32 and ≥ depth; big-endian is meaningless at 8 bpp; each max is 2^n - 1, each
  shift brings its channel to the least significant bit. Also that "some servers
  will send a *depth* identical to *bits-per-pixel* for historical reasons".
- **SetPixelFormat** (rfbproto §SetPixelFormat and §Client to Server Messages,
  RFC 6143 §7.5.1): optional for clients, mandatory for servers to support;
  absent it the ServerInit format applies; no acknowledgement; no outstanding
  `FramebufferUpdateRequest` when sent; colour map empty immediately after.
- **CPIXEL** (rfbproto §ZRLE, RFC 6143 §7.7.5): the four conditions, both
  placements, the low-three-bytes tie-break at depth ≤ 16.
- **TPIXEL** (rfbproto §Tight): narrower, fixed RGB order. Corrects a "believed
  to follow the same rule" note in `decoder-architecture.md`.

Unverified: how a real server behaves when asked for a format it dislikes. No
document covers it; a capture will.

## Deferred

- The four layouts Pillow cannot unpack, each waiting for a capture from a
  server that sends one and ignores `SetPixelFormat`.
- Colour map: `P` plus a palette, and the `SetColourMapEntries` ordering above.
  vncev is the server to build it against once a real one turns up behind it.
- The CPIXEL functions' use, which lands with ZRLE at decoder Phase 5.
- A raw-tuple form of `--pixel-format`.

## Risks

- A tolerance wide enough for 5-bit quantization can hide a real defect. The
  cross-format check compensates: no external truth needed, and it fails on the
  channel-order and shift errors the loose bound would swallow.
- Tagging moves the trust from our arithmetic to Pillow's mode strings. A mode
  meaning something other than we think decodes silently wrong, where a bad
  shift would at least be ours to read — hence unit tests asserting Pillow's
  behaviour per mode, not only which mode we picked.
- Retiring the 3.889 branch rests on one macOS version on a hosted runner. If an
  older ARD server announces something unreadable, it now gets a
  `SetPixelFormat` for `rgbx8888` — the correct fallback, untested against that
  server.

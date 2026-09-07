# CPIXEL depth quirk (#483): Design

Status: implemented.

## Problem

`cpixel_bytes()` (`vncdotool/pixelformat.py:177`) gates 3-byte CPIXEL
narrowing on `pixel_format.depth <= 24`, per RFC 6143 §7.7.5's literal text.
`_cpixel_placement()` (line 163) independently derives, from redshift/
greenshift/blueshift and channel widths alone, whether the colour bits fit in
the low or high three bytes -- exactly the technique `raw_mode()` already
uses to ignore `depth` for layout (`raw_mode` docstring, line 100; pinned by
`test_depth_does_not_affect_the_resolved_mode`).

libvncserver-example declares `depth=32` in `ServerInit` (`specs/pixel-format.md`
line 41) but its ZRLE encoder narrows to 3-byte CPIXELs regardless -- the same
"historical quirk rfbproto warns about" (§ServerInit note on servers reporting
depth == bpp) that `raw_mode` was already built to tolerate. `cpixel_bytes`
never got the same leniency: `specs/pixel-format.md` line 137 flagged this as
deferred, and current behaviour is pinned backwards by
`test_depth_32_is_never_a_cpixel` (`tests/unit/test_pixelformat.py:213`), which
asserts a depth-32, 8/8/8-channel format falls back to 4-byte PIXELs. Against
a real libvncserver-example server this decodes ZRLE data as one byte too wide
per pixel: `"ZRLE RLE tile at (0,0) decoded 4267 pixels, wanted 4096"`.

## Why depth is redundant here

RFC 6143 and rfbproto (`docs/rfbproto/rfbproto.rst:3697-3711`) state CPIXEL
applies when bpp is 32, depth is 24 or less, and the colour bits fit in
either the low or high three bytes -- three conditions, not two. But the
placement check already subsumes what the depth check is for: if every
channel's `shift + width` fits in 24 bits (or every shift is >= 8), the
colour data occupies at most 3 bytes on the wire regardless of what `depth`
claims. A format that genuinely needs all 4 bytes for colour -- shifts and
widths straddling the middle, e.g. `test_colour_bits_straddling_the_middle_
fall_back_to_pixel_width` (line 218) -- already gets refused by
`_cpixel_placement` returning `None`, independent of `depth`. Nothing in
`PixelFormat.__post_init__`'s validation ties `depth` to the shifts at all
(lines 41-55), so `depth` cannot be trusted to mean anything beyond a label a
server attaches to its own `ServerInit`.

This mirrors `raw_mode`'s existing rationale line-for-line: depth doesn't
affect where the channels sit, so don't gate byte-layout decisions on it.

## Proposed fix

Drop the `pixel_format.depth <= 24` condition from `cpixel_bytes()`. The
function becomes: 3-byte CPIXEL whenever truecolor, bpp == 32, and
`_cpixel_placement()` is not `None`; otherwise `bypp`. No change to
`_cpixel_placement()`, `cpixel_offset()`, or `tpixel_bytes()` --
`tpixel_bytes` keeps its `depth == 24` gate, since Tight/TPIXEL is a
narrower, fixed-order rule with no reported lying-depth case to justify
loosening it preemptively (RFC gives it no depth-tolerant corner case the
way ZRLE's own "corner case" note does).

## Test changes

- `test_depth_32_is_never_a_cpixel` currently pins the bug and must be
  replaced. Rename/rewrite to assert the opposite for the *narrow-channel*
  case: `cpixel_bytes(BGRX8888_DEPTH32) == 3`, `cpixel_offset(...) == 0`
  (`BGRX8888_DEPTH32` already exists as a fixture, `test_pixelformat.py:19`).
- Add a case where depth is high (32) *and* placement genuinely fails --
  e.g. reuse `test_colour_bits_straddling_the_middle_fall_back_to_pixel_
  width`'s shifts at depth 32 instead of 24 -- to show the fallback still
  fires on placement, not on depth, closing the "hypothetical format that
  truly needs 4 bytes" concern from a different angle than mere depth
  reporting.
- `test_the_three_bytes_carry_every_colour_bit`'s `every_layout()` generator
  (line 35) only yields depth 24, 16, 15, 12 -- add a depth-32 sweep (widths
  8/8/8, all shift permutations) so the cross-product test exercises the
  quirk directly, the way `every_layout` already exercises every other depth.

## Resolution

Implemented as proposed: `cpixel_bytes()` no longer checks `depth`
(`vncdotool/pixelformat.py`). Verified two ways before landing:

- Manually probed TigerVNC and x11vnc, both requested at a synthetic
  `depth=32` `PixelFormat` (bpp 32, RGBX shifts): both narrow to 3-byte
  CPIXELs regardless, decoding cleanly. Probed `libvncserver-example` at its
  real native `depth=32` ServerInit: `vncdo capture` against it, previously
  the exact crash #483 reported, now decodes cleanly.
- `capture.py`'s golden pipeline turned out unable to reach this case: it
  shells out to the real `vncdo` CLI (deliberately, so a hang is
  kernel-reaped rather than poisoning the test process), and the CLI's
  `--pixel-format` only lists the public registry, which a depth-32 variant
  has no reason to join (depth doesn't affect layout, so a name differing
  from `rgbx8888` only by depth is registry noise for every other caller).
  Rather than adding a second capture mechanism for one fixture, the fix is
  pinned with a deterministic unit test instead:
  `test_zrle_depth_32_still_narrows_to_three_bytes`
  (`tests/unit/test_decoder_zrle.py`), built the same way its neighbouring
  `test_zrle_high_cpixel_placement_reads_three_bytes_at_the_high_end` is --
  synthetic ZRLE bytes through a custom `ServerInit`, no fleet required.

Test changes landed: `tests/unit/test_pixelformat.py`'s
`test_depth_32_is_never_a_cpixel` renamed to
`test_depth_32_with_narrow_channels_is_still_a_cpixel` and inverted, a new
`test_colour_bits_straddling_the_middle_at_depth_32_still_falls_back` added,
and `every_layout()` extended to sweep depth 32.

The manual probes are now a committed, reusable tool:
`tests/goldens/probe_pixel_format.py` (`uv run python -m
tests.goldens.probe_pixel_format --server ... --depth ...`), rather than
throwaway scripts. Every docker-fleet truecolor server was probed at a
requested `depth=32`, plus `libvncserver-example` at its real native
depth-32 ServerInit: all four narrow to 3-byte CPIXELs regardless and decode
clean. `vncev` is colour-mapped (no CPIXEL) and wasn't probed; OS-hosted
servers (UltraVNC/Screen Sharing/QEMU) run in CI only and weren't probed
here. CI now runs the same sweep on every push against the fleet
(`.github/workflows/ci.yml`) and, per OS, against UltraVNC/Screen Sharing/
QEMU-KVM (`.github/workflows/os-servers.yml`), recording each server's
output as an artifact for future reference.

## Detecting a genuinely 4-byte server

Dropping the `depth` check trades a spec-literal read for an assumption:
every real ZRLE encoder narrows whenever placement fits, none actually uses
a 4th byte a narrower placement would also cover. Nothing before this
change could tell those two cases apart at runtime -- a wrong guess either
way would decode garbage or silently drift.

`ZRLEDecoder.decodePixels` (`vncdotool/decoders/zrle.py`) now checks that
after all a rectangle's tiles are read, `pos == end`: RFC 6143 7.7.6 has
every subencoding consume an exact, self-describing number of bytes, so a
rectangle's zlib chunk is fully accounted for only when `cpixel_bytes`
guessed the width the server actually used. A wrong guess leaves bytes
unconsumed (or, more often, runs out early inside a tile -- already caught
by the existing `short()` raises) and now ends the session with a named
`DecodeError` instead of misreading the next tile as a stray subencoding
byte. Pinned by
`test_zrle_leftover_bytes_after_a_tile_is_a_protocol_error`. Verified
against every committed ZRLE golden and the new depth-32 unit test: none
trip it, so it isn't a false-positive risk for the layouts already covered.

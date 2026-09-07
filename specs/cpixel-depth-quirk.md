# CPIXEL depth quirk (#483)

Status: implemented.

`cpixel_bytes()` (`vncdotool/pixelformat.py`) used to gate 3-byte CPIXEL
narrowing on `pixel_format.depth <= 24`, per RFC 6143 §7.7.5's literal text.
libvncserver-example declares `depth=32` in `ServerInit` but its ZRLE
encoder narrows to 3 bytes anyway -- the same "historical quirk" rfbproto
notes servers reporting depth == bpp for. Against a real server this
decoded ZRLE one byte too wide per pixel: `"ZRLE RLE tile at (0,0) decoded
4267 pixels, wanted 4096"`.

`_cpixel_placement()` already derives 3-byte eligibility purely from
channel shift+width, independent of `depth` -- the same technique
`raw_mode()` uses to ignore `depth` for layout. A layout that genuinely
needs 4 bytes already fails placement and falls back regardless of what
`depth` claims, so the `depth` check was redundant with it, not an
independent constraint. Fix: drop `depth <= 24` from `cpixel_bytes()`.
`tpixel_bytes()` (Tight) is untouched -- no known lying-depth Tight server
to justify loosening it preemptively.

No committed golden fixture: `tests/goldens/capture.py` shells out to the
real `vncdo` CLI, whose `--pixel-format` only lists the public registry,
which a depth-32-only variant has no reason to join (depth doesn't affect
layout, so a name differing from `rgbx8888` only by depth is registry noise
for every other caller). Pinned instead with a deterministic unit test,
`test_zrle_depth_32_still_narrows_to_three_bytes`
(`tests/unit/test_decoder_zrle.py`), synthetic bytes through a custom
`ServerInit`, no fleet required.

**Detecting a genuinely 4-byte server.** Dropping the `depth` check trades
a spec-literal read for an assumption -- every real encoder narrows
whenever placement fits, none needs the 4th byte. `ZRLEDecoder` now checks
that a rectangle's tiles fully consume its zlib chunk (`pos == end`): RFC
6143 7.7.6 has every subencoding consume an exact byte count, so leftover
bytes mean `cpixel_bytes` guessed a width the server isn't using. Ends the
session with a named error instead of misreading the next tile. Verified
against every committed ZRLE golden: none trip it.

**Verification.** `tests/goldens/probe_pixel_format.py` is a committed,
reusable probe (connect with a chosen or depth-overridden `PixelFormat`,
or `--native`, report clean decode or not) -- built for this investigation,
kept for future ad hoc use. Ran once against every reachable server: the
docker fleet (TigerVNC, TigerVNC-auth, x11vnc, libvncserver-example) plus,
via a one-off CI run in PR #488, UltraVNC/Screen Sharing/QEMU-KVM. All
seven decode clean at a requested `depth=32` (Screen Sharing's screenshot
is flat black, matching `VNCServer(..., renders_desktop=False)`'s
documented reason -- the decode itself still succeeded). `vncev` is
colour-mapped and wasn't probed.

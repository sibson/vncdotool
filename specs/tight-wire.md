# Tight encoding (RFB encoding type 7) — wire-format brief

Primary source: rfbproto pinned at `152107db63cd34b3536ad8ddf54a0cfc9017a9f9` (2025-06-03, `master` head as of 2026-09-01); the copy read hashes to blob `d16232d457341201c5375d1b21bc9c0310320d41`, identical to `rfbproto.rst` at that commit. Citations are reference links resolved at the bottom; anchors are GitHub rST section slugs, with line numbers at the pinned SHA inline so a claim stays checkable if slugs change. **RFC 6143 does not define Tight at all** — encoding 7 is outside it. Secondary sources, pinned: TigerVNC 1.16.2 `b555312d70d7ff017f866649a7e7167af4eb8fca`, TurboVNC 3.3.1 `afb793371a79240171f6eadb7bbcee2aaa422b44`, LibVNCServer `42494999e6492aaab9c1db785ecd293ef10b3aed` (`src/libvncclient/tight.c` blob `3ee0d5e071f8beac66efe414ca940e95423b76f6`).

## 1. TPIXEL, versus ZRLE's CPIXEL

A `TPIXEL` is a `PIXEL` in the agreed pixel format **except** when all of: *true-colour-flag* non-zero, *bits-per-pixel* = 32, *depth* = 24, and red/green/blue intensities each exactly 8 bits wide. Then it is **3 bytes**: byte 0 red, byte 1 green, byte 2 blue. [spec §Tight][S-tight] (3488–3497). Byte order is fixed R,G,B — it does **not** depend on *big-endian-flag*, nor on the red/green/blue shifts; shifts and maxes only decide whether the condition holds.

CPIXEL differs three ways: it applies at *depth* **24 or less**, not only 24; it is defined as *which 3 of the packed PIXEL's 4 bytes survive* (least- or most-significant three, whichever holds the RGB bits), so it keeps native packed order and endianness rather than being R,G,B; and it has a tie-break convention (prefer the three least-significant bytes). [spec §ZRLE][S-zrle] (3697–3712)

Divergence, harmless in practice: TigerVNC gates on `PixelFormat::is888()`, adding a requirement the spec omits — each shift a multiple of 8 [PixelFormat.cxx][PF]. LibVNCServer checks only `depth==24 && redMax==greenMax==blueMax==0xFF` at 32bpp [lvs L384][LVS384].

## 2. The compression-control byte

One `U8` opens every Tight rectangle [spec §Tight][S-tight] (3423–3429).

Bits 0–3, independently: bit *n* set means **reset zlib stream *n*** (streams 0..3) before decoding this rectangle (3431–3443). The reset must be honoured **even when the type is Fill or JPEG**, which carry no zlib data — NOTE1 (3620–3625).

Bit 7 = 0 → **BasicCompression**: bits 5–4 are the stream id to *use* (00→0 … 11→3), bit 6 is the *read-filter-id* flag (3445–3462). Bit 7 = 1 → bits 7–4 select (3464–3477):

| bits 7–4 | byte (reset nibble 0) | meaning |
|---|---|---|
| 1000 | 0x80 | **FillCompression** |
| 1001 | 0x90 | **JpegCompression** |
| 1010 | 0xA0 | **BasicCompression Without Zlib** |
| 1110 | 0xE0 | as above, plus *read-filter-id* |
| other | — | invalid |

So the shorthand "0x08 fill / 0x09 JPEG" is `comp_ctl >> 4`, and the basic-compression range is `comp_ctl >> 4` in **0x0–0x7** (stream id in bits 5–4, filter flag 0x4). TigerVNC's constants match exactly — `tightExplicitFilter=0x04`, `tightFill=0x08`, `tightJpeg=0x09`, `tightMaxSubencoding=0x09` [TightConstants.h][TC] — and it writes `tightJpeg << 4`, the byte `0x90` [TightJPEGEncoder L93][TJE93]. Framing rule: **strip the low 4 reset bits first**, then compare the remainder; TigerVNC consumes bits 0–3 in a reset loop, then shifts right 4 [TightDecoder L269][TD269].

**BasicCompression Without Zlib** (0xA0/0xE0) is legal only if the client advertised the Tight Encoding Without Zlib pseudo-encoding, **-317** [spec §no-zlib][S-nz] (4508–4514; also 3485–3486, 3626–3628).

## 3. FillCompression

Payload is **one TPIXEL and nothing else** — no length, no count — applying to every pixel of the rectangle [spec §Tight][S-tight] (3501–3504). Byte count is 3 when §1's condition holds, else *bits-per-pixel*/8.

## 4. JpegCompression

Payload: *length* in compact representation (1–3 bytes), then *length* bytes of *jpeg-data*, which is a **JFIF stream** [spec §Tight][S-tight] (3505–3533). There is no filter byte and no zlib; the 12-byte rule of §6 does not apply.

The spec says nothing about colour space; the JFIF stream carries its own. In practice it is baseline 3-component YCbCr decoding to 8-bit RGB, which the client then converts into its own pixel format. **It may also be 1-component grayscale**: TurboVNC emits grayscale JPEG when the client selected the "gray" subsampling level [turbo tight.c L820][TT820]. A decoder assuming three components breaks against TurboVNC with `-subsamp gray`.

## 5. BasicCompression and the three filters

With bit 6 set, the **second** byte is *filter-id*: 0 **CopyFilter**, 1 **PaletteFilter**, 2 **GradientFilter**. With bit 6 clear there is no filter byte and CopyFilter is implied [spec §Tight][S-tight] (3535–3552).

**CopyFilter** — raw TPIXELs, row-major, no padding. Row size `width*3` in the 3-byte-TPIXEL case, else `width * bpp/8` (3554–3558).

**PaletteFilter** — one `U8` = *palette size minus 1* (1 means 2 colours, 255 means 256), then that many TPIXELs, then indices. At exactly 2 colours each pixel is **1 bit**, MSB = leftmost pixel, and **each row is padded to a byte boundary**: row size `(width+7)/8`. Otherwise 8 bits per pixel, row size `width` (3559–3572). Confirmed independently by TigerVNC [TightDecoder L388][TD388] and by LibVNCServer's generic `rowSize = (rw*bitsPixel+7)/8` with `bitsPixel` 1 or 8 [lvs L254][LVS254].

**GradientFilter** — per colour component, the encoder sends a difference from a prediction:

```
P[i,j] := V[i-1,j] + V[i,j-1] - V[i-1,j-1];
if P < 0 then P := 0;  if P > MAX then P := MAX;
D[i,j] := V[i,j] - P[i,j];
```

`V` outside the rectangle is 0; MAX is that component's maximum intensity. Legal only when *bits-per-pixel* is **16 or 32** (3574–3594). The filter does not change data volume, so row size matches CopyFilter's. Two implicit points, and one open disagreement:

- The prediction is clamped **before** the difference is added, and the addition itself wraps modulo (MAX+1). Both LibVNCServer [lvs L484][LVS484] and TigerVNC (uint8 arithmetic) [TightDecoder L545][TD545] do this.
- **Unresolved.** For non-888 formats (e.g. 16bpp 5-6-5), LibVNCServer runs the gradient in *native component* space: extract with `>> shift`, clamp the estimate to that component's `*-max`, mask the sum with `& max`. TigerVNC instead converts to 8-bit-per-component RGB, runs with MAX=255, converts back — and its 16bpp path indexes a `uint8_t*` input by pixel index rather than byte offset, which looks like a stride bug. I could not settle this empirically because **neither TigerVNC nor TurboVNC ever emits the gradient filter** (no "gradient" match anywhere in TurboVNC's `tight.c`; TigerVNC's `TightEncoder.cxx` writes only copy/mono/indexed). LibVNCServer's native-component reading matches the spec's wording ("MAX is the maximum intensity value for a color component") but is untested against a live encoder — likely-correct, not confirmed.

After filtering the data is zlib-compressed on the selected stream; see §6 (3596–3618).

## 6. Compact length and the 12-byte uncompressed rule

1–3 bytes, 7 payload bits each, little-endian in 7-bit groups (3516–3532):

```
0xxxxxxx                     0..127          bits 0-6
1xxxxxxx 0yyyyyyy            128..16383      bits 0-6, then 7-13
1xxxxxxx 1yyyyyyy zzzzzzzz   16384..4194303  bits 0-6, 7-13, then 14-21
```

The third byte is a **full 8 bits**, not 7; maximum representable value 4194303. The spec's worked example: decimal 10000 → `0x90 0x4E`.

Threshold: "if the data size after applying the filter but before the compression is less th[a]n 12, then the data is sent as is, uncompressed" (3596–3600). The decoder must compute that size itself — `height * rowSize` from §5 — and if **< 12**, read exactly that many raw bytes with **no compact length prefix and no zlib**; otherwise read a compact length then that many bytes of zlib data. Confirmed in all three implementations: TigerVNC `if (length < 12)`, commented "This value should not be changed, doing so will break compatibility" [TightEncoder L246][TE246]; TurboVNC `#define TIGHT_MIN_TO_COMPRESS 12` [turbo tight.c L41][TT41]; LibVNCServer the same [lvs L38][LVS38]. Interaction with **BasicCompression Without Zlib**: the 12-byte short-circuit is checked *first*, and above the threshold a compact length is still read — it just prefixes raw filtered bytes rather than zlib data [lvs L253][LVS253].

## 7. Rectangle-size and JPEG constraints

**Width ≤ 2048 pixels** for any Tight rectangle; wider regions must be split into several rectangles encoded separately [spec §Tight][S-tight] (3417–3421). The spec states **no maximum pixel count**. TigerVNC additionally splits at `SubRectMaxArea = 65536` / `SubRectMaxWidth = 2048` [EncodeManager L52][EM52]; TurboVNC's per-compression-level table uses the same 65536/2048 pair [turbo tight.c L88][TT88]. A decoder should not *require* ≤65536 pixels, but sizing row buffers for 2048 is safe — both TigerVNC and LibVNCServer hard-code 2048 for gradient row buffers. Field wrinkle: TigerVNC's decoder notes that **TigerVNC servers before 1.16.0 sent oversized Fill rectangles**, so it applies the 2048 check to every type *except* Fill [TightDecoder L104][TD104]; a decoder that rejects wide Fill rects will fail.

**JpegCompression may be used only when *bits-per-pixel* is 16 or 32 and the client has advertised a quality level** via the JPEG Quality Level pseudo-encoding (3479–3483). The spec is silent on whether true-colour is required; JPEG under a colour map is meaningless and no implementation emits it. TigerVNC's own format gate is looser than the spec: `pf().bpp < 16` is the only check [TightJPEGEncoder L43][TJE].

## 8. Tight-related pseudo-encodings, and unasked-for JPEG

JPEG Quality Level **-23..-32** (-23 high quality, -32 low) [spec §quality][S-jq] (3979–3992). Compression Level **-247..-256** (-247 high compression, -256 low), a hint only with no defined per-level meaning [spec §compression][S-cl] (4139–4158). Tight PNG **-260** — a genuine encoding, not a pseudo-encoding — forbids BasicCompression and replaces it with **PngCompression** at bits 7–4 = 1010 [spec §TightPNG][S-png] (3937–3975). Also relevant: JPEG Fine-Grained Quality Level -412..-512 and JPEG Subsampling Level -763..-768 (3088–3089, 4516–4531).

**Does a server send JPEG when the client offered no quality level?** rfbproto settles it: "If the JPEG quality level is not specified, **JpegCompression is not used** in the Tight Encoding" (3984–3986). Both encoders agree, verified in source rather than inferred:

- **TigerVNC 1.16.2**: `TightJPEGEncoder::isSupported()` returns false unless the client advertised Tight *and* `pf().bpp >= 16` *and* at least one of `qualityLevel`, `fineQualityLevel`, `subsampling` is not -1 — closing comment literally "Tight support, but not JPEG" [TightJPEGEncoder L43][TJE]. `EncodeManager` only selects a JPEG encoder that reports `isSupported()` [EncodeManager L405][EM405].
- **TurboVNC 3.3.1**: `cl->tightQualityLevel` initialises to **-1** [rfbserver L443][RS443] and is set only from a -23..-32 or fine-grained pseudo-encoding [rfbserver L1178][RS1178]. Every `SendJpegRect` call site is guarded by `qualityLevel != -1` [turbo tight.c L820][TT820].

So a client offering encoding 7 and none of -23..-32 / -412..-512 / -763..-768 receives no JPEG rectangles from either. Caveat: that is a property of these two servers at these versions. Nothing in the wire format prevents a non-conforming server from sending `0x9_`, so a decoder without JPEG support should fail loudly rather than silently.

## 9. What a from-scratch decoder gets wrong

- **Ordering is mandatory.** The four zlib streams are per-connection and stateful across rectangles *and* across FramebufferUpdate messages. Tight rectangles must be decoded in the order received; they cannot be decoded out of order or in parallel without tracking which stream each touches. TigerVNC's parallel decoder computes an explicit conflict predicate over stream ids and reset bits before letting two rects run concurrently [TightDecoder L236][TD236].
- **Stream lifetime is the whole connection**, not the rectangle or the update. Reset only on an explicit bit 0–3, and reset even for Fill and JPEG rects (NOTE1, 3620–3625).
- **Servers differ in how they use the four streams.** TigerVNC pins stream 0 to full-colour, 1 to mono, 2 to indexed, and never sets a reset bit [TightEncoder L169][TE169]; TurboVNC rotates round-robin through a per-thread range of ids [turbo tight.c L955][TT955]. Maintain all four independently — assuming only stream 0 is live works against TigerVNC and fails against TurboVNC.
- **A zlib stream is not "one deflate blob per rectangle."** The server sync-flushes at each rectangle boundary and keeps the dictionary. Feed the decompressor the rectangle's bytes and ask for exactly `height * rowSize` output, retaining state for the next rectangle. Reading "until end of stream" hangs.
- **The compressed-vs-uncompressed choice is not signalled on the wire.** It is derived from the decoder's own `height * rowSize < 12` computation (§6), which depends on palette size and TPIXEL width. Getting the TPIXEL condition wrong silently desynchronises the byte stream rather than merely producing a wrong-looking image.
- **SetPixelFormat changes TPIXEL width mid-connection.** A client must not have an outstanding FramebufferUpdateRequest when it sends SetPixelFormat, precisely because the next update's format would be ambiguous [spec §SetPixelFormat][S-spf] (1691–1694); with ContinuousUpdates the Fence **SyncNext** flag exists for the same reason (2163–2167). The pixel format does *not* reset the zlib streams.
- **The filter byte is conditional** — present only when bit 6 is set, never for Fill or JPEG. Consuming it unconditionally (or never) is the most common framing bug.
- **Palette size is stored minus one.** A byte of 1 means two colours and therefore 1-bit rows. A byte of 0 (one colour) is not produced by the palette filter; a solid rectangle is sent as FillCompression instead.

<!-- citations -->
[S-tight]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#tight-encoding
[S-zrle]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#zrle-encoding
[S-png]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#tight-png-encoding
[S-jq]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#jpeg-quality-level-pseudo-encoding
[S-cl]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#compression-level-pseudo-encoding
[S-nz]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#tight-encoding-without-zlib-pseudo-encoding
[S-spf]: https://github.com/rfbproto/rfbproto/blob/152107db63cd34b3536ad8ddf54a0cfc9017a9f9/rfbproto.rst#setpixelformat
[TC]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightConstants.h
[TJE]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightJPEGEncoder.cxx#L43-L63
[TJE93]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightJPEGEncoder.cxx#L93
[TD104]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightDecoder.cxx#L104-L108
[TD236]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightDecoder.cxx#L236-L258
[TD269]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightDecoder.cxx#L269-L285
[TD388]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightDecoder.cxx#L388-L397
[TD545]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightDecoder.cxx#L545-L588
[TE169]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightEncoder.cxx#L169
[TE246]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/TightEncoder.cxx#L246-L260
[EM52]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/EncodeManager.cxx#L52-L55
[EM405]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/EncodeManager.cxx#L405-L435
[PF]: https://github.com/TigerVNC/tigervnc/blob/b555312d70d7ff017f866649a7e7167af4eb8fca/common/rfb/PixelFormat.cxx#L204-L225
[TT41]: https://github.com/TurboVNC/turbovnc/blob/afb793371a79240171f6eadb7bbcee2aaa422b44/unix/Xvnc/programs/Xserver/hw/vnc/tight.c#L41
[TT88]: https://github.com/TurboVNC/turbovnc/blob/afb793371a79240171f6eadb7bbcee2aaa422b44/unix/Xvnc/programs/Xserver/hw/vnc/tight.c#L88-L91
[TT820]: https://github.com/TurboVNC/turbovnc/blob/afb793371a79240171f6eadb7bbcee2aaa422b44/unix/Xvnc/programs/Xserver/hw/vnc/tight.c#L820-L876
[TT955]: https://github.com/TurboVNC/turbovnc/blob/afb793371a79240171f6eadb7bbcee2aaa422b44/unix/Xvnc/programs/Xserver/hw/vnc/tight.c#L955-L966
[RS443]: https://github.com/TurboVNC/turbovnc/blob/afb793371a79240171f6eadb7bbcee2aaa422b44/unix/Xvnc/programs/Xserver/hw/vnc/rfbserver.c#L443-L444
[RS1178]: https://github.com/TurboVNC/turbovnc/blob/afb793371a79240171f6eadb7bbcee2aaa422b44/unix/Xvnc/programs/Xserver/hw/vnc/rfbserver.c#L1178-L1192
[LVS38]: https://github.com/LibVNC/libvncserver/blob/42494999e6492aaab9c1db785ecd293ef10b3aed/src/libvncclient/tight.c#L38
[LVS253]: https://github.com/LibVNC/libvncserver/blob/42494999e6492aaab9c1db785ecd293ef10b3aed/src/libvncclient/tight.c#L253-L280
[LVS254]: https://github.com/LibVNC/libvncserver/blob/42494999e6492aaab9c1db785ecd293ef10b3aed/src/libvncclient/tight.c#L254-L255
[LVS384]: https://github.com/LibVNC/libvncserver/blob/42494999e6492aaab9c1db785ecd293ef10b3aed/src/libvncclient/tight.c#L384-L392
[LVS484]: https://github.com/LibVNC/libvncserver/blob/42494999e6492aaab9c1db785ecd293ef10b3aed/src/libvncclient/tight.c#L484-L534

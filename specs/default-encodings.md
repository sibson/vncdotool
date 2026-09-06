# Offering more than Raw by default

`vncdo` offers `tight,zrle,hextile,raw` unless `--encodings` says otherwise.
This is the measurement behind that list and the reasoning behind its order.

## What the encodings actually cost

Measured off the committed goldens — the same eight scenes, recorded from
tigervnc 1.12.0 at bgrx8888. Wire bytes are the server's own, read back out of
the fixtures. Decode medians were taken in one sitting on one machine, after
the palette expansion moved into C (#460).

| encoding | wire bytes | vs Raw | decode | vs Raw |
|---|---:|---:|---:|---:|
| Raw | 1,172,928 | 1.000x | 615 us | 1.0x |
| CoRRE | 1,172,928 | 1.000x | 609 us | 1.0x |
| RRE | 536,616 | 0.458x | 975 us | 1.6x |
| Hextile | 410,330 | 0.350x | 6987 us | 11.4x |
| ZRLE | 278,750 | 0.238x | 33,162 us | 53.9x |
| Tight | 279,025 | 0.238x | 1537 us | 2.5x |
| Tight, JPEG level 9 | 281,600 | 0.240x | 2275 us | 3.7x |

Three things fall out of that table.

**Tight dominates ZRLE outright here.** Same bytes to a tenth of a percent,
and 22x cheaper to decode. Wherever a server offers both, we want Tight.

**CoRRE is Raw.** tigervnc answers a CoRRE request with Raw, which is why
`EMITTED_BY_TIGERVNC` omits it. Both the byte count and the decode time are
Raw's, because the fixture is Raw rectangles. It has no place in a default
list.

**JPEG buys nothing on this catalogue and costs exactness.** It is 2,575 bytes
*larger* than lossless Tight. That is a property of these scenes — flat fills
and palettes, which lossless filters handle better than a DCT — and would
invert on photographic content. It is why JPEG stays opt-in behind
`--jpeg-quality`, and why a JPEG rectangle nobody asked for is refused rather
than decoded: a silently lossy capture is the wrong failure for a tool whose
main job is capturing screens for comparison.

## The default list

Ordered by preference, and every entry earns its place by covering servers the
one before it does not:

- **Tight** — best bandwidth and the cheapest compressed decode. Confirmed
  emitted by tigervnc; the fleet's libvncserver-example answers with Raw.
- **ZRLE** — the same bandwidth as Tight, and in RFB 3.8 core, so it is the
  natural second ask for a server without Tight. Expensive to decode, which is
  survivable in a fallback and is why it is not first.
- **Hextile** — older and in wider reach than either, and the last stop before
  giving up on compression.
- **Raw** — mandatory, and explicit here so the list reads as the full
  preference order rather than relying on the server's fallback.

Dropped: CoRRE and RRE. CoRRE is Raw in practice. RRE sends more than Hextile
(0.458x against 0.350x), and both are old enough that a server offering RRE
almost certainly offers Hextile too, so listing RRE would only change what
happens on a server that has RRE and nothing else — which the fleet has no
example of.

The list is ordered by bytes, not by decode cost. RRE decodes far cheaper than
Hextile (1.6x Raw against 11.4x) and Tight cheaper than both, so an ordering
that optimised CPU would look different. Bandwidth is why a user reaches for
these encodings; the CPU is ours to keep reasonable, and the place to do that
is our implementation, not the preference list.

`copyrect` is deliberately left out pending measurement. It is not an
alternative to the others but a complement — it encodes a moved rectangle as a
source offset — so it neither competes with Tight nor is exercised by the
scene catalogue, which never scrolls. Most viewers enable it always. It should
be added once there is a scene that moves content and a number to point at.

## What it costs users

`vncdo` sends less data and uses more CPU. Captures stay exact: every encoding
on the list is lossless. Scripts that pass `--encodings` are unaffected.

The standing risk is a server that mis-implements an encoding now requested by
default, where before everyone got Raw. CI exercises Tight against tigervnc,
x11vnc, UltraVNC, macOS Screen Sharing and QEMU/KVM; libvncserver-example
falls back to Raw for Tight, which is itself a useful proof that the fallback
path works.

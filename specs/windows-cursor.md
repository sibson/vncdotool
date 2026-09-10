# What Windows VNC servers do with the pointer

`specs/cursor-default.md` rests on a convention: a server that is offered the
Cursor pseudo-encoding (-239) stops compositing the mouse pointer into the
framebuffer. Neither RFC 6143 nor rfbproto requires that — both say only that
the client "is capable of drawing a mouse cursor locally" — so the fleet was
measured, and every fleet server held to it.

Then CI measured UltraVNC on Windows and it did not. This is why, and what
the other Windows servers do.

## The short answer

UltraVNC's gate is its own. The *class* of behaviour is not.

On Windows the pointer is never in what the server grabs: GDI screen capture
excludes the hardware cursor, so all three servers composite it in
deliberately. What differs is what turns that off, and none of the three
turns it off on -239 alone.

| server | gate on "stop painting, send a shape" |
|---|---|
| UltraVNC 1.6.x | requires **-232 PointerPos** as well as -239 |
| TightVNC 2.8.x | whoever moved the pointer last |
| TigerVNC WinVNC 1.16 | whoever moved the pointer last, plus a one-second grace |

## UltraVNC requires PointerPos

`winvnc/winvnc/vncclient.cpp:3114`, run after the whole `SetEncodings` list
has been parsed:

```c
if (!m_client->m_use_PointerPos) {
    if (!m_client->m_ForceCursorShape) {
        m_server->EnableXRichCursor(FALSE);
        m_client->m_encodemgr.EnableXCursor(FALSE);
        m_client->m_encodemgr.EnableRichCursor(FALSE);
    }
}
```

`m_use_PointerPos` is set only by `rfbEncodingPointerPos`, which
`rfb/rfbproto.h:551` defines as `0xFFFFFF18` — **-232**.

The gate is UltraVNC's; the number is not, and rfbproto is no help in
settling it. That document names PointerPos twice and contradicts itself:
`-225` in its registry of other encodings (`rfbproto.rst:3118`), and `-232`
in the Tight capability table under vendor `TGHT`, signature `POINTPOS`
(`:1606`) — inside the same registry's own "`-226 to -238` Tight options"
row. Neither table is accompanied by a wire format; the pseudo-encoding
sections never specify the rectangle.

Implementations settle it unanimously for `-232`, and none was found using
`-225`: UltraVNC `rfbproto.h:551`, TightVNC `EncodeOptions.cpp`,
libvncserver, TurboVNC and QEMU all define `0xFFFFFF18`. All three that send
it send the same thing — a bare 12-byte rectangle header, position in `x`
and `y`, `w=h=0`, no payload (UltraVNC `vncclient.cpp:6298`, TightVNC
`UpdateSender.cpp`, libvncserver `cursor.c:rfbSendCursorPos`). Confirmed on
the wire against libvncserver:

    Received <Encoding.PSEUDO_POINTER_POS: -232> rectangle 0x0+20+20

So a client offering -239 and not -232 has its RichCursor request accepted
during the loop and revoked at the end of it. UltraVNC then behaves exactly
as it does for a client that cannot draw cursors: it paints the pointer and
sends no Cursor rectangle. That matches what CI saw — a 12x19 region, the
size of a Windows arrow, changing at each pointer position.

`[admin] ForceCursorShape=1` in `ultravnc.ini` is the server-side override
(`SettingsManager.cpp:377`, default 0). The CI setup deliberately leaves it
alone: setting it would configure the server around what `vncdo` does not
offer, which is the thing being measured.

This is the same defect TigerVNC's viewer hit in
[TigerVNC#1342](https://github.com/TigerVNC/tigervnc/pull/1342), closed
`notourbug`.

## TightVNC and TigerVNC gate on who moved the pointer

TightVNC, `fb-update-sender/CursorUpdates.cpp:76`, with RichCursor enabled
and PointerPos not: a move by the server switches to painting the pointer and
sends a **0x0** shape to blank the client's copy; a move by the client
switches the other way, restores the framebuffer behind the pointer, and
sends the real shape.

TigerVNC, `common/rfb/VNCSConnectionST.cxx:401`:

```cpp
if (!client.supportsLocalCursor())
    return true;
if ((server->getCursorPos() != pointerEventPos) &&
    (time(nullptr) - pointerEventTime) > 0)
    return true;
```

Same idea, expressed as a guess about who last moved the pointer, with the
comment above it admitting as much: "Unfortunately we can't know for sure."

Both therefore answer -239 correctly for a client that has just moved the
pointer, and paint for one that has not. `vncdo` always moves the pointer
immediately before capturing, so both should measure clean — but the
guarantee is "no pointer if you moved it recently", not "no pointer".

## Offering -232 is safe, and the client had to change first

SetEncodings says "a server which does not support the extension will simply
ignore the pseudo-encoding", and that is what was measured: TigerVNC has no
PointerPos code at all, neatvnc never defines it, and QEMU defines the
constant but never reads it. None of them so much as noticed.

The breakage was on the client side. `rfb.py:_handleRectangle` aborts on an
encoding it has no decoder for, and libvncserver and x11vnc send the
rectangle as soon as it is asked for -- so `PointerPosDecoder` had to exist
before `-232` could be offered at all. With it, the whole fleet's answers are
unchanged and no server aborted.

## What this still does not measure

Whether `--localcursor` reproduces what a Windows server paints. UltraVNC and
TightVNC implement no alpha cursor encoding -- only `-240` and `-239`, whose
mask is one bit per pixel -- while the pointer they composite into the
framebuffer is a 32-bit ARGB Windows cursor with antialiased edges. So the
server's own render and the client's composite may differ at the edge, and
`specs/cursor-default.md`'s claim that the composite is faithful was measured
on x11vnc and libvncserver only.

The instrument is cheap: a capture from before `-232` (UltraVNC painting)
against one after it with `--localcursor`, same pointer position. Both are
already uploaded by the `cursor-evidence` artifact step.

RealVNC is not in the matrix. Its Windows server needs an account and a
licence key even on the free tier, which is not something to install
unattended on a CI runner. TigerVNC's WinVNC is the closest free descendant
of the RealVNC 4 codebase, which is what issue #206 was reported against.

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
`rfb/rfbproto.h:551` defines as `0xFFFFFF18` — **-232**. The gate is
UltraVNC's, but the number is not: rfbproto's Tight capability registry
assigns it to vendor `TGHT` under the signature `POINTPOS`, "Pointer
Position". It is absent only from the narrower list of pseudo-encodings that
document goes on to specify, so there is no written wire format for it. Every
implementation found agrees on one anyway — a bare 12-byte rectangle header
with `w=h=0` and no payload: UltraVNC `vncclient.cpp:6298`, TightVNC
`UpdateSender.cpp`, libvncserver `cursor.c:rfbSendCursorPos`. TurboVNC and
QEMU define the same constant and signature.

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

## What this does not measure

Whether offering -232 makes UltraVNC behave. It would, by the source above,
but `rfb.py:_handleRectangle` aborts the connection on an encoding it has no
decoder for, and UltraVNC's PointerPos rectangle is a bare 12-byte header
with `w=h=0` (`vncclient.cpp:6298`). Offering -232 without first adding a
decoder that consumes nothing would turn a working UltraVNC session into
`unknown encoding received`. Two things would have to change together:

* `const.py:72` calls -225 `POINTER_POS`. That number is unassigned in
  rfbproto's registry; -232, which is assigned, currently falls inside the
  undefined `TIGHT_226 = -226  # ... -238` span and so is not a member at all.
* A decoder for it, and -232 appended in `client.py` beside `PSEUDO_CURSOR`.

Offering it is safe for servers that do not implement it -- SetEncodings says
"a server which does not support the extension will simply ignore the
pseudo-encoding", and TigerVNC (no PointerPos code at all), neatvnc and QEMU
(which defines the constant but never reads it) were measured doing exactly
that. The breakage is on the client side: libvncserver and x11vnc send the
rectangle as soon as it is asked for, and today that aborts the connection.

RealVNC is not in the matrix. Its Windows server needs an account and a
licence key even on the free tier, which is not something to install
unattended on a CI runner. TigerVNC's WinVNC is the closest free descendant
of the RealVNC 4 codebase, which is what issue #206 was reported against.

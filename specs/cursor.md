# The mouse pointer in a capture

`vncdo --cursor` chooses one of three things a capture can do about the mouse
pointer. The default omits it, which is a change: captures used to contain
whatever the server painted, at whatever position the last `move` left it.

| `--cursor` | offers | capture contains |
|---|---|---|
| `none` (default) | `-239`, `-232` | no pointer, bar a server that paints one regardless |
| `server` | neither | whatever the server paints |
| `local` | `-239`, `-232` | the shape the server sent, drawn by us |

`--localcursor` and `--nocursor` still work, as aliases for `local` and
`none`. They are in users' scripts, and turning a working script into a usage
error is a worse trade than carrying two aliases. `api.connect(cursor=...)`
takes the same three values.

## Two pseudo-encodings, two halves of one job

**Cursor (-239)** carries the *shape*: the rectangle's `x`/`y` are the
hotspot, `w`/`h` the size, then `w*h` pixels and a
`floor((w + 7) / 8) * h` bitmask.

**PointerPos (-232)** carries the *position*: `x`/`y` are where the pointer
now is, `w = h = 0`, no payload at all.

Drawing a pointer locally needs both. Usually the client already knows the
position, because the client is what moved it — which is why `-239` alone is
normally enough. The gap is a pointer moved by something else: a person at
the physical keyboard, another client sharing the session, or the desktop
warping it. Then the client's idea of where the pointer is has gone stale,
and `-232` is the only channel that says so.

Neither number is well specified. RFC 6143 and rfbproto say only that a
client requesting Cursor "is declaring that it is capable of drawing a mouse
cursor locally" — never that the server must stop compositing. PointerPos is
worse: rfbproto names it twice and disagrees with itself, `-225` in its
registry of other encodings (`rfbproto.rst:3118`) and `-232` in the Tight
capability table under vendor `TGHT`, signature `POINTPOS` (`:1606`), inside
that same registry's own "`-226 to -238` Tight options" row. Neither table
gives a wire format.

Implementations settle it unanimously for `-232`, and none was found using
`-225`: UltraVNC, TightVNC, libvncserver, TurboVNC and QEMU all define
`0xFFFFFF18`. All three that send it send a bare 12-byte header (UltraVNC
`vncclient.cpp:6298`, TightVNC `UpdateSender.cpp`, libvncserver
`cursor.c:rfbSendCursorPos`).

So the default rests on convention, not on a requirement, and was measured
rather than assumed.

## What servers actually do

On Unix the pointer is usually absent from the framebuffer to begin with. On
Windows it never is: GDI screen capture excludes the hardware cursor, so
every Windows server composites it in deliberately, and what turns that off
differs per server.

| server | paints the pointer | stops when offered `-239` |
|---|---|---|
| tigervnc, +auth/vencrypt variants | no | n/a, answers 0x0 |
| wayvnc, qemu, qemu-tls | no | n/a, answers nothing |
| selenoid | no | n/a, answers 0x0 |
| x11vnc | **yes**, 18x18 | yes |
| libvncserver-example | **yes**, 32x32 | yes |
| **UltraVNC** | **yes**, 12x19 | **no, even offered `-232`** |
| **TightVNC** | **yes** | only when this client moved the pointer |
| **TigerVNC WinVNC** | **yes** | only when this client moved the pointer |

`tests/functional/test_cursor.py` and `cursor_report.py` keep this table
honest; the Windows rows come from the `os-servers` workflow, which is the
only place those three run.

### UltraVNC sends the shape and paints it anyway

`winvnc/winvnc/vncclient.cpp:3114`, after the whole `SetEncodings` list has
been parsed:

```c
if (!m_client->m_use_PointerPos) {
    if (!m_client->m_ForceCursorShape) {
        m_server->EnableXRichCursor(FALSE);
        m_client->m_encodemgr.EnableXCursor(FALSE);
        m_client->m_encodemgr.EnableRichCursor(FALSE);
    }
}
```

A client offering `-239` and not `-232` has its request accepted during the
loop and revoked at the end of it, and gets no shape. This is the same
defect TigerVNC's viewer hit in TigerVNC#1342, closed `notourbug`. `[admin]
ForceCursorShape=1` is the server-side override;
`tests/servers/ultravnc/setup.ps1` deliberately leaves it alone, because
setting it would configure the server around what `vncdo` does not offer.

Offering `-232` keeps the shape, and nothing more. Measured on a runner with
both offered: UltraVNC answers `-239` with a 32x32 rectangle, answers `-232`
with the position, and still composites a 12x19 arrow into the framebuffer
at the pointer. The code above governs only what the server sends; what it
paints is a separate switch. A client that asks for the shape and gets it
therefore has to discard it, or draw it twice.

### TightVNC and TigerVNC guess who moved it

TightVNC, `fb-update-sender/CursorUpdates.cpp:76`, with Cursor enabled and
PointerPos not: a move by the server switches to painting and sends a 0x0
shape to blank the client's copy; a move by the client switches the other
way, restores the framebuffer behind the pointer, and sends the real shape.

TigerVNC, `common/rfb/VNCSConnectionST.cxx:401`:

```cpp
if (!client.supportsLocalCursor())
    return true;
if ((server->getCursorPos() != pointerEventPos) &&
    (time(nullptr) - pointerEventTime) > 0)
    return true;
```

Both are the missing position channel, reconstructed by guessing — the
comment above TigerVNC's admits as much: "Unfortunately we can't know for
sure." Offering `-232` makes TightVNC's branch unreachable: with both
enabled, neither of its two `drawCursor` paths matches.

## Why the default is `none`

The pointer is nondeterministic content. Where it is depends on wherever the
last `move` left it, and whether it appears at all depends on which server
answered. Both `expect` and `stable` compare the whole framebuffer, so a
painted pointer is the same class of failure `specs/screen-stability.md`
already names for a blinking cursor.

The test suite had already paid for this. `X11VNC` carried a permanent
`extra_args=("--nocursor",)` so the scene and pixel-format grids, which
compare `screen.tobytes()` byte for byte, would not trip over it;
`tests/goldens/capture.py` recorded that flag into every fixture. A
workaround the harness needs on every server that paints is a wrong default.

Library callers could not reach the flag at all. `ThreadedVNCClientProxy`
defines `__getattr__` but no `__setattr__`, so the `client.nocursor = True`
of #206 assigns a dead attribute on the proxy and returns. `connect(cursor=)`
is where it has to be set instead.

## What it costs

A capture that used to contain a pointer no longer does. Anyone diffing
screenshots across the upgrade sees it, and vncdotool's users are exactly the
people who diff screenshots — #206 is template matching in OpenCV.
`--cursor local` draws it back, and on x11vnc and libvncserver it is the
server's own render pixel for pixel:
`test_localcursor_matches_the_server_side_render` asserts exactly that, by
capturing once in each mode and requiring no difference.

That test is the reason `server` exists. Without it the server's own render
is not obtainable and the claim above is unfalsifiable.

## Rejected: defaulting to `local`

It preserves today's pixels and needs no deprecation story. But it keeps
pointer-dependent content inside every `expect` comparison, which is the
problem being solved, and it makes every capture depend on the destructive
`drawCursor` paste (`specs/decoder-architecture.md`). On the servers that
never paint a pointer it changes nothing at all, so it does not even buy
consistency.

## Rejected: three separate flags

`--localcursor`, `--nocursor` and a new `--server-cursor` would reach the
same three states. Three cursor flags on a tool whose two already confuse
people is worse than one flag with three values, and the two that exist can
be kept as aliases either way.

## What `vnclog` does

`VNCLoggingServerFactory` keeps its own `cursor`, which stays `NONE`, so the
observer discards a cursor rectangle instead of compositing one. It forwards
the downstream client's SetEncodings verbatim and only observes, so it cannot
be used to obtain a server-side render either.

## Still unmeasured

Whether `--cursor local` is faithful on Windows. UltraVNC and TightVNC
implement no alpha cursor encoding — only `-240` and `-239`, whose mask is
one bit per pixel — while the pointer they composite is a 32-bit ARGB Windows
cursor with antialiased edges. The composite may therefore differ at the
edge, and the faithfulness claim above was measured on x11vnc and
libvncserver only.

`test_localcursor_matches_the_server_side_render` is the instrument, and runs
on the fleet today. Registering it for the Windows servers is what would
answer this.

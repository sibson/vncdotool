# The mouse pointer in a capture

`vncdo --cursor` chooses one of three things a capture can do about the mouse
pointer. The default omits it, which is a change: captures used to contain
whatever the server painted, at whatever position the last `move` left it.

| `--cursor` | offers | capture contains |
|---|---|---|
| `none` (default) | `-239`, `-232` | no pointer, on any server |
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
| qemu, qemu-tls | no | n/a, answers nothing |
| wayvnc | for the first ~70ms after a move, then removes it | n/a, answers nothing |
| selenoid | no | n/a, answers 0x0 |
| x11vnc | **yes**, 18x18 | yes |
| libvncserver-example | **yes**, 32x32 | yes |
| **UltraVNC** | **yes** | **usually, if `-232` was offered too -- not reliably, see below** |
| **TightVNC** | **yes** | only when this client moved the pointer |
| **TigerVNC WinVNC** | **yes** | only when this client moved the pointer |

`tests/functional/test_cursor.py` and `cursor_report.py` keep this table
honest; the Windows rows come from the `os-servers` workflow, which is the
only place those three run, against a real interactive desktop rather than
a container. That desktop is not otherwise quiet: the runner's own
hosted-compute-agent console covers nearly the whole screen and scrolls
continuously, and Explorer highlights whatever desktop icon the pointer
lands on. `os-servers.yml` minimizes every window before a single capture
runs, which is what makes the desktop content-stable at all; `CURSOR_NEAR`
sits clear of the default icon column for the same reason.

### UltraVNC requires PointerPos

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
loop and revoked at the end of it. UltraVNC then behaves as it does for a
client that cannot draw cursors at all: it paints, and sends no shape. This
is the same defect TigerVNC's viewer hit in TigerVNC#1342, closed
`notourbug`. `[admin] ForceCursorShape=1` is the server-side override;
`tests/servers/ultravnc/setup.ps1` deliberately leaves it alone, because
setting it would configure the server over what `vncdo` does not offer.

Offering both is not a complete fix, though. Two back-to-back `vncdo`
connections against the same UltraVNC instance in CI -- one moving the
pointer and capturing, disconnecting, then a second doing the same at a
different position -- showed the first capture clean and the second
containing a real Windows arrow cursor baked into an ordinary Tight
rectangle at the pointer's new position, `vncclient.cpp:3114`'s own
revocation logic notwithstanding. Nothing in what `vncdo` offers differed
between the two connections; whatever decided to paint anyway did so
server-side. `CursorPositionIndependent` (`tests/functional/utils.py`) is
not registered for `ULTRAVNC` (`cursor_position_unverifiable=True`)
because of this -- the wire-level check that Cursor and PointerPos are
both answered still runs and still passes. Root-causing the intermittency
needs access to a real UltraVNC install this repo does not have.

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

## The pointer is an overlay, not framebuffer content

`self.screen` holds the server's pixels and nothing else. Under `--cursor
local` the shape is kept as client state — `cursor`, `cmask`, `cfocus` — and
`renderScreen()` and `renderRegion()` composite it onto a copy at the moment
an image is asked for.
`updateCursor` and `updatePointerPos` record; they do not draw.

Capture, `expect`/`expectRegion` and `stable`/`stableRegion` all read through
the same pair, so all four see the same image. Compositing for the
comparisons as well as the captures is what makes a reference image usable:
`vncdo --cursor local capture ref.png` writes the pointer into `ref.png`, and
an `expect ref.png` in the same mode has to be comparing against something
that contains one. A script that wants pointer-free comparisons has the
default mode, which is the reason the default is `none`.

## One pointer, one position

`self.x`/`self.y` is where the pointer is, and it is the only answer to that
question. `mouseMove` sets it, `updatePointerPos` sets it, whichever moved
the pointer last. `renderScreen` draws there and `mouseDown`/`mouseUp` click
there. So on a desktop where something else moves the pointer — a person at
the physical keyboard, another client sharing the session — a `click`
following a `move` lands where that other thing left it, and a script that
wants it elsewhere moves the pointer there first.

### Except for a report that predates the move

A `-232` arriving within `POINTER_POS_SETTLE` of this client's own
`mouseMove` is discarded. x11vnc polls the X pointer rather than reading back
the event it just acted on, so between acting on a move and its next poll it
still holds the old position — and `cursor_position()` in
`x11vnc/src/cursor.c` reads that disagreement as a third-party warp and
reports the pre-move position. Believing it walks the pointer backwards: the
arrow is drawn where the pointer no longer is, and the next `click` goes
there too.

Neither the disagreement nor an agreement can settle this on its own.
Suppressing the echo to whoever moved the pointer is deliberate in both
servers whose source says so — libvncserver's `rfbDefaultPtrAddEvent`
("The cursor was moved by this client, so don't send CursorPos") and
x11vnc's own `last_pointer_client` case — so waiting for the server to
confirm our position would wait on a message a correct server will not send.
Only elapsed time separates a report that raced our move from one that
followed it, which is what TigerVNC's `pointerEventTime` comparison
(`common/rfb/VNCSConnectionST.cxx:401`) is also reduced to.

A report that agrees with the move is discarded along with the rest, and
costs nothing: `self.x`/`self.y` already holds that position. What the window
does give up is a genuine third-party move inside it, and a script moving the
pointer continuously — `mouseDrag` steps every 0.2s — restamps the window
faster than it expires, so `-232` is suppressed for the whole drag. A script
issuing a move every 0.2s has its own answer for where the pointer is.

`tests/functional/test_cursor.py` cannot be relied on to catch a regression
here. Whether x11vnc's poll lags at all varies with the state of the desktop
it is serving: the same fleet reproduced the stale report several times an
hour while the pointer sat over a window setting its own 16x16 cursor, and
not once after a restart put an 18x18 root-window cursor back under it.
`tests/unit/test_decoder_pointer_pos.py` is the instrument.

## What the capture waits for

`test_cursor.py`'s `at_each()` moves the pointer, pauses `CURSOR_SETTLE`, and
captures, once per position over one connection. That pause is there for
wayvnc and for nothing else.

Measured on the docker fleet, Docker Desktop on macOS, the near/far pair
taken over one `vncdo` connection and compared over `cursor_box()` exactly as
`assert_pointer_position_is_invisible` does:

| pause | wayvnc pairs carrying a pointer |
|---|---|
| omitted | 12/20 |
| 0.05 | 20/20 |
| 0.06 | 20/20 |
| 0.08 | 0/20 |
| 0.1 | 0/20 |
| 0.2 | 0/20 |
| 0.5 | 0/20 |

Taking each capture over its own connection gave the same edge: dirty
through 0.06, clean from 0.08. The artifact is a real arrow at the pointer,
10x16 and pixel-identical run to run, so wayvnc composites the pointer on the
move and takes it back out again between 60ms and 80ms later. `CURSOR_SETTLE`
is 0.2 to leave room on slower hardware. Every other fleet server --
tigervnc and its three variants, x11vnc, libvncserver-example, qemu,
qemu-tls -- was clean 10/10 with the pause omitted entirely.

The pause is not the detection window for a server that starts painting
again, which is what a settle before a capture looks like it must be for.
With x11vnc and libvncserver-example forced back into painting by
`--cursor server`, the pointer is in the framebuffer before the capture's own
refresh returns: over 30 moves each, the first full capture after the move
already carried it, at a median 16ms and 61ms respectively -- which is the
capture round trip itself, 20ms and 59ms measured with nothing moving. The
same near/far comparison run over the CLI caught the painted pointer 15/15 at
every pause tried, including none, on both servers. A capture cannot observe
the framebuffer without asking for it, and the asking already costs more than
the paint.

`CursorShapeOffered` and `CursorPositionIndependent` (`utils.py`) keep their
own 0.5s pauses: both also run against the Windows servers of the
`os-servers` workflow, on a real interactive desktop that none of this
measured.

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
problem being solved. On the servers that never paint a pointer it changes
nothing at all, so it does not even buy consistency.

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

# Keeping the pointer out of captures by default

`vncdo` offers the Cursor pseudo-encoding on every connection and discards the
shape unless `--localcursor` asks for it drawn. Captures therefore contain no
mouse pointer, whatever the server would otherwise have painted. This is the
measurement behind that and the reasoning behind the flags that survive it.

## What the wire actually guarantees

RFC 6143 and rfbproto say only that a client requesting Cursor "is declaring
that it is capable of drawing a mouse cursor locally", and then give the
pseudo-rectangle's layout: hotspot in *x-position*/*y-position*, then
`width * height` pixels, then a `floor((width + 7) / 8) * height` bitmask.

Neither document says the server must stop compositing the pointer into the
framebuffer once a client asks. That it does is convention, and the whole
behaviour below rests on it, so it was measured rather than assumed.

## What the fleet does

Each server driven through the real CLI: `move 50 50`, `pause 0.5`, `capture`,
in all three modes, every mode captured twice so scene churn is separated from
the effect. The noise column is that control; both x11vnc and qemu produced a
spurious difference on a single-pass run before it was added.

| server | noise | default vs `--nocursor` | `--nocursor` vs `--localcursor` | default vs `--localcursor` |
|---|---|---|---|---|
| tigervnc | none | identical | identical | identical |
| x11vnc | none | differs (50,50)-(60,66) | differs (50,50)-(60,66) | **identical** |
| libvncserver-example | none | differs (35,27)-(65,57) | differs (35,27)-(65,57) | **identical** |
| qemu | blinking text cursor | identical | identical | identical |

Three things fall out.

**Two of four servers paint the pointer, and stop when asked.** `--nocursor`
cannot un-paint framebuffer pixels — it only discards a Cursor
pseudo-rectangle in `updateCursor`. So x11vnc's and libvncserver's pointer
disappearing under `--nocursor` is proof that those servers stopped
compositing it the moment `-239` appeared in SetEncodings.

**The client-side composite is faithful.** On both servers that paint,
`--localcursor` reproduces the server's own render pixel for pixel, hotspot
included. Asking for Cursor therefore costs a user nothing they cannot get
back.

**Nothing loses a pointer irrecoverably.** tigervnc and qemu answer `-239`
with a degenerate 0x0 rectangle — the hide-pointer path of RFC 6143 7.6.1,
fixed in #449 — but neither painted one to begin with.

A four-move-then-capture run on x11vnc differs from `--nocursor` in exactly
the ten columns at the final position: no trail, because x11vnc repaints the
vacated region. `drawCursor` pastes destructively and has no undo (see
`specs/decoder-architecture.md`), so a server that did not repaint would smear.
None in the fleet does.

## Why the default changes

The pointer is nondeterministic content. Its position depends on wherever the
last `move` left it, and whether it appears at all depends on which server
answered — x11vnc and libvncserver paint it, tigervnc and qemu do not. Both
`expect` and `stable` compare the whole framebuffer, so a painted pointer is
the same class of failure `specs/screen-stability.md` already names for a
blinking cursor.

The test suite had already paid for this. `X11VNC` carried a permanent
`extra_args=("--nocursor",)` so the scene and pixel-format grids, which compare
`screen.tobytes()` against an oracle byte for byte, would not trip over the
pointer; `tests/goldens/capture.py` then recorded that flag into every
fixture's `conditions.json` so the replay could reproduce it. A workaround the
harness needs on every server that paints is a wrong default, not a fixture
detail.

Library callers could not reach the flag at all. `api.connect()` sets only
`username` and `password`, and `ThreadedVNCClientProxy` defines `__getattr__`
but no `__setattr__`, so the `client.nocursor = True` of #206 assigns a dead
attribute on the proxy and returns. That issue was closed as correctly
implemented, which it is for the CLI and never was for the library. The
default fixes it without adding API surface.

## What it costs users

A capture that used to contain a pointer no longer does, on any server that
composited one. Anyone diffing screenshots across the upgrade sees it, and
vncdotool's users are exactly the people who diff screenshots — #206 is
template matching in OpenCV. `--localcursor` draws it back, pixel-identical to
what the server used to send.

What becomes unreachable is the third state: not offering Cursor at all, and
letting the server paint. No flag restores it. That is deliberate — the only
server it would help is one that stops painting and then sends nothing usable,
which the fleet has no example of — but it is a real loss, and it costs one
test. `test_localcursor_matches_the_server_side_render` compared the client
composite against the server's own render, and the server's own render is no
longer something `vncdo` can obtain. `vnclog` does not provide a way round it:
it forwards the downstream client's SetEncodings verbatim and only observes.

The replacement asserts the property the change is for, and discriminates: a
capture must not depend on where the pointer is parked. Measured on x11vnc,
`move 50 50` against `move 200 150` differs across (50,50)-(210,166) under
today's default and is identical under the new one.

We keep `--nocursor` accepted as a no-op rather than removing it. It is in
users' scripts, removing it turns a working script into a usage error, and it
remains a truthful description of what happens.

## Rejected: a third flag

`--server-cursor`, meaning offer nothing and let the server paint, would keep
the old default reachable and keep the faithfulness test alive. It is the
strongest argument against this change and it still loses: three cursor flags
on a tool whose two already confuse people, added for one test and a server
nobody has produced.

## Rejected: defaulting `--localcursor` instead

It preserves today's pixels on the servers that matter and needs no
deprecation story. But it keeps pointer-dependent content inside every
`expect` comparison, which is the problem being solved, and it makes every
capture depend on the destructive `drawCursor` paste. On tigervnc and qemu it
changes nothing at all, so it does not even buy consistency.

## What `vnclog` does

`VNCLoggingServerFactory` keeps its own `pseudocursor`, which stays `False`, so
the observer discards a cursor rectangle instead of compositing one. Before
this change a downstream `vncdo` never offered `-239`, so no rectangle arrived
and nothing was composited; the observed screen is unchanged in the default
case. A downstream client that does ask for Cursor now gets a `vnclog`
screenshot without the pointer, which is the deterministic answer for captures
whose purpose is replay.

## Fixture migration

None. The eleven tigervnc fixtures were captured without `--nocursor`, so
their streams carry no `-239` rectangle and replay identically. The one x11vnc
fixture was captured with it, carries a single pseudo-cursor rectangle that
was discarded at capture time, and is discarded again on replay under the new
semantics. `conditions.json` loses its now-meaningless `nocursor` key and
`tests/unit/test_goldens.py` stops reading it; no stream is re-recorded.

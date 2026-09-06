# Screen Stability Design

Status: draft, under review. Sibling of the `expect` matching design; this is
the "Not in scope" item from it: blocking until the screen stops changing,
with no reference image.

## Problem

`expect FILE FUZZ` blocks until the screen matches a picture you already have.
Nothing blocks until the screen merely stops changing, and two callers want
exactly that.

`tests/goldens/scene-lossy.vdo` fakes it with `pause 1.5` between keystrokes
plus throwaway `capture step.png` calls, from when no fuzz separated a JPEG
rendering of the right scene from the wrong one. The metric that fixed that is
in [expect-matching.md](expect-matching.md), but a pause is still a guess: too
short and the capture tears, too long and the golden run pays for it eight
times over. Neither is a question about a reference image.

The stronger case is outside the test suite. An agent driving `vncdo` captures
a PNG and inspects it out of process; it cannot sit inside the reactor's
`expect` poll loop, because each turn through that loop costs it a model call.
What it needs before looking is "the screen has settled," which is a question
`expect` cannot ask without already knowing the answer.

## Command

    stable SECONDS [FUZZ]
    rstable SECONDS X Y W H [FUZZ]

FUZZ is optional and trails, as it does for `expect FILE [FUZZ]`, and is read
by the same `_trailing_fuzz`: a whole number in 0..255, or the next command
if it is not a number at all.

`SECONDS` is **the length of the trailing window during which the framebuffer
must have compared unchanged, within FUZZ, for the command to return.** It is
not a poll interval, not a delay, and not a timeout. `stable 1.5 0` returns
once 1.5 seconds have passed with no pixel change.

Two properties follow, and both belong in the user documentation:

- **Minimum runtime is always SECONDS.** Absence of change cannot be observed
  early. rfbproto's *FramebufferUpdateRequest* section says of an incremental
  request that "there may be an indefinite period between the
  *FramebufferUpdateRequest* and the *FramebufferUpdate*", so silence and
  slowness are the same observation. `stable 1.5` costs at least as much as the
  `pause 1.5` it replaces.
- **There is no upper bound.** Each qualifying change restarts the window, so
  the win over `pause` is at the top end, not the bottom: `pause 1.5` returns at
  1.5 s whether or not the repaint finished, where `stable 1.5` waits out however
  long the repaint actually takes and then proves 1.5 s of quiet.

### Why a region variant is not speculative

A server painting a clock or a blinking cursor never satisfies a whole-screen
window. Without `rstable` the only answer for those servers is "time out and
fail"; with it, the caller excludes the noisy corner and waits on the region it
cares about. That is the recovery path, not a symmetry exercise.

`rstable` needs all four geometry numbers. `rexpect FILE X Y [FUZZ]` gets away
with two because the reference image's own dimensions supply the width and
height; `rcapture FILE X Y W H` spells out all four because nothing else says
how big the region is. `stable` has no reference image, so it is an `rcapture`
in that respect.

Where the geometry goes is not a free choice: an optional argument has to be
last, so FUZZ trails and the geometry is infixed. That is `rexpect`'s shape
rather than `rcapture`'s, which the two existing region commands disagree
about — `rcapture` appends its geometry after the base command's arguments,
`rexpect` wedges X and Y in ahead of the fuzz. Optionality settles it.

## What "unchanged" compares

`imagematch.matches(frame, baseline, fuzz, blur)` is the comparison `expect`
uses, run against the previous frame instead of against a file. See
[expect-matching.md](expect-matching.md) for the metric and the measurements
behind it.

Nothing here needs its own comparison. What `stable` asks of a comparator is
what `expect` asks: that it see a small change on a large screen, and that it
not mistake a lossy re-encoding for one. Sharing it means FUZZ carries one
meaning across both commands, `--expect-fuzz` and `--expect-blur` reach both,
and the goldens that calibrated the metric calibrate this too.

One difference is worth knowing and not worth acting on. `expect` compares the
screen against a file that was written in some other pixel format, so its
default fuzz is what the negotiated format cannot express; `stable` compares
two frames that came from the same server in the same format, where that
quantisation cancels and the honest default would be 0. Sharing `--expect-fuzz`
is worth more than the two or three units this gives away.

## How the window is driven

Event-driven, on `commitUpdate`: the point where every rectangle of one
`FramebufferUpdate` message has been applied (`rfb.py:338`, `client.py:456`).
Nothing samples on a timer.

Per commit, against the last accepted frame:

- differs by more than FUZZ → adopt as the new baseline, restart the window
- differs by FUZZ or less → discard, leave the window running
- window reaches SECONDS → fire the deferred

The middle branch is the reason for pixel comparison over counting updates. A
Tight server re-encoding a region whose pixels did not meaningfully change
keeps the wire busy over a screen that is visually frozen; FUZZ is what decides
whether an arriving update *counts as change*, rather than a tolerance against
a reference.

Rectangle-level completeness needs no work here. One update message may carry
many rects, but `rfb.py:329` reads the count, calls `beginUpdate()`, consumes
that many, and only then commits, so no consumer ever observes a half-applied
message. What no message boundary marks is the end of a *logical* redraw, which
may span several updates. That is the gap `stable` fills, and RFB offers no
marker for it.

### Keeping a request outstanding

A server answers an incremental request only when something changes. So an
implementation that lets its request lapse hears nothing and reads its own
silence as stability, returning early for the wrong reason. **The window is only
valid while an incremental `FramebufferUpdateRequest` is pending throughout
it.** Re-arm on every commit, exactly as `_expectCompare` does at
`client.py:300`.

The client holds a single `self.deferred` slot, fired by `commitUpdate`, so
`stable` re-arms the same way `_expectCompare` does rather than holding a
deferred of its own across rounds.

With no baseline (`self.screen` is `None` on a fresh connection), the first
request is non-incremental to establish one, and the window starts after it
lands. `_expectCompare` already carries this shape.

`--incremental-refreshes` does not reach this command. The flag sets the
`incremental` argument to `captureScreen` (`command.py:254`); here the flag's
value is dictated by correctness, not preference, so `stable` chooses its own.

`--warp` does not scale SECONDS either, though it scales `pause`
(`command.py:279`). A pause is a scripted delay and replaying it at speed is
the point of the flag; this window is a threshold below which the screen is
not known to have settled, and shrinking it silently reintroduces the race the
command exists to remove.

## Timeout

`--timeout` covers it: exit status 40 (`ExitStatus.TIMEOUT`, `command.py:69`),
already documented under Exit Status in `docs/usage.rst`. No second timeout
argument.

A screen that changes more often than every SECONDS never satisfies the window
and hangs until that fires. There is deliberately **no "quietest window seen"
fallback**: a command that sometimes returns a frame it knows to be unstable
gives the caller no way to tell the two outcomes apart, and the caller in the
motivating case is an agent that believes it. Fail loudly; the recovery is
`rstable` over a calmer region, or a longer `--timeout`.

## Python API

    VNCDoToolClient.stableScreen(seconds, fuzz=None, blur=None) -> Deferred
    VNCDoToolClient.stableRegion(seconds, x, y, w, h, fuzz=None, blur=None) -> Deferred

Beside `expectScreen`/`expectRegion`, and resolving `fuzz` and `blur` through
the same `_expectFuzz`/`_expectBlur`. `stableRegion` calls `_requireOnScreen`,
so an off-screen region fails at once rather than settling against the black
padding `Image.crop` supplies.

`stableScreen` is not a verb phrase, unlike every neighbour — `captureScreen`,
`refreshScreen`, `expectScreen`. It buys a 1:1 mapping from the script command,
which is the property callers actually use when moving between `vncdo` and the
library. `waitStableScreen` reads better in isolation and breaks that mapping.

State for one call lives in a `_StableWatch`, not on the client: a baseline
frame, a timer and a settled flag outgrow the single `self.deferred` slot
`_expectCompare` threads its state through. The flag is load-bearing: after
the window fires, a commit can still arrive against the last armed deferred,
and without it the watch would re-arm and request forever.

## Out of scope

**Fence (-312) and ContinuousUpdates (-313).** Fence is a barrier, not an idle
detector: it reports that everything queued before it has been delivered, and
says nothing about future updates. It could tighten the window's start: do not
begin counting until a fence returns.

`rfb.py` now answers a server-initiated fence and can send a `ClientFence`, but
nothing yet initiates one and waits for it, which is what gating a window would
need; the pseudo-encoding is not even offered until something uses a fence.
ContinuousUpdates remains unimplemented. Neither is in RFC 6143, so a stability
test could not depend on them in any case.

## Testing

Unit, `tests/unit/test_client.py`: drive the protocol class with the mocked
transport the file already uses, and a `twisted.internet.task.Clock` for the
window, calling `commitUpdate` directly with prepared frames. Never start the
reactor. Cases worth one test each: window restarts on a change beyond FUZZ,
survives a repaint within FUZZ, a request stays outstanding across the window,
no baseline means a non-incremental first request.

Functional, against the fleet (`tests/functional/test_stable.py`): the window
is really waited out, and a window longer than `--timeout` exits 40.

What that suite cannot show is `stable` closing a race, because the fleet has
no race to close. `test_scene_player.py` captures behind a `pause 0.3` for a
repaint that is asynchronous to the key event, but a capture taken with no
wait at all reads the right scene every time — `capture` already blocks for a
whole-screen update. Proving the settling behaviour end to end needs a fixture
that animates and then stops, which the scene player is not. The two scene
tests in the suite are therefore smoke over a live server, and say so.

Then `tests/goldens/scene-lossy.vdo` loses its `pause 1.5` and its throwaway
`capture step.png` pairs, which is the change that shows whether any of this
works.

`CHANGELOG.md` gets an entry under `(UNRELEASED)`.

## Open questions

- Whether the default fuzz should be 0 rather than the pixel format's bound,
  since both frames come from the same server in the same format. It would
  cost `--expect-fuzz` reaching this command.
- Whether any common server sends periodic no-op updates that a pixel
  comparison would correctly ignore but that would still churn CPU on a large
  framebuffer. Not yet checked against the fleet.
- A fixture that animates and then stops, so the settling behaviour can be
  asserted end to end rather than only in unit tests.
- The `scene-lossy.vdo` migration below is not done; it needs the goldens
  regenerated, which is its own change.

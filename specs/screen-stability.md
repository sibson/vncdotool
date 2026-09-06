# Screen Stability — Design

Status: draft, under review. Sibling of the `expect` matching design; this is
the "Not in scope" item from it — blocking until the screen stops changing,
with no reference image.

## Problem

`expect FILE FUZZ` blocks until the screen matches a picture you already have.
Nothing blocks until the screen merely stops changing, and two callers want
exactly that.

`tests/goldens/scene-lossy.vdo` fakes it with `pause 1.5` between keystrokes
plus throwaway `capture step.png` calls, because under a lossy encoding no
single `maxrms` separates a JPEG rendering of the right scene from the wrong
scene. The pause is a guess: too short and the capture tears, too long and the
golden run pays for it eight times over.

The stronger case is outside the test suite. An agent driving `vncdo` captures
a PNG and inspects it out of process; it cannot sit inside the reactor's
`expect` poll loop, because each turn through that loop costs it a model call.
What it needs before looking is "the screen has settled", which is a question
`expect` cannot ask without already knowing the answer.

## Command

    stable SECONDS FUZZ
    rstable SECONDS FUZZ X Y W H

Both arguments are mandatory, matching `expect FILE FUZZ`, whose parser pops
`FUZZ` unconditionally (`command.py:258`).

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
  1.5s whether or not the repaint finished, where `stable 1.5` waits out however
  long the repaint actually takes and then proves 1.5s of quiet.

### Why a region variant is not speculative

A server painting a clock or a blinking cursor never satisfies a whole-screen
window. Without `rstable` the only answer for those servers is "time out and
fail"; with it, the caller excludes the noisy corner and waits on the region it
cares about. That is the recovery path, not a symmetry exercise.

Geometry is appended, not infixed: `rstable SECONDS FUZZ X Y W H`.

`rstable` needs all four numbers. `rexpect FILE X Y FUZZ` gets away with two
because the reference image's own dimensions supply the width and height;
`rcapture FILE X Y W H` spells out all four because nothing else says how big
the region is. `stable` has no reference image, so it is structurally an
`rcapture`.

That matters because the two existing region commands disagree about where the
geometry goes, and no command can follow both. `capture FILE` →
`rcapture FILE X Y W H` appends the geometry after the base command's own
arguments. `expect FILE FUZZ` → `rexpect FILE X Y FUZZ` (`command.py:272`)
infixes it, wedging X and Y between the two arguments `expect` already had and
pushing FUZZ to the end. Applied here the rules give
`rstable SECONDS FUZZ X Y W H` and `rstable SECONDS X Y W H FUZZ`
respectively.

## What "unchanged" compares

Not `_expectMatch`. That function compares **histograms** (`client.py:281`), and
a histogram is spatially blind: a scrolling terminal, a window dragged across a
uniform background, or any rearrangement that preserves the colour census reads
as identical. Against a reference image that weakness is bounded, because the
reference pins what the screen should contain. For a stability test it is the
whole failure mode — two consecutive frames of moving content would be declared
stable.

`stable` compares successive frames per pixel:

    max(ImageStat.Stat(ImageChops.difference(current, baseline)).rms)

`ImageChops` and `ImageStat` are already imported for `_quantizedMatch`. The
value is a per-channel RMS in 0–255 units; `FUZZ 0` demands exact equality, and
a small non-zero value absorbs the JPEG jitter that motivated the lossy golden.

**FUZZ therefore does not carry the same units as `expect`'s FUZZ.** Same name,
same shape (`rms <= maxrms`), different quantity — one is a distance between
histograms, the other a distance between images. `docs/usage.rst` has to say so
where it introduces the command; a reader who transplants a working `expect`
fuzz value into `stable` will otherwise get a number that means nothing here.

## How the window is driven

Event-driven, on `commitUpdate` — the point where every rectangle of one
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
may span several updates — that is the gap `stable` fills, and RFB offers no
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

With no baseline — `self.screen` is `None` on a fresh connection — the first
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
fallback** — a command that sometimes returns a frame it knows to be unstable
gives the caller no way to tell the two outcomes apart, and the caller in the
motivating case is an agent that will believe it. Fail loudly; the recovery is
`rstable` over a calmer region, or a longer `--timeout`.

## Python API

    VNCDoToolClient.stableScreen(seconds: float, maxrms: float = 0) -> Deferred
    VNCDoToolClient.stableRegion(seconds, maxrms, x, y, w, h) -> Deferred

Beside `expectScreen`/`expectRegion` (`client.py:234`), sharing the private
helper the way `_expectFramebuffer` is shared.

`stableScreen` is not a verb phrase, unlike every neighbour — `captureScreen`,
`refreshScreen`, `expectScreen`. It buys a 1:1 mapping from the script command,
which is the property callers actually use when moving between `vncdo` and the
library. `waitStableScreen` reads better in isolation and breaks that mapping.

State for one call lives in a `_StableWatch`, not on the client: a baseline
frame, a timer and a settled flag outgrow the single `self.deferred` slot
`_expectCompare` threads its state through. The flag is load-bearing — after
the window fires, a commit can still arrive against the last armed deferred,
and without it the watch would re-arm and request forever.

## Out of scope

**Fence (-312) and ContinuousUpdates (-313).** Fence is a barrier, not an idle
detector: it reports that everything queued before it has been delivered, and
says nothing about future updates. It could tighten the window's start — do not
begin counting until a fence returns — but the repo has constants only
(`const.py:101`, `const.py:217`, `const.py:254`) and no implementation, and
`specs/server-compatibility-plan.md:166` schedules both for Phase 3. Neither is
in RFC 6143, so a stability test cannot depend on them in any case.

## Testing

Unit, `tests/unit/test_client.py`: drive the protocol class with the mocked
transport the file already uses, and a `twisted.internet.task.Clock` for the
window, calling `commitUpdate` directly with prepared frames. Never start the
reactor. Cases worth one test each — window restarts on a change beyond FUZZ,
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

`CHANGELOG.rst` gets an entry under `(UNRELEASED)`.

## Open questions

- Whether `FUZZ` sharing a name with `expect`'s differently-scaled fuzz is
  worth the confusion, or whether the argument wants a different name.
  `docs/usage.rst` warns about it; a rename would be better.
- Whether any common server sends periodic no-op updates that a pixel
  comparison would correctly ignore but that would still churn CPU on a large
  framebuffer. Not yet checked against the fleet.
- A fixture that animates and then stops, so the settling behaviour can be
  asserted end to end rather than only in unit tests.
- The `scene-lossy.vdo` migration below is not done; it needs the goldens
  regenerated, which is its own change.

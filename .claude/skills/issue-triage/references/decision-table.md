# Triage outcomes

Every triaged issue lands in exactly one of A–G. If two seem to fit, prefer the
one that carries more evidence: a duplicate you can also reproduce is still A,
with the duplicate link in the comment. Add `duplicate` to A's labels in that
case — the outcome governs the workflow, the labels describe the issue, and an
issue that is genuinely both should say so.

Apply labels from the skill's fixed set as-is — don't recreate or restyle them,
and don't invent new ones. Remember `feature` is this repo's `enhancement`.

An open PR against the issue is not an eighth outcome — it changes the action
inside whichever of A–G you land in. See the section at the end.

## A — Confirmed and reproducible

You wrote a test, ran it, and it failed for the reason the reporter described.

Settle step 6 before doing any of this: if a PR is already open against the
issue, the branch-and-PR sequence below is off, and the last section governs.

1. Branch `claude/triage-issue-NNN` off the default branch.
2. Add `tests/unit/test_issue_NNN.py` per `repro-harness.md`, marked
   `@unittest.expectedFailure`, carrying the `TRIAGE ARTIFACT` docstring note
   that names the permanent home it should move to when fixed.
3. Confirm `python -m unittest tests.unit.test_issue_NNN -v` reports the
   expected failure and `flake8 --count --statistics vncdotool tests` is clean.
4. Open a PR: `test: reproduce #NNN — <symptom>`. The body must say where the
   test should move to at fix time, so the fixer doesn't need this skill.
5. Comment on the issue.

Labels: `bug`, `confirmed`, `has-repro`.

> Confirmed on `main` (`<sha>`). The cause is in
> [`vncdotool/client.py:NNN`](link) — `<one sentence, mechanism not symptom>`.
>
> I've added a failing regression test in #PPP:
>
> ```
> <real unittest output>
> ```
>
> It's marked `expectedFailure` so CI stays green; whoever fixes this can drop
> the marker and the test becomes the check. It's a standalone file for now so
> it's easy to find from here — it belongs in `tests/unit/<home>.py` once fixed.

## B — Confirmed, but not expressible as a unit test

You traced it to real code, but the trigger is environmental: a specific
third-party server's live behaviour (TigerVNC in shared mode, QEMU's key
handling, VMware, a RealVNC-only security type), a real network's timing or
disconnects, a platform-specific thread interaction. A mocked-transport test
here would pass or fail for the wrong reason, which is worse than no test —
and if the libvncserver functional harness can't produce the trigger either
(it is one specific server, run locally), there is nowhere honest to put a
committed reproduction.

Labels: `bug`, `confirmed`, `needs-integration-test`. No PR.

> Confirmed by inspection on `main` (`<sha>`): `<file:line trace>`.
>
> I couldn't turn this into a regression test — reproducing it needs
> `<the environmental trigger>`, which neither the mocked-transport suite in
> `tests/unit/` nor the libvncserver-based functional harness can produce.
> Flagging it as needing an integration test rather than leaving a fake one
> that would pass for the wrong reason.

## C — Undetermined, needs the reporter

You genuinely could not tell. Say what you tried — that's what separates this
from the "any update?" comments everyone hates — and ask only for what's missing
and not already in the thread. For this codebase the question that unlocks the
most threads is the server: which VNC server, which version, and the
`vncdo -v` log of a failing run.

Label: `needs-info`.

> I tried to reproduce this on `main` (`<sha>`) with `<what you did>`, and
> `<what happened instead>`.
>
> To get further I need:
> - `<specific fact>`
> - `<specific fact>`
>
> If it's no longer affecting you, saying so is just as useful — it lets us
> close this out.

## D — Probably already fixed

Name the commit. "Looks fixed" without one is a C, not a D.

Labels: `probably-fixed`, `needs-info` (the clock should run). Do not close.

> This looks fixed by `<sha>` (`<subject>`), released in `<version>` —
> `<what changed>`. You were on `<their version>`, which predates it.
>
> Could you confirm on `<latest>`? If it still happens I'll dig in properly.

## E — Duplicate

Comment on both: link the canonical issue here, and move any detail this thread
has that the canonical one lacks over there. Then leave both open.

Label: `duplicate`.

> Same root cause as #MMM — `<the shared mechanism>`. That one has the older
> thread, so it's the better place to track it; I've copied the extra detail
> from here across.
>
> Leaving this open for the maintainer to close.

## F — Question or docs gap

Answer it, with links into `docs/`. If the docs don't actually cover it, say so
explicitly — a question that the documentation should have answered is a docs
bug, and naming it is more useful than a private answer.

Label: `question`, or `documentation` when there's a real gap.

> `<direct answer>` — see [`docs/<file>.rst`](link).
>
> (This isn't covered well in the docs today; that's a gap worth closing.)

## G — Feature request

Not a defect. Summarise what it would take and what today's behaviour is, so the
next reader doesn't restart from the title.

Label: `feature`.

## When the trace hands you the fix

Outcome A sometimes ends with the fix in plain sight — the mechanism is fully
traced, and the codebase itself shows the corrective pattern (#90's fix was
"treat DesktopSize the way the QEMU pseudo-rect two branches up is already
treated"). What to do with that depends on confidence, and the bar is all four
of:

- the mechanism is proven by an executed reproduction, not inferred;
- the fix is small — roughly a dozen lines — and follows a precedent already
  in the codebase, which you cite by `file:line`;
- the full suite stays green with the fix applied and the repro test passes
  un-marked;
- when a wire-level repro exists, it flips from failing to passing and you
  quote both runs.

Below that bar, or when the fix involves a design choice the maintainer should
make, say what you traced and stop.

At that bar, **suggest — don't ship unasked**. Add one paragraph to the outcome
A comment: the fix shape, the precedent line it follows, and that a fix PR is
available on request. The triage PR stays a repro-only PR.

When the maintainer asks for the fix (or the invocation says to build it):

1. Branch `claude/fix-issue-NNN` off the default branch — a fresh branch, not
   more commits on the triage branch, so the repro PR keeps standing on its
   own for the maintainer to compare against.
2. Apply the fix, and land the regression test **in its permanent home** in
   final form: moved to the topical file, `expectedFailure` marker dropped,
   renamed for the behaviour it checks. This performs the migration the
   triage artifact's docstring prescribes.
3. Add the `CHANGELOG.rst` entry under `(UNRELEASED)`.
4. Re-run everything: unit suite, lint, and the wire-level repro if one
   exists. Quote before/after in the PR body.
5. The fix PR body notes it supersedes the repro PR — which should be closed
   unmerged when the fix lands, since its `expectedFailure` test would report
   an unexpected success on a fixed tree. Recommend; the maintainer closes.

## Repro evidence beyond the unit test

A wire-level reproduction — a real server or scripted byte-replay server
driven by the real `vncdo` CLI — is worth building when the unit test alone
could be suspected of mock artifacts. For a real server, reach for the
first-party harness in `tests/servers/` (docker-compose TigerVNC, UltraVNC
and friends, driven by `tests/servers/servers.mk`) before writing anything;
script a fake server only when the trigger is a wire sequence no runnable
server produces (TightVNC on Windows was the #90 case).

Where the evidence goes is a hard rule learned on #90:

- **The repro PR contains exactly one file: the `expectedFailure` test.**
  The PR is designed to be merged, so anything committed on it eventually
  lands on main — debugging scripts, logs and screenshots included, forever.
  Nothing evidentiary is committed, on any branch.
- **Everything else goes in the issue thread, as text.** The repro script
  and full logs belong in the triage comment inside `<details>` folds — a
  comment survives branch deletion, costs the repo nothing, and is where the
  next reader of the issue actually looks. Quote the decisive log lines
  outside the folds.
- **Screenshots are described, not posted.** The API cannot attach files to
  comments, and branch-hosted raw URLs die with the branch — so state what
  the image shows in verifiable terms (`1024x640, extrema ((0,0),(0,0),(0,0))
  — every pixel black`) and let the folded logs carry the proof. If the
  maintainer wants the pictures, they can be handed over out-of-band or
  attached via the web UI.

## When a PR is already open

Step 6 turned up an open PR against this issue. The classification doesn't
change — an issue with a fix in review is still confirmed, or still a
duplicate — but two things about the action do.

**Don't open a competing PR.** This overrides step 1 of outcome A. Someone is
waiting on review for work you'd be duplicating, and a second PR against the
same issue makes the maintainer arbitrate rather than merge. If your repro test
is genuinely worth having and the open PR lacks one, say so in the issue comment
and let the maintainer ask for it — the existing PR's author is better placed to
add it than a parallel branch is.

The one case where you still open yours: the PR predates a rewrite of the code
it touches and no longer applies, and you say that plainly. "It's stale" is not
enough; "it patches the pycryptodomex DES path, which `<sha>` removed" is.

**Say what you think of it.** A bare link is barely worth the notification. One
or two sentences: does it address the mechanism, does it carry a test, is it
mergeable against today's `main`. Getting this wrong in the reporter's favour is
the failure mode to avoid — "#323 fixes this" reads as a promise, and if it's
actually conflicted against `main` and cut from a fork's own `main` branch, the
reporter waits on something that isn't coming without more work.

Append to whichever outcome's template you're using:

> There's an open PR that touches this: #NNN (`<title>`, opened `<date>`,
> unreviewed). `<one or two sentences: what it changes, and whether it addresses
> the mechanism above.>`
>
> I haven't opened a competing PR. `<If a repro test is still worth having, one
> line saying so.>`

---
name: issue-triage
description: Triage open GitHub issues on sibson/vncdotool — work out whether a report still applies, prove it with a committed regression test when possible, ask the reporter a specific question when not, and cluster duplicates. Use this whenever the user mentions triage, the issue backlog, stale issues, "does this still apply", "is this still a bug", cleaning up old issues, or invokes /issue-triage. Also use it when asked to investigate a single issue number in depth before deciding what to do with it.
---

# vncdotool issue triage

vncdotool's backlog runs back to 2016. Most of it is not "unknown" so much as
"nobody has spent the twenty minutes". That is the job here: spend the twenty
minutes and leave behind evidence, so the maintainer's decision is a one-line
read rather than a fresh investigation.

What makes this tractable is that vncdotool is a *protocol client*, and its
unit suite (`tests/unit/`) drives the protocol classes directly with a mocked
transport — no VNC server, no network, 67 tests in well under a second. A
reporter's TigerVNC or QEMU is out of reach, but RFB is a byte protocol: when
the report carries a `-v` log or a byte trace, the server's misbehaviour is
often replayable as bytes fed straight into `RFBClient`. Where a test is
possible, a test beats any amount of prose.

## Two rules that matter more than the rest

**Only report what you actually ran.** If you say a bug reproduces, a test must
have executed and failed, and you quote its real output. A plausible-sounding
reproduction that was never run is worse than saying nothing — it puts a false
fact in a permanent public record, and the maintainer has no way to tell it from
a real one without redoing your work, which defeats the point of the exercise.
The same goes for "already fixed": name the commit, don't infer it from vibes.

**Read the comments before you write one.** Re-runs are normal — the backlog
gets swept more than once, and the same issue will come up again. If the last
comment on the issue is a previous triage comment, posting a near-identical one
turns this from a useful tool into a notification spammer that reporters mute.
Check first, and if the state hasn't changed, say so in your report to the
maintainer rather than on the issue.

Both rules exist because the audience for a triage comment is a human who was
mildly annoyed to get the notification. Earn it.

## Invocation

- `/issue-triage 90` — one issue, full depth.
- `/issue-triage` — a batch of the least-recently-updated open issues not yet
  triaged (default 5), followed by the overdue report. "Not yet triaged" means
  carrying none of `confirmed`, `has-repro`, `needs-info`, `probably-fixed`,
  `duplicate`, `documentation`, `question`, `needs-integration-test`. The four
  labels that predate this process — `bug`, `feature`, `help wanted`,
  `good first issue` — record the reporter's framing, not an investigation:
  nearly every open issue already carries `bug` or `feature`, and an issue
  carrying only those is still untriaged.

  The batch is selected by querying the API and sorting by `updated_at`
  ascending. It is never read off the filesystem. Files under `evals/fixtures/`
  are frozen copies used to grade this skill, so the issues they name are the
  ones most likely to be sitting in your context — which makes them a tempting
  and completely wrong answer to "which issues need triage". If a run is
  supplying a fixture in place of a live issue, that substitutes the *content*
  of one issue you were already asked about; it never tells you which issues to
  pick. Selecting the fixture set is the tell that the selection rule was
  skipped.
- `--dry-run` on either — do the whole investigation and print the report and the
  exact comment you *would* post, but take no write action. Use this whenever
  you're unsure, and note that the evals in `evals/` run this way.

## What you may and may not do

You may comment, apply labels from the set below, create a branch, and open a PR.

You may not close an issue. Never call `issue_write` with `state` or
`state_reason` — not for duplicates, not for obsolete reports, not for anything.
Deciding a report is dead is the maintainer's call, and the whole value of this
skill rests on that boundary being reliable. Never push to `main`.

You may not review, approve, or comment on someone else's open PR. When one
addresses the issue you're triaging, your assessment of it goes in the issue
comment and the run report — the reporter and the maintainer are the audience,
and a contributor whose two-year-old PR suddenly gets a critique from a triage
bot is not.

Labels, and only these: `bug`, `confirmed`, `has-repro`, `needs-info`,
`probably-fixed`, `duplicate`, `documentation`, `question`,
`needs-integration-test`, `feature`, `help wanted`, `good first issue`. Note
`feature` — this repo's word for what other projects label `enhancement`. If
none fits, that is a finding to report, not a licence to invent one. The first
run should verify the eight process labels (everything except `bug`, `feature`,
`help wanted`, `good first issue`) exist on the repo — a missing one is a setup
gap to report to the maintainer, not something to create or improvise around.

Every comment ends with the attribution footer:

```

---
_Generated by [Claude Code](https://claude.ai/code)_
```

Exactly that URL. Anything you write here — comment, PR body, PR title, commit
message — is public and permanent, so it carries no `claude.ai/code/session_...`
link and no `Claude-Session:` trailer. Those resolve for nobody but the person
who ran it, and they are noise in a thread the reporter has to read. The bare
`https://claude.ai/code` above is the whole attribution.

## Procedure

**1. Read.** `issue_read` with `get`, then `get_comments`. Pull out the reported
vncdotool, python and platform versions, the VNC **server** and its version —
for this codebase the server is usually the variable that matters most — the
repro if there is one, and whether a maintainer already replied. Apply the
idempotency check now: if the most recent comment is a prior triage comment, do
not re-post — either advance the state because something changed, or report it
as unchanged.

**2. Locate.** Map the symptom onto real code and cite `file:line`. The wire
protocol — handshake, security-type negotiation, encodings, server messages —
is `vncdotool/rfb.py` (`RFBClient`). Client commands — `keyPress`, mouse,
`captureScreen`, `expectScreen` — are `vncdotool/client.py`
(`VNCDoToolClient`, plus `VMWareClient`). The synchronous threaded API —
`connect()`, `disconnect()`, `shutdown()` — is `vncdotool/api.py`. The `vncdo`
CLI is `vncdotool/command.py`; the `vnclog` proxy is `vncdotool/loggingproxy.py`;
the keysym table is `vncdotool/keys.py`. If you cannot find the code the report
is about, that is itself the finding — say so rather than guessing.

**3. Check whether it was already fixed.** Old issues are frequently dead. In
rough order of speed:

```
git log -S'<symbol>' --oneline -- vncdotool/        # when did this change?
git log -L<start>,<end>:vncdotool/client.py         # history of these lines
grep -n '#<NNN>' CHANGELOG.rst                      # changelog references
```

plus `search_issues` for a *merged* PR mentioning the number. A fix you can name
beats a suspicion you can't. An open PR is a different finding and belongs in
step 6 — don't let one you spot here stand in for that search.

Check for a shallow clone first (`.git/shallow`, or a suspiciously short
`git log`). In one, `git log -S` blames the graft boundary commit for everything
older, which reads exactly like "changed recently" and will walk you into naming
the wrong commit. When history is truncated, get it from the API instead —
`search_commits` and the closed issue or PR will date a fix properly where local
history can't. Failing that, cite `CHANGELOG.rst`: an honest `CHANGELOG.rst:12`
is worth more than a confident sha that means nothing.

**4. Check version relevance.** The tree supports python >= 3.9 (CI runs
3.10–3.13). Two rewrites are the big dividing lines: 1.1.0 (2023) was the
python-3 modernization that touched nearly everything, and 1.3.0 (2026) replaced
pycryptodomex with cryptography.io — so an auth traceback naming
`pycryptodomex`, or any python-2-era report against 0.x, is not current
evidence. Say that plainly instead of treating the old trace as live — but
don't leap from "old" to "invalid": the underlying bug often survives the
rewrite. #90's black-capture reports span 2017 to 2025 across both rewrites.
Check the current code before deciding.

**5. Look for duplicates.** Search open and closed issues for the same symptom.
Canonical = oldest with the best repro.

Search the narrowest distinctive identifier **on its own** before adding
qualifying terms. GitHub search ANDs the terms, so every word you add can only
shrink the result set, and the duplicate you want is often the thread that
described the same bug in different words — the 2017 report says "black
picture", the 2023 ones say "black screen" or "artifacts on screenshots", and
`black screenshot` finds neither end of that chain. Add terms only to cut a
result set that came back too large — never as your opening move.

Recurring themes, as a starting point for the search and nothing more —
verify against the actual threads before relying on any of it, because
similar-sounding reports routinely have different causes: black or garbled
captures; per-server security-type/auth negotiation failures; hangs on exit
and threading/multiprocessing trouble around `api.connect`; key and symbol
handling differences between servers; silent disconnects and "Cannot connect"
noise; encoding negotiation; the `vnclog` proxy. A shared symptom is not a
shared cause — a black capture alone spans a server that never sends an update,
a capture that completes on a `PSEUDO_DESKTOP_SIZE` pseudo-rect before any
pixel data arrives (#90's trace), and an image-decode problem, and those are
three different bugs in three different files.

**6. Check for an open PR that already addresses it.** Step 3 asks whether a
fix landed; this asks whether one is *sitting in review*. They are different
states with different maintainer actions — "someone should look at this" versus
"review #NNN" — and an issue whose fix has been waiting in review is the most
actionable thing this skill can surface.

```
search_pull_requests   repo:sibson/vncdotool is:open <NNN>
list_pull_requests     state=open              # a handful; skimming is cheap
```

`search_issues` is not a substitute, and neither is the number search alone:
a PR routinely names one issue while addressing another. #323
(`Initial VNC Fence implementation`) cites only #322 in its body, yet it is
also the fix path for #66's years-old ClientFence request — a search for `66`
returns nothing. So search the bare number first, then skim the open list
(ignoring dependabot's dependency bumps), and treat an empty per-issue search
as absence of evidence, not evidence of absence.

Judge it, don't just link it. Does the diff address the mechanism you traced in
step 2, or something adjacent? Is it mergeable or gone stale against `main`?
Does it carry a test? A link plus one sentence of assessment is the
deliverable; approving or merging is not yours to do.

What this changes is the *action*, not the classification: an issue with a PR
open against it is still confirmed, or still a duplicate. See "When a PR is
already open" in `references/decision-table.md` — most importantly, do not open
a second PR that duplicates work someone is already waiting on review for.

**7. Classify.** bug, feature, question, or documentation. Before treating
anything as a defect, check `docs/` for whether it is a deliberate choice. The
one that catches people is in `docs/library.rst`: the api module runs the
Twisted reactor in a daemon thread, a reactor cannot be restarted, and the
context manager deliberately does *not* shut it down on exit — so
`api.shutdown()` is required or the process hangs at exit. Reports of hangs
under threading or multiprocessing sit right on this line.

Finding the design note settles less than it appears to, so don't stop there.
The documented intent usually covers *what* happens, not *how well*: requiring
`shutdown()` can be deliberate while hanging forever with no diagnostic when
it's missed is still a defect, and "the reactor is per-process" invites the
question of whether that's surfaced to the multiprocessing user before their
workers deadlock. Say which part is by design and which part is still open,
rather than closing the whole report because the headline behaviour is
documented.

If the docs justify the behaviour but only somewhere the affected user would
never look, name that gap too — a design note in `docs/library.rst` doesn't
help someone who only ever read the CLI examples in `docs/usage.rst`.

Once you have found the design note, it constrains what you may write next: do
not commit a test asserting that the documented behaviour is a defect. Writing
`@unittest.expectedFailure` around "the process hangs when `shutdown()` is
never called" encodes a claim the docs contradict, and it outlives the run —
the next person reads a failing test as an agreed bug. If the residual
complaint is the *quality* of the documented behaviour (a silent hang where a
diagnostic belongs), test that specific gap and say so, or leave it to prose.
The verdict has to match the analysis: recognising the behaviour as designed
and then filing it `bug` + `confirmed` with a failing test is the contradiction
this step exists to prevent.

**8. Try to reproduce.** See `references/repro-harness.md` for how to write a
vncdotool test — including the two traps that produce a test that silently
never ran. Bugs that are protocol parsing, key mapping, or command dispatch are
almost always unit-testable with a mocked transport; when the report quotes a
`-v` log or byte trace, the server's bytes are replayable even though the
server is not. Bugs that need a specific third-party server's live behaviour, a
real network, or a particular platform are not, and forcing a fake test for
them produces something that passes for the wrong reason. Knowing which is
which is most of the skill.

**9. Act.** Pick exactly one outcome from `references/decision-table.md` and
follow its template. Read that file before writing any comment. When the
investigation has proven the mechanism *and* the fix is small with an
in-codebase precedent, suggest the fix in the comment — one paragraph, with
the precedent cited by `file:line` — per "When the trace hands you the fix"
in the decision table; build the fix PR only when the maintainer asks.
Repro evidence beyond the test follows the rules in the same file: the repro
PR carries the test and nothing else, scripts and logs go in the issue
comment as folded text, and screenshots are described in verifiable terms
rather than committed or embedded — nothing evidentiary is ever committed to
a branch that can merge.

**10. Leave the tree as you found it.** Delete the scratch files *this run*
created, then check `git status`. If it is not clean, report exactly what is
there — never delete a file you did not create to make the output look tidy. An
untracked file you did not write belongs to someone: an interrupted earlier run,
or the maintainer's work in progress. Removing it to report a clean tree is
destroying someone else's data to improve your own status line, and it is
unrecoverable in a way nothing else in this skill is. "Working tree clean except
`tests/unit/foo.py`, which predates this run and I left alone" is the correct
outcome, not a failure.

## The overdue report

A bare `/issue-triage` ends with a list of issues that have gone quiet. Two ways
in, and the second matters more than the first:

- It carries `needs-info`, the newest comment is a triage comment, and that
  comment is more than 30 days old.
- **The newest comment is an unanswered question from a maintainer, more than 30
  days old, whatever the labels say.** Most of this backlog predates any
  labelling scheme, so the first rule alone sees nothing: #284 has had a
  maintainer's "which VNC server are you connecting to?" sitting unanswered
  since mid-2024, and it carries only `bug` and `help wanted`. An overdue check
  that only finds issues the process already touched will report an empty list
  over a backlog full of dead threads.

Both are readable from the API, so there's no state file to drift out of sync.

List each with number, title, days since the question, and one line on what a
close would be based on. Recommend; don't close. The maintainer decides.

## Report format

End every run with this, whether dry-run or not:

```
## Triage: #NNN <title>

**Outcome**: <A-G> — <one line>
**Evidence**: <commit / file:line / test result — the actual thing>
**Open PR**: <#NNN — one line on whether it addresses this, or "none found">
**Labels**: <applied or proposed>
**Actions taken**: <comment posted, PR #NNN opened, or "none (dry-run)">
```

`Open PR` is never blank. "none found" is a real result and says you looked;
an absent line reads as a step skipped.

For a batch, one block per issue, then the overdue section. Keep it terse — this
is a worklist, not an essay.

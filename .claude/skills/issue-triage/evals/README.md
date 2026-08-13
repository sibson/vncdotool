# issue-triage evals

This harness mirrors the one on sibson/redbeat, which is the reference for how
these evals are built and why. Three cases are recorded; each expectation was
verified by hand (fixing commits confirmed in history and release tags, the
#297 TypeError reproduced verbatim on current main, fence absence confirmed by
grep) before its assertions were written.

## Why cases read fixtures, not the live API

An eval pointed at a live issue decays in two directions, and neither failure is
loud.

The backlog moves. Someone fixes the bug and a "confirmed and reproducible"
expectation is now wrong — the run that correctly reports "already fixed" fails
an assertion, and the suite reports a regression that isn't one.

Worse, this skill *writes to the threads its own evals read*. The first real
triage run on an issue puts a full analysis in the thread; every later eval run
then scores well by reading back an answer a previous run posted. That's a
suite that looks healthy while measuring nothing.

So each case reads a frozen snapshot of the issue as originally filed —
`fixtures/issue-<N>.json`, built by `snapshot.py`. Comments after the pin date
are withheld, and `state` / `state_reason` / `labels` are stripped so a closed
issue can't announce its own verdict. Batch mode reads a frozen backlog from
`fixtures/backlog.json`, and the open-PR list is frozen in
`fixtures/open-prs.json` — the *whole* list, not just the PR a case is about,
because "search the number, then skim the list" is the step under test and a
one-entry fixture would hand the answer over before the search ran.

A fixture freezes the **input**, not the code, and that's deliberate: if the
bug gets fixed, the correct triage outcome genuinely changes, and an eval that
still demanded "confirmed" would be wrong rather than strict. `verified_against`
in `evals.json` records the commit the expectations were last checked against;
when a case starts failing well past that commit, decide whether the code moved
under the expectation before treating it as a skill regression.

## Get the repo into the state the skill assumes, first

Fixtures freeze the issue, not the repo the skill acts on. Anything the skill
treats as a precondition should be true before a run is recorded, or the suite
spends its budget rediscovering setup gaps.

The known gap right now: **eight of the twelve labels the skill uses do not
exist on sibson/vncdotool yet** — `confirmed`, `has-repro`, `needs-info`,
`probably-fixed`, `duplicate`, `question`, `documentation`,
`needs-integration-test`. (The repo has `bug`, `feature`, `help wanted`,
`good first issue`.) Create them before recording any run, or every case will
correctly and uselessly report that a live run would propose labels it cannot
apply.

## Running them

Ask Claude: **"run the issue-triage evals"**. For each case it spawns two
subagents in the same turn — one pointed at `.claude/skills/issue-triage/`, one
with no skill as a baseline — saving outputs under
`issue-triage-workspace/iteration-N/<eval-name>/{with_skill,without_skill}/`.
Then it grades each assertion, aggregates, and shows the comparison.

Every prompt carries `--dry-run`, so the suite investigates real code but writes
nothing. Verify that held:

```
python .claude/skills/issue-triage/evals/check_no_writes.py \
    issue-triage-workspace/iteration-N/*/*/transcript.jsonl
```

## Adding a case

```
# Claude fetches the issue and pipes it in; MCP tools aren't reachable from a script.
python snapshot.py --number 90 --as-of 2017-02-23 < fetched.json
```

`--list` and `--prs` refresh `backlog.json` and `open-prs.json` the same way.
Pin `--as-of` to the day the issue was filed, so the fixture is the report
rather than the discussion that followed — except where a case is *about* the
discussion (idempotency, overdue detection), which needs a later pin or a
synthetic thread.

Two rules carried over from the redbeat suite, both learned the hard way:

- **Assertions must be verified, not predicted.** Do the investigation for
  real, at the pinned commit, before writing what the run "should" find. An
  assertion loose enough that two contradictory answers both satisfy it is
  worse than no assertion.
- **A synthetic fixture must describe a world the agent can't falsify.** A case
  that asserts "a prior triage comment exists" while the real thread lacks one
  gets caught by any run that checks — rightly — and then measures only
  credulity. Synthetic threads are fine (the idempotency case needs one); lying
  about checkable state is not.

Closed issues make the strongest cases when they closed `completed` — the
resolution is knowable. Ones swept shut in bulk as `not_planned` record a
disposition, not a verdict; grading against them teaches the skill that old
means closeable.

## What each case is for

| Case | Guards against |
|---|---|
| `already-fixed-with-named-commit` (#110) | A "confirmed" verdict on a bug that died in the 1.1.0 rewrite — and the vaguer failure of saying "looks fixed" without naming `bc93eb9` / `3859a1f` (#250). Bonus judgment: the reporter's exact byte sequence is already a passing regression test (`test_rfb.py::test_auth_invalid33`), so proposing a new repro PR is the tell that step 3 was skipped. |
| `misattributed-fix-trap` (#297) | Naming a commit that doesn't explain the mechanism. `git log` on `captureScreen` points straight at `ec3f481` (#293), but the class-qualified TypeError is an unbound call that reproduces on current main — the plausible "fixed by #293" answer is wrong, and a real triage comment on the live thread fell for exactly this. The honest landing is F/C (docs gap around the Deferred-style API, cf. #266). |
| `open-pr-for-old-feature-request` (#66) | Triaging a feature request as untouched when its implementation is sitting in review — PR #323's body cites only #322, so a bare number search misses it and the list-skim has to catch it. Also: not opening a competing PR, and not reviewing #323 directly. |

Fixture pin dates: #110 at 2017-12-14, #297 at 2025-05-20, #66 at 2016-04-14
(each the filing date, so the fixture is the report, not the discussion — for
#297 that withholding is load-bearing, since a later comment on the live
thread names the misattributed fix). `open-prs.json` is pinned at 2026-08-13;
the two dependabot bodies are truncated with an explicit marker, and case 3
depends on #323 staying open — re-freeze and re-check when it merges or closes.

## Next candidates

Verified leads for future cases, not ground truth yet:

| Candidate | What it would guard |
|---|---|
| #90 (black captures, 2017–2025 thread) | The byte-replay judgment: the thread carries a `-v` log naming the exact protocol sequence, so "can't run TightVNC" must not become "can't reproduce". Also version-relevance: reports span both rewrites. |
| #284 (unanswered maintainer question, mid-2024) | Overdue detection on an issue with no process labels — the check that only finds issues the process already touched reports an empty list here. |
| #255 / #188 (threading, multiprocessing hangs) | The documented-design line: `docs/library.rst` makes `api.shutdown()` the caller's job, but "hangs silently when missed" may still be a defect. Guards both over-closing and committing a test that argues with the docs. |
| #310 (raspios "unknown security types") | Outcome B vs C judgment on an environment-specific auth failure, where the security-type list in the report is itself replayable evidence. |
| batch + overdue | Selection by API (not fixtures), no closes, and an overdue list that finds unlabelled dead threads. Needs `backlog.json` frozen first. |

## Keeping them honest

- If a case starts passing for both the with-skill and baseline runs, it has
  stopped discriminating and is no longer earning its slot.
- When a case fails, decide which is wrong — the skill or the expectation —
  before editing either.

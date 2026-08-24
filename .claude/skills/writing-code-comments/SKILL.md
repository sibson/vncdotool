---
name: writing-code-comments
description: Use when about to write or edit a comment, docstring, module header, CHANGELOG entry, or PR/commit description in any language, and when auditing a diff, branch, file, changelog section, or PR body for prose quality — including when review feedback calls comments, entries, or PR descriptions verbose, redundant, obvious, noisy, restating the code, oversized for the diff, or when a repo's conventions file has a comments or PR-description policy to apply.
---

# Writing Code Comments

## Overview

A comment carries one fact the reader cannot get anywhere else: from the
language, the library's docs, the specs, the identifier names, the code
itself, or from running it. Everything else is noise the reader must still
read.

**The repo's own policy wins.** Before writing or auditing, read the comments
section of the repo's conventions file (`CLAUDE.md`, `AGENTS.md`,
`CONTRIBUTING`). This skill is how to apply such a policy, not a replacement
for one.

**Say so if this repo does not carry a copy of this skill.** Check for
`.claude/skills/writing-code-comments/` in the project being worked on. If it
is missing, you are running from an install local to this machine, and a
session on the same repo elsewhere — a cloud container, someone else's
checkout — gets only what the repo commits, which is nothing. Nothing else
reports that gap: the session that lacks the skill has no way to know it
exists. Name it once, and carry on with the work.

## Mode A — Author time

Before writing any comment, name the fact it carries. Say it out loud in this
shape:

> "The reader cannot know that ___ from the code, and will be surprised later
> if they don't."

Fill the blank with something particular to *this* code: a server that ignores
what it was asked, an ordering nothing enforces, an obvious approach that does
not work here, a bound that comes from outside the file.

Then check where that fact already lives. True and non-obvious is **not** the
test — a sentence can be both and still be a paraphrase of the docstring above
it, of the code it describes, or of a comment in the module it wraps. Look at
the thing being described before you keep the comment: if the fact is already
written within the reader's reach, delete.

**Look outside the file too**, at the commit message introducing the change,
the PR, and `docs/`. A fact you just wrote in a commit body is already housed;
repeating it in a comment makes a second copy that drifts from the first. When
the repo's policy routes rationale to commits or `docs/`, that routing decides
the verdict — the comment goes, even where the fact is genuinely surprising and
lives nowhere in the code. Before keeping any comment that explains *why*, ask
what the commit message for this change says — or will say.

Can't fill it? Write no comment. That is the finished, correct outcome — not a
failure to be papered over with a shorter comment.

The comment IS that one fact, in plain prose, one or two lines. Not a preamble
plus the fact. Not the fact plus a restatement of the code.

## Name the source, or write nothing

A comment that survives Mode A still has to be *true*, and you have to know it
is. Before writing, name the source of the fact to yourself:

- **The spec or docs** — then cite which, so the reader can check.
- **Observed behaviour** — then say what was observed and where
  ("as observed on VMware ESXi"), not what the vendor supposedly does.
- **The code elsewhere** — then it is probably redundant; re-run Mode A.

Cite a source by naming it, not by its identifier. `R3` and `N2` are lookups,
not citations — the reader cannot check one without opening something else and
searching it. Name the constraint in the comment; if the document is worth
pointing at, point at it by title. An issue or PR number is not a citation to
fix but a comment to delete — that fact belongs in the commit message.

Point elsewhere only when what is there is surprising and too long to state
here. A pointer to something unsurprising is a second thing to read on the way
to learning nothing.

No source? You are inferring a story from a shape in the code. Write nothing.

This is the most damaging failure mode, because the output is indistinguishable
from expertise: a confident sentence about what some server "always" does,
inferred from a byte pattern. It cannot be checked, it never gets removed, and
readers trust it more than the code. Hedged phrasing is not a fix — "some
servers may" with no source is the same guess wearing a hat.

## Mode B — Sweep

Sweep the diff you are about to commit, not the branch you are about to open
a PR on. A sweep deferred to PR time has to be applied across every commit
that has landed since, and across a stack of PRs it means rebasing the stack
to fix comments. Keep a final pass at PR time for what arrived by rebase.

Auditing a diff, branch, or file:

0. **Was any of this authored in this session or branch?** Then its starting
   verdict is **delete**, and you may not decide otherwise by re-reading it.
   Reading your own comment replays the reasoning that produced it, and it
   scores as load-bearing because you are supplying the load. Reviewers come
   back with "describes the code", "verbose", "unnecessary context" — on
   comments the author's own sweep kept.

   A keep has to survive naming an artifact instead: the file and line, the
   commit subject, or the doc heading where the fact would live if the comment
   went — and showing that artifact does not already contain it. "The commit
   body I am about to write" is not such an artifact; it is the reason to
   delete. What does rescue a comment is a fact from outside this file that is
   written down nowhere: a server's behaviour, a constraint the language does
   not express, a bound another system imposes.

   **This step is a default, not a verdict, and it is the one place a keep is
   most likely to be lost.** A constraint imposed by something this file does
   not contain — a runtime that cannot be restarted, a library's threading
   model, a server that ignores what it was asked, a bound another process
   sets — survives the default and is exactly what the sweep is protecting.
   Freshness is not evidence against a fact: a true, external, unwritten
   constraint does not become redundant because you learned it this morning.
   Delete it only if you can name where it is already written. A sweep that
   returns every block as a delete has usually stopped checking.
1. Enumerate **every** comment and docstring in scope — not only the ones
   review flagged. Reviews catch samples; the pattern is repo-wide. Drop
   vendored files and published API reference from scope first.

   **File headers are in scope.** Module docstrings, script preambles, the
   comment block at the top of a YAML file, the banner above a function:
   these are where unearned prose collects, because "orientation" feels
   exempt. It isn't. A header earns its place the same way a line comment
   does — one fact the reader cannot get from the code below it. "What this
   file is for" is usually its name; "what it reads from the environment" is
   usually the next five lines.
2. Classify each one. Judge **per sentence, not per block** — a block is not a
   unit, and one load-bearing sentence does not carry the ones around it.
   - **keep** — every sentence in it carries a fact that lives nowhere else.
   - **rewrite** — the same facts, expressed better: a cryptic line opened
     back up, or a claim cut back to what its source actually supports. A
     rewrite carries *every* fact the original did.
   - **delete** — anything else.

   Dropping sentences and keeping the survivors is not a rewrite, whatever it
   is called. That block is a **delete**. Then ask separately, as a fresh
   Mode A decision, whether any surviving fact earns a new comment of its own —
   usually its home is the commit message or `docs/` instead.
3. Check every **kept** comment against the code as it stands now, not as it
   stood when the comment was written. A sweep that runs after a few commits
   of design change will find comments that were accurate when authored and
   are now false — the file that no longer exists, the fallback that was
   removed, the caller that stopped calling. A wrong comment is worse than
   the verbose one next to it, and it survives sweeps because it reads as
   considered. Renames inside your own branch are the commonest source: grep
   the diff for every identifier and filename you renamed, and check the prose
   that names them — comments, docs and specs alike.
4. Apply. Re-read each rewrite against Mode A as if authoring it fresh.
5. Report every verdict as a table, one row per block, with these columns:

   | Block | Verdict | Fact it carries | Where else that fact lives |
   |---|---|---|---|

   Fill the last column for **every** row, keeps included. For a delete it
   names where the fact already is — the file and line, the commit subject,
   the doc heading, "the code below". For a keep it must read `nowhere`, and
   writing that word is a claim you are making: that you looked at the
   artifact the fact would otherwise live in and it is not there. Name that
   artifact. `nowhere` with nothing behind it is the sweep failing silently.

   The point of writing the column is that it is checkable by someone else.
   A judgement you make and do not write down passes every time, because the
   only thing testing it is the reasoning that produced the comment. Counts
   alone read as diligence; a column of artifacts shows which keeps are
   really "explains the design I just chose".

**Shortening is not a fix.** A shortened unnecessary comment is still an
unnecessary comment, now also cryptic.

### What a rewrite is

**Rewrite is not a softer delete.** Before writing any replacement, put the
block's fact through Mode A as if you were authoring a comment at that line
today, with the original gone. Does that fact earn a comment here at all? If it
does not — because it lives in the design document the block cites, in the code
below it, in the docstring above it, in the commit body — then there is nothing
to rewrite and the verdict is **delete**. A rewrite that relocates a redundant
fact into better prose leaves the redundancy where it was and now makes it read
as considered. Reach for rewrite only when the fact would survive Mode A on its
own and it is the wording that fails.

Stripping a label, folding a citation inline, or dropping the offending clause
are all deletions of part of a block, not rewrites of it. If what makes the
block wrong is *what it says* rather than *how it says it*, no rewrite exists.

A bare requirement label — `R1`, `N2` — is a symptom, not the defect. Removing
the label leaves the sentence it introduced, and if that sentence restates the
design document, the code, or what the repo already knows, the verdict was
delete all along. Ask what the block would be worth with the label already
gone, and answer that question instead.

**"It is useful guidance" is not a keep.** A block that tells the reader what
the layout will be, what an invariant is, or how to think about a design is
still deleted when the code, the directory, or the type already shows it. The
test is where the fact lives, never how helpful the sentence sounds.

A rewrite carries every fact the original did, in prose someone can read once.
It is not the original with words removed. Dropping words is the operation that
produces the two failures below, and both were shipped by sweeps that reported
themselves clean.

A comment on a guard against oversized rectangles:

> **before** — `# A rectangle's dimensions are u16, so this bounds nothing on
> its own; the guard is against a server that sends a rectangle larger than the
> framebuffer it announced, which the u16 range permits.`
>
> **the trim** — `# set greater than max value`. Shorter, and now nobody can
> tell what it guards or why the constant has that value.
>
> **the rewrite** — `# Greater than any u16 dimension, so it refuses nothing
> until a subclass narrows it.`

A module docstring cut down mid-sentence by an earlier pass:

> **before** — a paragraph re-teaching the design document it cites.
>
> **the trim** — a fragment with no verb, still re-teaching the design
> document. Two defects where there was one.
>
> **the rewrite** — there isn't one. The fact was already in `specs/`; the
> verdict was **delete** and the trim was avoiding it.

A rewrite is finished when it is a complete grammatical sentence, when it
states the fact rather than gesturing at it, and when it still reads correctly
with the code hidden. **If your rewrite is shorter than the original but no
clearer, the verdict was delete.** A block you are shortening because you
cannot defend keeping it whole is a delete wearing a rewrite's label.

## Mode C — Changelog entries

A `CHANGELOG` entry is read by someone scanning a release to decide whether it
affects them. One line, one user-visible fact: what is different for them now.
The mechanism, the old behaviour, the wording of the old output, and the
reassurance that something *else* is unchanged are all commit-message and PR
material — the same routing Mode A applies to comments.

Write the change the way a user would notice it, then stop:

> ``vncdo`` failures print to stderr as plain messages (@sibson, #395)

The same entry before the cut:

> ``vncdo`` failures now read as CLI errors: the message goes to stderr on its
> own, instead of being rendered as ``CRITICAL:root:<message>`` by the logging
> module. The failure's traceback moved to ``-vv``, and log records no longer
> carry the ``:root:`` logger name. Exit statuses are unchanged.

Both are accurate. The second makes every reader scanning the release parse
three sentences to reach the one thing they needed, and two of its facts are
invisible unless you already run `-v`.

**The cut test.** Delete everything after the first clause. Does a reader still
know whether this release affects them? If yes, the rest was never load-bearing.

| In an entry | Verdict |
|---|---|
| The mechanism: how the bug worked, which call was wrong | delete — commit-message material |
| What did *not* change ("exit codes are unchanged") | delete unless a reader would assume otherwise |
| A detail only visible under a debug flag | delete |
| The user-visible symptom, or what a user must now do differently | keep |
| A break, migration, or flag whose meaning changed | keep, and add the second sentence saying what to do |

## Mode D — Docs written alongside the code

A README beside the code is not exempt because it is prose. It is read by
someone who wants to run the thing and know what it does not prove, and it
grows the same way comments do: by accumulating the investigation that
produced the current design.

Apply the same routing. Evidence — the error strings, the run URLs, the two
tools that refused, what upstream shipped in 2022 — is what the commits that
found it are for. The README carries the conclusion and the constraints a
reader will hit.

The test: **would this line still be worth reading by someone who never saw
the branch that changed it?** A sentence that only makes sense as an answer
to "why isn't it the other way" is journey, not documentation.

Watch the line count across a branch. A doc that doubles while the code it
describes gets simpler is recording the work, not the result.

**A doc gets the same verdicts as a comment.** Sweep it with Mode B, including
step 0, and read every row of the Quick reference against it: a paragraph that
narrates the code is a delete in `specs/` exactly as it is in the file it
describes, a section heading naming no recognisable subject is a rewrite, and a
sentence describing what the branch changed — "now live with the pump rather
than on the decoder" — is commit-message material wherever it sits. Tables are
in scope too: a cell so generic it could describe any row is not documentation,
whatever the table around it does.

## Mode E — PR and commit bodies

A PR or commit body is read by someone deciding where to spend their
attention, not by the archive. Its size tracks the diff, not the session that
produced it — a three-line deletion does not earn a "Summary" section, and a
mistake made while landing the change (wrong branch, a push that missed a
merge, a retried command) is memory for the session that made it, never
reviewer material. The same routing Mode A applies to comments applies here.

Write what changed and, if it isn't obvious from the diff, why — then stop:

> Removes a comment on `_run()` in `benchmark.py` that only restated what
> #422's commit message already says.

The same body before the cut:

> ## Summary
> Follow-up to #422: the comment sweep asked for on that PR ran a commit
> late, after #422 had already been squash-merged, so the cleanup never
> reached main. This lands it: removes the comment on `_run()` in
> `benchmark.py` that just restates what #422's commit body already says.
>
> ## Test plan
> - [x] `make test`
> - [x] `flake8 --count --statistics vncdotool tests`

Both are accurate. The second spends two headers and a narrative paragraph on
a one-line diff, and the fact a reviewer needs — what changed, and that it's
covered by #422's rationale — is buried in the middle of it.

**Size it, then cut to the size.** Roughly one line of body per ten lines of
diff, and six lines maximum unless you were asked for more. The first line
answers "what changed", and where the change is visible to a user it says so in
those terms rather than in the vocabulary of the implementation. Reading only
the first sentence is not the test — a body whose opening line is fine and
whose next three paragraphs re-explain the diff fails while passing it.

Count the lines of the body you are about to post. Over the budget, cut whole
sentences — starting with any that restate the diff — and count again. Do not
reflow a long body into fewer, denser lines; that is the trim the sweep section
forbids, applied to a PR.

**Say nothing about checks CI runs.** A "Tested:" line or a test-plan
checklist naming the suite and the linter tells the reviewer what a red check
would have told them, and they have to read it to find that out. Name only
what you ran that CI does not — a manual repro, a mutation check, a run against
a server the fleet does not carry.

| In a PR/commit body | Verdict |
|---|---|
| What changed, sized to the diff | keep |
| Why it changed, when not obvious from the diff | keep |
| A "Tested:" line or checklist naming checks CI already runs and gates on | delete — a red check says it |
| How the change was landed (wrong branch, late push, a retry) | delete — that's the assistant's own memory, not the reviewer's |
| "Follow-up to #N" when the diff is self-explanatory without it | keep only if it changes how the reviewer reads the diff |
| A "Summary" / "Test plan" header pair on a change too small to need sections | delete the headers, keep the two facts as plain lines |
| What was deliberately left alone or considered and rejected | keep only if a reviewer would otherwise flag it — everything else is already in the commits |

## Three things this does not reach

**Published API reference.** If a module is pulled into generated docs
(Sphinx `automodule`, godoc, rustdoc, javadoc), its public docstrings are the
reference a caller reads *instead of* the code. "Restates the name" does not
apply — the caller has nowhere else to look. Judge those for accuracy instead:
a docstring naming a parameter that no longer exists is the defect. Check
before sweeping: grep the docs directory for the module name.

**Strings the tooling prints.** A test method's docstring is its label in
verbose runners and CI logs (`unittest -v` prints the first line under the test
name); the same goes for argparse help, `__doc__` used as CLI usage, and
deprecation messages. Deleting one does not remove noise, it blanks a line in
someone's report. Run the tool and look before sweeping these.

**Vendored code.** Imported third-party files carry their original author's
conventions and were never in this repo's style. Check provenance before
sweeping one — a copyright line naming someone outside the project, or a first
commit that adds the file whole. Leave them, and exclude them when sampling the
repo for what good looks like: their idioms will read as defects and they are
not evidence of anything about this codebase.

## The delete test

Delete the comment. Read the code. Would an intelligent reader who knows the
language be surprised later? Restore it only then.

## Quick reference

| Candidate | Verdict |
|---|---|
| Restates the identifier name, the next line, or the docstring above it | delete |
| Paraphrases the code, class, or module it describes — even accurately | delete |
| Docstring opening that renames the function in prose | delete that sentence, keep the rest |
| Anything in the language reference, library docs, or spec | delete |
| Names who calls this, or where it is used from | delete — that is what a search finds, and it goes stale |
| Describes the change: "now watches", "no longer needs", "was previously" | delete — commit-message material |
| Names the task, issue, PR, or an alternative you rejected | delete — commit-message and `docs/` material |
| Answers a review comment, or points at the discussion that prompted it | delete — the reviewer reads the thread, the next reader does not |
| Cites a requirement by bare identifier: `R3`, `N2` | rewrite — name the constraint, or the document by title |
| Explains why the design is *this* rather than something else | delete — that is the commit body |
| File header saying what the file is for, or which env vars it reads | delete — the name says the first, the code says the second |
| True when written, false now: names a deleted file, a removed path, a caller that stopped calling | delete, and check its neighbours — rot arrives in clusters |
| Banner or section-divider comment | delete, or fold into prose |
| Commented-out code: a `# ~` debug write, a scratch print, a disabled branch | delete — that is what version control is for |
| A heading naming no subject the reader can recognise | rewrite to name the thing it is about, or delete the section under it |
| A docstring sentence pointing forward to something defined below it | rewrite to stand alone, or delete |
| A doc table cell so generic it could describe any row: "calls a client method" | rewrite to name the specific thing, or drop the column |
| Compressed until the reasoning is gone | rewrite at full length; clarity outranks brevity |
| Asserts what an external system does, with no cited spec or stated observation | delete, or rewrite down to what was actually observed |
| A behaviour nothing in the code enforces, or a constraint from outside the file | keep |
| A PR/commit body with headers and a narrative for a diff a sentence would cover | delete the narrative — size the body to the diff (Mode E) |

## Red flags — stop

- "I'll add a short comment for clarity" — clarity of *what*? Name the fact or write nothing.
- "This byte pattern only makes sense if the server does X" — you are guessing X. Say what the code matches, not why you think it exists.
- "Every sentence in it is true and non-obvious" — not the test. Ask where the fact already lives: the code below, the docstring above, the module it wraps.
- "The reviewer said verbose, I'll trim it" — trimming preserves the defect. Delete or rewrite.
- "Explaining what I changed helps the reviewer" — the diff does that. The comment must still read correctly on `main` a year later.
- "This function is complex, it deserves a docstring" — complexity is a reason to fix the names first.
- "That's the file header, it's orientation" — headers are in scope. Same test, same verdicts.
- "I wrote this an hour ago and it still reads as necessary" — of course it does. Name where the fact lives without it, or delete.
- "I deleted six and rewrote thirteen, the sweep was thorough" — counts are not evidence. List what you kept and why; the weak keeps show up immediately.
- "This PR body explains how I got here" — a rebase, a late push, a wrong branch is your own memory, not the reviewer's. Cut it.

## Rationalizations

| Excuse | Reality |
|---|---|
| "Documenting is good practice" | Documenting a *surprise* is. Documenting the visible is subtraction. |
| "Obvious to me, not to others" | Others read the same code. If names hide the intent, fix the names. |
| "Better to over-explain than under-explain" | Both cost. Noise trains readers to skip comments, including the load-bearing one. |
| "The limit says trim, so I compressed it" | Length was never the axis. A cryptic comment fails harder than a long one. |
| "It documents why I picked this approach" | Only if it is still surprising *as it stands*. Rejected alternatives go in the commit. |
| "A future AI reader might need it" | An AI reader already has every public document. Same test applies. |
| "It's the most plausible explanation for this code" | Plausible is not known. An invented why outlives everyone who could correct it. |
| "I hedged it, so it's honest" | An unsourced guess with "may" in front is still an unsourced guess. |
| "The changelog entry should explain the fix" | It should name the symptom. The reader wants to know if it was *their* bug, not how it worked. |
| "A Summary section makes the PR easier to scan" | A header pair on a one-line diff makes it slower to scan, not easier. Plain lines, sized to the diff, scan fastest. |

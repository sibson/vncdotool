---
name: writing-code-comments
description: Use when about to write or edit a comment, docstring, module header, or CHANGELOG entry in any language, and when auditing a diff, branch, file, or changelog section for prose quality — including when review feedback calls comments or entries verbose, redundant, obvious, noisy, restating the code, or when a repo's conventions file has a comments policy to apply.
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
   considered.
4. Apply. Re-read each rewrite against Mode A as if authoring it fresh.
5. Report every verdict, and for each **keep**, the fact it carries in a
   handful of words. Counts alone read as diligence; a list of kept facts
   shows which ones are really "explains the design I just chose".

**Shortening is not a fix.** A shortened unnecessary comment is still an
unnecessary comment, now also cryptic.

### Sweeping your own work

Judging a comment you wrote an hour ago is not the same task. Reading it
replays the reasoning that produced it, and it scores as load-bearing because
you are supplying the load. Reviewers of that same branch come back with
"describes the code", "verbose", "unnecessary context" — on comments the
author's own sweep kept.

So for anything authored in this session or branch, do not decide by reading
it. Decide by naming, out loud, where the fact lives if the comment goes:

> "Deleting this, the fact survives in ___."

The commit body, the PR, the README, the code itself — any of those is a
delete. Only "nowhere, and the next reader hits it at this line" is a keep.
Anything written to explain a decision made *in this branch* starts as a
delete: that is what the commit message is for, and you are about to write it.

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
| Cites a requirement by bare identifier: `R3`, `N2` | rewrite — name the constraint, or the document by title |
| Explains why the design is *this* rather than something else | delete — that is the commit body |
| File header saying what the file is for, or which env vars it reads | delete — the name says the first, the code says the second |
| True when written, false now: names a deleted file, a removed path, a caller that stopped calling | delete, and check its neighbours — rot arrives in clusters |
| Banner or section-divider comment | delete, or fold into prose |
| Compressed until the reasoning is gone | rewrite at full length; clarity outranks brevity |
| Asserts what an external system does, with no cited spec or stated observation | delete, or rewrite down to what was actually observed |
| A behaviour nothing in the code enforces, or a constraint from outside the file | keep |

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

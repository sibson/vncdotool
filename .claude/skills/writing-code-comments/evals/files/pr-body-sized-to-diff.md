# Task

Below is a pull request description that is about to be posted, and the diff it
describes. Rewrite the description so it follows the repo's policy, then list
what you cut and why.

## Repo conventions (from CLAUDE.md)

> A pull request description is read by someone deciding where to spend their
> attention, not by the archive: a title plus a few sentences saying what
> changed, what a reviewer would not guess from the diff, and what was tested.
> Under ~15 lines. The commit bodies already carry the full rationale, and
> restaging them in the description only makes the reviewer read it twice.
> Findings outside the diff get a line and a pointer, not a section.

## Context

CI on this repo runs the unit suite and flake8 on every pull request, and a red
check blocks the merge button. The commit body on the single commit in this
branch already carries the full rationale, including the rejected
`effective_pixel_format` alternative.

## The diff

Four changed files: the capture guard in `tests/functional/utils.py` now
resolves both sides through the recorded `ServerInit` instead of comparing the
`pixel_format` string from `conditions.json`; `tests/unit/test_goldens.py`
gains one test that fails a vacuous pair; two fixture `conditions.json` files
are untouched.

## The proposed description

> ## Summary
>
> The golden duplicate-format guard compared the `pixel_format` *string* in
> conditions.json, so a fixture captured with no `--pixel-format` — recorded as
> `null` — never matched a named format, even when the server's own format was
> that format. tigervnc announces exactly `bgrx8888`, so a `-native` and a
> `-bgrx8888` fixture both passed the guard and their `TestCrossFormat_` case
> compared two recordings of identical wire bytes while looking green.
>
> Both sides now resolve through the recorded ServerInit, which is the only
> thing that says what a `null` negotiated. `test_goldens.py` makes the same
> comparison and fails such a pair: the capture guard only helps whoever is
> capturing, while the replay check also reaches fixtures already committed.
>
> No conditions.json schema change, so every committed fixture replays
> untouched and #406 needs no recapture. The alternative, an
> `effective_pixel_format` field, reads better but is derived data that can
> drift from the bytes it describes.
>
> ## Test plan
>
> - [x] `make test` — 303 pass
> - [x] `flake8 --count --statistics vncdotool tests`
> - [x] New unit test is mutation-checked: with its assertion removed, the
>       vacuous pair passes green.

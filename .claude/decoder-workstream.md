# Decoder workstream — overnight run state

Durable state for the stacked-PR run over `specs/decoder-architecture.md`.
Lives only on `claude/decoder-workstream-stacked-prs-rx9sra` (the tracking
branch); no phase branch carries it, so no PR diff contains it.

## Standing instructions (survive an interruption; re-read this file first)

- Scope: Phases 1 through 4 of the build order, one stacked PR per phase.
- Stack: each phase branch bases on the previous phase's branch. Never merge;
  every PR is left open for review.
- Branches: `claude/decoder-p1-pixelformat`, `-p2-pump`, `-p3-encodings`,
  `-p4-hextile`. PRs open non-draft.
- Verify before opening: `make test`, `flake8 --count --statistics vncdotool tests`.
  Docker is unreachable in this container, so fleet/functional checks happen only
  in CI; watch each PR to green before starting the next phase.
- Per PR, after CI is green: `/code-review` at high effort plus a CLAUDE.md
  comment-convention sweep, fixes applied as commits, findings summarized in one
  PR comment. No inline review comments.
- Quiet overnight: message the user only when blocked on a decision only they
  can make.
- Re-arm a `send_later` check-in ~1h out every turn until the stack is done.

## Progress

| Phase | Branch | PR | Code | CI green | Reviewed |
|---|---|---|---|---|---|
| 1 pixel format | claude/decoder-p1-pixelformat | — | not started | — | — |
| 2 pump/Raw/CopyRect | claude/decoder-p2-pump | — | not started | — | — |
| 3 --encodings, RRE/CoRRE | claude/decoder-p3-encodings | — | not started | — | — |
| 4 Hextile | claude/decoder-p4-hextile | — | not started | — | — |

## Already landed before this run

Phase -1 (#385, released 1.4.1), Phase 0 (goldens #392, capture tooling),
`vncdotool/pixelformat.py` (#397). Phase 1 remainder: wire `raw_mode` into
`client.py`, delete `PF2IM`, add `--pixel-format`, cross-format golden check.

## Log

- (setup) branch scaffolding written, check-ins armed.

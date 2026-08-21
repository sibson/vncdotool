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
- Oracles, by fleet. On the Docker fleet the scene player can push the committed
  PNGs to the server's X framebuffer, so validation is against
  `tests/goldens/scenes/<key>.png` -- never against a Raw replay, which would
  make the oracle a second capture (`specs/decoder-goldens.md`). On the OS fleet
  (`os-servers.yml`: ultravnc, screen-sharing) nothing can put a known image on
  the server's screen, so there is no oracle image and the comparison there is
  the same scene decoded with Raw against the encoding under test.
- Per PR, after CI is green: `/code-review` at high effort plus a CLAUDE.md
  comment-convention sweep, fixes applied as commits, findings summarized in one
  PR comment. No inline review comments.
- Quiet overnight: message the user only when blocked on a decision only they
  can make.
- An hourly Routine (`trig_01BoHfxfegLMGu2FmPg9Jscm`, fires at :20) restarts this
  work after any interruption. Delete it once all four PRs are open, green and
  reviewed. Its fired turns may arrive without `mcp__github__*` tools, and there
  is no `gh` CLI here: when that happens, do the code work and push over git,
  and leave PR-opening and CI-checking to a turn that has them rather than
  reporting the phase blocked.

## Progress

| Phase | Branch | PR | Code | CI green | Reviewed |
|---|---|---|---|---|---|
| 1 pixel format | claude/decoder-p1-pixelformat | #399 | done | watching | panel running |
| 2 pump/Raw/CopyRect | claude/decoder-p2-pump | — | not started | — | — |
| 3 --encodings, RRE/CoRRE | claude/decoder-p3-encodings | — | not started | — | — |
| 4 Hextile | claude/decoder-p4-hextile | — | not started | — | — |

## Already landed before this run

Phase -1 (#385, released 1.4.1), Phase 0 (goldens #392, capture tooling),
`vncdotool/pixelformat.py` (#397). Phase 1 remainder: wire `raw_mode` into
`client.py`, delete `PF2IM`, add `--pixel-format`, cross-format golden check.

## Delegation

The user asked for Sonnet subagents on the mechanical chunks of a phase (per-decoder
unit tests from captured fixtures, docs, CHANGELOG) with the architecture-bearing
parts kept inline, plus a parallel review panel per PR. Reviewers read the branch by
commit (`git diff origin/main...origin/<branch>`), never the working tree, so a
concurrent checkout cannot confuse them, and they are told not to edit: fixes are
applied here.

Review panel, three lenses: protocol correctness against RFC 6143/rfbproto; test
adequacy (would a regression actually fail?); CLAUDE.md conventions and the comment
sweep.

## Log

- (setup) branch scaffolding written, check-ins armed.
- Phase 1 built, PR #399 opened off main. Review panel spawned.

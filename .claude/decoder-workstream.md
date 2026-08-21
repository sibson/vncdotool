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
| 1 pixel format | claude/decoder-p1-pixelformat | #399 | done | green (85554d2) | reviewed, 4 findings fixed |
| 2 pump/Raw/CopyRect | claude/decoder-p2-pump | #402 | done | green (1491bf4) | reviewed, 6 findings fixed |
| 3 --encodings, RRE/CoRRE | claude/decoder-p3-encodings | #405 | done | green (fd9cf7c) | reviewed, 4 findings fixed |
| 4 Hextile | claude/decoder-p4-hextile | #406 | done | green (13cd50c) | reviewed, 3 findings fixed |

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
- Phase 1 review found four real defects, all fixed: fixtures record no
  SetPixelFormat so a non-native capture replayed at the wrong pixel width;
  the tolerance was read off the native format; three ways the cross-format
  check passed while asserting nothing; and an unreadable requested format
  escaped setImageMode as an exception, hanging api.connect instead of
  failing it.
- The second golden capture is rgbx8888, not rgb565: a reduced format cannot
  be captured at all until the scene key patch survives quantization, which
  invalidates the committed fixture and needs the fleet to re-capture.
- CI runs the Docker fleet (`tests/functional`) and both OS servers, so a
  functional test is how this run proves anything against a real server --
  tests/functional/test_pixel_format.py does it for R3.
- Phase 2 built, PR #402 opened on top of #399. **N1 is not met**: Raw is
  3.8ms on main against 4.7ms through the pump (`make bench`, median of 60).
  Two hypotheses profiled and reverted; what remains is per-rectangle
  generator and buffer cost. Measured and reported rather than papered over
  or fixed by inventing API. The user's call in the morning.
- Phase 2's review found a severe one: a failed decode returned without
  re-arming expect(), so _handleExpected re-entered the dead generator, read
  its StopIteration as success, painted a phantom rectangle out of the
  untouched backing and ran on to commitUpdate -- all after the session was
  declared bad. Fixed with a real terminal state (abortConnection), plus five
  others: zero-dimension rectangles wrongly refused (R5), MAX_DESKTOP_SIZE
  bounding nothing so 65535x65535 asked for 17GB and parked forever,
  unvalidated yielded counts, zlib.error/MemoryError uncaught, a reused
  backing never cleared, and module-scope decoder instances shared between
  connections (R7).
- Phases 3 and 4 open as #405 and #406. Hextile is 84 lines against the 193
  it deleted; rfb.py is down from 1249 to 1056.
- N2 is half measured, and that half now passes in CI: Hextile puts fewer
  bytes on the wire than Raw for the same scene, measured through vnclog. The
  render-time half needs a captured Hextile fixture, so it needs the fleet.
- All four PRs green at their current heads and all reviewed. The hourly
  Routine is deleted; nothing wakes this session on its own any more.
- Measured, not assumed: tigervnc really emits RRE and Hextile when asked
  (the fleet job asserts it), so the support table's yes for both is
  confirmed against the current image.

- Phase 3's review found copyRectangle pasting black for a source running off
  the framebuffer (Pillow zero-fills a crop that leaves the image), clipping
  instead of growing the canvas, and never calling drawCursor. All three were
  unreachable while it was a stub.
- Phase 4's review fuzzed the decoder against an independent encoder and found
  two: colours carried across a raw tile, which rfbproto forbids -- and the
  test committed with it asserted that as correct -- and a tile declaring zero
  subrectangles was refused for having no foreground.
- The first fleet run on #406 failed on my own bandwidth test: `key` and
  `pause` never issue a FramebufferUpdateRequest, so the capture held only the
  handshake and the comparison was between two constants.

## Open questions for the morning

1. **N1.** Raw is ~20% slower through the pump (3.8ms -> 4.7ms). Accept it as
   the cost of the architecture, or spend a fast path on it?
2. **The rgb565 golden capture.** Needs a quantization-tolerant scene key,
   which invalidates the committed fixture and needs a re-capture.
3. **The encoding probe** for the UltraVNC and Screen Sharing columns of the
   support table: not done, wants its own change now that --encodings exists.

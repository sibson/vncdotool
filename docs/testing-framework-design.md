# Server Testing Framework — Design

Status: draft, under review. Companion to
[server-compatibility-plan.md](server-compatibility-plan.md); this document
designs the Phase 0 framework that plan calls for.

## Problem

vncdotool talks to many VNC server implementations and breaks against them
invisibly: only LibVNCServer is meaningfully covered today. We need a common
set of scenarios run against real servers, a road for evidence from servers
we cannot host, and regression coverage that survives without any server at
all.

## Principle

**Unit tests are the regression layer. Live servers are for smoke and
discovery. Captures are for discovery against servers we can't run.**

Replay of recorded traffic is inherently flaky and never runs in CI. A bug
found against a live server or a capture is *distilled* into a byte-level
unit test (the `test_issue_90` pattern: feed crafted bytes into
`VNCDoToolClient` with a mocked transport — no socket, no reactor,
deterministic). The live tier and the capture kit are bug *sources*; the
unit suite is where bugs stay fixed.

## The three legs

### 1. Unit layer (regression)

- Protocol quirk tests: crafted server bytes driven into the client, one
  test per distilled bug. Lives in the topical files
  (`tests/unit/test_rfb.py`, `test_client.py`) per existing convention;
  `test_issue_NNN.py` remains the triage staging area.
- **Decoder golden tests**: per-encoding FBU byte sequences (raw, RRE,
  hextile, ZRLE, Tight, ...) fed to the client, decoded framebuffer
  asserted pixel-exactly. Fixture bytes are captured once (via the capture
  tool, against any server that speaks the encoding) and committed. This
  replaces the pexpect golden-PNG tests with a stronger net: deterministic
  by construction, and coverage per encoding rather than per whatever
  LibVNCServer's example happens to negotiate.
- `api.py` logic continues to be covered here with mocked transports.

### 2. Live fleet (smoke + discovery)

Tier 1 = the Docker Compose fleet (`tests/servers/`). Tier 2 = OS-hosted
servers on Windows/macOS runners (`os-servers.yml`).

**Scenario grid**: a small core scenario set crossed with every server —
connect, key press, mouse move, screenshot (and expect where a desktop
renders). Implemented as plain `unittest` test methods on the existing
server-test mixin — one method per scenario, one subclass per server.
No scenario registry / NamedTuple machinery: the method grid *is* the
matrix. A reduced capability model survives on the server descriptors
(`renders_desktop`, `known_size`, auth fields) to drive honest skips —
e.g. macOS Screen Sharing's black framebuffer.

**Execution model**: every fleet scenario runs the real CLI via
`subprocess.run(["vncdo", ...], timeout=N)`.

- One hang-containment mechanism for every hang class: the kernel reaps the
  child. No reactor thread in the test process, no `api.shutdown()`
  ordering, no poisoned reactor coupling tests to each other. This is what
  lets the framework cope with a client that (pre-Phase 1) still hangs
  against hostile servers: CI fails on timeout, never hangs.
- It exercises the CLI surface (arg parsing, exit codes, `--nocursor`, ...)
  as a side effect, so the old pexpect CLI tests fold in here.

**Input verification — event sinks, not pixels**: "did the server process
`type foo`" is asserted against an event log, never a screenshot.

- *vncev container* (client conformance): libvncserver's `vncev` as a
  compose service printing every received event; tests assert keysyms,
  press/release pairs, and order from `docker compose logs`. Verifies what
  the client put on the wire, server-independent. Direct pexpect
  replacement.
- *X-side sink* (server processing): X-based fleet containers (x11vnc/Xvfb,
  Xvnc) run `xev`/`xinput test` inside, logging to stdout or a file; tests
  read it via `docker compose logs` / `docker exec`. Verifies the server
  translated the VNC event into a real X event — the full path. Per-server
  input quirks surface as event-log diffs.

Both are poll-a-log-with-deadline. Tier 2 has no sink yet; see open
questions.

**In-process API suite** (small, separate): the library API needs live
coverage of its *lifecycle*, not of server compatibility — `api.connect`,
error propagation, timeouts, `api.shutdown` cleanliness — against a single
known-good container. One reactor per process means this suite runs in its
own process invocation. It does not fan out across the fleet: server
compatibility is already proven by the subprocess grid.

### 3. Capture kit (discovery for unhosted servers)

For servers we cannot run (RealVNC, Proxmox, ...), contributors submit
evidence instead of access.

**Capture tool**: a `--capture-raw ARCHIVE.zip` flag on the existing proxy
CLI (`vnclog`). Contributor pip-installs released vncdotool, points their
client (or a `vncdo` script) through the proxy at their server, and gets a
capture archive to attach to an issue. No repo checkout required.

Capture archive format — bytes stay dumb, parsing happens at
replay/distill time, so the format never needs versioning:

    session.vdo   # what was driven (vncdo script / logged commands)
    s2c.bin       # raw server-to-client stream
    c2s.bin       # raw client-to-server stream
    meta.json     # server version string, security types offered,
                  # vncdotool version, geometry, timestamps

**Auth is stripped at capture time, before bytes touch disk.** The recorded
handshake is not the credential exchange that happened; it is a synthetic
`none`-auth one that vnclog writes in its place:

    s2c.bin:  <recorded greeting> <none-only security list>
              [<SecurityResult ok>] <recorded ServerInit onwards>
    c2s.bin:  <recorded greeting> [<chosen type: none>]
              <recorded ClientInit onwards>

The bracketed steps depend on the version the original client negotiated —
pre-3.7 has the server pick the type in a 4-byte field, and pre-3.8 `none`
carries no SecurityResult. Nothing from the real auth exchange is written:
not zeroed, not shortened, *absent*.

This replaces equal-length zero redaction, and is a stronger guarantee for
a contributor to reason about — "the archive contains no credential bytes"
rather than "the credential bytes are zeros". It is also what makes replay
a dumb byte-pusher: the archive already describes a session any client can
connect to without a password, whatever the original server demanded.

**Stripping requires following the handshake.** Skipping the auth exchange
means knowing where it ends, which needs a grammar for it. vncdotool has
one for `none`, VNC auth and ARD, and none for tight, vencrypt, rsa-aes or
MS-Logon — so a session negotiating one of those still aborts the capture
by default, exactly as the zero-redaction design did, with the reason
restated: not "we cannot find the secret" but "we cannot find the end of
it". The escape hatch below is the same one.

**`--capture-raw-unsafe` records the handshake verbatim**, every auth type
alike, for the bug that lives in the negotiation itself — and for ARD,
whose Diffie-Hellman exchange stripping now removes along with everything
else. Its archives carry a real key exchange and whatever credentials it
protected; the paved-road doc says so, and says to use a disposable
password and rotate it. It supersedes `--capture-raw-unsafe-auth`, which is
removed rather than aliased: the kit is unreleased.

**Replay tool** — `vncdo-replay`, a shipped console script, two modes:

    vncdo-replay --server capture.zip    # serve the recorded s2c.bin
    vncdo-replay capture.zip             # run the recorded session.vdo

The two are separate processes on purpose. An earlier revision had the
server fork its own client so a single command reproduced the whole
session; driving it turned out to be the wrong job for the thing serving
the bytes, and it made the tool awkward to point at a GUI viewer or at a
`vncdo` invocation with an extra command appended. Two composable tools,
one terminal each.

`--server` listens on a port and plays `s2c.bin` back at whatever connects,
pacing the handshake against the client's real replies — the same grammar
the capture side uses, which is what keeps the two from drifting — and
holding the recorded framebuffer until the client's first
FramebufferUpdateRequest. A capture holds one finite recording of the
screen, so those bytes get exactly one chance to be useful; sent before the
client asked, they go past a client that asks a moment later, which then
waits forever. There is no security-type divergence check: a stripped
archive offers `none` and cannot diverge, and an unsafe one is served
as-is and left to desync if the live client chose differently.

Client mode is a thin wrapper: pull `session.vdo` out of the archive and
hand it to `vncdo`, defaulting `-s` to the replay server's own
`127.0.0.1::5999`. Trailing arguments pass through, so
`vncdo-replay capture.zip capture screen.png` replays the recorded input
and then takes a screenshot. Being faithful to what the original client
sent is the point: a replay driven by different events is a different
session, and a replay of a different session is not evidence.

No recorded capture is ever replayed in CI. One inline-bytes end-to-end
test, `tests/functional/test_replay.py`, does run in CI to guard the
server's own handshake logic. The end product of any capture investigation
is a distilled unit test with inline bytes; the capture itself is
issue-thread evidence, not a repo fixture.

## What this removes

- **pexpect**: replaced by `subprocess.run` + event-sink log assertions.
- **Native libvncserver build** (`make libvnc-examples`, host toolchain
  requirement, build harness): if libvncserver's example server stays in
  the matrix, it becomes one more compose service, built in-container and
  pinned/cached like the rest of the fleet.
- **Golden PNG comparisons against a live server**: superseded by unit
  decoder goldens (leg 1).
- **Replay/transcripts as CI fixtures**: never existed; explicitly out.

## Compatibility matrix visibility

The CI grid is the matrix: server × scenario as test names, visible per
run. A hand-maintained caveats table lives in the compatibility plan doc.
A generated `docs/compatibility.rst` is explicitly **not** a requirement;
revisit only if someone asks for it.

## In-flight PRs

- **#340** (digest pins, versions.md, image build cache): orthogonal and
  compatible — proceed.
- **#341** (scenario registry framework): superseded by this design. The
  registry's consumers (recorder replaying Python scenario bodies, Tier 3
  checklist generation) no longer exist — the Tier 3 artifact is a `.vdo`
  script, which is already data. Salvage: the capability model (reduced),
  the server descriptors, and any container/mixin plumbing that maps onto
  the plain-method grid. Close or rework accordingly.
- **#342** (issue-90 byte-level reproduction): the template for leg 1
  distilled tests; lands independently.

## Phasing

1. Fleet smoke grid as subprocess tests + vncev/X event sinks; fold CLI
   tests in; retire pexpect and the native build. (Reworks #341's branch
   terrain.)
2. Decoder golden unit tests: capture per-encoding fixture bytes, commit,
   delete golden-PNG suite.
3. `--capture-raw` flag + auth stripping + contributor paved-road doc.
4. `vncdo-replay` as distillation aid.
5. In-process API lifecycle suite against one container.

Each phase is independently landable; 1 and 2 remove the most CI fragility
and can proceed while 3–5 follow.

## Open questions / TODOs

- **Tier 2 input validation**: Windows/macOS have no event sink today.
  Investigate per-OS agents (AutoHotkey key listener on Windows, an event
  tap on macOS) so `type`/`move` can be verified server-side there rather
  than remaining connect/screenshot-only smoke.
- **Special keys across servers**: the vncev sink proves which keysym the
  client put on the wire, which is necessary but not sufficient. Reported
  KEYMAP bugs are about what a *server* does with that keysym, and look
  locale- or layout-dependent, so they can only be caught by driving the
  key classes (named keys, function keys, modifier combos, keypad) at every
  fleet server and reading the X-side sink. Needs a per-class matrix rather
  than the one-key-per-server smoke case that exists today.
- **Fleet expansion** (TightVNC, QEMU, more): follows the plan's tier
  process; this framework adds a server as one descriptor + one subclass.
- **Phase 1 interplay**: once "fail loudly, never hang" lands in the
  client, per-test subprocess timeouts can tighten, and the in-process API
  suite can grow adversarial cases (misbehaving-server lifecycle) using the
  replay tool locally.

# Server Testing Framework Design

Status: built. Companion to
[server-compatibility-plan.md](server-compatibility-plan.md); this document
designs the Phase 0 framework that plan calls for. "Open questions / TODOs"
below are follow-on work, not gaps in the framework itself.

## Problem

vncdotool talks to many VNC server implementations and breaks against them
invisibly: only LibVNCServer is meaningfully covered today. This calls for a
common set of scenarios run against real servers, a road for evidence from
servers that cannot be hosted, and regression coverage that survives without
any server at all.

## Principle

**Unit tests are the regression layer. Live servers are for smoke and
discovery. Captures are for discovery against servers that can't be run.**

Replay of recorded traffic is inherently flaky and never runs in CI. A bug
found against a live server or a capture is *distilled* into a byte-level
unit test (the `test_issue_90` pattern: feed crafted bytes into
`VNCDoToolClient` with a mocked transport: no socket, no reactor,
deterministic). The live tier and the capture kit are bug *sources*; the
unit suite is where bugs stay fixed.

## The three legs

### 1. Unit layer (regression)

- Protocol quirk tests: crafted server bytes driven into the client, one
  test per distilled bug. Lives in the topical files
  (`tests/unit/test_rfb.py`, `test_client.py`) per existing convention;
  `test_issue_NNN.py` remains the triage staging area.
- **Decoder golden tests**: per-encoding FBU byte sequences (raw, RRE,
  hextile, ZRLE, Tight, and so on) fed to the client, decoded framebuffer
  asserted pixel-exactly. Fixture bytes are captured once (via the capture
  tool, against any server that speaks the encoding) and committed. This
  replaces the pexpect golden-PNG tests with a stronger net: deterministic
  by construction, and coverage per encoding rather than per whatever
  LibVNCServer's example happens to negotiate.
- `api.py` logic continues to be covered here with mocked transports.

### 2. Live fleet (smoke + discovery)

Tier 1 = the Docker Compose fleet (`tests/servers/`). Tier 2 = OS-hosted
servers on Windows/macOS runners (`os-servers.yml`).

**Scenario grid**: a small core scenario set — connect, key press, mouse
move, screenshot (and expect where a desktop renders) — implemented as
plain `unittest` test methods on the server-test mixin, one method per
scenario and one subclass per server. No scenario registry / NamedTuple
machinery: the method grid *is* the matrix. A reduced capability model
survives on the server descriptors (`renders_desktop`, `size`, auth
fields) to drive honest skips, for example, macOS Screen Sharing's black
framebuffer.

The Docker fleet runs this grid against two servers
(`test_server_compat_docker.py`). TigerVNC is the fast path: `vncdo` broken
outright fails in seconds rather than part-way through suites that take
minutes. libvncserver-example is there because it has no X server, so it
cannot run the scene player and the encoding and pixel-format grids cannot
reach it — the grid is the only thing that sends it input. Every other fleet
server is covered in more detail by those grids and stays out of this one.

QEMU has no X server either. It reaches the encoding grid on screens `type`
asks OVMF's UEFI shell to draw, with a Raw capture of the same screen as the
oracle — the firmware boots no guest, so there is no scene player and no
committed PNG to hold a capture against. Checking the other decoders against
the simplest one is weaker than what a scene server gets. The pixel-format
grid and the decoder goldens still do not reach QEMU.

Tier 2 keeps a subclass per server for the same reason as
libvncserver-example: for an OS-hosted server the smoke grid is the only
coverage there is.

**Fleet identity**: the fleet is machine-global, fixed ports 5931-5943 and
one compose project, while checkouts are many, and the Dockerfile bakes
committed files (the scene PNGs, `scene_player.py`, the entrypoints) into
its images. So a checkout that never ran `make servers-up` tests against
whichever checkout did, reading that checkout's baked files back off the
wire as if they were its own. `tests/servers/fleet-tag.sh` hashes the
Dockerfile's COPY inputs, plus the Dockerfile and `docker-compose.yml`
themselves; `servers.mk` tags the images with it, and `fleet_mismatch()` in
`tests/functional/utils.py` reads the tag back off the running container, so
the mismatch fails by name in `servers-up` and in the tests that depend on
baked content.

The hash is of the working tree, because that is what `docker compose build`
bakes. Identical content hashes identically whether committed or not, which
CI relies on: `FLEET_TAG` is also the GHCR pull key that decides whether a
fleet is fetched or rebuilt.

**Execution model**: every fleet scenario runs the real command-line tool via
`subprocess.run(["vncdo", ...], timeout=N)`.

- One hang-containment mechanism for every hang class: the kernel reaps the
  child. No reactor thread in the test process, no `api.shutdown()`
  ordering, no poisoned reactor coupling tests to each other. This is what
  lets the framework cope with a client that (pre-Phase 1) still hangs
  against hostile servers: CI fails on timeout, never hangs.
- It exercises the command-line tool's surface (arg parsing, exit codes,
  `--nocursor`, and more) as a side effect, so the old pexpect command-line
  tests fold in here.

**Input verification (event sinks, not pixels)**: "did the server process
`type foo`" is asserted against an event log, never a screenshot.

- *vncev container* (client conformance): libvncserver's `vncev` as a
  compose service printing every received event; tests assert keysyms,
  press/release pairs, and order from `docker compose logs`. Verifies what
  the client put on the wire, server-independent. Direct pexpect
  replacement.
- *X-side sink* (server processing): X-based fleet containers (x11vnc/Xvfb,
  Xvnc) run `xev`/`xinput test` inside, logging to stdout or a file; tests
  read it via `docker compose logs` / `docker exec`. Verifies the server
  translated the VNC event into a real X event, the full path. Per-server
  input quirks surface as event-log diffs.

Both are poll-a-log-with-deadline. Tier 2 has no sink yet; see open
questions.

**In-process API suite** (small, separate): the library API needs live
coverage of its *lifecycle*, not of server compatibility. That means
`api.connect`, error propagation, timeouts, and `api.shutdown` cleanliness,
tested against a single known-good container. One reactor per process means

exactly one module (`test_api_lifecycle.py`) may ever touch `vncdotool.api`
in-process; it is safe inside the shared functional discover because every
other module is subprocess-only and never touches that reactor, regardless
of run order.

`make test-api` also runs it alone. It does not fan out across
the fleet:
server compatibility is already proven by the subprocess grid.

### 3. Capture kit (discovery for unhosted servers)

For servers that cannot be run (RealVNC, Proxmox, and others), contributors
submit evidence instead of access.

**Capture tool**: a `--capture-raw ARCHIVE.zip` flag on the existing proxy
command-line tool (`vnclog`). Contributor pip-installs released vncdotool,
points their client (or a `vncdo` script) through the proxy at their server,
and gets a capture archive to attach to an issue. No repo checkout required.

Capture archive format. Bytes stay dumb, and parsing happens at
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

The bracketed steps depend on the version the original client negotiated.
Pre-3.7 has the server pick the type in a 4-byte field, and pre-3.8 `none`
carries no SecurityResult. Nothing from the real auth exchange is written:
not zeroed, not shortened, *absent*.

This replaces equal-length zero redaction, and is a stronger guarantee for
a contributor to reason about: "the archive contains no credential bytes"
rather than "the credential bytes are zeros." It is also what makes replay
a dumb byte-pusher: the archive already describes a session any client can
connect to without a password, whatever the original server demanded.

**Stripping requires following the handshake.** Skipping the auth exchange
means knowing where it ends, which needs a grammar for it. vncdotool has
one for `none`, VNC auth and ARD, and none for tight, vencrypt, rsa-aes or
MS-Logon. A session negotiating one of those still aborts the capture by
default, exactly as the zero-redaction design did, with the reason restated:
not "the secret can't be found" but "the end of it can't be found." The
escape hatch below is the same one.

**`--capture-raw-unsafe` records the handshake verbatim**, every auth type
alike, for the bug that lives in the negotiation itself, and for ARD,
whose Diffie-Hellman exchange is now removed by stripping along with
everything else. Its archives carry a real key exchange and whatever credentials it
protected; the paved-road doc says so, and says to use a disposable
password and rotate it. It supersedes `--capture-raw-unsafe-auth`, which is
removed rather than aliased: the kit is unreleased.

**Replay tool**: `vncdo-replay`, a shipped console script, two modes:

    vncdo-replay --server capture.zip    # serve the recorded s2c.bin
    vncdo-replay capture.zip             # run the recorded session.vdo

The two are separate processes on purpose. An earlier revision had the
server fork its own client so a single command reproduced the whole
session; driving it turned out to be the wrong job for the thing serving
the bytes, and it made the tool awkward to point at a GUI viewer or at a
`vncdo` invocation with an extra command appended. Two composable tools,
one terminal each.

There is no security-type divergence check: a stripped archive offers
`none` and cannot diverge, and an unsafe one is served as-is and left to
desync if the live client chose differently. Rationale for the handshake
pacing, the framebuffer-hold behaviour, and the client-mode wrapper is in
`docs/capture.rst`.

No recorded capture is ever replayed in CI. One inline-bytes end-to-end
test, `tests/functional/test_replay.py`, does run in CI to guard the
server's own handshake logic. The end product of any capture investigation
is a distilled unit test with inline bytes; the capture itself is
issue-thread evidence, not a repo fixture.

## The screen-change source

Golden fixtures need a VNC server whose screen changes on demand.
`tests/goldens/scene_player.py` does it, and
[decoder-goldens.md](decoder-goldens.md) designs it along with the capture
path and the fixtures.

What it cannot do is choose the rectangles: the server decides how a screen
change becomes rects. Dictating them needs an app that marks its own,
and only libvncserver can be made to. Measured against 0.9.14, it has no
framebuffer comparator at all, so `rfbMarkRectAsModified` decides granularity
exactly, while x11vnc diffs a framebuffer it merely polls. So an example off
`pnmshow` stays the route to the cases that need a chosen layout: many
scattered rectangles, mid-session resize, and CopyRect, which marking cannot
reach at all and needs an explicit `rfbDoCopyRect`. It costs one
`cmake --build` target and one image stage, the fleet already building
libvncserver from a pinned release.

## What this removes

- **pexpect**: replaced by `subprocess.run` + event-sink log assertions.
- **Native libvncserver build** (`make libvnc-examples`, host toolchain
  requirement, build harness): if libvncserver's example server stays in
  the matrix, it becomes one more compose service, built in-container and
  pinned/cached like the rest of the fleet.
- **Golden PNG comparisons against a live server**: superseded by unit
  decoder goldens (leg 1).
- **Replay/transcripts as CI fixtures**: never existed; explicitly out.

## What each suite proves

None of them subsumes another.

- **The smoke test** is the critical user journey: connect, send input,
  capture a screen. It catches `vncdo` breaking outright, and runs first.
- **The compatibility grids** drive real products, so they cover a wider
  variety of settings and behaviours than a fixture can carry.
- **The scene tests** are decoder resilience to variation in server
  behaviour, held against the image the server was actually shown rather
  than against anything our decoder produced.
- **The goldens** replay committed wire bytes offline, so any feature can be
  tested on every OS we support, and a server nobody can deploy locally or
  in CI can still be covered by someone sending us a capture of it.

## Compatibility matrix visibility

The CI grid is the matrix: server × scenario as test names, visible per
run. A hand-maintained caveats table lives in the compatibility plan doc.
A generated `docs/compatibility.rst` is explicitly **not** a requirement;
revisit only if someone asks for it.

## In-flight PRs

- **#340** (digest pins, versions.md, image build cache): orthogonal and
  compatible; proceed.
- **#341** (scenario registry framework): closed, superseded by this
  design. Its `Scenario`/`ScenarioContext`/`SCENARIOS` registry, the
  capability-gated `requires` matching, and the generated
  `test_<scenario>` methods all existed to serve the recorder-replay and
  Tier 3 checklist consumers that never landed; nothing else in the fleet
  reads them, so none of it carried forward. The one genuine idea inside
  it (a server declaring what it can do, so a test can skip a capability
  it lacks rather than weaken its own assertion) stays deferred rather
  than added speculatively: `renders_desktop` and `size` already gate
  inline where the plain-method grid needs it, and a `capabilities`
  property with no caller is exactly the unused abstraction this repo's
  own conventions rule out. Revisit if a second plain method needs the
  same gate. The other salvageable piece, the deferred input-reactive
  surface, is recorded below instead of in code.
- **#342** (issue-90 byte-level reproduction): the template for leg 1
  distilled tests; lands independently.

## Phasing

1. Fleet smoke grid as subprocess tests + vncev/X event sinks; fold
   command-line tests in; retire pexpect and the native build. (Reworks
   #341's branch terrain.)
2. Decoder golden unit tests: capture per-encoding fixture bytes, commit,
   delete golden-PNG suite. Scaffolded at Raw and one pixel format; the
   remaining matrix values arrive with the client features that can request
   them, per `decoder-goldens.md`.
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
- **QEMU scenes via a UEFI application**: a payload rather than a guest OS.
  OVMF's shell auto-runs `startup.nsh` off its boot media, so a small
  gnu-efi application (Debian packages the library) can draw a scene
  through the GOP `Blt()` protocol and read keys through
  `SIMPLE_TEXT_INPUT_PROTOCOL`, on a FAT image `mtools` builds without root
  or a loop mount. Converting the committed scene PNGs to raw BGRX at build
  time keeps a PNG decoder out of the C. Measured 2026-09-09:
  `-device VGA,edid=on,xres=256,yres=192` makes QEMU serve exactly the scene
  geometry, and the payload adds under a megabyte against the ~250MB a guest
  with Xorg costs. QEMU would then be an ordinary scene server, reaching
  both grids and the goldens through the existing pipeline rather than a
  second fixture shape. The goldens need the container's RFB port published
  as well, since `vnclog` cannot dial the WebSocket the fleet exposes.
- **Fleet expansion** (TightVNC, more): follows the plan's tier process;
  this framework adds a server as one descriptor, plus its membership of
  whichever server lists it belongs in.
- **macOS Screen Sharing pixel rendering is permanently untestable in CI**:
  confirmed by hand against a real Mac (2026-09-06) that ARD auth as the
  actual console owner does capture a real desktop (thousands of distinct
  colors, legible window content) rather than the black frame CI sees.
  The gap is the hosted runner, not the account: it has no attached display
  for WindowServer to composite into, so even the console owner's own
  session captures as near-solid color there. Closing it needs a
  self-hosted runner with a live desktop, which `macos.sh` refuses to run
  against on purpose (see `tests/servers/screen-sharing/README.md`), not
  worth the security/maintenance cost of a permanent GUI Mac as CI infra.
  Manual verification, as done here, is the intended check for changes that
  touch this path.
- **Input-reactive test surface**: nothing in the fleet reacts to input at
  a known screen position (`tests/servers/draw-content.sh` paints static
  content once at start-up), so a keyboard/mouse test can only assert "some
  repaint happened" or "the session didn't disconnect," never "the right
  pixels changed." Needs a deterministic reactive surface in the container
  desktop (for example, a full-screen `xterm` echoing keystrokes at a fixed
  position, plus a pointer-tracking app), which is image work with real
  flakiness risk (font rendering, timing) and its own spike. The scene player
  does not cover it: it paints the image its key names, whatever that key
  was, so it cannot answer "which keysym arrived," which is what the KEYMAP
  issues need.
- **Phase 1 interplay**: once "fail loudly, never hang" lands in the
  client, per-test subprocess timeouts can tighten, and the in-process API
  suite can grow adversarial cases (misbehaving-server lifecycle) using the
  replay tool locally.

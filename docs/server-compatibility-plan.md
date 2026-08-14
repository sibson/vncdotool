# Server Compatibility Plan

Compatibility with the many VNC server implementations in the wild is an
ongoing challenge for vncdotool. This document takes stock of where we are,
maps the gaps to the failures users actually report, and lays out a phased
plan to close them.

## Where we are today

**Protocol surface implemented in `vncdotool/rfb.py`:**

| Area | Supported | Notes |
|---|---|---|
| Protocol versions | 3.3, 3.7, 3.8 + quirks: 3.889 (Apple ARD), 4.0 (Intel AMT), 4.1/5.0 (RealVNC) | Unknown versions are logged but negotiation picks the highest known version ≤ server's |
| Security types | None (1), VNC Authentication (2), ARD Diffie-Hellman (30) | Anything else → "unknown security types" and disconnect |
| Encodings | Raw, CopyRect, RRE, CoRRE, Hextile, ZRLE | No Tight, no TRLE, no JPEG quality/compression level pseudo-encodings |
| Pseudo-encodings | Cursor, DesktopSize, LastRect, QEMU Extended Key Event | No ExtendedDesktopSize, ContinuousUpdates, Fence, Extended Clipboard |
| Transports | TCP, Unix socket | No WebSocket (noVNC, Proxmox), no TLS |

**Test coverage:** unit tests with hand-crafted byte strings; functional
tests against LibVNCServer example servers (in CI since #330) and an
optional Xvnc (TigerVNC) smoke test that only runs where `xvnc` is
installed. No other server implementation is exercised anywhere.

## What actually breaks, per the issue tracker

- **Unsupported security types** — RealVNC-flavoured servers (Raspberry Pi
  OS default) offer only RA2/RA2ne/etc.: #310. Proxmox and other
  TLS-fronted servers need VeNCrypt: #138.
- **Unsupported encodings** — servers that assume Tight support: #264.
- **Pixel-format assumptions** — black or corrupted captures when a server
  ignores our `SetPixelFormat` or uses a format outside the handful mapped
  in `client.PF2IM`: #90, #275. The ZRLE decoder hard-codes 3-byte
  compressed pixels (32bpp/depth-24/little-endian only), the Raw path has a
  literal `TODO convert pixel format?`, and the CoRRE subrect decoder has
  two latent bugs (`format` string missing its f-prefix, loop bound uses
  `sz` instead of `end`) that bite the first time a server sends CoRRE
  subrects.
- **Hangs instead of errors** — when negotiation or decoding goes wrong the
  reactor keeps waiting forever and the API never returns: #322 (silent
  disconnect/hang against shared TigerVNC), #284 ("Stopping factory" with
  no diagnosis), #262, #146. One concrete suspect: `ServerCutText` length
  is parsed as *unsigned* (`!xxxI`), but TigerVNC's Extended Clipboard
  sends a *negative* length, which we then treat as a gigantic read that
  never completes.
- **Missing protocol features users need** — SetDesktopSize (#301),
  ContinuousUpdates/Fence for sync and capture performance (#66, #201,
  #273), WebSocket transport (#259), choosing depth/encoding from the CLI
  (#167, #168), QEMU keysym gaps for symbol characters (#269).

Two structural problems underlie all of these:

1. **We can't see regressions.** Only LibVNCServer is in CI, so a change
   that breaks TigerVNC or QEMU ships silently, and a fix for one server
   can't be verified against the others.
2. **Failures are silent.** The protocol layer's default response to
   anything unexpected is `log.msg(...)` + `loseConnection()`, which the
   blocking API surfaces as an eternal hang rather than an actionable
   error.

## The plan

### Phase 0 — Measure: a server compatibility matrix in CI

Goal: every change runs the same scenario suite against a fleet of real
servers, and the results are visible.

The framework itself is designed in
[testing-framework-design.md](testing-framework-design.md), which
supersedes this section's original sketch on several points. Summary:

- **Unit tests are the regression layer; live servers are for smoke and
  discovery.** Recorded traffic never replays in CI — bugs found live or
  via capture are distilled into byte-level unit tests, and per-encoding
  decoder golden tests (crafted/captured FBU bytes → pixel-exact
  framebuffer assertions) replace live golden-PNG comparisons.
- A small core scenario grid (connect, key press, mouse move, screenshot)
  runs as plain `unittest` methods against every fleet server, each
  scenario executed via `subprocess.run(["vncdo", ...], timeout=N)` so a
  hanging client fails CI instead of hanging it. Input is verified via
  event sinks (a `vncev` container; `xev`-style logs inside X-based
  containers), not pixels.
- Fleet targets: **TigerVNC**, **TightVNC**, **x11vnc**, **QEMU**,
  containerized **LibVNCServer examples**; later noVNC/websockify,
  wayvnc. The native libvncserver source build and the pexpect harness
  are retired.
- The capture kit (`vncdolog --capture`, scrub-at-capture) plus an
  in-repo replay tool cover servers we cannot host — discovery evidence,
  not CI fixtures.
- A generated `docs/compatibility.rst` is **not** a requirement; the CI
  grid is the matrix, plus a hand-maintained caveats table here.

How the servers themselves are obtained, pinned, and kept current — for
local dev, CI, and gold-file creation — is covered in
[Acquiring and maintaining server access](#acquiring-and-maintaining-server-access).

Acceptance: CI shows a per-server pass/fail grid driven by the Tier 1
compose fleet; the proxy CLI has a `--capture` mode; decoder golden unit
tests exist for at least the encodings LibVNCServer and TigerVNC
negotiate.

### Phase 1 — Robustness: fail loudly, never hang

Goal: an incompatible server produces a clear, specific error in seconds,
not an infinite hang. This converts every future compatibility gap from a
debugging session into a good bug report.

- Add a negotiation timeout and surface **structured exceptions** through
  both `api.connect()` and the CLI: `UnsupportedSecurityTypes(types)`,
  `UnsupportedEncoding(enc)`, `AuthenticationError` (exists), each naming
  the server version string and what it offered. (#262, #284, #322, #146)
- Accept any server protocol version: per RFC 6143 §7.1.1, treat anything
  ≥ 3.8 as 3.8 and unknown intermediates as the nearest lower known
  version, logging the oddity instead of refusing. Keep the quirk table
  for versions that change semantics (ARD).
- Handle `ServerCutText` with a signed length and ignore Extended
  Clipboard payloads gracefully instead of misreading them as a huge
  unsigned read (prime suspect for #322).
- Fix the CoRRE decoder bugs; enable `PixelFormat.VALIDATE` in tests.
- On unknown rectangle encodings, include the encoding name/number and the
  negotiated list in the error so reports like #264 arrive pre-diagnosed.

Acceptance: killing/misbehaving the server in any functional scenario
fails the API call with a descriptive exception within the timeout; new
unit tests cover version quirks, signed cut-text lengths, and CoRRE.

### Phase 2 — Cover the servers people actually run

Goal: the default configurations of TigerVNC, TightVNC, UltraVNC, QEMU,
and TLS-fronted servers work out of the box. Ordered by expected impact:

1. **Tight encoding** (decode; plus Tight auth type 16 negotiation, which
   TightVNC requires before falling back to VNC auth). Default encoding
   for the largest cluster of servers. (#264)
2. **VeNCrypt security type (19)** with the TLSNone/TLSVnc/X509None/
   X509Vnc/Plain subtypes, built on Twisted's TLS support. Unlocks
   Proxmox (#138), TigerVNC with TLS, vino, and the "Plain" subtype some
   headless servers use. (#310 partially)
3. **Pixel-format correctness pass**: generalize the ZRLE compressed-pixel
   reader for bpp/endianness, implement Raw/RRE/Hextile conversion from
   any server-native true-color format to the client's working format,
   and support color-map mode (`SetColourMapEntries` is parsed today but
   discarded by the client layer). Property-based tests render reference
   images through every decoder × pixel-format combination. (#90, #275,
   #168)
4. **UltraVNC MS-Logon II (113/116)** — documented, implemented in other
   open clients; moderate effort.
5. **RealVNC RA2/RA2ne (5/6/13)** — partially reverse-engineered in other
   clients; spike first, and if infeasible, detect it and print exact
   instructions for switching the server to "VNC password" mode. (#310)

Acceptance: the Phase 0 matrix gains passing columns for TigerVNC (TLS),
TightVNC (Tight encoding negotiated), and QEMU; screenshots verified
pixel-exact against reference images for every supported pixel format.

### Phase 3 — Protocol features that modern servers expect

- **ExtendedDesktopSize** pseudo-encoding + **SetDesktopSize** client
  message (#301), replacing the legacy DesktopSize-only path.
- **ContinuousUpdates + Fence** for reliable synchronization and faster
  captures (#66, #201, #273).
- **Extended Clipboard** (beyond the Phase 1 "don't hang" guard) for
  non-Latin-1 text.
- **WebSocket transport** (`ws://`/`wss://` server addresses) targeting
  noVNC and Proxmox (#259, #138); optional dependency, Twisted-native.
- **Keysym audit** against QEMU/KVM for symbol characters and layouts
  (#269, #65).

### Phase 4 — Keep it working

- Maintain the hand-written caveats table in this doc; revisit
  auto-generation only if someone asks for it.
- Add a "compatibility bug" issue template asking for server product +
  version, and a one-liner to record a `vncdolog --capture` directory;
  each confirmed bug contributes a distilled unit test before it is
  closed.
- Add `server:<name>` issue labels and a `vncdo probe`-style diagnostic
  command that connects, prints the server version string, offered
  security types, and negotiated encodings, then exits — the first thing
  to ask any reporter to run.
- Slower matrix jobs (QEMU with a real guest image, the Tier 2 OS
  runners) run change-triggered behind path filters — never on a
  schedule — keeping PR CI fast and idle-repository cost zero.

## Acquiring and maintaining server access

The matrix, the gold files, and every phase after them depend on one
operational question: how do we get — and keep — access to the servers we
claim to support? The answer is three tiers with different acquisition
models, plus a shared reproducibility discipline.

**Guiding principle: live servers beat recordings, always.** A recorded
capture proves we *once* interoperated with one version of a server; a
live test proves we *still* do. Captures are therefore discovery
evidence for servers we cannot run — never a substitute where live
access is possible, and never CI fixtures: the durable regression floor
is the unit test distilled from them
(see [testing-framework-design.md](testing-framework-design.md)).
Concretely:

- Every server sits at the **most-live tier it can occupy**, and tier
  assignment is revisited as circumstances change: a new container image,
  a licensing change, or emulation making a Tier 3 server runnable
  promotes it to Tier 1/2.
- We actively invest in promotions. For example, RealVNC on Raspberry Pi
  OS — today's canonical Tier 3 case — is a candidate for a live CI job
  via a QEMU-emulated Pi OS image on an ubuntu runner; if that works it
  leaves Tier 3 entirely.
- Where both exist, the live run is the source of truth for the
  compatibility matrix; captures serve discovery and as source material
  for unit-level decoder golden bytes, refreshed *from* live runs where
  possible rather than treated as an independent authority.

### Tier 1 — Containerized Linux fleet (we own it, fully reproducible)

TigerVNC, TightVNC, x11vnc, QEMU, LibVNCServer examples, and later
websockify/noVNC are all runnable on Linux, so we own them outright as a
**Docker Compose fleet**:

- One `tests/servers/docker-compose.yml` defines a service per
  server × configuration (`tigervnc`, `tigervnc-auth`, `tigervnc-tls`,
  `x11vnc`, `qemu`, …), each on a distinct localhost port, each **pinned by
  image digest**. Where no trustworthy upstream image exists, a small
  in-repo Dockerfile under `tests/servers/<name>/` pins the package or
  source-tarball version instead — we prefer vendored Dockerfiles over
  third-party desktop images we don't control.
- `make servers-up`, `make servers-down`, and `make server-<name>` wrap
  compose so contributors never need to learn the fleet's internals; the
  same compose file is what the CI matrix jobs run. **Local dev and CI use
  identical bytes.**
- The native `libvncserver.mk` source build is retired: LibVNCServer's
  example servers (and `vncev`, the event-sink verifier) join the fleet as
  compose services, built in-container and pinned like the rest. No host
  toolchain requirement remains.

### Tier 2 — OS-bound live servers on hosted runners (change-triggered)

UltraVNC only runs on Windows; Apple Screen Sharing/ARD only on macOS.
Windows *containers* don't solve this: they exist
(`mcr.microsoft.com/windows/servercore` etc.) but are GUI-less — there is
no desktop session for a VNC server to share, so a screen-sharing server
has nothing to serve — and they only run on Windows hosts anyway (no help
for local dev on Linux/macOS, and no such thing as a macOS container at
all). So these two stay on full GitHub-hosted `windows-latest` /
`macos-latest` VMs, which are free for public repositories — but we only
spin them up when something relevant changes:

- The workflow triggers on `pull_request`/`push` **path-filtered to code
  that can affect server compatibility** (`vncdotool/**`, the workflow
  itself, server setup scripts) plus `workflow_dispatch` for on-demand
  runs. No scheduled runs: doc- and test-only changes never start an OS
  VM, and a quiet repository consumes nothing.
- Accepted trade-off: drift in the runner images or the Chocolatey
  package surfaces on the next change-triggered run rather than the night
  it happens. Because these jobs are report-only (never PR-blocking), a
  drift failure costs a tracked issue, not a broken merge queue.
- Each successful run can upload a wire capture as an artifact for
  offline debugging; jobs are promoted to blocking only once they prove
  stable.

### Tier 3 — Capture-only servers (community-sourced evidence)

RealVNC (Raspberry Pi OS), VMware/ESXi consoles, Proxmox, MobaXterm, and
anything else licensing or hardware puts out of CI's reach are covered by
community-recorded captures — but per the guiding principle, Tier 3 is
the tier of **last resort**: membership means "we have not yet found a
way to run this server live", and each Tier 3 server carries a note on
what its promotion path would be (emulation, a licensing change, a
self-hosted runner). Until promoted, the supply chain for these is the
community, so contributing a capture must be a paved road (detailed in
[testing-framework-design.md](testing-framework-design.md)):

1. **Record**: `vncdolog --capture DIR` sits between the reporter's
   client (or a `vncdo` script) and their server; out comes a capture
   directory — `session.vdo`, raw `s2c.bin`/`c2s.bin` streams, and
   `meta.json` (server version string, security types offered, geometry).
   The proxy scrubs secrets by construction: password bytes and auth
   challenges/responses are redacted at capture time, never trusted to
   manual editing.
2. **Submit**: attach the capture to a "compatibility bug" or "server
   report" issue. Captures are issue-thread evidence, not repo fixtures.
3. **Distill**: a maintainer replays the capture at the real client with
   the in-repo replay tool (`tests/tools/replay_server.py`), finds the
   bug, and lands a byte-level unit test — that test, not the capture,
   is the permanent regression guard.

Golden bytes for decoder unit tests follow the same discipline at Tier 1:
per-encoding FBU fixture bytes are captured once against a pinned fleet
container, committed inline in the unit suite, and regenerated only via
reviewable PR diffs.

### Staying current: pins, drift, and ownership

- **One source of version truth**: every pin (image digests, Chocolatey
  version, `LIBVNCSERVER_VERSION`) lives in the compose file plus a short
  `tests/servers/versions.md` table that CI, make, and manifests all
  reference.
- **Pinned on PRs, latest on schedule**: PR CI always runs the pinned
  fleet. A weekly scheduled job — Tier 1 containers only, cheap ubuntu
  minutes; OS runners are exercised solely by change-triggered runs and
  manual dispatch — re-runs the matrix against `:latest` images / newest
  packages and *files an issue* on failure instead of breaking PRs, so
  upstream drift becomes a tracked task, not a fire.
- Version-bump PRs (Dependabot/Renovate on image digests, or the weekly
  job's issue) regenerate any decoder golden bytes sourced from that
  server in the same PR, so pins and fixtures always move together.
- Ownership is explicit per tier: Tier 1 is maintainable by anyone with
  Docker; Tier 2 needs no hardware, only workflow upkeep; Tier 3 is
  honestly documented as "we do not own this access" and lives or dies by
  the recording pipeline — which is why the paved road above matters.

### Spike results (Tier 1 / Tier 2 viability)

**Tier 1 — VIABLE.** Branch `claude/spike-server-fleet` (commit
`bbfd188`) holds a working proof: three in-repo Dockerfile-based services
(`tigervnc` no-auth, `tigervnc-auth` VNC-password, `x11vnc` over Xvfb)
defined in `tests/servers/docker-compose.yml` with `nc`-based
healthchecks, `make servers-up`/`servers-down`/`test-servers` wrappers, and
a parameterized `tests/functional/test_servers.py` that connects, types,
and captures against each server. GitHub Actions run
[31729730724](https://github.com/sibson/vncdotool/actions/runs/31729730724)
is green end-to-end: image builds + healthcheck-gated `up --wait` in
~39s, all three per-server tests pass, non-black screenshots uploaded as
artifacts, clean teardown — ~70s total, no flakiness observed. Local
verification ran the identical test module against natively-started
servers on the same ports (3/3 pass; the dev sandbox's egress policy
blocks registry pulls, a sandbox limitation, not a design one — the
maintainer's machine with normal Docker Hub access runs the compose path
directly).

Findings worth keeping:
- `api.connect()` leaves the Twisted reactor thread running until
  `api.shutdown()` — without it, test processes and CI steps hang forever
  after passing. Any harness built on the API needs a
  `tearDownModule`-style shutdown. (Also more evidence for the Phase 1
  "hangs instead of errors" theme.)
- Debian/Ubuntu split TigerVNC packaging: `vncpasswd` lives in
  `tigervnc-tools`, needed alongside `tigervnc-standalone-server`.
- Images stay small and layer-cached (~15–20s builds); healthchecks make
  `up --wait` a reliable barrier.

**Graduated:** this spike's workflow has been folded into the `servers` job
in `.github/workflows/ci.yml` (PR-blocking, runs on every `pull_request` and
`push` to `main`); `spike-servers.yml` is deleted.

Tier 1 follow-ups:
- **Publish the screenshot gallery to GitHub Pages.** Captures currently
  reach the web only as a zipped artifact: the job summary carries a
  server/port/resolution table, but seeing the pixels means download →
  unzip → open `index.html`. Actions has no inline preview for artifact
  contents, and inlining the PNGs as `data:` URIs doesn't help — the
  markdown sanitizer strips them. Deploying the generated gallery to
  Pages gives a stable URL to link from the job summary (and outlives
  artifact expiry, which matters once fixtures reference these images).
  Needs Pages enabled on the repo, plus a decision on whether runs
  overwrite one `latest/` gallery or are namespaced by run ID. Interim
  option if Pages is unwanted: push captures to an orphan branch and have
  the workflow post/update a PR comment with `raw.githubusercontent.com`
  image links, so they render inline where review happens.
- **Stop paying the image build tax on every run.** GitHub-hosted runners
  start with an empty Docker cache, so layer caching only helps within a
  run — each CI run rebuilds from scratch (~35s of the ~70s total).
  Options: `docker/build-push-action` with `cache-from/to: type=gha`, or
  publish the images to GHCR once and have CI pull pinned digests, which
  folds into the digest-pinning item below.
- Pin base images by digest and fold this workflow into the main CI one.
- Deepen what the per-server scenario actually asserts (see Phase 0).

**Tier 2 — VIABLE on both OSes**, proven on branch
`claude/spike-os-servers` (commit `2de3252`, workflow
`spike-os-servers.yml`); final run
[31730610001](https://github.com/sibson/vncdotool/actions/runs/31730610001)
has both jobs green after four evidence-driven rounds. The recipe below
now lives as checked-in setup/diagnostic scripts under
`tests/servers/ultravnc/` and `tests/servers/screen-sharing/` (each with
a README recording why it does what it does), driven by
`tests/functional/test_os_servers.py`, which reuses the same server
description, round trip and screenshot gallery as Tier 1 via
`tests/functional/vncservers.py`.

*Windows / UltraVNC — works, full recipe:*
- `choco install ultravnc`; `winvnc.exe` lands at the fixed path
  `C:\Program Files\uvnc bvba\UltraVNC\winvnc.exe` (never search
  `Program Files` recursively — minutes-slow on runner images).
- UltraVNC refuses all connections until a password is set, regardless of
  `AuthRequired` — there is no no-auth shortcut. The `ultravnc.ini`
  `passwd=` hex uses the classic VNC password-*file* obfuscation (DES
  with the fixed `vncauth.c` key, bit-reversed) — not the
  challenge-response transform — and is computable in a few lines of
  Python on the runner.
- Must run as a Windows service (`winvnc.exe -install` +
  `Start-Service`); `winvnc.exe -run` opens an interactive settings
  dialog instead of serving.
- `vncdo type` + `capture` succeed with genuine, non-black desktop
  content — Windows gives us real visual assertions.

*macOS / Screen Sharing — works at the protocol level, with one caveat:*
- `sysadminctl -addUser` a dedicated user, then `kickstart -activate
  -configure -access -on -users … -privs -all -restart -agent`; Screen
  Sharing is socket-activated on port 5900 out of the box.
- Auth is **ARD/Diffie-Hellman (type 30)** with username+password —
  vncdotool's existing ARD support handles it. The legacy VNC-password
  path is confirmed dead on modern macOS: kickstart accepts the flags
  silently but the server still demands ARD auth. (Bonus finding: when
  no username is supplied, `rfb.py` falls into an interactive
  `input("username:")` prompt and crashes with `EOFError` on a TTY-less
  runner — another Phase 1 fail-loudly item.)
- The captured framebuffer is fully black: the runner has no rendered
  desktop to serve. So macOS jobs validate protocol, auth, and input
  events, but not pixels — visual assertions need a follow-up spike into
  whether a display can be attached, or must be scoped out for macOS.

*Graduation into Phase 0 proper:* both jobs graduate under the
change-triggered policy above — Windows as a full type+capture check with
real screen content, macOS as a protocol/auth/input check with pixel
assertions explicitly excluded until the black-framebuffer question is
answered. Productionizing should keep the dedicated-user and
service-mode setup steps and move passwords into repository secrets.

**Graduated:** this spike's workflow now lives at
`.github/workflows/os-servers.yml` (renamed from `spike-os-servers.yml`),
change-triggered and path-filtered per the policy above, report-only via
`continue-on-error: true`. Credentials come from `VNC_OS_SERVER_USERNAME`/
`VNC_OS_SERVER_PASSWORD` repository secrets, falling back to the spike
values when unset.

## Sequencing and effort

| Phase | Rough size | Depends on |
|---|---|---|
| 0 — CI matrix + capture kit + decoder goldens | Medium; pure test/infra, no protocol risk | — |
| 1 — Robustness/error reporting | Small–medium; touches negotiation paths | 0 (to verify against matrix) |
| 2 — Tight, VeNCrypt, pixel formats | Large; the core protocol work | 0, 1 |
| 3 — Desktop size, CU/Fence, WebSocket, clipboard | Medium, parallelizable per feature | 2 |
| 4 — Docs, templates, diagnostics | Small, ongoing | 0 |

Phases 0 and 1 are deliberately front-loaded: they are cheap, carry no
protocol-breakage risk, and multiply the value of everything after them —
every Phase 2/3 feature lands with matrix coverage, and every future user
report arrives as an actionable error message plus, ideally, a capture.

## Issue map

| Issue | Addressed by |
|---|---|
| #90, #168, #275 | Phase 2.3 pixel formats |
| #138, #259 | Phase 2.2 VeNCrypt + Phase 3 WebSocket |
| #146, #262, #284, #322 | Phase 1 timeouts/errors (+ cut-text fix) |
| #167 | Phase 2.1/2.3 + CLI flag |
| #201, #66, #273 | Phase 3 ContinuousUpdates/Fence |
| #264 | Phase 2.1 Tight + Phase 1 diagnostics |
| #269, #65 | Phase 3 keysym audit |
| #301 | Phase 3 ExtendedDesktopSize |
| #310 | Phase 2.2/2.5 VeNCrypt, RA2 spike |

## Risks

- **Proprietary auth (RA2)**: may prove infeasible; the fallback is
  first-class detection + documentation, which still removes the "silent
  failure" cost.
- **GUI servers in CI can be flaky**: mitigate with generous startup
  polling, per-server retry, and by quarantining unstable servers to a
  non-blocking change-triggered job rather than PR-blocking CI.
- **Decoder rewrites regress existing users**: the Phase 0 decoder
  golden unit tests (pixel-exact, per encoding) are the guard rail; land
  them first.
- **Upstream supply disappears**: a Chocolatey package or base image we
  pin can vanish or break. Mitigations: vendored in-repo Dockerfiles
  rather than third-party images, pins with the weekly drift job to catch
  breakage early, and distilled unit tests as the permanent floor — a
  server we lose live access to degrades to Tier 3, not to zero coverage.
- **Tier 3 evidence goes stale**: a capture records one server version
  at one moment. `meta.json`'s version field makes staleness visible,
  and the paved capture road keeps the cost of a refreshed contribution
  low.

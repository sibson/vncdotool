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

- Extract the common scenarios from the existing functional tests
  (connect, authenticate, keyboard, mouse, capture, expect) into a
  server-parameterized base class.
- Add CI jobs for each server installable in GitHub Actions runners:
  - **TigerVNC** (`tigervnc-standalone-server`) — plain and with password;
    also a `-SecurityTypes TLSVnc` variant once VeNCrypt lands (Phase 2).
  - **TightVNC** (`tightvncserver`).
  - **x11vnc** (libvncserver-based, but a different config surface).
  - **QEMU's built-in server** (`qemu-system-x86_64 -vnc`) — the primary
    VM-automation use case and the origin of several key-event bugs.
  - **LibVNCServer examples** (already present, keep as-is).
  - Later: noVNC/websockify (once WebSocket lands), wayvnc.
- Make each functional run record the wire traffic via the existing
  `loggingproxy` module and upload transcripts as CI artifacts. Recorded
  handshakes become **replayable unit-test fixtures**, so a compatibility
  bug reported against a server we can't install (RealVNC, macOS Screen
  Sharing, UltraVNC) can still be captured once and guarded forever.
- Generate a docs page (`docs/compatibility.rst`) from the matrix results:
  server × auth × encodings × known caveats.

How the servers themselves are obtained, pinned, and kept current — for
local dev, CI, and gold-file creation — is covered in
[Acquiring and maintaining server access](#acquiring-and-maintaining-server-access).

Acceptance: CI shows a per-server pass/fail grid driven by the Tier 1
compose fleet; the recording proxy has a raw-transcript mode; a fixture
harness exists with at least the LibVNCServer and TigerVNC handshakes
checked in.

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

- Publish the auto-generated compatibility table in the docs and link it
  from the README.
- Add a "compatibility bug" issue template asking for server product +
  version, and a one-liner to capture a `loggingproxy` transcript; each
  confirmed bug contributes a replay fixture before it is closed.
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
transcript proves we *once* interoperated with one version of a server; a
live test proves we *still* do. Recordings are therefore a regression
floor and a fallback for servers we cannot run — never a substitute where
live access is possible. Concretely:

- Every server sits at the **most-live tier it can occupy**, and tier
  assignment is revisited as circumstances change: a new container image,
  a licensing change, or emulation making a Tier 3 server runnable
  promotes it to Tier 1/2, and its fixtures demote to secondary
  regression guards.
- We actively invest in promotions. For example, RealVNC on Raspberry Pi
  OS — today's canonical Tier 3 case — is a candidate for a live CI job
  via a QEMU-emulated Pi OS image on an ubuntu runner; if that works it
  leaves Tier 3 entirely.
- Where both exist, the live run is the source of truth for the
  compatibility matrix; transcripts serve unit-level decoder tests and
  offline regression, and are refreshed *from* live runs (Tier 1
  deterministically, Tier 2 from nightly artifacts) rather than treated
  as an independent authority.

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
- The native `libvncserver.mk` source build stays as-is; it doubles as the
  no-Docker fallback path and covers the "current git LibVNCServer" case
  containers pin away.

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
- Each successful run can refresh that server's transcript fixtures as an
  artifact; jobs are promoted to blocking only once they prove stable.

### Tier 3 — Transcript-only servers (community-sourced fingerprints)

RealVNC (Raspberry Pi OS), VMware/ESXi consoles, Proxmox, MobaXterm, and
anything else licensing or hardware puts out of CI's reach are covered by
recorded fingerprints — but per the guiding principle, Tier 3 is the tier
of **last resort**: membership means "we have not yet found a way to run
this server live", and each Tier 3 server carries a note on what its
promotion path would be (emulation, a licensing change, a self-hosted
runner). Until promoted, the supply chain for these is the community, so
contributing a fingerprint must be a paved road:

1. **Record**: a `vncdo record`-style command (a thin wrapper over the
   existing `loggingproxy`, extended with a raw-transcript mode — Phase 0
   work item) sits between the reporter's client and their server. They
   run a short scripted scenario checklist (connect, auth, type, capture);
   out comes a fixture directory. The recorder scrubs secrets by
   construction: password bytes and auth challenges/responses are redacted
   at capture time, never trusted to manual editing.
2. **Describe**: the fixture's `manifest.yaml` (see below) plus the output
   of `vncdo probe` (server version string, offered security types,
   negotiated encodings) — the "fingerprint" proper.
3. **Submit**: a "server fingerprint" issue template and a PR checklist
   (manifest complete, transcript scrubbed, ≤ ~100 KB, scenarios covered).
   A CI job replays every contributed fixture against the decoder, so
   fingerprint PRs are **self-verifying** and cheap to review.
4. **Reward**: each merged fixture automatically adds its row to the
   `docs/compatibility.rst` support matrix, crediting the contributor —
   the server they care about becomes visibly supported, which is the
   incentive to contribute and to keep the fixture fresh when the server
   updates.

### Gold files: creation and regeneration rules

- Fixtures live at `tests/fixtures/<server>/<scenario>/` with a
  `manifest.yaml` recording: server product and version, image digest (or
  OS/runner version for Tier 2, reporter's environment for Tier 3), server
  command line, recorder identity, date, and the vncdotool commit used.
- **Tier 1 gold files are deterministic**: `make fixtures-regen
  SERVER=<name>` spins the pinned container, replays the scenario through
  the recording proxy, and rewrites the fixture. Regeneration is always a
  reviewable PR diff, never a silent CI side effect.
- **Tier 2/3 gold files are opportunistic**: refreshed from Tier 2 run
  artifacts or new community recordings (Tier 3), and likewise only
  replaced via PR.
- Transcripts are handshakes plus a few update rounds — kilobytes each —
  so they live in-repo with a ~100 KB per-fixture budget; no LFS.

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
  job's issue) regenerate that server's Tier 1 gold files in the same PR,
  so pins and fixtures always move together.
- Ownership is explicit per tier: Tier 1 is maintainable by anyone with
  Docker; Tier 2 needs no hardware, only workflow upkeep; Tier 3 is
  honestly documented as "we do not own this access" and lives or dies by
  the recording pipeline — which is why the paved road above matters.

### Spike results (Tier 1 / Tier 2 viability)

**Tier 1 — VIABLE.** Branch `claude/spike-server-fleet` (commit
`bbfd188`) holds a working proof: three in-repo Dockerfile-based services
(`tigervnc` no-auth, `tigervnc-auth` VNC-password, `x11vnc` over Xvfb)
defined in `tests/servers/docker-compose.yml` with `nc`-based
healthchecks, `make servers-up`/`servers-down`/`test-fleet` wrappers, and
a parameterized `tests/functional/test_fleet.py` that connects, types,
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

**Tier 2 — pending.** Branch `claude/spike-os-servers` (UltraVNC on
`windows-latest`, Screen Sharing/ARD on `macos-latest`) is still
iterating; per-OS verdicts and recipes will be recorded here.

## Sequencing and effort

| Phase | Rough size | Depends on |
|---|---|---|
| 0 — CI matrix + transcript fixtures | Medium; pure test/infra, no protocol risk | — |
| 1 — Robustness/error reporting | Small–medium; touches negotiation paths | 0 (to verify against matrix) |
| 2 — Tight, VeNCrypt, pixel formats | Large; the core protocol work | 0, 1 |
| 3 — Desktop size, CU/Fence, WebSocket, clipboard | Medium, parallelizable per feature | 2 |
| 4 — Docs, templates, diagnostics | Small, ongoing | 0 |

Phases 0 and 1 are deliberately front-loaded: they are cheap, carry no
protocol-breakage risk, and multiply the value of everything after them —
every Phase 2/3 feature lands with matrix coverage, and every future user
report arrives as an actionable error message plus, ideally, a transcript.

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
- **Decoder rewrites regress existing users**: the Phase 0 transcript
  fixtures and pixel-exact reference images are the guard rail; land them
  first.
- **Upstream supply disappears**: a Chocolatey package or base image we
  pin can vanish or break. Mitigations: vendored in-repo Dockerfiles
  rather than third-party images, pins with the weekly drift job to catch
  breakage early, and transcript fixtures as the permanent floor — a
  server we lose live access to degrades to Tier 3, not to zero coverage.
- **Tier 3 fixtures go stale**: a fingerprint records one server version
  at one moment. The manifest's version field and the compatibility table
  make staleness visible, and the paved recording road keeps the cost of
  a refreshed contribution low.

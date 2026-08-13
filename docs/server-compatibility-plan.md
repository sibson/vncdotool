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

Acceptance: CI shows a per-server pass/fail grid; a transcript fixture
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
- Nightly (rather than per-PR) runs for the slower matrix jobs (QEMU with
  a real guest image) to keep PR CI fast.

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
  polling, per-server retry, and by quarantining unstable servers to the
  nightly job rather than PR CI.
- **Decoder rewrites regress existing users**: the Phase 0 transcript
  fixtures and pixel-exact reference images are the guard rail; land them
  first.

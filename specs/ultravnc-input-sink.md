# UltraVNC input-sink design

Addresses the "Tier 2 input validation" open question in
[testing-framework.md](testing-framework.md): Windows/macOS have no event
sink today, so `test_keypress`/`test_mousemove` in `test_os_servers.py`
only prove UltraVNC accepted the input without dropping the connection,
not that the OS actually received it.

Scope is UltraVNC (Windows) only. macOS/Screen Sharing needs a different
mechanism (an event tap) and is deliberately a separate design, following
the same phased-independently-landable pattern the rest of the testing
framework doc uses. The special-keys-per-server matrix (a second open
question in the parent doc) is also out of scope — this covers the same
ground the existing smoke scenarios already cover (one key, one move),
not a new key-class matrix.

## Prerequisite spike: does a hook in the test's session see the input?

**Everything below assumes something unproven, and the spike settles it
before any of the rest gets written.**

UltraVNC runs as a Windows *service* (`winvnc.exe -install`, see
`Start-UltraVncService` in `setup.ps1`). The listener is started from the
CI step. A low-level keyboard hook only observes input in its own Windows
session, so if the service injects into the interactive/console session
while the CI step runs in a different one, the listener sees nothing at
all. The failure looks exactly like "the input never arrived" — an empty
log — which is indistinguishable from the bug this sink exists to catch.

The spike: start the listener, run one `vncdo key x` against UltraVNC, and
check whether a line appears. Log `A_ScriptDir`-adjacent diagnostics
(the AHK process's session id, and the service's) so a negative result
says *why*.

If the sessions don't match, the mechanism changes — a service-side hook,
or a different sink entirely — and this design needs revisiting rather
than patching. Nothing else here is worth building until the spike comes
back positive.

## Architecture

Follows the same poll-a-log-with-deadline pattern Tier 1's `vncev`/`xev`
sinks already use in `test_events.py`:

1. **AutoHotkey v2 listener** (`tests/servers/ultravnc/input-sink.ahk`) —
   installed via `choco install autohotkey -y --no-progress` (which
   resolves to v2 today) and started from `setup.ps1`, alongside
   `Install-UltraVNC`. Runs for the whole CI job; hooks keyboard input and
   appends key down/up events plus edge-triggered cursor-position samples
   to one log file.
2. **A generalized poller in `vncservers.py`** — the offset/regex/deadline
   logic currently in `test_events.py`'s `wait_for_log_line`, extracted as
   `wait_for_text(fetch, patterns, deadline, offset)` and parameterized
   over how the log text is fetched. `test_events.py` keeps
   `_compose_logs` and calls `wait_for_text(lambda: _compose_logs("vncev"), ...)`;
   the new tests supply a file-reading fetch function instead.
   `wait_for_log_line` retires; both call sites become explicit about what
   they're polling.
3. **`TestUltraVNCInputSink`** in `test_os_servers.py` — a new `TestCase`,
   not a branch in the shared `_VNCServerTestMixin`, mirroring
   `TestVNCEVSink`'s shape and named for the server under test (not the
   host OS), consistent with `TestVNCEVSink`/`TestX11SideSink`.

`sink_log_path()` and `_read_sink_log()` live in `vncservers.py` next to
the poller, not in the test module: the torn-line guard below is part of
the same fetch contract `wait_for_text` depends on, and belongs with it.

## Log format

One log file, one writer (the AHK script), line-oriented:

```
KEY DOWN x 2026-08-17T12:03:41.221Z
KEY UP x 2026-08-17T12:03:41.298Z
POS 37,91 2026-08-17T12:03:41.500Z
```

Key names are AHK's own key-name strings (`x`, `Enter`, `F1`, `Ctrl`) —
no keysym translation, since this is a same-machine OS-level check, not
wire-level like `vncev`.

Keyboard events are captured via a pass-through hook (`~*` hotkeys /
`InputHook`) so the listener observes without blocking real input.

**The script must create the log file at startup, before its first
event.** `Start-InputSinkListener` deletes the log and then waits for it
to reappear as its readiness check; a script that creates the file lazily
on first keystroke would make that check hang until the timeout and
report a working listener as broken.

The log path is passed to the script as a **command-line argument**
(`A_Args[1]`), not read from the environment. `Start-Process` does pass
the environment through, but an explicit argument is visible in the
process list and in the setup log, so a listener writing somewhere
unexpected is diagnosable without inspecting a running process's
environment block. CI's job-level `VNCDOTOOL_INPUT_SINK_LOG` (set next to
`VNCDOTOOL_SCREENSHOT_DIR` in `os-servers.yml`) is what `setup.ps1` reads
to build that argument and what `sink_log_path()` reads on the Python
side, so both ends still derive from one value with no guessing.

### Cursor position is logged on change, never on a tick

A fixed-interval sample would keep re-emitting the same `POS` line for as
long as the cursor doesn't move, so a later test's offset-based match
could pass on an ambient re-sample instead of confirming that test's own
`move` happened — or mask a real failure where the cursor never moved.
Edge-triggered logging (compare current position to the last-logged one,
write only on a difference) makes "no line after the offset" the correct
signal for "nothing happened," which is what the assertion needs. The
scan tick that drives the comparison affects detection latency only (worst
case one tick, well under the poll deadline), not correctness, so it stays
a fixed constant in the script rather than a configurable value.

The cost of edge-triggering is that a move to where the cursor already
sits logs nothing, which the test has to account for — see
`test_mousemove_seen_by_sink` below.

## Poller generalization

```python
def wait_for_text(
    fetch: Callable[[], str],
    needle_patterns: List[str],
    deadline: float = LOG_POLL_DEADLINE,
    offset: int = 0,
) -> str:
    """Poll fetch() until every pattern has matched past offset, or give up."""
    remaining = set(needle_patterns)
    end = time.monotonic() + deadline
    text = ""
    while time.monotonic() < end:
        text = fetch()[offset:]
        remaining = {p for p in remaining if not re.search(p, text, re.MULTILINE)}
        if not remaining:
            return text
        time.sleep(LOG_POLL_INTERVAL)
    return text
```

`fetch()` must return the full accumulated text so far, growing
monotonically, complete lines only. `_compose_logs` already satisfies
this (docker buffers and flushes per line). A file read does not,
automatically: it can race the AHK writer mid-append and see a torn last
line. `_read_sink_log` handles it by dropping any trailing line that
isn't newline-terminated before returning — a line still being written
can't have matched a pattern requiring its trailing timestamp anyway, so
dropping it costs nothing; the next poll picks it up complete. Dropping a
partial line also keeps `offset` honest: the offset a test records in
`setUp` never lands mid-line, so the line reads whole once it completes.

**The default deadline is Tier 1's and is wrong for Tier 2.** OS-hosted
servers exist in this suite precisely because they behave differently
from containers, and `OS_SERVER_TIMEOUT` defaults to 60s with the note
that macOS Screen Sharing took over five seconds just to acknowledge a
key event. The sink tests pass a deadline derived from
`ULTRAVNC.timeout`, not the 15s container constant.

## Test structure

```python
class TestUltraVNCInputSink(TestCase):
    """Server processing: did UltraVNC's AHK listener see the real OS input."""

    def setUp(self) -> None:
        if sys.platform != "win32":
            self.skipTest("UltraVNC sink only runs on the Windows runner")
        if not sink_log_path().exists():
            self.fail(
                f"input sink log not found at {sink_log_path()} -- "
                "start the listener first with tests/servers/ultravnc/setup.ps1"
            )
        self.offset = len(_read_sink_log())

    def test_keypress_seen_by_sink(self) -> None:
        result = run_vncdo(ULTRAVNC, "key", "x")
        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

        log = wait_for_text(
            _read_sink_log,
            [r"^KEY DOWN x ", r"^KEY UP x "],
            deadline=ULTRAVNC.timeout,
            offset=self.offset,
        )
        down = re.search(r"^KEY DOWN x ", log, re.MULTILINE)
        up = re.search(r"^KEY UP x ", log, re.MULTILINE)
        self.assertIsNotNone(down, f"no keydown seen in sink log:\n{log}")
        self.assertIsNotNone(up, f"no keyup seen in sink log:\n{log}")
        self.assertLess(down.start(), up.start(), f"keyup seen before keydown:\n{log}")

    def test_mousemove_seen_by_sink(self) -> None:
        # Park somewhere else first: positions are logged on change, and the
        # smoke test's `move 10 10` (or a rerun of this test) may already have
        # left the cursor on the target, which would log nothing at all.
        result = run_vncdo(ULTRAVNC, "move", "0", "0", "move", "37", "91")
        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

        log = wait_for_text(
            _read_sink_log, [r"^POS 37,91 "], deadline=ULTRAVNC.timeout, offset=self.offset
        )
        self.assertRegex(log, r"(?m)^POS 37,91 ", f"no matching cursor position:\n{log}")
```

Patterns are anchored to the start of a line and delimited by the space
before the timestamp. Unanchored `POS 37,91` would also match inside
`POS 37,910`, and unanchored `KEY DOWN x` would match AHK's `XButton1`
name — both are substring matches that would report success for input
that never happened.

`setUp` distinguishes two failure modes: `skipTest` when this platform
simply isn't Windows (the class doesn't apply), versus `self.fail` when
it is Windows but the listener isn't up — a real gap, not something to
skip past silently (same rule #361 established for the fleet: fail
loudly, never silently skip). The existing `_VNCServerTestMixin`
smoke tests (`test_connect`/`test_keypress`/`test_mousemove`) are
untouched; this is an additive, dedicated class, same separation Tier 1
already keeps between smoke and sink concerns.

`self.offset` is captured once in `setUp`, which unittest runs before
every test method — so this is a dedup of the per-test `offset = len(...)`
line, not a change to when offsets are taken.

The smoke class (`TestServer_ultravnc`) and this one share a module and a
machine, and `dir(module)` orders the smoke class first. Its `key x`
leaves stale `KEY DOWN x` lines in the log, which the offset already
handles; its `move 10 10` leaves the *cursor* somewhere, which the offset
cannot handle — hence the park move above rather than simply picking
coordinates that differ from the smoke test's.

## setup.ps1 integration

```powershell
function Install-AutoHotkey {
    Write-Host '--- installing AutoHotkey'
    for ($attempt = 1; $attempt -le $InstallAttempts; $attempt++) {
        choco install autohotkey -y --no-progress
        if (Test-Path $AutoHotkeyExe) {
            Write-Host "installed $AutoHotkeyExe"
            return
        }
        Write-Host "::warning::AutoHotkey install attempt $attempt did not produce $AutoHotkeyExe"
        Start-Sleep -Seconds (5 * $attempt)
    }
    throw "AutoHotkey not found at $AutoHotkeyExe after $InstallAttempts install attempts"
}

function Start-InputSinkListener {
    Write-Host '--- starting input-sink listener'
    Remove-Item $SinkLog -ErrorAction SilentlyContinue
    $script = Join-Path $PSScriptRoot 'input-sink.ahk'
    Start-Process -FilePath $AutoHotkeyExe -ArgumentList @($script, $SinkLog)

    # The script creates the log before its first event, so the file
    # appearing is the listener being ready, not the first keystroke.
    $deadline = (Get-Date).AddSeconds(15)
    while (-not (Test-Path $SinkLog) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Path $SinkLog)) {
        throw "input-sink log never appeared at $SinkLog"
    }
    Write-Host "input-sink listener running, logging to $SinkLog"
}

# Additive verification, not the server itself: an AHK hiccup shouldn't
# take down UltraVNC or the smoke tests that don't need it.
try {
    Install-AutoHotkey
    Start-InputSinkListener
} catch {
    Write-Host "::warning::input-sink listener setup failed: $_"
}
```

This is deliberately isolated from `Install-UltraVNC`'s existing
all-or-nothing throw: UltraVNC install failure still fails the whole
setup script (it always has), but an AutoHotkey/listener failure is
caught and logged as a warning, not fatal. The sink is additive
verification on top of a server that already works without it; a choco
hiccup installing AutoHotkey shouldn't take down `test_connect` and the
other smoke tests that don't depend on the sink at all.
`TestUltraVNCInputSink.setUp` already surfaces the gap loudly and
specifically when the log never appears.

Nothing stops the listener. In CI the VM is destroyed at the end of the
job, so there is nothing to clean up.

## The listener is a keylogger

It hooks every keystroke on the machine, from any source, and writes them
in plaintext to a file that nothing rotates or deletes — and setup.ps1
leaves it running.

`setup.ps1` and the UltraVNC README already say to run this only on a
throwaway machine, on the grounds that it configures unattended remote
control with a throwaway password. Both need extending to cover this too:
a developer running the setup script on a real workstation to reproduce a
CI failure gets a permanent global key logger as a side effect, which the
existing warning does not lead them to expect.

## Out of scope / follow-ups

- macOS/Screen Sharing event-tap sink — separate design.
- Special-keys-per-server matrix — separate design (parent doc's other
  open question); this only re-verifies the one key/one move the smoke
  tests already drive.
- AutoHotkey script implementation itself (`input-sink.ahk`) is specified
  here at the log-format/behavior level; exact AHK v2 syntax is an
  implementation detail for the plan, not a design fork.

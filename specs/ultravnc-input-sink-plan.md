# UltraVNC Input Sink: Prerequisite Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer the one question [specs/ultravnc-input-sink.md](ultravnc-input-sink.md) says gates the whole design: does a keyboard hook started from the CI step's own process see input that UltraVNC's Windows *service* injects, or do the two run in different Windows sessions and see nothing of each other?

**Architecture:** A throwaway AutoHotkey v2 listener and a PowerShell driver script, added as one new step in `os-servers.yml`'s Windows leg. The step installs AutoHotkey, starts the listener, drives one `vncdo key x` against the already-running UltraVNC service, and fails the CI step loudly if the listener's log shows no key event — turning "did the spike pass" into the step's own exit code rather than something a human has to eyeball. Everything here is deleted once the verdict is recorded; none of it is the production `input-sink.ahk`.

**Tech Stack:** AutoHotkey v2 (`choco install autohotkey`), PowerShell 7 (`pwsh`), the existing `os-servers.yml` GitHub Actions workflow, the `vncdo` CLI already on PATH in that job.

## Global Constraints

- AutoHotkey v2 only — `choco install autohotkey` resolves to 2.0.26 today; do not pin `--version=1.1.x`.
- This step targets only the `windows-latest` runner leg (`matrix.runner == 'windows-latest'`) — the macOS leg is untouched.
- No CHANGELOG.rst entry: this is a throwaway spike, not a user-visible fix.
- Every file this task creates is deleted in the final step, win or lose — nothing here is meant to survive to the next plan.
- Pushing to the remote / triggering a CI run requires the user's explicit go-ahead at execution time (this repo's global convention) — do not push unattended.

---

### Task 1: Run the session-visibility spike and record the verdict

**Files:**
- Create: `tests/servers/ultravnc/spike-input-sink.ahk`
- Create: `tests/servers/ultravnc/spike-check-session.ps1`
- Modify: `.github/workflows/os-servers.yml` (temporary step, removed in Step 8)
- Modify: `specs/ultravnc-input-sink.md` (Prerequisite spike section gets its verdict)

**Interfaces:**
- Consumes: `VNCDOTOOL_OS_SERVER_PORT` / `VNCDOTOOL_OS_SERVER_PASSWORD` env vars already set by `os-servers.yml` (see `tests/functional/vncservers.py:97-99` for the defaults they fall back to); the `winvnc.exe` process already running from `setup.ps1`'s `Start-UltraVncService`.
- Produces: nothing consumed by later tasks — this task's only output is a pass/fail verdict written into `specs/ultravnc-input-sink.md`, which the *next* plan (the real implementation) is gated on. Nothing here is imported or reused by production code.

- [ ] **Step 1: Write the spike AHK listener**

`tests/servers/ultravnc/spike-input-sink.ahk`:

```ahk
#Requires AutoHotkey v2.0
#SingleInstance Force

; Throwaway spike for specs/ultravnc-input-sink.md's "Prerequisite spike"
; section. Not the production listener -- delete once the spike's answer
; is recorded and the real input-sink.ahk lands.

logPath := A_Args[1]

pid := DllCall("kernel32\GetCurrentProcessId", "UInt")
sessionId := 0
DllCall("kernel32\ProcessIdToSessionId", "UInt", pid, "UInt*", &sessionId)

; Create the log immediately: the driver's readiness check is "the file
; exists", not "a key has been pressed" -- matches the eager-creation
; requirement the real listener will also need.
FileAppend("LISTENER SESSION " sessionId " PID " pid " " A_Now "`n", logPath)

~x::FileAppend("KEY DOWN x SESSION " sessionId " " A_Now "`n", logPath)
~x Up::FileAppend("KEY UP x SESSION " sessionId " " A_Now "`n", logPath)
```

- [ ] **Step 2: Write the spike driver script**

`tests/servers/ultravnc/spike-check-session.ps1`:

```powershell
<#
.SYNOPSIS
    Spike: prove an AutoHotkey hook can see input UltraVNC's service injects.

.DESCRIPTION
    Throwaway investigation for the design in specs/ultravnc-input-sink.md.
    Answers exactly one question: does a process started from this CI step
    share a Windows session with the UltraVNC service, so a keyboard hook
    in one sees input from the other? Not the production listener. Delete
    this script (and spike-input-sink.ahk) once the spike's answer is
    recorded in the spec and the real input-sink.ahk lands.

.EXAMPLE
    pwsh tests/servers/ultravnc/spike-check-session.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = $(if ($env:VNCDOTOOL_OS_SERVER_PORT) { [int]$env:VNCDOTOOL_OS_SERVER_PORT } else { 5900 }),
    [string]$Password = $(if ($env:VNCDOTOOL_OS_SERVER_PASSWORD) { $env:VNCDOTOOL_OS_SERVER_PASSWORD } else { 'vncspike1' }),
    [int]$InstallAttempts = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AutoHotkeyExe = 'C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe'
$Script = Join-Path $PSScriptRoot 'spike-input-sink.ahk'
$LogPath = Join-Path ([System.IO.Path]::GetTempPath()) 'spike-input-sink.log'

function Install-SpikeAutoHotkey {
    Write-Host '--- installing AutoHotkey for the spike'
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

Install-SpikeAutoHotkey

Remove-Item $LogPath -ErrorAction SilentlyContinue

Write-Host '--- starting spike listener'
Start-Process -FilePath $AutoHotkeyExe -ArgumentList @($Script, $LogPath)

$deadline = (Get-Date).AddSeconds(15)
while (-not (Test-Path $LogPath) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
}
if (-not (Test-Path $LogPath)) {
    throw 'spike listener never created its log -- AutoHotkey failed to start'
}

$winvnc = Get-Process winvnc -ErrorAction SilentlyContinue
if (-not $winvnc) {
    throw 'winvnc.exe is not running -- setup.ps1 must run before this spike'
}
Write-Host "winvnc.exe session: $($winvnc.SessionId)"
Write-Host "spike listener log:`n$(Get-Content $LogPath -Raw)"

Write-Host '--- driving one key event through vncdo'
vncdo -s "127.0.0.1::$Port" -p $Password key x
Start-Sleep -Seconds 2

$log = Get-Content $LogPath -Raw
Write-Host "spike listener log after key event:`n$log"

if ($log -notmatch 'KEY DOWN x') {
    throw (
        "spike FAILED: no key event reached the listener. winvnc.exe is in " +
        "session $($winvnc.SessionId); see the listener log above for its " +
        "own session. If they differ, the service and this CI step run in " +
        "different Windows sessions and the hook mechanism in " +
        "specs/ultravnc-input-sink.md needs to change before anything else " +
        "in that design is built."
    )
}
Write-Host 'spike PASSED: the listener saw the injected key event.'
```

- [ ] **Step 3: Add the spike step to the Windows CI leg**

In `.github/workflows/os-servers.yml`, add a new step immediately after the existing `Run OS server functional tests` step (so UltraVNC is already confirmed healthy) and before `Capture screenshots and build the gallery`:

```yaml
      - name: 'SPIKE: verify an AHK hook shares UltraVNC''s Windows session'
        if: matrix.runner == 'windows-latest'
        run: pwsh tests/servers/ultravnc/spike-check-session.ps1
```

- [ ] **Step 4: Commit the spike**

```bash
git add tests/servers/ultravnc/spike-input-sink.ahk tests/servers/ultravnc/spike-check-session.ps1 .github/workflows/os-servers.yml
git commit -m "spike: check whether an AHK hook shares UltraVNC's Windows session"
```

- [ ] **Step 5: Push and trigger the CI run**

**Stop and ask the user before this step** — pushing to the remote requires their explicit go-ahead per this repo's working conventions, and it's what actually triggers the GitHub Actions run.

```bash
git push -u origin ultravnc-input-sink
```

- [ ] **Step 6: Read the spike step's log in the Actions run**

Open the `os-servers` workflow run for this push, find the `windows-latest` job, and read the `SPIKE: verify an AHK hook shares UltraVNC's Windows session` step's log. It prints:
- `winvnc.exe session: N`
- the listener's own `LISTENER SESSION` line
- the full log contents before and after the key event

The step's own exit code is the verdict: green means the listener's log contained `KEY DOWN x` and the sessions therefore do line up; red means it didn't, and the thrown error message states the two session IDs for the postmortem.

- [ ] **Step 7: Record the verdict in the design doc**

Open `specs/ultravnc-input-sink.md`'s "Prerequisite spike" section and append a dated verdict paragraph directly under the existing text, stating the observed session IDs (both if they differ, the winvnc one either way), the pass/fail result, and — if it failed — that the "Architecture" section onward needs to be revisited before implementation starts, rather than patched.

Example (pass case — adapt to the actual run's numbers and date):

```markdown
**Spike result (2026-08-19, run <link to the Actions run>):** passed. Both
winvnc.exe and the AHK listener ran in session 1 on the windows-latest
runner; the listener's log showed `KEY DOWN x`/`KEY UP x` for the driven
key. The mechanism in this design holds; proceeding to implementation.
```

- [ ] **Step 8: Remove the throwaway spike files**

Whether the spike passed or failed, its files were never meant to persist — the pass case gets superseded by the real `input-sink.ahk` in the next plan, and the fail case means this exact mechanism is wrong.

```bash
git rm tests/servers/ultravnc/spike-input-sink.ahk tests/servers/ultravnc/spike-check-session.ps1
```

Manually remove the spike step block from `.github/workflows/os-servers.yml` (the one added in Step 3).

- [ ] **Step 9: Commit the verdict and cleanup**

```bash
git add specs/ultravnc-input-sink.md .github/workflows/os-servers.yml
git commit -m "spike: record UltraVNC session-visibility verdict, remove throwaway files"
```

---

## What comes after this plan

If the spike passed, the next plan implements the real design end to end: `input-sink.ahk`, `wait_for_text`/`_read_sink_log` in `vncservers.py`, `TestUltraVNCInputSink` in `test_os_servers.py`, and the permanent `Install-AutoHotkey`/`Start-InputSinkListener` additions to `setup.ps1` — all as specified in `specs/ultravnc-input-sink.md`. That plan isn't written yet: writing it before this spike returns would mean writing concrete steps for a mechanism that might not work, which is exactly what the spec's own gating language warns against.

If the spike failed, the next step is revisiting the "Architecture" section of the spec (a service-side hook, or a different sink entirely) — back to brainstorming, not to a plan.

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

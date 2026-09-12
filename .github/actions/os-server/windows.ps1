<#
.SYNOPSIS
    Start every Windows VNC server the OS-server job measures.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# So a failing setup is reported by the throw below, naming the server, and
# not by PowerShell 7.4's own message for a native command that exited
# non-zero.
$PSNativeCommandUseErrorActionPreference = $false

$Password = $env:PASSWORD
if (-not $Password) {
    throw 'PASSWORD is not set'
}

# tests/functional/utils.py reads this.
"VNCDOTOOL_OS_SERVER_PASSWORD=$Password" |
    Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

$Advanced = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
Set-ItemProperty -Path $Advanced -Name HideIcons -Value 1 -Type DWord
if ((Get-ItemProperty -Path $Advanced -Name HideIcons).HideIcons -ne 1) {
    throw 'HideIcons did not take, and the desktop icons would stay on screen'
}
# Restarting Explorer is what applies HideIcons: it reads the value when it
# draws the desktop. Winlogon starts it again on its own.
Get-Process explorer -ErrorAction SilentlyContinue | Stop-Process -Force
$Deadline = (Get-Date).AddSeconds(30)
while (-not (Get-Process explorer -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $Deadline) {
        throw 'explorer did not restart, so the desktop would be served blank'
    }
    Start-Sleep -Milliseconds 500
}

$FirstPort = if ($env:PORT) { [int]$env:PORT } else { 5900 }
$Servers = @(
    @{ Name = 'ultravnc'; Port = $FirstPort },
    @{ Name = 'tightvnc'; Port = 5901 },
    @{ Name = 'tigervnc-win'; Port = 5902 }
)

foreach ($server in $Servers) {
    Write-Host "=== setting up $($server.Name) on port $($server.Port)"
    $env:PORT = $server.Port
    & pwsh -File "tests/servers/$($server.Name)/setup.ps1"
    if ($LASTEXITCODE -ne 0) {
        throw "$($server.Name) setup failed with exit code $LASTEXITCODE"
    }
}

Write-Host '=== moving windows off the pointer probe'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public struct RECT { public int Left, Top, Right, Bottom; }
public static class Desktop {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(
        IntPtr window, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out RECT rect);
}
'@

# CURSOR_NEAR, CURSOR_FAR and CURSOR_EXTENT in tests/functional/utils.py put
# the compared boxes inside (0, 0)-(198, 168). Windows are moved clear of
# that rather than minimized: a capture with every window gone is bare
# desktop, which is black whenever the wallpaper has not painted, and
# test_capture asks for a capture with something in it.
$ProbeRight, $ProbeBottom = 198, 168
$ClearX, $ClearY = 220, 180

function Get-TopLevelWindows {
    Get-Process | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero }
}

# user32 reaches only the calling process's own session, so finding nothing
# would mean the windows are somewhere this cannot move them -- and the
# check below would then pass without having looked at anything.
$Windows = @(Get-TopLevelWindows)
if ($Windows.Count -eq 0) {
    throw 'no top-level window is visible from here, so none can be moved off the probe'
}
Write-Host "moving $($Windows.Count) window(s) to $ClearX,$ClearY"

foreach ($process in $Windows) {
    # SW_RESTORE first: SetWindowPos does not move a maximized window.
    [Desktop]::ShowWindow($process.MainWindowHandle, 9) | Out-Null
    # SWP_NOSIZE | SWP_NOZORDER
    [Desktop]::SetWindowPos(
        $process.MainWindowHandle, [IntPtr]::Zero, $ClearX, $ClearY, 0, 0, 0x0005) | Out-Null
}

foreach ($process in Get-TopLevelWindows) {
    $rect = New-Object RECT
    if (-not [Desktop]::GetWindowRect($process.MainWindowHandle, [ref]$rect)) {
        continue
    }
    if ($rect.Left -lt $ProbeRight -and $rect.Right -gt 0 -and
        $rect.Top -lt $ProbeBottom -and $rect.Bottom -gt 0) {
        throw "$($process.ProcessName) stayed at $($rect.Left),$($rect.Top) over the probe region"
    }
}

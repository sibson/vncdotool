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
# Explorer reads HideIcons when it draws the desktop and re-reads it for
# nothing short of a restart. Winlogon brings it back on its own.
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

# Last, so that windows the installers above opened are minimized too.
Write-Host '=== clearing the desktop'
# Shell.Application is served by explorer, which refuses the call until it is
# listening again after the restart above.
$Deadline = (Get-Date).AddSeconds(30)
while ($true) {
    try {
        (New-Object -ComObject Shell.Application).MinimizeAll()
        break
    } catch {
        if ((Get-Date) -gt $Deadline) {
            throw "no window could be minimized, and the agent's console covers the desktop: $_"
        }
        Start-Sleep -Milliseconds 500
    }
}

<#
.SYNOPSIS
    Collect logs, config and service state for all three Windows VNC servers.

    Never fails: a run that has already gone wrong must not lose the
    evidence to a second error.
#>
[CmdletBinding()]
param(
    [string]$Destination = 'diagnostics'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

& (Join-Path $PSScriptRoot 'ultravnc' 'collect-diagnostics.ps1') `
    -Destination (Join-Path $Destination 'ultravnc')

$registry = @{
    tightvnc       = 'HKLM\SOFTWARE\TightVNC\Server'
    'tigervnc-win' = 'HKLM\SOFTWARE\TigerVNC\WinVNC4'
}
foreach ($name in $registry.Keys) {
    $dir = Join-Path $Destination $name
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    # The password is under these keys as an obfuscated blob anyone can reverse.
    reg export $registry[$name] (Join-Path $dir 'config.reg') /y 2>&1 | Out-Null
    if (Test-Path (Join-Path $dir 'config.reg')) {
        (Get-Content (Join-Path $dir 'config.reg')) |
            Where-Object { $_ -notmatch '^"(Password|PasswordViewOnly|ControlPassword)"' } |
            Set-Content (Join-Path $dir 'config.reg')
    }
}

Get-Service -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'uvnc|winvnc|tvnserver|TigerVNC' -or $_.DisplayName -match 'VNC' } |
    Format-List * |
    Out-File (Join-Path $Destination 'services.txt')

Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'winvnc|tvnserver|winvnc4' } |
    Format-List * |
    Out-File (Join-Path $Destination 'processes.txt')

Get-NetTCPConnection -LocalPort 5900, 5901, 5902 -ErrorAction SilentlyContinue |
    Out-File (Join-Path $Destination 'ports.txt')

Write-Host "collected Windows VNC diagnostics into $Destination"
Get-ChildItem $Destination -Recurse | Format-Table FullName, Length

<#
.SYNOPSIS
    Collect UltraVNC logs, config and service state into a directory.

.DESCRIPTION
    Everything worth looking at when the Windows server misbehaves, in one
    place so CI can upload it as an artifact. Never fails: a run that has
    already gone wrong must not lose the evidence to a second error.

.EXAMPLE
    pwsh tests/servers/ultravnc/collect-diagnostics.ps1 -Destination diagnostics
#>
[CmdletBinding()]
param(
    [string]$Destination = 'diagnostics',
    [string]$InstallDir = 'C:\Program Files\uvnc bvba\UltraVNC'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

Copy-Item (Join-Path $InstallDir 'ultravnc.ini') $Destination -ErrorAction SilentlyContinue
Get-ChildItem $InstallDir -Filter *.log -ErrorAction SilentlyContinue |
    Copy-Item -Destination $Destination -ErrorAction SilentlyContinue

Get-Service -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'uvnc|winvnc' -or $_.DisplayName -match 'UltraVNC' } |
    Format-List * |
    Out-File (Join-Path $Destination 'service.txt')

Get-Process -Name winvnc -ErrorAction SilentlyContinue |
    Out-File (Join-Path $Destination 'process.txt')

Get-EventLog -LogName Application -Source '*vnc*' -Newest 20 -ErrorAction SilentlyContinue |
    Out-File (Join-Path $Destination 'eventlog.txt')

Get-NetTCPConnection -LocalPort 5900 -ErrorAction SilentlyContinue |
    Out-File (Join-Path $Destination 'port5900.txt')

Write-Host "collected UltraVNC diagnostics into $Destination"
Get-ChildItem $Destination | Format-Table Name, Length

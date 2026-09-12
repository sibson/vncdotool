<#
.SYNOPSIS
    Install, configure and start UltraVNC as a Windows service, for
    tests/functional/test_server_compat_native.py. See README.md.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '..' 'windows-common.ps1')

$Port = if ($env:PORT) { [int]$env:PORT } else { 5900 }
$WaitSeconds = if ($env:WAIT_SECONDS) { [int]$env:WAIT_SECONDS } else { 60 }
$Password = $env:PASSWORD
if (-not $Password) {
    throw 'PASSWORD is not set: UltraVNC authenticates a password and nothing else'
}
Assert-HostedRunner

# Chocolatey always installs UltraVNC here. Do not go looking for winvnc.exe
# under C:\Program Files instead: a recursive scan of that tree takes over
# five minutes on the loaded runner image.
$InstallDir = 'C:\Program Files\uvnc bvba\UltraVNC'
$WinVnc = Join-Path $InstallDir 'winvnc.exe'
# Some UltraVNC builds read the ini from ProgramData rather than from the
# install directory, so it gets written to both.
$ProgramDataDir = 'C:\ProgramData\uvnc bvba\UltraVNC'

Write-Host '--- installing UltraVNC'
Install-WithRetry -Package 'ultravnc' -Evidence $WinVnc

Write-Host '--- writing ultravnc.ini'
$passwdHex = Get-VncPasswordHex -Password $Password -TrailingNull

# ForceCursorShape=1 is deliberately absent: it overrides UltraVNC's
# revocation of RichCursor for a client that did not ask for PointerPos
# (-232), which is what these tests measure.
#
# The wallpaper goes on connect and comes back on disconnect, and every vncdo
# run is its own connection, so RemoveWallpaper=1 is what makes the desktop
# differ between two captures.
$ini = @"
[admin]
UseRegistry=0

[ultravnc]
PortNumber=$Port
HTTPPortNumber=0
passwd=$passwdHex
AllowLoopback=1
AuthHosts=+127.0.0.1
NewMSLogon=0
RemoveWallpaper=0
NeverShutdown=1
DebugMode=1
DebugLevel=9
FileTransferEnabled=1
"@

$iniPath = Join-Path $InstallDir 'ultravnc.ini'
Set-Content -Path $iniPath -Value $ini -Encoding ASCII
New-Item -ItemType Directory -Force -Path $ProgramDataDir | Out-Null
Copy-Item $iniPath (Join-Path $ProgramDataDir 'ultravnc.ini') -Force
Write-Host "wrote $iniPath (port $Port, password set)"

Write-Host '--- installing and starting the UltraVNC service'
Invoke-Native -Command $WinVnc -Arguments @('-install') | Out-Null
Start-Sleep -Seconds 3

$service = Get-Service |
    Where-Object { $_.Name -match 'uvnc|winvnc' -or $_.DisplayName -match 'UltraVNC' } |
    Select-Object -First 1
if (-not $service) {
    Get-Service | Format-Table Name, DisplayName, Status
    throw 'no UltraVNC service exists after winvnc.exe -install'
}
Start-Service -Name $service.Name
Write-Host "started service $($service.Name) ($($service.DisplayName))"

Wait-ForPort -Server 'UltraVNC' -Port $Port -WaitSeconds $WaitSeconds

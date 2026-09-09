<#
.SYNOPSIS
    Install, configure and start TightVNC 2.x as a Windows service.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '..' 'windows-common.ps1')

$Port = if ($env:PORT) { [int]$env:PORT } else { 5901 }
$WaitSeconds = if ($env:WAIT_SECONDS) { [int]$env:WAIT_SECONDS } else { 60 }
$Password = $env:PASSWORD
if (-not $Password) {
    throw 'PASSWORD is not set: this job configures VNC authentication'
}
Assert-HostedRunner

$InstallDir = 'C:\Program Files\TightVNC'
$TvnServer = Join-Path $InstallDir 'tvnserver.exe'
# Named by tvnserver-app/NamingDefs.cpp: RegistryPaths::SERVER_PATH. The
# service runs as LocalSystem and reads HKLM, never HKCU.
$RegPath = 'HKLM:\SOFTWARE\TightVNC\Server'
$ServiceName = 'tvnserver'

Write-Host '--- installing TightVNC'
# The chocolatey package registers and starts the service itself but
# configures neither port nor password.
Install-WithRetry -Package 'tightvnc' -Evidence $TvnServer

Write-Host '--- configuring TightVNC'
Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
New-Item -Path $RegPath -Force | Out-Null

# Value names from server-config-lib/Configurator.cpp.
$settings = @{
    RfbPort                 = $Port
    AcceptRfbConnections    = 1
    UseVncAuthentication    = 1
    UseControlAuthentication = 0
    AcceptHttpConnections    = 0
    # A plain desktop is a steadier thing to diff two captures of.
    RemoveWallpaper         = 1
    LoopbackOnly            = 1
    AlwaysShared            = 1
}
foreach ($name in $settings.Keys) {
    New-ItemProperty -Path $RegPath -Name $name -Value $settings[$name] `
        -PropertyType DWord -Force | Out-Null
}
Set-RegistryBinary -Path $RegPath -Name 'Password' -Hex (Get-VncPasswordHex -Password $Password)
Write-Host "wrote $RegPath (port $Port, password set)"

Write-Host '--- starting the TightVNC service'
Start-Service -Name $ServiceName
Write-Host "started service $ServiceName"

Wait-ForPort -Server 'TightVNC' -Port $Port -WaitSeconds $WaitSeconds

<#
.SYNOPSIS
    Install, configure and start TigerVNC's WinVNC as a Windows service.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '..' 'windows-common.ps1')

$Version = if ($env:TIGERVNC_VERSION) { $env:TIGERVNC_VERSION } else { '1.16.2' }
$Port = if ($env:PORT) { [int]$env:PORT } else { 5902 }
$WaitSeconds = if ($env:WAIT_SECONDS) { [int]$env:WAIT_SECONDS } else { 60 }
$Password = $env:PASSWORD
if (-not $Password) {
    throw 'PASSWORD is not set: this job configures VncAuth'
}
Assert-HostedRunner

# Named by win/winvnc/VNCServerWin32.cxx (RegConfigPath) and
# VNCServerService.cxx (Name).
$RegPath = 'HKLM:\SOFTWARE\TigerVNC\WinVNC4'
$ServiceName = 'TigerVNC'

Write-Host "--- downloading TigerVNC winvnc $Version"
# The chocolatey `tigervnc` package installs the viewer only: TigerVNC split
# the server out of that installer in 1.11 and ships it as its own download.
$Url = "https://sourceforge.net/projects/tigervnc/files/stable/$Version/" +
    "tigervnc64-winvnc-$Version.exe/download"
$Installer = Join-Path $env:TEMP "tigervnc64-winvnc-$Version.exe"
Invoke-WebRequest -Uri $Url -OutFile $Installer -UseBasicParsing
$Size = (Get-Item $Installer).Length
# SourceForge answers /download with a redirect to a mirror, and on a bad day
# with an HTML interstitial instead. Either way the file is written, so its
# size is what says which arrived.
if ($Size -lt 1MB) {
    Get-Content $Installer -TotalCount 20
    throw "$Url returned $Size bytes, which is not an installer"
}
Write-Host "downloaded $Installer ($Size bytes)"

Write-Host '--- installing TigerVNC winvnc'
Start-Process -FilePath $Installer -Wait `
    -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-'

# Two known install directories rather than a recursive scan: walking
# C:\Program Files takes over five minutes on the loaded runner image.
$Candidates = @(
    'C:\Program Files\TigerVNC Server\winvnc4.exe',
    'C:\Program Files\TigerVNC\winvnc4.exe'
)
$WinVnc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $WinVnc) {
    Get-ChildItem 'C:\Program Files' -Filter 'Tiger*' | Format-Table Name
    throw "winvnc4.exe not found in any of: $($Candidates -join ', ')"
}
Write-Host "installed $WinVnc"

Write-Host '--- configuring TigerVNC winvnc'
# The installer may have registered and started the service already, and may
# not have.
Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
New-Item -Path $RegPath -Force | Out-Null
New-ItemProperty -Path $RegPath -Name 'PortNumber' -Value $Port -PropertyType DWord -Force | Out-Null
# LocalHost confines the listener to loopback, which is all these tests use.
New-ItemProperty -Path $RegPath -Name 'LocalHost' -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $RegPath -Name 'QueryConnect' -Value 0 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $RegPath -Name 'SecurityTypes' -Value 'VncAuth' -PropertyType String -Force | Out-Null
Set-RegistryBinary -Path $RegPath -Name 'Password' -Hex (Get-VncPasswordHex -Password $Password)
Write-Host "wrote $RegPath (port $Port, password set)"

Write-Host '--- registering and starting the TigerVNC service'
if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
    Invoke-Native -Command $WinVnc -Arguments @('-register') | Out-Null
    Start-Sleep -Seconds 3
}
if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
    Get-Service | Format-Table Name, DisplayName, Status
    throw "no $ServiceName service exists after winvnc4.exe -register"
}
Start-Service -Name $ServiceName
Write-Host "started service $ServiceName"

Wait-ForPort -Server 'TigerVNC winvnc' -Port $Port -WaitSeconds $WaitSeconds

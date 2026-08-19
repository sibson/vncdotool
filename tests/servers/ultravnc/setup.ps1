<#
.SYNOPSIS
    Install, configure and start UltraVNC as a Windows service.

.DESCRIPTION
    Sets up an UltraVNC server on the machine this runs on -- a GitHub
    windows-latest runner in CI -- so that vncdotool's functional tests
    (tests/functional/test_os_servers.py) have a live Windows server to
    talk to on 127.0.0.1.

    See README.md in this directory for why the server is installed as a
    service, and why a password is mandatory.

    This configures a machine for unattended remote control with a
    throwaway password, so run it only on a throwaway machine.

.EXAMPLE
    pwsh tests/servers/ultravnc/setup.ps1 -Password hunter2
#>
[CmdletBinding()]
param(
    # Defaults match tests/functional/vncservers.py, which the tests read
    # from VNCDOTOOL_OS_SERVER_PASSWORD/PORT too.
    [string]$Password = $(if ($env:VNCDOTOOL_OS_SERVER_PASSWORD) { $env:VNCDOTOOL_OS_SERVER_PASSWORD } else { 'vncspike1' }),
    [int]$Port = $(if ($env:VNCDOTOOL_OS_SERVER_PORT) { [int]$env:VNCDOTOOL_OS_SERVER_PORT } else { 5900 }),
    [int]$WaitSeconds = 60,
    [int]$InstallAttempts = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Chocolatey always installs UltraVNC here. Do not go looking for
# winvnc.exe under C:\Program Files instead: a recursive scan of that tree
# takes over five minutes on the loaded runner image.
$InstallDir = 'C:\Program Files\uvnc bvba\UltraVNC'
$WinVnc = Join-Path $InstallDir 'winvnc.exe'
# Some UltraVNC builds read the ini from ProgramData rather than from the
# install directory, so it gets written to both.
$ProgramDataDir = 'C:\ProgramData\uvnc bvba\UltraVNC'

$PasswdScript = Join-Path $PSScriptRoot 'vnc_passwd_hex.py'


function Install-UltraVNC {
    Write-Host '--- installing UltraVNC'
    # The community feed intermittently answers with something that isn't
    # valid XML, which choco reports as "Unable to find package" and, worse,
    # still exits 0 -- so retry, and judge success by the installed file.
    for ($attempt = 1; $attempt -le $InstallAttempts; $attempt++) {
        choco install ultravnc -y --no-progress
        if (Test-Path $WinVnc) {
            Write-Host "installed $WinVnc"
            return
        }
        Write-Host "::warning::UltraVNC install attempt $attempt did not produce $WinVnc"
        Start-Sleep -Seconds (5 * $attempt)
    }
    throw "winvnc.exe not found at $WinVnc after $InstallAttempts install attempts"
}

function Write-UltraVncIni {
    Write-Host '--- writing ultravnc.ini'
    # The helper writes the hex to a file rather than to stdout, so the
    # value never lands in the step log; read it back and drop the file.
    $passwdFile = Join-Path ([System.IO.Path]::GetTempPath()) 'ultravnc-passwd.hex'
    uv run python $PasswdScript $Password $passwdFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $passwdFile)) {
        throw 'could not compute the ultravnc.ini password hex'
    }
    $passwdHex = (Get-Content $passwdFile -Raw).Trim()
    Remove-Item $passwdFile -Force

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
RemoveWallpaper=1
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
}

function Start-UltraVncService {
    Write-Host '--- installing and starting the UltraVNC service'
    # Out-Host, or winvnc's own console output would end up in this
    # function's return value alongside the service name.
    & $WinVnc -install | Out-Host
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
}

function Wait-ForPort {
    param([int]$PortNumber, [int]$Seconds)

    Write-Host "--- waiting up to $Seconds seconds for port $PortNumber"
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $probe = Test-NetConnection -ComputerName 127.0.0.1 -Port $PortNumber -WarningAction SilentlyContinue
        if ($probe.TcpTestSucceeded) {
            Write-Host "port $PortNumber is open"
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "UltraVNC never started listening on port $PortNumber"
}


Install-UltraVNC
Write-UltraVncIni
Start-UltraVncService
Wait-ForPort -PortNumber $Port -Seconds $WaitSeconds

Write-Host "UltraVNC is serving on 127.0.0.1:$Port"

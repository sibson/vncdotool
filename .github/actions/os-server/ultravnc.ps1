<#
.SYNOPSIS
    Install, configure and start UltraVNC as a Windows service, for
    tests/functional/test_os_servers.py. See tests/servers/ultravnc/README.md.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Port = if ($env:PORT) { [int]$env:PORT } else { 5900 }
$WaitSeconds = if ($env:WAIT_SECONDS) { [int]$env:WAIT_SECONDS } else { 60 }
$Password = $env:PASSWORD
if (-not $Password) {
    throw 'PASSWORD is not set: UltraVNC authenticates a password and nothing else'
}

# The service stays installed after this job, and after the checkout is gone.
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw "refusing to run: RUNNER_ENVIRONMENT=$($env:RUNNER_ENVIRONMENT) is not a " +
        'GitHub-hosted runner, and this leaves the machine remotely controllable.'
}

# tests/functional/vncservers.py reads this.
"VNCDOTOOL_OS_SERVER_PASSWORD=$Password" |
    Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

# Chocolatey always installs UltraVNC here. Do not go looking for winvnc.exe
# under C:\Program Files instead: a recursive scan of that tree takes over
# five minutes on the loaded runner image.
$InstallDir = 'C:\Program Files\uvnc bvba\UltraVNC'
$WinVnc = Join-Path $InstallDir 'winvnc.exe'
# Some UltraVNC builds read the ini from ProgramData rather than from the
# install directory, so it gets written to both.
$ProgramDataDir = 'C:\ProgramData\uvnc bvba\UltraVNC'

Write-Host '--- installing UltraVNC'
# The community feed intermittently answers with something that isn't valid
# XML, which choco reports as "Unable to find package" and, worse, still exits
# 0 -- so retry, and judge success by the installed file.
$installed = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    choco install ultravnc -y --no-progress
    if (Test-Path $WinVnc) {
        Write-Host "installed $WinVnc"
        $installed = $true
        break
    }
    Write-Host "::warning::UltraVNC install attempt $attempt did not produce $WinVnc"
    Start-Sleep -Seconds (5 * $attempt)
}
if (-not $installed) {
    throw "winvnc.exe not found at $WinVnc after 3 install attempts"
}

Write-Host '--- writing ultravnc.ini'
# The helper writes the hex to a file rather than to stdout, so the value
# never lands in the step log; read it back and drop the file.
$passwdFile = Join-Path ([System.IO.Path]::GetTempPath()) 'ultravnc-passwd.hex'
uv run python tests/servers/ultravnc/vnc_passwd_hex.py $Password $passwdFile
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

Write-Host '--- installing and starting the UltraVNC service'
# Out-Host, or winvnc's own console output would end up in the pipeline
# alongside the service name.
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

Write-Host "--- waiting up to $WaitSeconds seconds for port $Port"
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    $probe = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
    if ($probe.TcpTestSucceeded) {
        Write-Host "UltraVNC is serving on 127.0.0.1:$Port"
        exit 0
    }
    Start-Sleep -Seconds 2
}
throw "UltraVNC never started listening on port $Port"

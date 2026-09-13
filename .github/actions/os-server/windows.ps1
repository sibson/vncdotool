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

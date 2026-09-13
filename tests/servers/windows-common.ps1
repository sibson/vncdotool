function Invoke-Native {
    <#
    .DESCRIPTION
        Every native command here has a normal run in which it exits
        non-zero -- choco on a bad feed response, winvnc -install or
        -register when the service is already there -- and PowerShell 7.4
        turns that into a terminating error under $ErrorActionPreference =
        'Stop'. Callers judge by what appeared afterwards instead, so the
        exit code is returned rather than raised.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    try {
        # A PowerShell function emits everything written to the output
        # stream, so without Out-Host the caller receives the command's own
        # output as well as the exit code.
        & $Command @Arguments 2>&1 | Out-Host
    } catch {
        Write-Host "::warning::$Command $Arguments raised $($_.Exception.Message)"
        return 1
    }
    return $LASTEXITCODE
}

function Assert-HostedRunner {
    # The service outlives both the job and the checkout, and a self-hosted
    # runner is someone's real machine.
    if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
        throw "refusing to run: RUNNER_ENVIRONMENT=$($env:RUNNER_ENVIRONMENT) is not a " +
            'GitHub-hosted runner, and this leaves the machine remotely controllable.'
    }
}

function Get-VncPasswordHex {
    param(
        [Parameter(Mandatory = $true)][string]$Password,
        [switch]$TrailingNull
    )
    $file = Join-Path ([System.IO.Path]::GetTempPath()) "vnc-passwd-$([guid]::NewGuid()).hex"
    $arguments = @('run', 'python', 'tests/servers/vnc_passwd.py')
    if ($TrailingNull) { $arguments += '--trailing-null' }
    $arguments += @($Password, $file)
    $code = Invoke-Native -Command 'uv' -Arguments $arguments
    if (-not (Test-Path $file)) {
        throw "vnc_passwd.py exited $code without writing $file"
    }
    $hex = (Get-Content $file -Raw).Trim()
    Remove-Item $file -Force
    return $hex
}

function Set-RegistryBinary {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Hex
    )
    $bytes = [byte[]]::new($Hex.Length / 2)
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        $bytes[$i] = [System.Convert]::ToByte($Hex.Substring($i * 2, 2), 16)
    }
    New-ItemProperty -Path $Path -Name $Name -Value $bytes -PropertyType Binary -Force | Out-Null
}

function Wait-ForPort {
    param(
        [Parameter(Mandatory = $true)][string]$Server,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$WaitSeconds = 60
    )
    Write-Host "--- waiting up to $WaitSeconds seconds for $Server on port $Port"
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        $probe = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
        if ($probe.TcpTestSucceeded) {
            Write-Host "$Server is serving on 127.0.0.1:$Port"
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$Server never started listening on port $Port"
}

function Install-WithRetry {
    <#
    .DESCRIPTION
        The community feed intermittently answers with something that isn't
        valid XML, which choco reports as "Unable to find package" while
        still exiting 0. Success is therefore judged by the installed file
        rather than by the exit code.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Package,
        [Parameter(Mandatory = $true)][string]$Evidence,
        [int]$Attempts = 3
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        Invoke-Native -Command 'choco' -Arguments @('install', $Package, '-y', '--no-progress') | Out-Null
        if (Test-Path $Evidence) {
            Write-Host "installed $Evidence"
            return
        }
        Write-Host "::warning::$Package install attempt $attempt did not produce $Evidence"
        Start-Sleep -Seconds (5 * $attempt)
    }
    throw "$Evidence not found after $Attempts attempts to install $Package"
}

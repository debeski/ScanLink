[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("x64", "x86")]
    [string]$ExpectedArch,

    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [int]$StartupTimeoutSeconds = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = (Get-Content (Join-Path $repoRoot "VERSION") -Raw).Trim()
if (![System.IO.Path]::IsPathRooted($InstallerPath)) {
    $InstallerPath = Join-Path $repoRoot $InstallerPath
}
$installer = (Resolve-Path $InstallerPath).Path
$installDir = Join-Path $env:RUNNER_TEMP "ScanLink-smoke-$ExpectedArch"
$appExe = Join-Path $installDir "ScanLink.exe"
$logPath = Join-Path $env:LOCALAPPDATA "ScanLink\scanner.log"
$healthUri = "http://127.0.0.1:5000/health"
$appProcess = $null

$portInUse = $false
try {
    $null = Invoke-RestMethod -Uri $healthUri -TimeoutSec 2
    $portInUse = $true
} catch {
}
if ($portInUse) {
    throw "Port 5000 already serves a process; the installed-app smoke test requires an isolated runner."
}

$installerArgs = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER /TASKS=`"startupicon`" /DIR=`"$installDir`""
$installProcess = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru
if ($installProcess.ExitCode -ne 0) {
    throw "Installer exited with code $($installProcess.ExitCode)."
}

$requiredFiles = @(
    $appExe,
    (Join-Path $installDir "app_icon.ico"),
    (Join-Path $installDir "README.md"),
    (Join-Path $installDir "static\scanlink.js"),
    (Join-Path $installDir "unins000.exe")
)
foreach ($requiredFile in $requiredFiles) {
    if (!(Test-Path $requiredFile -PathType Leaf)) {
        throw "Required installed file is missing: $requiredFile"
    }
    if ((Get-Item $requiredFile).Length -le 0) {
        throw "Required installed file is empty: $requiredFile"
    }
}

$protocolKey = "HKCU:\Software\Classes\scanlink"
$protocolCommandKey = "$protocolKey\shell\open\command"
if ((Get-ItemPropertyValue -Path $protocolKey -Name "URL Protocol") -ne "") {
    throw "scanlink URL Protocol registration is invalid."
}
$protocolCommand = Get-ItemPropertyValue -Path $protocolCommandKey -Name "(default)"
$expectedProtocolCommand = "`"$appExe`" `"%1`""
if ($protocolCommand -ne $expectedProtocolCommand) {
    throw "Unexpected scanlink protocol command: $protocolCommand"
}

$startupCommand = Get-ItemPropertyValue -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "ScanLink"
if ($startupCommand -ne "`"$appExe`"") {
    throw "Unexpected startup command: $startupCommand"
}

$startMenuLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ScanLink.lnk"
if (!(Test-Path $startMenuLink -PathType Leaf)) {
    throw "Start menu shortcut is missing: $startMenuLink"
}

try {
    $appProcess = Start-Process -FilePath $appExe -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    $health = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 3
            break
        } catch {
            $appProcess.Refresh()
            if ($appProcess.HasExited) {
                throw "Installed ScanLink exited before its health endpoint became available."
            }
            Start-Sleep -Seconds 1
        }
    }

    if ($null -eq $health) {
        throw "Installed ScanLink did not become healthy within $StartupTimeoutSeconds seconds."
    }
    if ($health.status -ne "ok") {
        throw "Unexpected health status: $($health.status)"
    }
    if ($health.version -ne $version) {
        throw "Installed version $($health.version) does not match VERSION $version."
    }
    if ($health.arch -ne $ExpectedArch) {
        throw "Installed architecture $($health.arch) does not match $ExpectedArch."
    }
    if (!$health.http_enabled) {
        throw "Installed ScanLink did not enable its HTTP listener."
    }
    if ($health.busy) {
        throw "Freshly installed ScanLink unexpectedly reports itself busy."
    }

    $missingJob = Invoke-WebRequest -Uri "http://127.0.0.1:5000/scan/smoke-missing" -SkipHttpErrorCheck
    $missingPayload = $missingJob.Content | ConvertFrom-Json
    if ($missingJob.StatusCode -ne 404 -or $missingPayload.error.code -ne "job_not_found") {
        throw "Installed ScanLink returned an unexpected missing-job response."
    }

    $probeId = "install-smoke-$ExpectedArch-$PID"
    Start-Process -FilePath "scanlink://probe?docId=$probeId"
    $probeDeadline = [DateTime]::UtcNow.AddSeconds(15)
    $protocolObserved = $false
    while ([DateTime]::UtcNow -lt $probeDeadline) {
        if ((Test-Path $logPath) -and (Select-String -Path $logPath -SimpleMatch $probeId -Quiet)) {
            $protocolObserved = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (!$protocolObserved) {
        throw "The registered scanlink protocol did not launch the installed app."
    }

    $healthAfterProtocol = Invoke-RestMethod -Uri $healthUri -TimeoutSec 3
    if ($healthAfterProtocol.status -ne "ok") {
        throw "ScanLink became unhealthy after the protocol launch check."
    }

    $shutdown = Invoke-RestMethod -Uri "http://127.0.0.1:5000/shutdown" -Method Post -TimeoutSec 3
    if ($shutdown.message -ne "Shutting down...") {
        throw "Installed ScanLink returned an unexpected shutdown response."
    }
    if (!$appProcess.WaitForExit(15000)) {
        throw "Installed ScanLink did not exit cleanly after shutdown."
    }
} catch {
    if (Test-Path $logPath) {
        Write-Host "---- ScanLink log ----"
        Get-Content $logPath -Tail 200
    }
    throw
} finally {
    if ($null -ne $appProcess) {
        $appProcess.Refresh()
        if (!$appProcess.HasExited) {
            Stop-Process -Id $appProcess.Id -Force
        }
    }
}

Write-Host "Installed ScanLink $version ($ExpectedArch) passed the Windows smoke test."

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

# Exercise the real first-launch consent rather than bypassing Windows trust.
Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public static class ScanLinkConsent {
    private delegate bool EnumWindow(IntPtr window, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindow callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumWindow callback, IntPtr parameter);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, StringBuilder text, int maximum);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] private static extern IntPtr GetDlgItem(IntPtr window, int identifier);
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    public static bool Approve(string executable) {
        bool approved = false;
        EnumWindows((window, parameter) => {
            uint processId;
            GetWindowThreadProcessId(window, out processId);
            try {
                if (!String.Equals(Process.GetProcessById((int)processId).MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase)) return true;
            } catch { return true; }
            var text = new StringBuilder();
            EnumChildWindows(window, (child, unused) => {
                var value = new StringBuilder(4096);
                GetWindowText(child, value, value.Capacity);
                text.AppendLine(value.ToString());
                return true;
            }, IntPtr.Zero);
            if (!text.ToString().Contains("ScanLink localhost")) return true;
            IntPtr yes = GetDlgItem(window, 6); // IDYES, independent of UI language.
            if (yes == IntPtr.Zero) return true;
            SendMessage(yes, 0x00F5, IntPtr.Zero, IntPtr.Zero); // BM_CLICK
            approved = true;
            return false;
        }, IntPtr.Zero);
        return approved;
    }
}
'@

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
    $secureDeadline = [DateTime]::UtcNow.AddSeconds(45)
    while (!$health.https_enabled -and [DateTime]::UtcNow -lt $secureDeadline) {
        if ([ScanLinkConsent]::Approve($appExe)) {
            Write-Host "Approved the Windows certificate prompt for ScanLink localhost."
        }
        if ($health.https_setup -eq "failed") { throw "Automatic HTTPS setup failed." }
        Start-Sleep -Milliseconds 500
        $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 3
    }
    if (!$health.https_enabled -or $health.https_setup -ne "ready") {
        throw "Automatic HTTPS setup did not finish."
    }
    # Use normal Windows TLS verification: no trust bypass or certificate CLI.
    $secureHealth = Invoke-RestMethod -Uri "https://localhost:5443/health" -TimeoutSec 5
    if ($secureHealth.version -ne $version) { throw "Trusted HTTPS returned the wrong version." }
    $stressResults = @(1..120 | ForEach-Object -Parallel {
        $response = Invoke-RestMethod -Uri "https://localhost:5443/health" -TimeoutSec 10
        if ($response.status -ne "ok" -or !$response.https_enabled) { throw "HTTPS stress request failed." }
        $true
    } -ThrottleLimit 12)
    if ($stressResults.Count -ne 120) { throw "HTTPS stress did not complete every request." }
    Write-Host "120 concurrent-batch HTTPS requests passed with normal Windows certificate verification."
    $identityPath = Join-Path $env:LOCALAPPDATA "ScanLink\https\active.json"
    $firstIdentity = (Get-Content $identityPath -Raw | ConvertFrom-Json).identity
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
    $appProcess = Start-Process -FilePath $appExe -PassThru
    $restartDeadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    $restarted = $false
    while ([DateTime]::UtcNow -lt $restartDeadline) {
        try {
            $secureHealth = Invoke-RestMethod -Uri "https://localhost:5443/health" -TimeoutSec 3
            if ($secureHealth.https_setup -eq "ready") { $restarted = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (!$restarted) { throw "Trusted HTTPS did not recover after restart." }
    $secondIdentity = (Get-Content $identityPath -Raw | ConvertFrom-Json).identity
    if ($firstIdentity -ne $secondIdentity) { throw "Restart unnecessarily replaced the HTTPS identity." }
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:5000/shutdown" -Method Post -TimeoutSec 3
    if (!$appProcess.WaitForExit(15000)) { throw "Restarted ScanLink did not exit cleanly." }

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

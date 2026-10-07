$ErrorActionPreference = 'Stop'
$report = Join-Path $PSScriptRoot 'Vastgame-Diagnostics.txt'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Wait -PassThru
    Write-Host "Diagnostic report: $report"
    exit $process.ExitCode
}
'Vastgame Windows diagnostics (read-only checks)' | Set-Content -LiteralPath $report -Encoding UTF8
function Record-Check([string]$Name, [scriptblock]$Check) {
    "`r`n--- $Name ---" | Add-Content -LiteralPath $report
    try {
        (& $Check 2>&1 | Out-String -Width 220) | Add-Content -LiteralPath $report
    } catch {
        $_.Exception.Message | Add-Content -LiteralPath $report
    }
}
Record-Check 'Windows version' { Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' | Select-Object ProductName,DisplayVersion,CurrentBuildNumber,UBR | Format-List }
Record-Check 'CPU virtualization' { Get-CimInstance Win32_Processor | Select-Object Name,VirtualizationFirmwareEnabled,SecondLevelAddressTranslationExtensions,VMMonitorModeExtensions | Format-List }
Record-Check 'Hypervisor visible to Windows' { Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,HypervisorPresent | Format-List }
Record-Check 'Required Windows features' {
    foreach ($name in @('VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux','Microsoft-Hyper-V-Hypervisor')) {
        Get-WindowsOptionalFeature -Online -FeatureName $name | Select-Object FeatureName,State | Format-List
    }
}
Record-Check 'Current boot configuration' { & bcdedit.exe /enum '{current}' }
Record-Check 'Virtualization and WSL services' { Get-Service vmcompute,hns,WslService,LxssManager -ErrorAction Continue | Select-Object Name,Status,StartType | Format-Table -AutoSize }
Record-Check 'WSL version' { & wsl.exe --version }
Record-Check 'WSL status' { & wsl.exe --status }
Record-Check 'Vastgame prerequisite result' { Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'Vastgame\wsl-prerequisites.json') }
foreach ($log in @('Microsoft-Windows-Hyper-V-Hypervisor-Admin','Microsoft-Windows-Hyper-V-Compute-Admin')) {
    Record-Check $log { Get-WinEvent -FilterHashtable @{LogName=$log;StartTime=(Get-Date).AddHours(-24);Level=@(1,2,3)} -MaxEvents 15 | Select-Object TimeCreated,Id,Message | Format-List }
}
Write-Host "Saved diagnostic report: $report" -ForegroundColor Green
Write-Host 'Send Vastgame-Diagnostics.txt to the person helping you.'

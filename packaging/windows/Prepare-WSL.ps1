param([Parameter(Mandatory=$true)][string]$ResultPath)
$ErrorActionPreference = 'Stop'

function Initialize-WSLPrerequisites {
    $computer = Get-CimInstance Win32_ComputerSystem
    if (-not $computer.HypervisorPresent) {
        $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
        if ($cpu.VirtualizationFirmwareEnabled -eq $false) {
            throw 'Windows cannot see hardware virtualization. Enable Intel VT-x / AMD SVM in BIOS, or expose nested virtualization if this PC is itself a VM, then restart Windows.'
        }
    }
    $restart = $false
    foreach ($name in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $name
        if ([string]$feature.State -eq 'EnablePending') {
            $restart = $true
        } elseif ([string]$feature.State -ne 'Enabled') {
            Write-Host "Enabling Windows feature: $name"
            Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart | Out-Null
            $restart = $true
        }
    }
    $boot = (& bcdedit.exe /enum '{current}' | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot check Windows hypervisor boot settings. Run Complete Vastgame Setup with administrator approval.' }
    if ($boot -match '(?im)^\s*hypervisorlaunchtype\s+Off\s*$') {
        Write-Host 'Enabling Windows hypervisor at boot.'
        & bcdedit.exe /set '{current}' hypervisorlaunchtype Auto | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Windows refused to enable the hypervisor. Check administrator permissions or device policy.' }
        $restart = $true
    }
    if ($restart) { return $true }
    if (-not $computer.HypervisorPresent) {
        throw 'Windows features are enabled, but the Windows hypervisor is not running. Restart Windows. If this persists, check BIOS virtualization, nested virtualization or conflicting virtualization software. No Vastgame environment has been imported.'
    }
    $service = Get-Service -Name vmcompute -ErrorAction SilentlyContinue
    if (-not $service) { throw 'The Windows Host Compute Service is missing. Repair the Virtual Machine Platform Windows feature and restart Windows.' }
    if ($service.StartType -eq 'Disabled') { Set-Service -Name vmcompute -StartupType Manual }
    if ($service.Status -ne 'Running') { Start-Service -Name vmcompute }
    (Get-Service -Name vmcompute).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
    return $false
}

try {
    $restart = Initialize-WSLPrerequisites
    $status = 'ready'
    $message = 'Windows virtualization prerequisites are ready.'
    if ($restart) {
        $status = 'restart'
        $message = 'Required Windows features or hypervisor boot settings were enabled. Restart Windows before continuing Vastgame setup.'
    }
    @{ status=$status; message=$message } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    Write-Host $message
    exit 0
} catch {
    @{ status='error'; message=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

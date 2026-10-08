$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$app = $PSScriptRoot
function Checked-WSL([string[]]$Arguments) {
    & wsl.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "WSL failed (exit $LASTEXITCODE). Correct the displayed error, then run Complete Vastgame Setup again." }
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This installer requires x64 Windows 11 or Windows 10 build 19041 or newer.' }
    $build = [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
    if ($build -lt 19041) { throw 'Windows build 19041 or newer is required for WSL 2.' }
    # Credentials and portable pairing belong only to the installing Windows user.
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18', 'S-1-5-32-544')) {
        $principal = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $app -AclObject $acl
    Write-Host 'Checking Windows virtualization features and services...'
    $resultPath = Join-Path $app 'wsl-prerequisites.json'
    if (Test-Path -LiteralPath $resultPath) { Remove-Item -LiteralPath $resultPath }
    $prepare = Join-Path $app 'Prepare-WSL.ps1'
    $check = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$prepare`" -ResultPath `"$resultPath`"" -Wait -PassThru
    if (-not (Test-Path -LiteralPath $resultPath)) { throw 'Windows prerequisite check did not finish. Approve its administrator request, then retry setup.' }
    $requirements = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
    if ($check.ExitCode -ne 0 -or $requirements.status -eq 'error') { throw $requirements.message }
    if ($requirements.status -eq 'restart') {
        $resume = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
        New-Item -Path $resume -Force | Out-Null
        $resumeScript = 'Complete-Setup.ps1'
        if (Test-Path -LiteralPath (Join-Path $app 'release.json')) { $resumeScript = 'Install-Vastgame.ps1' }
        New-ItemProperty -Path $resume -Name VastgameSetup -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$app\$resumeScript`"" -PropertyType String -Force | Out-Null
        Write-Host $requirements.message -ForegroundColor Yellow
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($requirements.message + "`n`nSave your work and restart Windows. Setup will resume after you sign in; you can also open Complete Vastgame Setup from Start.", 'Vastgame: restart required', 'OK', 'Information') | Out-Null
        exit 0
    }
    if ($requirements.status -ne 'ready') { throw 'Windows prerequisite check returned an unexpected result. Retry setup.' }
    & wsl.exe --status *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Enabling WSL 2. Windows may request administrator approval and a reboot.'
        $resume = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
        New-Item -Path $resume -Force | Out-Null
        $resumeScript = 'Complete-Setup.ps1'
        if (Test-Path -LiteralPath (Join-Path $app 'release.json')) { $resumeScript = 'Install-Vastgame.ps1' }
        New-ItemProperty -Path $resume -Name VastgameSetup -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$app\$resumeScript`"" -PropertyType String -Force | Out-Null
        $enable = Start-Process -FilePath 'wsl.exe' -Verb RunAs -ArgumentList '--install --no-distribution --web-download' -Wait -PassThru
        if ($enable.ExitCode -notin @(0, 3010, 1641)) { throw "WSL installation failed (exit $($enable.ExitCode)). Enable virtualization in your PC firmware if Windows reports it is unavailable." }
        if ($enable.ExitCode -in @(3010, 1641)) { throw 'Windows requested a restart to finish installing WSL. Restart Windows, then open Complete Vastgame Setup.' }
        & wsl.exe --status *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Restart Windows, then open Complete Vastgame Setup from the Start menu. Your installer files are retained.' }
    }
    $ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (-not (Test-Path -LiteralPath $ts)) {
        Write-Host 'Installing native Tailscale...'
        $msi = Join-Path $app 'assets\tailscale.msi'
        $signature = Get-AuthenticodeSignature -FilePath $msi
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Tailscale') { throw 'Tailscale installer signature validation failed.' }
        $install = Start-Process -FilePath 'msiexec.exe' -Verb RunAs -ArgumentList "/i `"$msi`" /passive /norestart" -Wait -PassThru
        if ($install.ExitCode -notin @(0, 3010, 1641)) { throw "Tailscale installation failed (exit $($install.ExitCode))." }
    }
    $identity = Get-Content -Raw -LiteralPath (Join-Path $app 'identity.json') | ConvertFrom-Json
    $status = (& $ts status --json | Out-String | ConvertFrom-Json)
    if ($status.BackendState -ne 'Running') {
        $keyFile = Join-Path $app 'tailscale-auth-key'
        if (Test-Path -LiteralPath $keyFile) {
            & $ts up "--auth-key=file:$keyFile" --timeout=120s
        } else {
            Write-Host 'Enroll this new Windows device in Tailscale using the sign-in link below.'
            & $ts up --timeout=120s
        }
        if ($LASTEXITCODE -ne 0) { throw 'Tailscale enrollment is incomplete. Finish sign-in, then run Complete Vastgame Setup again.' }
        $status = (& $ts status --json | Out-String | ConvertFrom-Json)
    }
    if ($status.BackendState -ne 'Running' -or $status.CurrentTailnet.Name -ne $identity.tailnet) { throw 'Tailscale must be signed into the same tailnet as your Vastgame VMs. Switch to that account and rerun Complete Vastgame Setup.' }
    $distroOutput = & wsl.exe --list --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list WSL distributions. Check that WSL is installed, then retry setup.' }
    $distros = (($distroOutput | Out-String) -replace '\x00', '').Split("`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    if ($distros -notcontains 'Vastgame') {
        Write-Host 'Creating the private Vastgame WSL environment...'
        $storage = Join-Path $env:LOCALAPPDATA 'Vastgame-WSL'
        New-Item -ItemType Directory -Force -Path $storage | Out-Null
        Checked-WSL @('--import', 'Vastgame', $storage, (Join-Path $app 'assets\ubuntu-root.tar.gz'), '--version', '2')
    }
    $linuxApp = (& wsl.exe -d Vastgame -u root --exec wslpath -u $app | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $linuxApp) { throw 'Cannot map the installer directory into WSL.' }
    $linuxTS = (& wsl.exe -d Vastgame -u root --exec wslpath -u $ts | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $linuxTS) { throw 'Cannot map Tailscale into WSL.' }
    $nativePowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $linuxPowerShell = (& wsl.exe -d Vastgame -u root --exec wslpath -u $nativePowerShell | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $linuxPowerShell) { throw 'Cannot map Windows PowerShell into WSL.' }
    Write-Host 'Checking WSL internet DNS...'
    $dnsServers = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | ForEach-Object { $_.DNSServer.ServerAddresses } | Where-Object {
        $address = $null
        [Net.IPAddress]::TryParse($_, [ref]$address) -and $address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and -not [Net.IPAddress]::IsLoopback($address)
    } | Select-Object -Unique)
    Write-Host 'Preparing dependencies and verifying Vast/Drive accounts...'
    Checked-WSL (@('-d', 'Vastgame', '-u', 'root', '--exec', 'bash', "$linuxApp/install-backend.sh", $linuxApp, $linuxTS, $linuxPowerShell) + $dnsServers)
    Write-Host 'Checking CLI and native Windows integration...'
    Checked-WSL @('-d', 'Vastgame', '-u', 'vastgame', '--exec', '/home/vastgame/.local/bin/vastgame', 'help')
    Checked-WSL @('-d', 'Vastgame', '-u', 'vastgame', '--exec', 'env', 'PATH=/home/vastgame/.local/bin:/usr/bin:/bin', 'vastgame-native', 'resolution')
    Checked-WSL @('-d', 'Vastgame', '-u', 'vastgame', '--exec', 'env', 'PATH=/home/vastgame/.local/bin:/usr/bin:/bin', 'tailscale', 'ip', '-4')
    # Existing uploaded games start from their remote manifests; no local binaries are bundled.
    if (Test-Path -LiteralPath (Join-Path $app 'accounts.tar')) { Remove-Item -LiteralPath (Join-Path $app 'accounts.tar') -Force }
    $keyFile = Join-Path $app 'tailscale-auth-key'
    if (Test-Path -LiteralPath $keyFile) { Remove-Item -LiteralPath $keyFile -Force }
    Set-Content -LiteralPath (Join-Path $app 'ready') -Value 'ready' -Encoding ASCII
    Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name VastgameSetup -ErrorAction SilentlyContinue
    Write-Host 'Vastgame is ready. Open Vastgame from the Start menu, then use vastgame list or vastgame start GAME.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host "SETUP INCOMPLETE: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No Vast VM was rented or destroyed. Open Complete Vastgame Setup to retry.'
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message + "`n`nRun Complete Vastgame Setup from the Start menu to retry.", 'Vastgame setup incomplete', 'OK', 'Warning') | Out-Null
    exit 1
}

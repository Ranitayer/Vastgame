$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    $release = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'release.json') | ConvertFrom-Json
    foreach ($entry in $release.files.PSObject.Properties) {
        if ([IO.Path]::GetFileName($entry.Name) -ne $entry.Name) { throw 'Unsafe release filename.' }
        $actual = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $entry.Name) -Algorithm SHA256).Hash
        if ($actual -ne $entry.Value) { throw "Release checksum failed: $($entry.Name)" }
    }
    $candidates = @((Join-Path $env:LOCALAPPDATA 'Vastgame'))
    $command = Get-Command vastgame.cmd -ErrorAction SilentlyContinue
    if ($command) { $candidates += Split-Path $command.Source }
    $registration = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VastgamePersonalWindows_is1' -ErrorAction SilentlyContinue
    if ($registration.InstallLocation) { $candidates += $registration.InstallLocation }
    $app = $candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'Moonlight\Moonlight.exe') } | Select-Object -First 1
    if (-not $app) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Install-Vastgame.ps1')
        exit $LASTEXITCODE
    }
    $ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $paths = @()
    foreach ($path in @($PSScriptRoot, $app, $ts, $powershell)) {
        $mapped = (& wsl.exe -d Vastgame -u vastgame --exec wslpath -u $path | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $mapped) { throw 'Finish Vastgame setup before applying this update.' }
        $paths += $mapped
    }
    & wsl.exe -d Vastgame -u vastgame --exec bash "$($paths[0])/update-backend.sh" @paths
    if ($LASTEXITCODE -ne 0) { throw 'Update failed. Read its recovery message above.' }
    Write-Host "Vastgame $($release.version) updated. Future updates: vastgame update" -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

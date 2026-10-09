$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('Vastgame-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $base = 'https://github.com/Ranitayer/Vastgame/releases/latest/download'
    $zip = Join-Path $temporary 'Vastgame.zip'
    Write-Host 'Downloading the latest Vastgame release...'
    $checksumFile = Join-Path $temporary 'Vastgame.zip.sha256'
    Invoke-WebRequest -UseBasicParsing -Uri "$base/Vastgame.zip.sha256" -OutFile $checksumFile -TimeoutSec 60
    $checksum = ((Get-Content -Raw -Encoding UTF8 -LiteralPath $checksumFile).Trim() -split '\s+')[0]
    if ($checksum -notmatch '^[0-9a-f]{64}$') { throw 'Invalid release checksum.' }
    Invoke-WebRequest -UseBasicParsing -Uri "$base/Vastgame.zip" -OutFile $zip -TimeoutSec 300
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $checksum) { throw 'Download checksum mismatch; no update applied.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $total = 0
        foreach ($entry in $archive.Entries) {
            $total += $entry.Length
            if ($entry.FullName -notmatch '^Vastgame/[A-Za-z0-9._-]+$' -or $total -gt 128MB) { throw 'Unsafe update archive.' }
        }
        if ($archive.Entries.Count -gt 100) { throw 'Too many update files.' }
    } finally { $archive.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $temporary)
    $bundle = Join-Path $temporary 'Vastgame'
    $release = Get-Content -Raw -LiteralPath (Join-Path $bundle 'release.json') | ConvertFrom-Json
    $installedApp = $PSScriptRoot
    if (-not (Test-Path -LiteralPath (Join-Path $installedApp 'ready'))) { $installedApp = Join-Path $env:LOCALAPPDATA 'Vastgame' }
    $installed = Join-Path $installedApp 'release.json'
    if (Test-Path -LiteralPath $installed) {
        $current = Get-Content -Raw -LiteralPath $installed | ConvertFrom-Json
        if ($current.source_commit -eq $release.source_commit) { Write-Host "Vastgame $($current.version) is already current."; exit 0 }
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $bundle 'Update-Vastgame.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Vastgame update did not complete.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue }

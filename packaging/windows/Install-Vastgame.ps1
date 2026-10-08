$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    $app = Join-Path $env:LOCALAPPDATA 'Vastgame'
    if ((Test-Path -LiteralPath (Join-Path $app 'ready')) -and [IO.Path]::GetFullPath($app) -ne [IO.Path]::GetFullPath($PSScriptRoot)) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Update-Vastgame.ps1')
        exit $LASTEXITCODE
    }
    New-Item -ItemType Directory -Force -Path $app | Out-Null
    # Protect private imports before any account or pairing file is written.
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18', 'S-1-5-32-544')) {
        $principal = New-Object Security.Principal.SecurityIdentifier($sid)
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    Set-Acl -LiteralPath $app -AclObject $acl
    $release = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'release.json') | ConvertFrom-Json
    foreach ($entry in $release.files.PSObject.Properties) {
        if ([IO.Path]::GetFileName($entry.Name) -ne $entry.Name) { throw 'Unsafe release filename.' }
        $source = Join-Path $PSScriptRoot $entry.Name
        if ($entry.Name -eq 'stream.json' -and [IO.Path]::GetFullPath($app) -eq [IO.Path]::GetFullPath($PSScriptRoot)) { continue }
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.Value) { throw "Release checksum mismatch: $($entry.Name)" }
    }
    if ([IO.Path]::GetFullPath($app) -ne [IO.Path]::GetFullPath($PSScriptRoot)) {
        foreach ($entry in $release.files.PSObject.Properties) {
            if ($entry.Name -eq 'stream.json' -and (Test-Path -LiteralPath (Join-Path $app 'stream.json'))) { continue }
            Copy-Item -LiteralPath (Join-Path $PSScriptRoot $entry.Name) -Destination (Join-Path $app $entry.Name) -Force
        }
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'release.json') -Destination $app -Force
    }
    $assets = Join-Path $app 'assets'
    New-Item -ItemType Directory -Force -Path $assets | Out-Null
    $dependencies = Get-Content -Raw -LiteralPath (Join-Path $app 'dependencies.json') | ConvertFrom-Json
    function Download-Dependency($name, $filename) {
        $target = Join-Path $assets $filename
        $spec = $dependencies.$name
        if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $spec.sha256) {
            Write-Host "Downloading $name (first installation only)..."
            Invoke-WebRequest -UseBasicParsing -Uri $spec.url -OutFile $target -TimeoutSec 1800
        }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $spec.sha256) { throw "$name checksum mismatch." }
        return $target
    }
    if (-not (Test-Path -LiteralPath (Join-Path $app 'Moonlight\Moonlight.exe'))) {
        $moonlightZip = Download-Dependency 'moonlight' 'moonlight.zip'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $nextMoonlight = Join-Path $assets 'Moonlight'
        if (Test-Path -LiteralPath $nextMoonlight) { Remove-Item -LiteralPath $nextMoonlight -Recurse -Force }
        [IO.Compression.ZipFile]::ExtractToDirectory($moonlightZip, $nextMoonlight)
        if (-not (Test-Path -LiteralPath (Join-Path $nextMoonlight 'Moonlight.exe'))) { throw 'Moonlight executable missing from the dependency archive.' }
        if (Test-Path -LiteralPath (Join-Path $app 'Moonlight')) { Remove-Item -LiteralPath (Join-Path $app 'Moonlight') -Recurse -Force }
        Move-Item -LiteralPath $nextMoonlight -Destination (Join-Path $app 'Moonlight')
        New-Item -ItemType File -Force -Path (Join-Path $app 'Moonlight\portable.dat') | Out-Null
    }
    if (-not (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'))) { $null = Download-Dependency 'tailscale' 'tailscale.msi' }
    $distros = ((& wsl.exe --list --quiet 2>$null | Out-String) -replace '\x00', '').Split("`n") | ForEach-Object { $_.Trim() }
    if ($distros -notcontains 'Vastgame') { $null = Download-Dependency 'ubuntu' 'ubuntu-root.tar.gz' }
    if (-not (Test-Path -LiteralPath (Join-Path $app 'identity.json'))) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object Windows.Forms.OpenFileDialog
        $dialog.Title = 'Choose your private Vastgame-Accounts.tar (never upload it to GitHub)'
        $dialog.Filter = 'Vastgame account bundle (*.tar)|*.tar'
        if ($dialog.ShowDialog() -ne 'OK') { throw 'Account setup is required. Export a private account bundle on your configured Linux PC, then rerun Vastgame.' }
        Copy-Item -LiteralPath $dialog.FileName -Destination (Join-Path $app 'accounts.tar') -Force
        $identity = (& tar.exe -xOf (Join-Path $app 'accounts.tar') identity.json | Out-String)
        if ($LASTEXITCODE -ne 0) { throw 'Private account bundle has no identity.json.' }
        $null = $identity | ConvertFrom-Json
        [IO.File]::WriteAllText((Join-Path $app 'identity.json'), $identity, (New-Object Text.UTF8Encoding($false)))
        $pairingDirectory = Join-Path $app 'Moonlight\Moonlight Game Streaming Project'
        $pairing = Join-Path $pairingDirectory 'Moonlight.ini'
        if (-not (Test-Path -LiteralPath $pairing)) {
            $content = (& tar.exe -xOf (Join-Path $app 'accounts.tar') moonlight.ini 2>$null | Out-String)
            if ($LASTEXITCODE -eq 0) {
                New-Item -ItemType Directory -Force -Path $pairingDirectory | Out-Null
                [IO.File]::WriteAllText($pairing, $content, (New-Object Text.UTF8Encoding($false)))
            }
        }
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'Complete-Setup.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Setup is incomplete. Read the message above, then rerun Vastgame.' }
    if (-not (Test-Path -LiteralPath (Join-Path $app 'ready'))) { exit 0 }
    $userPath = [string][Environment]::GetEnvironmentVariable('Path', 'User')
    if (($userPath -split ';') -notcontains $app) { [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';')+';'+$app), 'User') }
    $shell = New-Object -ComObject WScript.Shell
    $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Vastgame'
    New-Item -ItemType Directory -Force -Path $menu | Out-Null
    foreach ($name in @('Vastgame','Update Vastgame')) {
        $shortcut = $shell.CreateShortcut((Join-Path $menu ($name+'.lnk')))
        $shortcut.TargetPath = Join-Path $app $(if ($name -eq 'Vastgame') { 'Vastgame.cmd' } else { 'Update-Vastgame.cmd' })
        $shortcut.WorkingDirectory = $app
        $shortcut.Save()
    }
    Remove-Item -LiteralPath $assets -Recurse -Force
    Write-Host 'Vastgame installed. Open Vastgame from Start. Future updates: vastgame update' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

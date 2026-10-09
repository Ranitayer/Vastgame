param([switch]$PrepareUpdate, [string]$Application = (Join-Path $env:LOCALAPPDATA 'Vastgame'))
$ErrorActionPreference = 'Stop'
# Use Microsoft's documented runtime keys; verify its bootstrapper before execution.
$runtimeKeys = @(
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
)
function Has-WebView {
    foreach ($key in $runtimeKeys) {
        $version = (Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue).pv
        if ($version -and $version -ne '0.0.0.0') { return $true }
    }
    return $false
}
try {
    if (-not (Has-WebView)) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $bootstrapper = Join-Path ([IO.Path]::GetTempPath()) ('Vastgame-WebView-' + [Guid]::NewGuid().ToString('N') + '.exe')
        try {
            Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrapper -TimeoutSec 120
            $signature = Get-AuthenticodeSignature -LiteralPath $bootstrapper
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'WebView2 installer signature verification failed.' }
            $installer = Start-Process -FilePath $bootstrapper -ArgumentList '/silent','/install' -PassThru -Wait
            if ($installer.ExitCode -ne 0 -or -not (Has-WebView)) { throw 'WebView2 installation incomplete. Install the Microsoft Evergreen runtime, then retry.' }
        } finally { Remove-Item -LiteralPath $bootstrapper -Force -ErrorAction SilentlyContinue }
    }
    $app = [IO.Path]::GetFullPath($Application)
    $executable = Join-Path $app 'vastgame-desktop.exe'
    if ($PrepareUpdate) {
        foreach ($process in @(Get-Process -Name 'vastgame-desktop' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable })) {
            $null = $process.CloseMainWindow()
            if (-not $process.WaitForExit(10000)) { throw 'Close the Vastgame desktop window and retry the update. The rig was retained.' }
        }
    } elseif (Test-Path -LiteralPath $executable) {
        $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Vastgame'
        New-Item -ItemType Directory -Force -Path $menu | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $menu 'Vastgame.lnk'))
        $shortcut.TargetPath = $executable
        $shortcut.WorkingDirectory = $app
        $shortcut.Save()
    }
    exit 0
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }

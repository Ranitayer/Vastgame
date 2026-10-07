param(
    [Parameter(Mandatory=$true)][string]$Address,
    [ValidateRange(1,100)][int]$Count = 20,
    [ValidateRange(0.05,10)][double]$Interval = 0.2,
    [ValidateRange(1,10)][int]$TimeoutSeconds = 2
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
$samples = New-Object 'System.Collections.Generic.List[double]'
$ping = New-Object Net.NetworkInformation.Ping
try {
    for ($i=0; $i -lt $Count; $i++) {
        try {
            $reply = $ping.Send($Address, $TimeoutSeconds * 1000)
            if ($reply.Status -eq [Net.NetworkInformation.IPStatus]::Success) { $samples.Add([double]$reply.RoundtripTime) }
        } catch { }
        if ($i -lt ($Count - 1)) { Start-Sleep -Milliseconds ([int]($Interval * 1000)) }
    }
} finally { $ping.Dispose() }
$received = $samples.Count
$loss = 100.0 * ($Count - $received) / $Count
Write-Output "$Count packets transmitted, $received received, $($loss.ToString('F3'))% packet loss"
if ($received -gt 0) {
    $measure = $samples | Measure-Object -Minimum -Maximum -Average
    $variance = 0.0
    foreach ($sample in $samples) { $variance += [Math]::Pow($sample - $measure.Average, 2) }
    $jitter = [Math]::Sqrt($variance / $received)
    $summary = '{0:F3}/{1:F3}/{2:F3}/{3:F3}' -f $measure.Minimum, $measure.Average, $measure.Maximum, $jitter
    Write-Output "rtt min/avg/max/mdev = $summary ms"
    exit 0
}
exit 1

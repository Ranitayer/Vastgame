$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class VastgameDisplay {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct Mode {
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string device;
        public ushort spec, driver, size, extra;
        public uint fields;
        public int x, y;
        public uint orientation, fixedOutput;
        public short color, duplex, yResolution, tt, collate;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string form;
        public ushort pixels;
        public uint bits, width, height, flags, frequency;
        public uint icmMethod, icmIntent, media, dither, reserved1, reserved2, panWidth, panHeight;
    }
    [DllImport("user32.dll",CharSet=CharSet.Unicode)]
    public static extern bool EnumDisplaySettings(string device, int mode, ref Mode data);
}
'@
$mode = New-Object VastgameDisplay+Mode
$mode.size = [Runtime.InteropServices.Marshal]::SizeOf($mode)
$display = [Windows.Forms.Screen]::PrimaryScreen.DeviceName
if (-not [VastgameDisplay]::EnumDisplaySettings($display, -1, [ref]$mode)) { throw 'Cannot read the current Windows display mode.' }
if ($mode.width -lt 320 -or $mode.height -lt 200 -or $mode.frequency -lt 10) { throw 'Windows returned an invalid display mode.' }
@{ resolution = "$($mode.width)x$($mode.height)"; refresh = $mode.frequency } | ConvertTo-Json -Compress

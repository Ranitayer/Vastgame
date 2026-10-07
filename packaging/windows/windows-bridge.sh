#!/usr/bin/env bash
set -euo pipefail
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/vastgame/windows.json"
native_powershell() {
  local executable
  executable="$(jq -er '.powershell | select(type == "string" and length > 0)' "$cfg")" || {
    echo 'Windows PowerShell path is missing. Run Complete Vastgame Setup again.' >&2
    return 1
  }
  "$executable" "$@"
}
case "${0##*/}" in
  tailscale)
    executable="$(jq -er '.tailscale' "$cfg")"
    "$executable" "$@" | sed 's/\r$//'
    ;;
  moonlight)
    root="$(jq -er '.application' "$cfg")"
    cd "$root/Moonlight"
    exec ./Moonlight.exe "$@"
    ;;
  ping)
    root="$(jq -er '.application' "$cfg")"
    count=20; interval=0.2; wait=2; address=''
    while (( $# )); do
      case "$1" in
        -c) count="$2"; shift 2 ;;
        -i) interval="$2"; shift 2 ;;
        -W) wait="$2"; shift 2 ;;
        -4|-n) shift ;;
        -*) echo "Unsupported ping option: $1" >&2; exit 2 ;;
        *) address="$1"; shift ;;
      esac
    done
    native_powershell -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$root/Native-Ping.ps1")" \
      -Address "$address" -Count "$count" -Interval "$interval" -TimeoutSeconds "$wait" | sed 's/\r$//'
    ;;
  vastgame-native)
    root="$(jq -er '.application' "$cfg")"
    result="$(native_powershell -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$root/Native-Screen.ps1")" | tr -d '\r')"
    case "${1:-}" in
      resolution) jq -er '.resolution | select(test("^[0-9]+x[0-9]+$"))' <<<"$result" ;;
      refresh) jq -er '.refresh | select(type == "number" and . >= 10 and . <= 1000)' <<<"$result" ;;
      *) exit 2 ;;
    esac
    ;;
  *) exit 2 ;;
esac

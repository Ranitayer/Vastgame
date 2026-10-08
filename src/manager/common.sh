#!/usr/bin/env bash
set -Eeuo pipefail

# Manual route-gate override:
#   vastgame force
#   vastgame force connect
VASTGAME_FORCE_ROUTE=0

if [[ "${1:-}" == "force" ]]; then
    VASTGAME_FORCE_ROUTE=1
    shift
fi

MAX_PRICE="0.70"
MAX_RESULTS=15
DISK_GB=250
STATUS_PORT=48199

VAST_START_TIMEOUT=900
TAILSCALE_TIMEOUT=1200
WOLF_TIMEOUT=10800

LOCAL_MAX_RTT_MS=120
LOCAL_MAX_LOSS_PCT=1
LOCAL_MAX_JITTER_MS=15

CFGDIR="${XDG_CONFIG_HOME:-$HOME/.config}/vastgame"
STATEDIR="${XDG_STATE_HOME:-$HOME/.local/state}/vastgame"

TEMPLATE_FILE="$CFGDIR/template_hash"
INSTANCE_FILE="$STATEDIR/instance_id"
KNOWN_HOSTS="$STATEDIR/known_hosts"
HISTORY_FILE="$STATEDIR/host_history.json"
BOOTSTRAP_FILE="$APP_ROOT/src/bootstrap/start.sh"
RUNTIME_DIR="$APP_ROOT/src/runtime"
CLIENT_DIR="$APP_ROOT/src/client"
NATIVE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/vastgame/native"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/vastgame"
BOOTSTRAP_CONFIG="$CFGDIR/bootstrap.json"

EU_COUNTRIES='[AT,BE,BG,HR,CY,CZ,DE,DK,EE,ES,FI,FR,GB,GR,HU,IE,IS,IT,LI,LT,LU,LV,NL,NO,PL,PT,RO,SE,SI,SK,CH]'

mkdir -p "$CFGDIR" "$STATEDIR"

bold() {
    printf '\033[1m%s\033[0m\n' "$*"
}

ok() {
    printf '✓ %s\n' "$*"
}

warn() {
    printf '⚠ %s\n' "$*"
}

die() {
    if [[ "${VG_FAILURE_INSTANCE:-}" =~ ^[0-9]+$ ]] && declare -F collect_failure_report >/dev/null; then
        progress_clear
        collect_failure_report "$VG_FAILURE_INSTANCE" "$*"
    fi
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

elapsed() {
    local s="$1"
    printf '%dm %02ds' "$((s / 60))" "$((s % 60))"
}

check_dependencies() {
for c in flock vastai jq column curl tailscale ssh timeout sed grep tr date python3 ping awk cut mktemp wc; do
    command -v "$c" >/dev/null 2>&1 ||
        die "Missing command: $c"
done
}

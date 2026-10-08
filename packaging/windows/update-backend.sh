#!/usr/bin/env bash
set -Eeuo pipefail
bundle="$1"
user_home="$(getent passwd "$(id -u)" | cut -d: -f6)"
[[ "$user_home" == /home/vastgame ]] || { echo 'Run this updater as the Vastgame WSL user.' >&2; exit 1; }
exec python3 "$bundle/apply_update.py" --home "$user_home" --bundle "$bundle" --application "$2" --tailscale "$3" --powershell "$4"

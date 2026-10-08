#!/usr/bin/env bash
set -euo pipefail
HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
[[ -n "$HOME" ]] || { echo 'Cannot resolve the Vastgame WSL user home.' >&2; exit 1; }
export HOME
export PATH="$HOME/.local/bin:$HOME/.local/share/vastgame/venv/bin:$PATH"
export VASTGAME_WINDOWS=1
args=()
for argument in "$@"; do
  if [[ "$argument" =~ ^[A-Za-z]:[\\/] || "$argument" == \\\\* ]]; then
    argument="$(wslpath -u "$argument")"
  fi
  args+=("$argument")
done
cd "$HOME"
exec "$HOME/.local/share/vastgame/app/bin/vastgame" "${args[@]}"

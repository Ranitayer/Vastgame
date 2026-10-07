#!/bin/bash
set -euo pipefail
source /opt/gow/bash-lib/utils.sh
source /opt/gow/startup.d/10-create-dirs.sh
export XDG_RUNTIME_DIR="/tmp/vastgame-prepare-$UID"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
# Runtime installation needs an X display, not a GPU compositor. Xvfb avoids
# NVIDIA/headless DRM modifier failures while keeping the real game launcher intact.
command -v xvfb-run >/dev/null || { echo 'Preparation image is missing xvfb-run' >&2; exit 1; }
xvfb-run -a --server-args='-screen 0 1280x720x24 -nolisten tcp' dbus-run-session -- \
    /usr/bin/python3 -u /opt/vastgame/prepare_game.py "$1"
# Require the fresh readiness marker
# and prefix in this same container namespace before reporting success.
exec /usr/bin/python3 -c 'import json, sys; from prepare_game import require_ready; require_ready(json.load(open(sys.argv[1])))' "$1"

# Sourced by the stock GOW startup AFTER its Lutris directory setup.
# The stock launcher still creates the display, compositor, audio and input.
LUTRIS=/opt/vastgame/launch-game.sh
LUTRIS_ARGS=()
# Stock GOW's launcher invokes `command -v gamescope` in this same shell.
# Add cursor capture while retaining its native size/refresh/compositor setup.
VASTGAME_GAMESCOPE="$(type -P gamescope)"
gamescope() { "$VASTGAME_GAMESCOPE" --force-grab-cursor "$@"; }

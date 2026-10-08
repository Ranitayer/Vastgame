# ============================================================
# GAME CATALOG AND PER-GAME STATE
# ============================================================

GAME_ROOT="$CFGDIR/games"
SELECTED_GAME_FILE="$STATEDIR/selected_game"
REMOTE_ROOT="gdrive:VastGaming"

calculate_disk_requirement() {
    local id manifest
    id="$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)"
    [[ -n "$id" ]] || return 0
    valid_game_id "$id" || die "Invalid selected game ID"
    manifest="$(game_manifest "$id")"
    DISK_GB="$(python3 - "$manifest" <<'PY_DISK'
import json, math, sys
from pathlib import Path
m = json.loads(Path(sys.argv[1]).read_text())
p = m.get('package', {})
a, u = p.get('size', 0), p.get('unpacked_bytes', 0)
if not all(type(x) is int and x > 0 for x in (a, u)):
    raise SystemExit('Package the game first: archive and installed sizes are required')
parts = p.get('parts', [])
# Eight bounded parts in flight, streamed into the installed tree; legacy archives
# still need space for the complete compressed input beside the installation.
scratch = sum(sorted((x['size'] for x in parts), reverse=True)[:8]) if parts else a
reserve = 35 * 1024**3  # guest + container images + Proton/prefix/state
print(max(60, math.ceil(((u + scratch) * 1.15 + reserve) / 10**9)))
PY_DISK
)" || die "Could not determine safe VM disk capacity"
}

valid_game_id() {
    [[ "${1:-}" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]]
}

game_manifest() { printf '%s/%s/manifest.json' "$GAME_ROOT" "$1"; }

ensure_save_catalog() {
    mkdir -p "$CACHE_DIR"
    [[ -f "$CACHE_DIR/ludusavi.json.gz" ]] || cp "$CLIENT_DIR/ludusavi.json.gz" "$CACHE_DIR/ludusavi.json.gz"
}

game_discover_saves() {
    ensure_save_catalog
    local id="${1:-}"
    valid_game_id "$id" || die "Usage: vastgame saves <game-id> [--title <Ludusavi title>] [--refresh]"
    [[ -f "$(game_manifest "$id")" ]] || die "Unknown game: $id"
    python3 "$CLIENT_DIR/save_discovery.py" "$(game_manifest "$id")" --catalog "$CACHE_DIR/ludusavi.json.gz" "${@:2}"
}

game_add() {
    python3 "$CLIENT_DIR/game_catalog.py" add "$@" --catalog "$GAME_ROOT"
}

game_ingest() {
    local dependency
    for dependency in rclone tar zstd; do
        command -v "$dependency" >/dev/null 2>&1 || die "Missing import dependency: $dependency"
    done
    python3 "$CLIENT_DIR/ingest.py" "$@" --catalog "$GAME_ROOT" --cache "$CACHE_DIR/ingest"
}

game_package() {
    local dependency
    for dependency in rclone tar zstd; do
        command -v "$dependency" >/dev/null 2>&1 || die "Missing package dependency: $dependency"
    done
    local id="${1:-}" manifest source
    valid_game_id "$id" || die "Usage: vastgame game package <id>"
    manifest="$(game_manifest "$id")"
    [[ -f "$manifest" ]] || die "Unknown game: $id"
    source="$(jq -r '.source.path // empty' "$manifest")"
    [[ -d "$source" ]] || die "Source folder is unavailable: $source"
    python3 "$CLIENT_DIR/package_publish.py" "$manifest" "$source" "$CACHE_DIR/package/$id" ||
        die "Package publication failed; previous package selection retained"
    ok "Packaged $id"
}

game_list() {
    mkdir -p "$GAME_ROOT"
    shopt -s nullglob
    local found=0 m
    for m in "$GAME_ROOT"/*/manifest.json; do
        found=1
        jq -r '[.id,.name,.version,.game.executable] | @tsv' "$m"
    done
    (( found )) || echo "No games registered."
}

game_validate() {
    local id="${1:-}" manifest
    valid_game_id "$id" || die "Usage: vastgame game validate <id>"
    manifest="$(game_manifest "$id")"
    [[ -f "$manifest" ]] || die "Unknown game: $id"
    python3 "$CLIENT_DIR/game_catalog.py" validate "$manifest" --id "$id" || die "Invalid game: $id"
    ok "Manifest valid: $id"
}

game_enable_dlss() {
    local id="${1:-}" manifest
    valid_game_id "$id" || die "Usage: vastgame dlss <id>"
    manifest="$(game_manifest "$id")"
    [[ -f "$manifest" ]] || die "Unknown game: $id"
    jq '.runner.version //= "ge-proton" | .compatibility.nvidia_ngx=true | del(.graphics.dlss,.graphics.path_tracing,.graphics.ray_tracing) | if .graphics == {} then del(.graphics) else . end' "$manifest" > "$manifest.tmp" && mv "$manifest.tmp" "$manifest"
    ok "NVIDIA compatibility configured for $id; choose graphics settings in-game"
}

game_inspect() {
    local id="${1:-}"
    valid_game_id "$id" || die "Usage: vastgame game inspect <id>"
    [[ -f "$(game_manifest "$id")" ]] || die "Unknown game: $id"
    jq . "$(game_manifest "$id")"
}

game_select() {
    local id="${1:-}"
    valid_game_id "$id" || die "Usage: vastgame game select <id>"
    [[ -f "$(game_manifest "$id")" ]] || die "Unknown game: $id"
    printf '%s\n' "$id" > "$SELECTED_GAME_FILE"
    ok "Selected $id"
}

purge_remote_tree() {
    local target="$1" output rc
    output="$(rclone purge "$target" 2>&1)" && return 0
    rc=$?
    if grep -Eqi 'directory not found|object not found|not found' <<<"$output"; then
        return 0
    fi
    printf '%s\n' "$output" >&2
    return "$rc"
}

game_remove() {
    local id="${1:-}" answer
    valid_game_id "$id" || die "Usage: vastgame game remove <id>"
    [[ -d "$GAME_ROOT/$id" ]] || die "Unknown game: $id"
    local instances
    instances="$(all_vastgame_instances)" || die "Cannot check active VMs; removal refused"
    jq -e 'length == 0' >/dev/null <<<"$instances" || die "Stop all Vastgame VMs before removing a game; remote saves may still be in use"
    read -rp "Remove local package metadata and remote games/$id + state/$id? [y/N]: " answer
    [[ "$answer" =~ ^[yY]$ ]] || return 0
    command -v rclone >/dev/null 2>&1 || die "rclone is required for a clean remote purge"
    purge_remote_tree "$REMOTE_ROOT/games/$id" || die "Remote game purge failed; local metadata was kept"
    purge_remote_tree "$REMOTE_ROOT/state/$id" || die "Remote state purge failed; local metadata was kept"
    python3 - "$GAME_ROOT/$id" <<'PY_REMOVE'
import shutil, sys
shutil.rmtree(sys.argv[1])
PY_REMOVE
    [[ "$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)" == "$id" ]] && rm -f "$SELECTED_GAME_FILE"
    ok "Removed $id"
}

state_backup() {
    local gid="${1:-}" id
    valid_game_id "$gid" || die "Usage: vastgame backup <game-id>"
    id="$(pick_instance)" || die "No Vastgame VM found"
    remote_state backup "$id" "$gid" || die "Backup failed; VM retained"
    ok "Verified backup saved for $gid"
}

state_restore() {
    local gid="${1:-}" id
    valid_game_id "$gid" || die "Usage: vastgame restore <game-id>"
    id="$(pick_instance)" || die "No Vastgame VM found"
    remote_state restore "$id" "$gid" || die "Restore failed; game data retained"
    ok "Verified state restored for $gid"
}

state_resume() {
    local gid="${1:-}" id
    valid_game_id "$gid" || die "Usage: vastgame state resume <game-id>"
    id="$(pick_instance)" || die "No Vastgame VM found"
    remote_state resume "$id" "$gid" || die "Cannot release shutdown block; VM retained"
}

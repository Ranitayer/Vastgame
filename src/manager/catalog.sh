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
    local folder="${1:-}" id="${2:-}" exe name manifest dlss=false
    if [[ "$folder" == "--dlss" ]]; then
        dlss=true
        folder="${2:-}"
        id="${3:-}"
    elif [[ "${3:-}" == "--dlss" ]]; then
        dlss=true
    fi
    [[ -d "$folder" ]] || die "Game folder not found: $folder"
    folder="$(cd "$folder" && pwd)"
    name="$(basename "$folder")"
    if [[ -z "$id" ]]; then
        id="$(tr '[:upper:]' '[:lower:]' <<<"$name" | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
    fi
    valid_game_id "$id" || die "Invalid game id: $id"
    [[ ! -e "$(game_manifest "$id")" ]] || die "Game already exists: $id"
    mapfile -t exes < <(find "$folder" -type f -iname '*.exe' -printf '%P\n' |
        grep -Eiv '(^|/)(_commonredist|redist|crash|crashreport|installer|unins)' |
        sort | head -21)
    (( ${#exes[@]} > 0 )) ||
        mapfile -t exes < <(find "$folder" -type f -iname '*.exe' -printf '%P\n' | sort | head -21)
    (( ${#exes[@]} > 0 )) || die "No Windows executable found in $folder"
    local preferred="" candidate base lower_name lower_id lower_base
    local -a original_exes
    lower_name="$(tr '[:upper:]' '[:lower:]' <<<"$name")"
    lower_id="$(tr '[:upper:]' '[:lower:]' <<<"$id")"
    for candidate in "${exes[@]}"; do
        base="${candidate##*/}"
        base="${base%.*}"
        lower_base="$(tr '[:upper:]' '[:lower:]' <<<"$base")"
        if [[ "$lower_base" == "$lower_name" || "$lower_base" == "$lower_id" ]]; then
            preferred="$candidate"
            break
        fi
    done
    if [[ -n "$preferred" ]]; then
        original_exes=("${exes[@]}")
        exes=("$preferred")
        for candidate in "${original_exes[@]}"; do
            [[ "$candidate" == "$preferred" ]] || exes+=("$candidate")
        done
    fi
    exe="${exes[0]}"
    if (( ${#exes[@]} > 1 )); then
        warn "Multiple executables found; selecting $exe. Review with game inspect: ${exes[*]}"
    fi
    mkdir -p "$GAME_ROOT/$id"
    jq -n --arg id "$id" --arg name "$name" --arg root "$folder" --arg exe "$exe" --argjson dlss "$dlss" \
      '{schema:1,id:$id,name:$name,version:"v1",source:{path:$root},game:{executable:$exe,working_dir:(($exe|split("/")[:-1])|join("/")),arguments:[]},runner:{type:"wine",version:"ge-proton"},environment:{},state:{saves:[],configs:[],shaders:[]},compatibility:{nvidia_ngx:$dlss}}' \
      > "$(game_manifest "$id")"
    if [[ -f "$CLIENT_DIR/save_discovery.py" ]]; then
        ensure_save_catalog
        python3 "$CLIENT_DIR/save_discovery.py" "$(game_manifest "$id")" --catalog "$CACHE_DIR/ludusavi.json.gz" ||
            warn "Known save lookup unavailable; existing prefix persistence remains enabled"
    fi
    jq . "$(game_manifest "$id")"
    ok "Added game $id"
}

game_package() {
    local id="${1:-}" manifest source archive sha unpacked parts_dir
    valid_game_id "$id" || die "Usage: vastgame game package <id>"
    command -v rclone >/dev/null 2>&1 || die "rclone is required for remote game packages"
    manifest="$(game_manifest "$id")"
    [[ -f "$manifest" ]] || die "Unknown game: $id"
    source="$(jq -r '.source.path // empty' "$manifest")"
    [[ -d "$source" ]] || die "Source folder is unavailable: $source"
    archive="$GAME_ROOT/$id/game-v1.tar.zst"
    sha="$archive.sha256"
    unpacked="$(du -sB1 "$source" | awk '{print $1}')"
    printf 'Packaging %s: %s\n' "$id" "$(numfmt --to=iec "$unpacked")"
    if command -v pv >/dev/null 2>&1; then
        tar -C "$source" -cf - . | pv -s "$unpacked" -pterb | zstd -q -f -T0 -o "$archive"
    else
        tar -C "$source" -cf - . | zstd -q -f -T0 -o "$archive"
    fi
    sha256sum "$archive" > "$sha"
    parts_dir="$GAME_ROOT/$id/.parts-v1"
    python3 - "$archive" "$parts_dir" <<'PY_SPLIT'
from pathlib import Path
import shutil, sys
source, dest = Path(sys.argv[1]), Path(sys.argv[2])
if dest.exists():
    shutil.rmtree(dest)
dest.mkdir(parents=True)
with source.open('rb') as inp:
    index = 0
    while True:
        data = inp.read(256 * 1024 * 1024)
        if not data:
            break
        (dest / f'part-{index:05d}').write_bytes(data)
        index += 1
PY_SPLIT
    python3 "$CLIENT_DIR/package_publish.py" "$manifest" "$archive" "$parts_dir" "$unpacked" ||
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
    local id="${1:-}" manifest exe source
    valid_game_id "$id" || die "Usage: vastgame game validate <id>"
    manifest="$(game_manifest "$id")"
    [[ -f "$manifest" ]] || die "Unknown game: $id"
    jq -e --arg id "$id" '
      .schema == 1 and .id == $id and (.name|type)=="string" and
      (.game.executable|type)=="string" and (.game.executable|length)>0 and
      ((.game.executable|startswith("/"))|not) and ((.game.executable|contains(".."))|not)
    ' "$manifest" >/dev/null || die "Invalid manifest: $id"
    exe="$(jq -r '.game.executable' "$manifest")"
    source="$(jq -r '.source.path // empty' "$manifest")"
    [[ -n "$source" && -f "$source/$exe" ]] || die "Executable missing from source: $source/$exe"
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


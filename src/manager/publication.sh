publish_runtime() {
    local archive="$STATEDIR/runtime.zip" gid manifest
    RUNTIME_SHA="$(python3 - "$RUNTIME_DIR" "$archive" <<'PY_RUNTIME_BUNDLE'
from pathlib import Path
import hashlib, sys, zipfile
root, dest = map(Path, sys.argv[1:])
with zipfile.ZipFile(dest, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(root.iterdir()):
        if p.suffix in ('.py', '.sh'):
            info = zipfile.ZipInfo(p.name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, p.read_bytes())
print(hashlib.sha256(dest.read_bytes()).hexdigest())
PY_RUNTIME_BUNDLE
)" || die "Cannot build runtime bundle"
    rclone copyto "$archive" "gdrive:VastGaming/system/v1/runtime/$RUNTIME_SHA.zip" --immutable --checksum --no-update-modtime --retries 3 || die "Runtime upload failed before VM rental"
    rclone copyto "gdrive:VastGaming/system/v1/runtime/$RUNTIME_SHA.zip" "$archive.verify" --retries 3 || die "Runtime readback failed before VM rental"
    [[ "$(sha256sum "$archive.verify" | cut -d ' ' -f 1)" == "$RUNTIME_SHA" ]] || die "Runtime readback checksum failed"
    rm -f "$archive.verify"
    # The bootstrap reads this mutable metadata from Drive. Publish local save
    # discovery/settings without rebuilding or touching immutable game binaries.
    gid="$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)"
    if [[ -n "$gid" ]]; then
        valid_game_id "$gid" || die "Invalid selected game ID"
        manifest="$(game_manifest "$gid")"
        # Windows imports intentionally omit the original Linux source folder.
        # Validate launch/state metadata, not a source EXE that need not exist here.
        PYTHONPATH="$RUNTIME_DIR" python3 - "$manifest" "$gid" <<'PY_GAME_METADATA' || die "Invalid game metadata; no VM rented"
import json, sys
from pathlib import Path
from game_session import validate
from game_state import state_entries
m = validate(json.loads(Path(sys.argv[1]).read_text()))
if m['id'] != sys.argv[2] or not m.get('package', {}).get('archive'):
    raise ValueError('Selected game is not packaged or has an incorrect ID')
for kind in ('saves', 'configs', 'shaders'):
    state_entries(m, '/nonexistent-vastgame-validation', kind)
PY_GAME_METADATA
        GAME_MANIFEST_SHA="$(sha256sum "$manifest" | cut -d ' ' -f 1)"
        GAME_MANIFEST_PATH="games/$gid/manifests/$GAME_MANIFEST_SHA.json"
        export GAME_MANIFEST_PATH GAME_MANIFEST_SHA
        rclone copyto "$manifest" "$REMOTE_ROOT/$GAME_MANIFEST_PATH" --immutable --checksum --no-update-modtime --retries 3 ||
            die "Game metadata upload failed before VM rental"
        rclone copyto "$REMOTE_ROOT/$GAME_MANIFEST_PATH" "$archive.manifest.verify" --retries 3 ||
            die "Game metadata readback failed before VM rental"
        cmp -s "$manifest" "$archive.manifest.verify" || die "Game metadata readback differs; no VM rented"
        rm -f "$archive.manifest.verify"
    fi
}

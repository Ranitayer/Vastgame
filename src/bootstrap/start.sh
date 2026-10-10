#!/bin/bash
set -Eeuo pipefail

LOG=/var/log/vast-gaming-bootstrap.log
exec > >(tee "$LOG") 2>&1

fail() {
  echo "[VASTGAME] ERROR: $*"
  if declare -F progress_set >/dev/null; then
    # Keep the first concrete failure when worker/join traps add a summary.
    [ -s /var/lib/vast-gaming/status/error.json ] || progress_set error error "$*" || true
  fi
  exit 1
}

bootstrap_failure() {
  local code="$1" line="$2" command="$3" source="$4"
  # Log the command name and source location, never expanded credentials/arguments.
  command="${command%% *}"
  [[ "$command" =~ ^[a-zA-Z0-9_./:-]+$ ]] || command='shell expression'
  echo "[VASTGAME] FAILURE: source=$source line=$line exit=$code command=$command"
  fail "Bootstrap command failed at $source:$line (exit $code); see preceding output"
}

BOOT_RCLONE_CONFIG_B64="${RCLONE_CONFIG_B64:-}"
BOOT_TS_AUTHKEY="${TS_AUTHKEY:-}"


CORE_REMOTE="gdrive:VastGaming/system/v1/vastgame-core-v1.tar.zst"
CORE_SHA_REMOTE="gdrive:VastGaming/system/v1/vastgame-core-v1.tar.zst.sha256"

GOW_REMOTE="gdrive:VastGaming/system/v1/gow-images-v1.tar.zst"
GOW_SHA_REMOTE="gdrive:VastGaming/system/v1/gow-images-v1.tar.zst.sha256"


CORE_ARCHIVE=/tmp/vastgame-core-v1.tar.zst
CORE_SHA=/tmp/vastgame-core-v1.tar.zst.sha256

GOW_ARCHIVE=/tmp/gow-images-v1.tar.zst
GOW_SHA=/tmp/gow-images-v1.tar.zst.sha256
GAME_ID="${VASTGAME_GAME_ID:-}"

# Template environment is available before checking a minimal VM's dependencies.
if [ -r /etc/environment ]; then
  set +u
  source /etc/environment
  set -u
fi
# Publish cancellation evidence before dependency installation can fail.
mkdir -p /var/lib/vast-gaming/status /srv/gaming/profiles
[[ "${VASTGAME_LAUNCH_LABEL:-}" =~ ^vastgame-[0-9]+$ ]] || fail "Invalid VM launch identity"
[[ "$GAME_ID" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || fail "Invalid game identity"
printf '%s\n' "$VASTGAME_LAUNCH_LABEL" > /var/lib/vast-gaming/status/instance-label
printf '%s\n' "$GAME_ID" > /var/lib/vast-gaming/status/game-id
# This bootstrap only starts a guarded runtime; cancellation stays durable during restores.
touch /var/lib/vast-gaming/status/bootstrap-launch-guard-v1
if [[ -e /var/lib/vast-gaming/status/stopping ]]; then
  echo "[VASTGAME] Startup cancelled; game launch blocked"
  exit 0
fi
if [ "${VASTGAME_TEMPLATE_PROFILE:-}" = core-v1 ]; then
  declare -F prepare_core_vm >/dev/null || fail 'Core VM setup missing from startup transport'
  trap 'bootstrap_failure "$?" "$LINENO" "$BASH_COMMAND" "${BASH_SOURCE[0]}"' ERR
  prepare_core_vm
fi

mkdir -p \
  /etc/rclone \
  /etc/wolf \
  /var/run/wolf \
  /var/lib/vast-gaming/status \
  /var/lib/tailscale \
  /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}

for x in curl tar gzip base64 flock sed python3 zstd sha256sum jq timeout; do
  command -v "$x" >/dev/null || fail "$x missing"
done

# Small, atomic status records; parallel restores have separate task files.
PROGRESS_HELPER=/tmp/vastgame-progress.py
cat >"$PROGRESS_HELPER" <<'PY_PROGRESS'
import hashlib, http.server, json, os, pathlib, sys, time

root = pathlib.Path(os.environ.get("VASTGAME_STATUS_DIR", "/var/lib/vast-gaming/status"))
root.mkdir(parents=True, exist_ok=True)
mode, key = sys.argv[1:3]

def write(action, state="running", **metrics):
    data = dict(action=action, state=state, updated=time.time(), **metrics)
    dest = root / (key + ".json")
    tmp = root / (key + "." + str(os.getpid()) + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(dest)

if mode == "set":
    write(sys.argv[4], sys.argv[3])
elif mode == "serve":
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/progress.json":
                return super().do_GET()
            tasks = {}
            for name in ("phase", "error", "core", "state", "identity", "game", "images", "setup", "proton", "dx12", "prefix"):
                try:
                    tasks[name] = json.loads((root / (name + ".json")).read_text())
                except (OSError, ValueError):
                    pass
            body = json.dumps(dict(version=1, tasks=tasks)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    os.chdir(root)
    http.server.ThreadingHTTPServer((key, 48199), Handler).serve_forever()
elif mode == "download":
    for line in sys.stdin:
        print(line, end="", flush=True)
        try:
            stats = json.loads(line).get("stats", {})
            if stats.get("totalBytes", 0) > 0:
                write("Downloading", bytes=stats.get("bytes", 0), total=stats["totalBytes"],
                      speed=stats.get("speed", 0), eta=stats.get("eta"))
            else:
                write("Downloading; waiting for total size")
        except (ValueError, TypeError, AttributeError):
            pass
elif mode in ("verify", "stream"):
    file = pathlib.Path(sys.argv[3])
    total, count = file.stat().st_size, 0
    start = last = time.monotonic()
    action = "Verifying SHA256" if mode == "verify" else "Extracting archive"
    write(action, bytes=0, total=total)
    digest = hashlib.sha256()
    with file.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            if mode == "verify":
                digest.update(chunk)
            else:
                sys.stdout.buffer.write(chunk)
            count += len(chunk)
            now = time.monotonic()
            if now - last >= 1:
                speed = count / max(now - start, .001)
                write(action, bytes=count, total=total, speed=speed, eta=(total-count)/speed)
                last = now
    if mode == "verify":
        expected = pathlib.Path(sys.argv[4]).read_text().split()[0].lower()
        if len(expected) != 64 or digest.hexdigest() != expected:
            write("SHA256 mismatch", "error")
            sys.exit(1)
        write("Checksum verified")
    else:
        sys.stdout.buffer.flush()
        write("Finishing extraction / loading")
PY_PROGRESS
progress_set() { python3 "$PROGRESS_HELPER" set "$@"; }
progress_phase() {
  echo "[VASTGAME] PHASE=$1"
  progress_set phase running "$1"
}
progress_download() {
  local key="$1"
  shift
  progress_set "$key" running "Starting download"
  if "${RCLONE[@]}" copyto "$@" --stats 1s --stats-log-level NOTICE --use-json-log 2>&1 |
     python3 "$PROGRESS_HELPER" download "$key"
  then
    progress_set "$key" running "Download complete"
  else
    progress_set "$key" error "Download failed; see bootstrap log"
    return 1
  fi
}
progress_verify() { python3 "$PROGRESS_HELPER" verify "$@"; }
progress_stream() { python3 "$PROGRESS_HELPER" stream "$@"; }
rm -f /var/lib/vast-gaming/status/{phase,error,core,state,identity,game,images,setup,proton,dx12,prefix}.json
for task in core state identity game images setup proton dx12 prefix; do
  progress_set "$task" pending "Waiting"
done
trap 'bootstrap_failure "$?" "$LINENO" "$BASH_COMMAND" "${BASH_SOURCE[0]}"' ERR


mkdir -p /opt/vastgame

# Check Python compatibility before downloading runtime images or games.
if ! python3 -c "import importlib.util; assert any(importlib.util.find_spec(n) for n in ('tomllib', 'tomli', 'pip._vendor.tomli'))"; then
  timeout 120 apt-get update -qq &&
    timeout 180 apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends python3-tomli ||
    fail "TOML parser installation failed before downloads"
  python3 -c "import importlib.util; assert any(importlib.util.find_spec(n) for n in ('tomllib', 'tomli', 'pip._vendor.tomli'))" ||
    fail "Wolf Python preflight failed"
fi

progress_phase BOOT

# ----------------------------------------------------------------------
# Tailscale
# ----------------------------------------------------------------------

[ -r /etc/environment ] && {
  set +u
  source /etc/environment 2>/dev/null || true
  set -u
}

TS_AUTHKEY="${TS_AUTHKEY:-$BOOT_TS_AUTHKEY}"
[ -n "${TS_AUTHKEY:-}" ] || fail "TS_AUTHKEY missing"

if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

hostnamectl set-hostname vast-gaming || true
systemctl enable --now tailscaled

TSIP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"

if [ -z "$TSIP" ]; then
  echo "[VASTGAME] Authenticating Tailscale..."

  timeout 60s tailscale up \
    --auth-key="$TS_AUTHKEY" \
    --hostname=vast-gaming \
    --accept-dns=false \
    --ssh \
    || fail "Tailscale login failed"
fi

for i in $(seq 1 30); do
  TSIP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
  [ -n "$TSIP" ] && break
  sleep 2
done

[ -n "$TSIP" ] || fail "No Tailscale IP after login"

tailscale set \
  --hostname=vast-gaming \
  --accept-dns=false \
  --ssh || true

echo "[VASTGAME] Tailscale online: $TSIP"
ln -sf "$LOG" /var/lib/vast-gaming/status/bootstrap.log
pkill -f 'python3 -m http.server 48199' >/dev/null 2>&1 || true
pkill -f '^python3 /tmp/vastgame-progress.py serve ' >/dev/null 2>&1 || true
nohup python3 "$PROGRESS_HELPER" serve "$TSIP" \
  >/var/log/vast-gaming-status-http.log 2>&1 &

# ----------------------------------------------------------------------
# rclone / Google Drive
# ----------------------------------------------------------------------

for i in $(seq 1 60); do
  [ -r /etc/environment ] && {
    set +u
    source /etc/environment 2>/dev/null || true
    set -u
  }

  [ -z "${RCLONE_CONFIG_B64:-}" ] &&
    RCLONE_CONFIG_B64="$BOOT_RCLONE_CONFIG_B64"

  [ -n "${RCLONE_CONFIG_B64:-}" ] && break

  sleep 2
done

[ -n "${RCLONE_CONFIG_B64:-}" ] ||
  fail "RCLONE_CONFIG_B64 missing"

if ! command -v rclone >/dev/null; then
  curl -fsSL https://rclone.org/install.sh | bash
fi

RCLONE_B64="$(
  printf '%s' "$RCLONE_CONFIG_B64" |
  tr -d '\r\n\t '
)"

RCLONE_B64="${RCLONE_B64#\"}"
RCLONE_B64="${RCLONE_B64%\"}"
RCLONE_B64="${RCLONE_B64#<}"
RCLONE_B64="${RCLONE_B64%>}"

printf '%s' "$RCLONE_B64" |
  base64 -d > /etc/rclone/rclone.conf ||
  fail "rclone config decode failed"

chmod 600 /etc/rclone/rclone.conf

RCLONE=(rclone --config /etc/rclone/rclone.conf)

"${RCLONE[@]}" lsd gdrive:VastGaming >/dev/null ||
  fail "Google Drive failed"

# Runtime is immutable and pinned by SHA256, keeping Vast's startup payload small.
RUNTIME_SHA="__VASTGAME_RUNTIME_SHA__"
[[ "$RUNTIME_SHA" =~ ^[a-f0-9]{64}$ ]] || fail "Missing pinned runtime digest; start through vastgame"
"${RCLONE[@]}" copyto "gdrive:VastGaming/system/v1/runtime/$RUNTIME_SHA.zip" /tmp/vastgame-runtime.zip || fail "Runtime download failed"
printf '%s  %s\n' "$RUNTIME_SHA" /tmp/vastgame-runtime.zip | sha256sum -c - || fail "Runtime checksum failed"
python3 - <<'PY_RUNTIME'
from pathlib import Path
import zipfile
with zipfile.ZipFile('/tmp/vastgame-runtime.zip') as archive:
    for name in archive.namelist():
        if '/' in name or not name.endswith(('.py', '.sh')):
            raise ValueError('Unsafe runtime member')
        Path('/opt/vastgame', name).write_bytes(archive.read(name))
PY_RUNTIME
chmod 755 /opt/vastgame/launch-game.sh
# This runtime blocks new launches and records game activity before starting it.
touch /var/lib/vast-gaming/status/launch-guard-v1
python3 -c "import sys; sys.path.insert(0, '/opt/vastgame'); import configure_wolf, game_state" || fail "Runtime Python preflight failed"

# ----------------------------------------------------------------------
# Core v1 — only ~13 MB
# ----------------------------------------------------------------------

progress_phase CORE
echo "[VASTGAME] Restoring core runtime"

rm -f "$CORE_ARCHIVE" "$CORE_SHA"

progress_download core \
  "$CORE_REMOTE" \
  "$CORE_ARCHIVE" \
  --retries 3 \
  --low-level-retries 10

"${RCLONE[@]}" copyto \
  "$CORE_SHA_REMOTE" \
  "$CORE_SHA" \
  --retries 3 \
  --low-level-retries 10

progress_verify core "$CORE_ARCHIVE" "$CORE_SHA" || fail "core SHA256 verification failed"

rm -rf /opt/vastgame-core-v1

progress_stream core "$CORE_ARCHIVE" | zstd -dc |
  tar -C /opt -xf - ||
  fail "core extraction failed"

[ -x /opt/vastgame-core-v1/install.sh ] ||
  fail "core installer missing"

progress_phase RESTORE
mkdir -p /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}
progress_set state pending "Waiting for game state"

game_restore() {
  [ -n "$GAME_ID" ] || { progress_set game done "No game selected"; return 0; }
  case "$GAME_ID" in
    *[!a-z0-9._-]*) fail "Invalid game id" ;;
  esac
  local archive="/tmp/vastgame-${GAME_ID}.tar.zst"
  local checksum="/tmp/vastgame-${GAME_ID}.tar.zst.sha256"
  local manifest="/srv/gaming/profiles/${GAME_ID}/manifest.json"
  local package_path
  package_path="$(jq -r '.package.archive' "$manifest")"
  [[ "$package_path" =~ ^games/$GAME_ID/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$ ]] || fail "Unsafe game package path"
  local remote="gdrive:VastGaming/$package_path"
  "${RCLONE[@]}" copyto "gdrive:VastGaming/$(jq -r '.package.checksum' "$manifest")" "$checksum" --retries 3 --low-level-retries 10 || fail "Game checksum download failed"
  parts_count="$(jq '.package.parts // [] | length' "$manifest")"
  if (( parts_count > 0 )); then
    restore_error="$(python3 /opt/vastgame/multipart_restore.py "$manifest" "$checksum" 2>&1)" || fail "$restore_error"
  else
    mkdir -p "/srv/gaming/games/${GAME_ID}.installing"
    progress_download game "$remote" "$archive" --retries 3 --low-level-retries 10 || fail "Game package download failed"
    progress_verify game "$archive" "$checksum" || fail "Game package checksum failed"
    progress_stream game "$archive" | zstd -dc | tar -C "/srv/gaming/games/${GAME_ID}.installing" -xf - || fail "Game package extraction failed"
    python3 - "$manifest" <<'PY_CHECK_LEGACY'
import json, sys
from pathlib import Path
sys.path.insert(0, '/opt/vastgame')
from game_session import validate
m = validate(json.loads(Path(sys.argv[1]).read_text()))
root = Path('/srv/gaming/games') / (m['id'] + '.installing')
for field, directory in [('executable', False), ('working_dir', True)]:
    path = (root / m['game'].get(field, '')).resolve()
    if not path.is_relative_to(root.resolve()) or not (path.is_dir() if directory else path.is_file()):
        raise ValueError('Restored ' + field + ' missing or outside game directory')
PY_CHECK_LEGACY
    rm -rf "/srv/gaming/games/${GAME_ID}"
    mv "/srv/gaming/games/${GAME_ID}.installing" "/srv/gaming/games/${GAME_ID}"
  fi
  dlss="$(python3 - "$manifest" <<'PY_VALIDATE_GAME'
import json, sys
sys.path.insert(0, '/opt/vastgame')
from game_session import validate
from compatibility import nvidia_ngx_enabled
from pathlib import Path
m = validate(json.loads(Path(sys.argv[1]).read_text()))
root = Path('/srv/gaming/games') / m['id']
exe = (root / m['game']['executable']).resolve()
if not exe.is_relative_to(root.resolve()) or not exe.is_file():
    raise ValueError('Restored executable missing or outside the game directory')
print(str(nvidia_ngx_enabled(m)).lower())
PY_VALIDATE_GAME
)" || fail "Game manifest/executable validation failed"
  rm -f "$archive" "$checksum"
  if (( parts_count == 0 )); then progress_set game done "Game package ready: $GAME_ID"; fi
}

# Reassert immutable runtime after restoring state.
echo "[VASTGAME] Installing core runtime"
progress_set core running "Installing runtime"

/opt/vastgame-core-v1/install.sh ||
  fail "core runtime installation failed"
progress_set core done "Runtime ready"

rm -f "$CORE_ARCHIVE" "$CORE_SHA"

nvidia-smi >/dev/null ||
  fail "Host GPU failed"

docker info >/dev/null 2>&1 ||
  fail "Docker unavailable"

systemctl disable --now vast-gaming-backup.timer vast-gaming-backup.service vast-gaming-final-backup.service >/dev/null 2>&1 || true
rm -f /var/lib/vast-gaming/last-backup

# ----------------------------------------------------------------------
# Parallel stage:
#   A = game download, verification, and extraction in parallel
#   B = Wolf/Lutris image restore if not already available
# ----------------------------------------------------------------------

gow_restore() {
  if docker image inspect \
       ghcr.io/games-on-whales/wolf:stable \
       >/dev/null 2>&1 &&
     docker image inspect \
       ghcr.io/games-on-whales/lutris:edge \
       >/dev/null 2>&1
  then
    progress_set images done "Images already cached"
    echo "[VASTGAME] GOW images already available"
    return 0
  fi

  echo "[VASTGAME] GOW_SYNC=START"

  rm -f "$GOW_ARCHIVE" "$GOW_SHA"

  progress_download images \
    "$GOW_REMOTE" \
    "$GOW_ARCHIVE" \
    --retries 3 \
    --low-level-retries 10

  "${RCLONE[@]}" copyto \
    "$GOW_SHA_REMOTE" \
    "$GOW_SHA" \
    --retries 3 \
    --low-level-retries 10

  progress_verify images "$GOW_ARCHIVE" "$GOW_SHA" || return 1

  progress_stream images "$GOW_ARCHIVE" | zstd -dc |
    docker load ||
    return 1

  docker image inspect \
    ghcr.io/games-on-whales/wolf:stable \
    >/dev/null 2>&1 ||
    return 1

  docker image inspect \
    ghcr.io/games-on-whales/lutris:edge \
    >/dev/null 2>&1 ||
    return 1

  rm -f "$GOW_ARCHIVE" "$GOW_SHA"

  progress_set images done "Wolf / Lutris images ready"
  echo "[VASTGAME] GOW_SYNC=DONE"
}


# ------------------------------------------------------------
# Stable Wolf / Moonlight identity
# ------------------------------------------------------------
WOLF_IDENTITY_REMOTE="gdrive:VastGaming/system/v1/wolf-identity-v1.tar.gz"
WOLF_IDENTITY_TMP="/tmp/wolf-identity-v1.tar.gz"
WOLF_IDENTITY_DIR="/tmp/wolf-identity-v1"

echo "[VASTGAME] Restoring stable Wolf/Moonlight identity"

rm -rf "$WOLF_IDENTITY_DIR" "$WOLF_IDENTITY_TMP"
mkdir -p "$WOLF_IDENTITY_DIR"

progress_download identity \
  "$WOLF_IDENTITY_REMOTE" \
  "$WOLF_IDENTITY_TMP" \
  || fail "Could not restore Wolf identity snapshot"

tar -xzf "$WOLF_IDENTITY_TMP" \
  -C "$WOLF_IDENTITY_DIR" \
  || fail "Could not extract Wolf identity snapshot"

for f in config.toml cert.pem key.pem; do
  [ -s "$WOLF_IDENTITY_DIR/$f" ] \
    || fail "Wolf identity snapshot missing $f"
done

PAIR_COUNT="$(
  grep -c '^\[\[paired_clients\]\]' \
    "$WOLF_IDENTITY_DIR/config.toml" \
    || true
)"

[ "$PAIR_COUNT" -eq 1 ] \
  || fail "Wolf identity snapshot does not contain exactly one paired client"

mkdir -p /etc/wolf/cfg

install -m 0644 \
  "$WOLF_IDENTITY_DIR/config.toml" \
  /etc/wolf/cfg/config.toml

install -m 0644 \
  "$WOLF_IDENTITY_DIR/cert.pem" \
  /etc/wolf/cfg/cert.pem

install -m 0600 \
  "$WOLF_IDENTITY_DIR/key.pem" \
  /etc/wolf/cfg/key.pem

rm -rf "$WOLF_IDENTITY_DIR" "$WOLF_IDENTITY_TMP"

echo "[VASTGAME] Wolf identity restored: one paired client"
progress_set identity done "Pairing restored"

prepare_game_environment() {
# Fix the prefix ownership problem permanently.
RETRO_UID="$(
  docker run \
    --rm \
    --entrypoint id \
    ghcr.io/games-on-whales/lutris:edge \
    -u retro 2>/dev/null |
  tail -n1 || true
)"

RETRO_GID="$(
  docker run \
    --rm \
    --entrypoint id \
    ghcr.io/games-on-whales/lutris:edge \
    -g retro 2>/dev/null |
  tail -n1 || true
)"

[[ "$RETRO_UID" =~ ^[0-9]+$ ]] || RETRO_UID=1000
[[ "$RETRO_GID" =~ ^[0-9]+$ ]] || RETRO_GID=1000

  # All writable preparation mounts must be ready before the non-root container.
  # Leave game extraction/staging alone while its worker is running.
  mkdir -p "/srv/gaming/profiles/$GAME_ID/logs" "/srv/gaming/prefixes/$GAME_ID" "/srv/gaming/lutris/$GAME_ID" "/srv/gaming/shaders/$GAME_ID/cache"
  chown -R "$RETRO_UID:$RETRO_GID" "/srv/gaming/profiles/$GAME_ID" "/srv/gaming/prefixes/$GAME_ID" "/srv/gaming/lutris/$GAME_ID" "/srv/gaming/shaders/$GAME_ID" /var/lib/vast-gaming/status
  chmod -R u+rwX "/srv/gaming/profiles/$GAME_ID" "/srv/gaming/prefixes/$GAME_ID" "/srv/gaming/lutris/$GAME_ID" "/srv/gaming/shaders/$GAME_ID" /var/lib/vast-gaming/status
  mkdir -p "/srv/gaming/lutris/$GAME_ID/home"/{.local,.config,.cache}
  chown -R "$RETRO_UID:$RETRO_GID" "/srv/gaming/lutris/$GAME_ID"
  progress_set proton running "Preparing Proton"
  preparation_log="/srv/gaming/profiles/$GAME_ID/logs/preparation.log"
  # Add only the setup display dependencies; inherit the exact cached Lutris base.
  # Docker's layer cache reuses this image on repeated setup attempts.
  if ! timeout --foreground 300 docker build --network=host -t vastgame-preparation:v1 - > "$preparation_log" 2>&1 <<'PREPARATION_IMAGE'
FROM ghcr.io/games-on-whales/lutris:edge
USER root
RUN (apt-get -o Acquire::Retries=3 update || (. /etc/os-release; curl -fsS --connect-timeout 10 --max-time 30 "https://old-releases.ubuntu.com/ubuntu/dists/$VERSION_CODENAME/Release" -o /dev/null && sed -i -E 's#https?://(archive|security).ubuntu.com/ubuntu/?#https://old-releases.ubuntu.com/ubuntu/#g' /etc/apt/sources.list.d/ubuntu.sources && apt-get -o Acquire::Retries=3 update)) && apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends xvfb xauth mangohud && (if apt-cache show mangohud:i386 2>/dev/null | grep -q '^Package:'; then apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends mangohud:i386; fi) && rm -rf /var/lib/apt/lists/*
PREPARATION_IMAGE
  then
    tail -n 60 "$preparation_log" || true
    fail "Preparation display installation failed; see $preparation_log"
  fi
  if ! timeout --foreground 2400 docker run --rm --name "vastgame-prepare-$GAME_ID" \
    --runtime=nvidia --gpus all --ipc=host \
    --cap-add SYS_ADMIN --cap-add SYS_NICE \
    --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --ulimit nofile=524288:524288 --device /dev/dri \
    --user "$RETRO_UID:$RETRO_GID" -e HOME=/home/retro -e USER=retro -e UNAME=retro \
    -e PYTHONPATH=/opt/vastgame -e NVIDIA_DRIVER_CAPABILITIES=all -e NVIDIA_VISIBLE_DEVICES=all \
    -v "/srv/gaming/lutris/$GAME_ID:/var/lutris:rw" \
    -v "/srv/gaming/lutris/$GAME_ID/home:/home/retro:rw" \
    -v /srv/gaming/games:/games:rw -v /srv/gaming/profiles:/profiles:rw \
    -v /srv/gaming/prefixes:/prefixes:rw -v /srv/gaming/shaders:/shaders:rw \
    -v /opt/vastgame:/opt/vastgame:ro -v /var/lib/vast-gaming/status:/vastgame-status:rw \
    --entrypoint /bin/bash vastgame-preparation:v1 \
    /opt/vastgame/prepare-game.sh "/profiles/$GAME_ID/manifest.json" >> "$preparation_log" 2>&1
  then
    docker rm -f "vastgame-prepare-$GAME_ID" >/dev/null 2>&1 || true
    tail -n 60 "$preparation_log" || true
    fail "Game environment preparation failed; see $preparation_log"
  fi
  chown -R "$RETRO_UID:$RETRO_GID" "/srv/gaming/lutris/$GAME_ID" "/srv/gaming/prefixes/$GAME_ID" "/srv/gaming/profiles/$GAME_ID"
}

if [ -n "$GAME_ID" ]; then
  [[ "$GAME_ID" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || fail "Invalid game id"
  manifest="/srv/gaming/profiles/$GAME_ID/manifest.json"
  mkdir -p "$(dirname "$manifest")"
  "${RCLONE[@]}" copyto "gdrive:VastGaming/${VASTGAME_GAME_MANIFEST:-games/$GAME_ID/v1/manifest.json}" "$manifest" --retries 3 --low-level-retries 10 || fail "Game manifest download failed"
  if [[ -n "${VASTGAME_GAME_MANIFEST_SHA:-}" ]]; then
    [[ "$(sha256sum "$manifest" | cut -d ' ' -f 1)" == "$VASTGAME_GAME_MANIFEST_SHA" ]] || fail "Launch manifest integrity mismatch"
  fi
  PYTHONPATH=/opt/vastgame python3 - "$manifest" "$GAME_ID" <<'PY_MANIFEST'
import json, sys
from pathlib import Path
from game_session import validate
m = validate(json.loads(Path(sys.argv[1]).read_text()))
if m['id'] != sys.argv[2]:
    raise ValueError('Game manifest ID mismatch')
PY_MANIFEST
fi

progress_phase DRIVE

(
  trap 'rc=$?; if (( rc != 0 )); then fail "Game restore failed (exit $rc)"; fi' EXIT
  game_restore
) &
GAME_PID=$!

(
  trap 'rc=$?; if (( rc != 0 )); then fail "Wolf / Lutris restore failed (exit $rc)"; fi' EXIT
  gow_restore
) &
GOW_PID=$!

GOW_OK=0
GAME_OK=0

wait "$GOW_PID" && GOW_OK=1 || true
[ "$GOW_OK" = 1 ] || fail "Wolf/Lutris image restore failed"
# Proton, DX12 and prefix creation overlap the remaining game download/extraction.
if [ -n "$GAME_ID" ]; then
  prepare_game_environment
fi
wait "$GAME_PID" && GAME_OK=1 || true

[ "$GAME_OK" = 1 ] || fail "Game restore failed"

[ "$GOW_OK" = 1 ] ||
  fail "Wolf/Lutris image restore failed"

# ----------------------------------------------------------------------
# Docker / NVIDIA validation without pulling another CUDA image.
# ----------------------------------------------------------------------

progress_phase DOCKER
progress_set setup running "Validating GPU and configuring Lutris"

if declare -F prepare_core_gpu_runtime >/dev/null; then prepare_core_gpu_runtime || fail "GPU driver/CDI validation failed"; fi
docker run \
  --rm \
  --runtime=nvidia \
  --gpus all \
  --entrypoint nvidia-smi \
  ghcr.io/games-on-whales/wolf:stable \
  >/dev/null ||
  fail "Docker GPU failed"

# ----------------------------------------------------------------------
# Persistent Lutris configuration
# ----------------------------------------------------------------------

CFG=/etc/wolf/cfg/config.toml

[ -f "$CFG" ] ||
  fail "Wolf config missing after state restore"

# Direct Moonlight app; preserve the identity archive and original Wolf UI.
if [ -n "$GAME_ID" ]; then
  mkdir -p "/srv/gaming/lutris/$GAME_ID" "/srv/gaming/profiles/$GAME_ID/logs" "/srv/gaming/prefixes/$GAME_ID"
  wolf_error="$(python3 /opt/vastgame/configure_wolf.py "$CFG" "/srv/gaming/profiles/$GAME_ID/manifest.json" /var/lib/vast-gaming/status 2>&1)" || fail "Direct Wolf app configuration failed: $wolf_error"
  # Check the cached image supports the startup hook before renting time on a broken session.
  docker run --rm -v /opt/vastgame:/opt/vastgame:ro -e PYTHONPATH=/opt/vastgame --entrypoint /bin/bash vastgame-preparation:v1 -c \
    'command -v mangohud && grep -q startup.d /opt/gow/startup-app.sh && grep -q LUTRIS_ARGS /opt/gow/startup-app.sh && command -v lutris && /usr/bin/python3 -c "from game_session import lutris_api; lutris_api()"' || fail "Lutris image missing startup hook/API"
fi

# Game publication and setup must both finish before state or Wolf can launch.
mkdir -p /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}
chown -R "${RETRO_UID:-1000}:${RETRO_GID:-1000}" /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}
chmod -R u+rwX /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}
progress_set setup done "Lutris directories ready"
if [ -n "$GAME_ID" ]; then
  progress_set state running "Restoring verified saves, configs and shaders"
  python3 /opt/vastgame/game_state.py restore "$GAME_ID" --config /etc/rclone/rclone.conf || fail "Game state restore failed"
  progress_set state done "Game state ready"
  manifest="/srv/gaming/profiles/$GAME_ID/manifest.json"
  dlss="$(python3 - "$manifest" <<'PY_NGX'
import json, sys
sys.path.insert(0, '/opt/vastgame')
from compatibility import nvidia_ngx_enabled
print(str(nvidia_ngx_enabled(json.load(open(sys.argv[1])))).lower())
PY_NGX
)" || fail "NVIDIA profile validation failed"
  if [[ "$dlss" == true ]]; then
    ngx_dir="/srv/gaming/prefixes/${GAME_ID}/drive_c/windows/system32"
    mkdir -p "$ngx_dir"
    for dll in nvngx.dll _nvngx.dll; do
      driver_dll="$(find -L /usr/lib /usr/lib64 -type f -path "*/nvidia/wine/$dll" -print -quit 2>/dev/null || true)"
      [ -s "$driver_dll" ] || fail "DLSS requested but NVIDIA $dll is missing on this VM"
      install -m 0644 "$driver_dll" "$ngx_dir/$dll"
    done
    echo "[VASTGAME] NVIDIA compatibility ready; graphics settings remain controlled in-game"
  fi

else
  for task in proton dx12 prefix; do progress_set "$task" done "No game selected"; done
  progress_set state done "Generic empty game state"
fi


# ----------------------------------------------------------------------
# Wolf host devices
# ----------------------------------------------------------------------

modprobe uinput || true
modprobe uhid || true
modprobe nvidia_drm modeset=1 || true

curl -fsSL \
  https://raw.githubusercontent.com/games-on-whales/wolf/stable/85-wolf.rules \
  -o /etc/udev/rules.d/85-wolf.rules

udevadm control --reload-rules || true
udevadm trigger || true

[ -e /dev/uinput ] ||
  fail "/dev/uinput missing"

[ -e /dev/uhid ] ||
  fail "/dev/uhid missing"

[ -d /dev/dri ] ||
  fail "/dev/dri missing"

[ "$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || true)" = "Y" ] ||
  fail "nvidia_drm modeset disabled"

IFACE="$(
  ip route show default |
  awk '/default/{print $5;exit}'
)"

HOSTMAC="$(
  cat "/sys/class/net/$IFACE/address"
)"

# ----------------------------------------------------------------------
# Wolf
#
# IMPORTANT: no systemctl daemon-reload after this point.
# ----------------------------------------------------------------------


# Generic baseline: shader caches are empty until a game manifest provisions them.
progress_set setup running "Shader cache namespace ready"

# ------------------------------------------------------------
# Wolf config sanity guard
# ------------------------------------------------------------
CFG=/etc/wolf/cfg/config.toml

[ -s "$CFG" ] || fail "Wolf config missing before startup"

# This exact corruption previously broke Wolf.
if grep -Eq \
  'VKD3D_SHADER_CACHE_PATH|DXVK_SHADER_CACHE_PATH' \
  "$CFG"
then
  fail "Shader environment leaked into Wolf config.toml"
fi

cp -a "$CFG" /etc/wolf/cfg/config.toml.pre-vastgame-start

python3 - <<'PYTOML' || fail "Wolf TOML invalid"
import sys
sys.path.insert(0, '/opt/vastgame')
from configure_wolf import tomllib
with open('/etc/wolf/cfg/config.toml', encoding='utf-8') as f:
    tomllib.loads(f.read())
PYTOML

if [[ -e /var/lib/vast-gaming/status/stopping ]]; then
  echo "[VASTGAME] Startup cancelled; game launch blocked"
  exit 0
fi
progress_phase WOLF
progress_set setup running "Starting Wolf streaming server"

progress_set setup running "Testing CUDA conversion and NVIDIA encoding"
timeout 30 docker run --rm --runtime=nvidia --gpus all --entrypoint gst-launch-1.0 ghcr.io/games-on-whales/wolf:stable \
  -q -e videotestsrc num-buffers=10 ! video/x-raw,format=BGRA,width=1920,height=1080 ! cudaupload ! cudaconvertscale ! \
  'video/x-raw(memory:CUDAMemory),format=NV12' ! nvh264enc ! fakesink || fail "CUDA video conversion/encoding failed; see bootstrap log"

docker rm -f wolf >/dev/null 2>&1 || true

docker run -d \
  --name wolf \
  --restart unless-stopped \
  --network=host \
  --runtime=nvidia \
  --gpus all \
  -e WOLF_USE_ZERO_COPY=FALSE \
  -e WOLF_INTERNAL_IP="$TSIP" \
  -e WOLF_INTERNAL_MAC="$HOSTMAC" \
  -e WOLF_SOCKET_PATH=/var/run/wolf/wolf.sock \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -v /etc/wolf:/etc/wolf:rw \
  -v /var/run/wolf:/var/run/wolf:rw \
  -v /var/run/docker.sock:/var/run/docker.sock:rw \
  --device /dev/dri/ \
  --device /dev/uinput \
  --device /dev/uhid \
  -v /dev/:/dev/:rw \
  -v /run/udev:/run/udev:rw \
  --device-cgroup-rule "c 13:* rmw" \
  --device-cgroup-rule "c 226:* rmw" \
  ghcr.io/games-on-whales/wolf:stable

READY=0

for i in $(seq 1 60); do
  if curl -fsS --connect-timeout 2 --max-time 5 \
       http://127.0.0.1:47989/serverinfo \
       >/dev/null 2>&1
  then
    READY=1
    break
  fi

  sleep 2
done

[ "$READY" = 1 ] || {
  docker logs --tail 120 wolf || true
  fail "Wolf server failed"
}

docker exec wolf nvidia-smi >/dev/null 2>&1 || {
  docker logs --tail 120 wolf || true
  fail "Wolf lost GPU access"
}

for i in $(seq 1 30); do
  if [ -S /var/run/wolf/wolf.sock ]; then
    chmod 666 /var/run/wolf/wolf.sock || true
    break
  fi

  sleep 1
done

# READY FIRST.
# Do not block Moonlight behind a huge tar/gzip/upload anymore.
progress_set setup done "Streaming checks passed"
progress_phase READY

touch /var/run/vast-gaming-ready

echo "VAST GAMING READY | vast-gaming | $TSIP"

# Independent checkpoints never stop the game. Changing files are rejected by
# inventory + archive + final recheck; the prior committed snapshot stays intact.
if [ -n "$GAME_ID" ]; then
  cat > /etc/systemd/system/vastgame-checkpoint.service <<EOF
[Unit]
Description=Verified Vastgame game-state checkpoint
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/vastgame/game_state.py backup $GAME_ID --live --instance $VASTGAME_LAUNCH_LABEL --label $VASTGAME_LAUNCH_LABEL --config /etc/rclone/rclone.conf --receipt /srv/gaming/profiles/$GAME_ID/checkpoint-receipt.json
TimeoutStartSec=1800
Nice=10
IOSchedulingClass=idle
EOF
  cat > /etc/systemd/system/vastgame-checkpoint.timer <<'EOF'
[Unit]
Description=Periodic verified Vastgame checkpoints
[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min
[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now vastgame-checkpoint.timer || fail "Periodic checkpoint timer could not start"
fi

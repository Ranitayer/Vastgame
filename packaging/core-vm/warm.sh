#!/usr/bin/env bash
# Run after booting the prepared disk with its own kernel and systemd.
set -Eeuo pipefail
systemctl is-active --quiet docker
docker info >/dev/null
for pair in 'wolf stable' 'lutris edge'; do
  read -r name tag <<<"$pair"
  digest=$(cat "/opt/vastgame-build/$name.image")
  docker pull "$digest"
  docker tag "$digest" "ghcr.io/games-on-whales/$name:$tag"
done
docker build --network=host -t vastgame-preparation:v1 -f /opt/vastgame-build/preparation.Dockerfile /opt/vastgame-build
seed=/opt/vastgame/runtime-seed
mkdir -p "$seed" /opt/vastgame-build/{profiles,prefixes,shaders,status} /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}
uid=$(docker run --rm --runtime=runc --entrypoint id vastgame-preparation:v1 -u retro)
gid=$(docker run --rm --runtime=runc --entrypoint id vastgame-preparation:v1 -g retro)
cat >/opt/vastgame-build/profiles/core-cache.json <<'JSON'
{"schema":1,"id":"core-cache","name":"Runtime build probe","version":"v1","game":{"executable":"cmd.exe","arguments":[]},"runner":{"type":"wine","version":"ge-proton"},"environment":{},"compatibility":{}}
JSON
# Use the real Lutris preparation path to download/validate the runner and DLLs.
# No game executable is launched; cmd.exe only initializes a disposable prefix.
mkdir -p "$seed/home"
chown -R "$uid:$gid" "$seed" /opt/vastgame-build/{profiles,prefixes,shaders,status}
docker run --rm --runtime=runc --network=host --ipc=host --cap-add SYS_ADMIN \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --user "$uid:$gid" -e HOME=/home/retro -e USER=retro -e UNAME=retro -e PYTHONPATH=/opt/vastgame \
  -v "$seed:/var/lutris" -v "$seed/home:/home/retro" \
  -v /srv/gaming/games:/games \
  -v /opt/vastgame-build/profiles:/profiles -v /opt/vastgame-build/prefixes:/prefixes \
  -v /opt/vastgame-build/shaders:/shaders -v /opt/vastgame-build/status:/vastgame-status \
  -v /opt/vastgame-build/runtime:/opt/vastgame:ro \
  --entrypoint /bin/bash vastgame-preparation:v1 /opt/vastgame/prepare-game.sh /profiles/core-cache.json
python3 - "$seed" <<'PY'
import json, shutil, sys
from pathlib import Path
seed=Path(sys.argv[1])
record=json.loads(Path('/opt/vastgame-build/profiles/core-cache/prepared.json').read_text())
env=record['environment']
if not env.get('PROTONPATH','').startswith('/home/retro/'):
    raise SystemExit('Build did not resolve an installed Proton version')
(seed/'runtime-seed.json').write_text(json.dumps(env))
# Keep runtime downloads, not the probe library, configuration, prefix or telemetry.
for path in (seed/'library', seed/'share/pga.db', seed/'share/pga.db-wal', seed/'share/pga.db-shm', seed/'home/.config', seed/'home/.cache', seed/'home/.local/state'):
    if path.is_dir(): shutil.rmtree(path)
    else: path.unlink(missing_ok=True)
PY
# Record the installed package versions and exact frozen runtime inventory.
mkdir -p /usr/share/vastgame
dpkg-query -W > /usr/share/vastgame/core-packages.txt
find "$seed" -type f -exec sha256sum {} + > /usr/share/vastgame/runtime-files.sha256
printf '%s\n' core-image-v1 > /usr/share/vastgame/core-image
rm -rf /opt/vastgame-build /var/lib/apt/lists/*

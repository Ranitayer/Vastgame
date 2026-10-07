#!/usr/bin/env bash
set -Eeuo pipefail
application="$1"
tailscale="$2"
powershell="$3"
shift 3
user=vastgame
export DEBIAN_FRONTEND=noninteractive
bash "$application/prepare-network.sh" "$@"
apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends \
  ca-certificates curl jq util-linux openssh-client iputils-ping pv zstd xz-utils \
  python3 python3-venv python3-pip rclone gawk procps tar gzip coreutils
id "$user" >/dev/null 2>&1 || useradd -m -s /bin/bash "$user"
home="$(getent passwd "$user" | cut -d: -f6)"
mkdir -p "$home/.local/share/vastgame" "$home/.local/bin" "$home/.config/vastgame" "$home/.ssh"
# Archives are built locally from an allowlist, and include no game archives or VM IDs.
tar --no-same-owner -xf "$application/backend.tar" -C "$home"
if [ -f "$application/accounts.tar" ]; then
  tar --no-same-owner --skip-old-files -xf "$application/accounts.tar" -C "$home"
fi
python3 -m venv "$home/.local/share/vastgame/venv"
"$home/.local/share/vastgame/venv/bin/pip" install --disable-pip-version-check 'vastai==1.8.3' 'PyYAML==6.0.3'
cp "$application/run-vastgame.sh" "$home/.local/bin/vastgame"
for name in tailscale moonlight vastgame-native ping; do
  cp "$application/windows-bridge.sh" "$home/.local/bin/$name"
done
python3 - "$home/.config/vastgame/windows.json" "$application" "$tailscale" "$powershell" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(dict(application=sys.argv[2], tailscale=sys.argv[3], powershell=sys.argv[4])))
PY
chown -R "$user:$user" "$home/.local" "$home/.config" "$home/.ssh"
chmod 700 "$home" "$home/.ssh" "$home/.config/vastai" "$home/.config/rclone"
find "$home/.ssh" "$home/.config/vastai" "$home/.config/rclone" -type f -exec chmod 600 {} +
chmod 755 "$home/.local/bin/"{vastgame,tailscale,moonlight,vastgame-native,ping} "$home/.local/share/vastgame/app/bin/vastgame"
dns_generation=true
if grep -q '^generateResolvConf=false' /etc/wsl.conf; then dns_generation=false; fi
printf '[user]\ndefault=%s\n[network]\ngenerateResolvConf=%s\n[interop]\nenabled=true\nappendWindowsPath=true\n[boot]\nsystemd=false\n' "$user" "$dns_generation" > /etc/wsl.conf
# Account validation performs only read-only requests, never rents or stops a VM.
runuser -u "$user" -- env PATH="$home/.local/share/vastgame/venv/bin:/usr/bin:/bin" \
  rclone lsd gdrive:VastGaming > /dev/null
runuser -u "$user" -- env PATH="$home/.local/share/vastgame/venv/bin:/usr/bin:/bin" \
  vastai show user > /dev/null
printf 'Vastgame backend and account checks passed.\n'

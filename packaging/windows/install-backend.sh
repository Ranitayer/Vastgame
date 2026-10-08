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
# Private imports include account configuration, never VM IDs or game archives.
if [ -f "$application/accounts.tar" ]; then
  python3 - "$application/accounts.tar" "$home" <<'PY_ACCOUNTS'
import re, sys, tarfile
from pathlib import Path
root=Path(sys.argv[2])
allowed={'.config/vastai/vast_api_key','.config/vastai/vast_role','.config/rclone/rclone.conf',
         '.config/vastgame/template_hash','.config/vastgame/bootstrap.json','.ssh/id_ed25519','.ssh/id_ed25519.pub'}
with tarfile.open(sys.argv[1]) as archive:
    seen=set(); total=0
    for member in archive:
        name=member.name; total+=member.size
        if name in ('identity.json','moonlight.ini'): continue
        if (not member.isfile() or name in seen or total>64*1024**2 or
            not (name in allowed or re.fullmatch(r'\.config/vastgame/games/[a-z0-9][a-z0-9._-]{0,63}/manifest\.json',name))):
            raise ValueError('Unsafe private account bundle')
        seen.add(name)
        target=root/name
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()): raise ValueError('Unsafe account destination')
        if target.exists(): continue
        target.parent.mkdir(parents=True,exist_ok=True)
        with archive.extractfile(member) as source, target.open('xb') as output: output.write(source.read())
        target.chmod(0o600)
PY_ACCOUNTS
fi
python3 -m venv "$home/.local/share/vastgame/venv"
"$home/.local/share/vastgame/venv/bin/pip" install --disable-pip-version-check 'vastai==1.8.3' 'PyYAML==6.0.3'
cp "$application/run-vastgame.sh" "$home/.local/bin/vastgame"
for name in tailscale moonlight vastgame-native ping; do
  cp "$application/windows-bridge.sh" "$home/.local/bin/$name"
done
python3 "$application/apply_update.py" --fresh --home "$home" --bundle "$application" \
  --application "$application" --tailscale "$tailscale" --powershell "$powershell"
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

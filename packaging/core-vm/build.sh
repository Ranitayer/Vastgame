#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
[[ $(uname -m) == x86_64 ]] || { echo 'Core VM build requires x86_64'; exit 1; }
# libguestfs is root inside its appliance; the host process must remain unprivileged.
# passt drops host-root privileges and cannot access root-private socket directories.
[[ $(id -u) != 0 ]] || { echo 'Run the image builder without sudo; guest installation still runs as guest root'; exit 1; }
for tool in docker virt-filesystems virt-resize virt-customize qemu-img qemu-system-x86_64 ssh ssh-keygen jq; do
  command -v "$tool" >/dev/null || { echo "Missing build tool: $tool"; exit 1; }
done
# Some distributions package the appliance DHCP client as an optional dependency.
if [[ -f /usr/lib/guestfs/supermin.d/packages ]] &&
   grep -qx dhcpcd /usr/lib/guestfs/supermin.d/packages &&
   ! command -v dhcpcd >/dev/null && ! command -v dhclient >/dev/null; then
  echo 'Missing appliance DHCP client: install dhcpcd before building'; exit 1
fi
: "${GITHUB_SHA:?Build requires a source commit ID}"
: "${CORE_IMAGE:?Set the destination image repository}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
# Guest images must live on disk, not a small RAM-backed /tmp on desktops.
: "${RUNNER_TEMP:=$PWD/build/core-vm-work}"
mkdir -p "$RUNNER_TEMP"
python3 - "$RUNNER_TEMP" <<'PYSPACE'
import shutil, sys
if shutil.disk_usage(sys.argv[1]).free < 40 * 1024**3:
    raise SystemExit('Core VM build needs at least 40 GiB free in RUNNER_TEMP')
PYSPACE
docker info >/dev/null
work=$(mktemp -d "$RUNNER_TEMP/vastgame-core.XXXXXX")
socket_dir=$(mktemp -d /tmp/vastgame-guestfs-sockets.XXXXXX)
# libguestfs uses XDG_RUNTIME_DIR, independently of LIBGUESTFS_TMPDIR, for
# passt sockets and PID files. Scope the override to this builder process.
export XDG_RUNTIME_DIR="$socket_dir"
container=''
guest_pid=''
cleanup() {
  if [[ -n "$guest_pid" ]]; then
    kill "$guest_pid" 2>/dev/null || true
    wait "$guest_pid" 2>/dev/null || true
  fi
  [[ -z "$container" ]] || docker rm "$container" >/dev/null 2>&1 || true
  rm -rf -- "$work" "$socket_dir"
}
trap cleanup EXIT
base_tag=docker.io/vastai/kvm:ubuntu_cli_22.04-2025-11-21
docker pull --platform linux/amd64 "$base_tag"
base=$(docker image inspect "$base_tag" --format '{{index .RepoDigests 0}}')
[[ "$base" =~ @sha256:[0-9a-f]{64}$ ]] || { echo 'Base digest missing'; exit 1; }
container=$(docker create --entrypoint /bin/true "$base")
docker cp "$container:/root/images/ubuntu.img" "$work/base.img"
docker rm "$container" >/dev/null; container=''
# Grow the actual guest filesystem, not merely the outer Docker filesystem.
size=$(qemu-img info --output=json "$work/base.img" | jq -r '."virtual-size"')
target=$((32 * 1024 * 1024 * 1024))
(( size > target )) && target=$size
qemu-img create -f qcow2 "$work/ubuntu.img" "$target"
export LIBGUESTFS_BACKEND=direct
# Prefer hardware acceleration locally; CI also supports software-only builders.
if [[ -r /dev/kvm && -w /dev/kvm ]]; then
  export LIBGUESTFS_BACKEND_SETTINGS=force_kvm
else
  export LIBGUESTFS_BACKEND_SETTINGS=force_tcg
fi
echo 'Checking guest networking before resizing or downloading gaming images'
virt-customize --dry-run -a "$work/base.img" --network --memsize 1024 \
  --run-command 'getent ahostsv4 github.com >/dev/null'
rootfs=$(virt-filesystems -a "$work/base.img" --filesystems --long | awk '$3 == "ext4" {print $1}')
[[ "$rootfs" =~ ^/dev/sd[a-z][0-9]+$ ]] || { echo 'Expected one Ubuntu ext4 root partition'; exit 1; }
if (( target > size )); then
  virt-resize --expand "$rootfs" "$work/base.img" "$work/ubuntu.img"
else
  qemu-img convert -O qcow2 "$work/base.img" "$work/ubuntu.img"
fi
rm -f "$work/base.img"
for pair in 'wolf stable' 'lutris edge'; do
  read -r name tag <<<"$pair"
  docker pull "ghcr.io/games-on-whales/$name:$tag"
  digest=$(docker image inspect "ghcr.io/games-on-whales/$name:$tag" --format '{{index .RepoDigests 0}}')
  [[ "$digest" =~ @sha256:[0-9a-f]{64}$ ]] || exit 1
  printf '%s\n' "$digest" > "$work/$name.image"
done
cp src/bootstrap/core-vm.sh "$work/core-vm.sh"
cp packaging/core-vm/guest.sh "$work/guest.sh"
cp packaging/core-vm/warm.sh "$work/warm.sh"
cp -a src/runtime "$work/runtime"
# Reuse the launcher’s preparation Dockerfile exactly, including its EOL mirror guard.
sed -n '/^FROM ghcr.io\/games-on-whales\/lutris:edge$/,/^PREPARATION_IMAGE$/p' src/bootstrap/start.sh | sed '$d' > "$work/preparation.Dockerfile"
test -s "$work/preparation.Dockerfile"
virt-customize -a "$work/ubuntu.img" --network --memsize 4096 --smp 2 \
  --mkdir /opt/vastgame-build \
  --copy-in "$work/guest.sh:/opt/vastgame-build" \
  --copy-in "$work/warm.sh:/opt/vastgame-build" \
  --copy-in "$work/core-vm.sh:/opt/vastgame-build" \
  --copy-in "$work/preparation.Dockerfile:/opt/vastgame-build" \
  --copy-in "$work/runtime:/opt/vastgame-build" \
  --copy-in "$work/wolf.image:/opt/vastgame-build" \
  --copy-in "$work/lutris.image:/opt/vastgame-build" \
  --run-command 'bash /opt/vastgame-build/guest.sh'
# Container preparation needs the guest's own systemd/cgroups, not an appliance
# chroot. Use a localhost-only temporary SSH key and remove all build identity.
ssh-keygen -q -t ed25519 -N '' -f "$work/build-key"
virt-customize -a "$work/ubuntu.img" --ssh-inject "root:file:$work/build-key.pub" \
  --run-command 'touch /etc/cloud/cloud-init.disabled; mkdir -p /etc/ssh/sshd_config.d; printf "PermitRootLogin prohibit-password\n" > /etc/ssh/sshd_config.d/99-vastgame-build.conf; printf "network:\n  version: 2\n  ethernets:\n    buildnic:\n      match:\n        macaddress: 52:54:00:12:34:56\n      dhcp4: true\n" > /etc/netplan/99-vastgame-build.yaml; chmod 600 /etc/netplan/99-vastgame-build.yaml'
port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
accel=tcg; cpu=max
if [[ -r /dev/kvm && -w /dev/kvm ]]; then accel=kvm; cpu=host; fi
qemu-system-x86_64 -accel "$accel" -cpu "$cpu" -m 4096 -smp 2 \
  -drive "file=$work/ubuntu.img,format=qcow2,if=virtio" \
  -netdev "user,id=buildnet,hostfwd=tcp:127.0.0.1:$port-:22" \
  -device virtio-net-pci,netdev=buildnet,mac=52:54:00:12:34:56 \
  -display none -serial "file:$work/guest-boot.log" -monitor none > "$work/qemu.log" 2>&1 &
guest_pid=$!
ssh_args=(-i "$work/build-key" -p "$port" -o BatchMode=yes -o ConnectTimeout=3 \
          -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$work/known-hosts")
echo 'Booting the local guest to prepare Docker and Proton'
ready=0
for attempt in {1..120}; do
  kill -0 "$guest_pid" 2>/dev/null || { cat "$work/qemu.log" "$work/guest-boot.log"; exit 1; }
  if ssh "${ssh_args[@]}" root@127.0.0.1 true 2>/dev/null; then ready=1; break; fi
  sleep 3
done
[[ "$ready" = 1 ]] || { cat "$work/qemu.log" "$work/guest-boot.log"; echo 'Local guest SSH did not become ready'; exit 1; }
ssh "${ssh_args[@]}" root@127.0.0.1 'bash /opt/vastgame-build/warm.sh'
ssh "${ssh_args[@]}" root@127.0.0.1 'rm -f /etc/cloud/cloud-init.disabled /etc/netplan/99-vastgame-build.yaml /etc/ssh/sshd_config.d/99-vastgame-build.conf; sync; systemctl poweroff'
for attempt in {1..60}; do
  kill -0 "$guest_pid" 2>/dev/null || break
  sleep 1
done
if kill -0 "$guest_pid" 2>/dev/null; then echo 'Guest did not shut down cleanly; image will not be published'; exit 1; fi
wait "$guest_pid"; guest_pid=''
# No client identity, SSH keys, tailnet membership or game state is shipped.
virt-sysprep -a "$work/ubuntu.img" --operations ssh-hostkeys,ssh-userdir,machine-id,logfiles,tmp-files,bash-history
cp packaging/core-vm/Dockerfile "$work/Dockerfile"
printf '%s\n' '*' '!Dockerfile' '!ubuntu.img' > "$work/.dockerignore"
docker build --build-arg "BASE_IMAGE=$base" -t "vastgame-core-unsquashed:$GITHUB_SHA" "$work"
# Drop the overwritten original guest disk from the distributed image layers.
python3 packaging/core-vm/flatten.py "vastgame-core-unsquashed:$GITHUB_SHA" "$CORE_IMAGE:build-$GITHUB_SHA"
mkdir -p build
jq -n --arg base "$base" --arg commit "$GITHUB_SHA" --arg image "$CORE_IMAGE:build-$GITHUB_SHA" \
  --arg wolf "$(cat "$work/wolf.image")" --arg lutris "$(cat "$work/lutris.image")" \
  '{base_image:$base,source_commit:$commit,image:$image,wolf:$wolf,lutris:$lutris,live_validated:false}' > build/core-vm-receipt.json
echo 'Experimental image built. The working Vast template has not been changed.'

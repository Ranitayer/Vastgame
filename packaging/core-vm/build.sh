#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
[[ $(uname -m) == x86_64 ]] || { echo 'Core VM build requires x86_64'; exit 1; }
for tool in docker virt-filesystems virt-resize virt-customize qemu-img jq; do
  command -v "$tool" >/dev/null || { echo "Missing build tool: $tool"; exit 1; }
done
: "${GITHUB_SHA:?Build requires a source commit ID}"
: "${CORE_IMAGE:?Set the destination image repository}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/vastgame-core.XXXXXX")
container=''
cleanup() {
  [[ -z "$container" ]] || docker rm "$container" >/dev/null 2>&1 || true
  rm -rf -- "$work"
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
# Software virtualization also works on builders without nested KVM.
export LIBGUESTFS_BACKEND_SETTINGS=force_tcg
rootfs=$(virt-filesystems -a "$work/base.img" --filesystems --long | awk '$3 == "ext4" {print $1}')
[[ "$rootfs" =~ ^/dev/sd[a-z][0-9]+$ ]] || { echo 'Expected one Ubuntu ext4 root partition'; exit 1; }
if (( target > size )); then
  virt-resize --expand "$rootfs" "$work/base.img" "$work/ubuntu.img"
else
  qemu-img convert -O qcow2 "$work/base.img" "$work/ubuntu.img"
fi
for pair in 'wolf stable' 'lutris edge'; do
  read -r name tag <<<"$pair"
  docker pull "ghcr.io/games-on-whales/$name:$tag"
  digest=$(docker image inspect "ghcr.io/games-on-whales/$name:$tag" --format '{{index .RepoDigests 0}}')
  [[ "$digest" =~ @sha256:[0-9a-f]{64}$ ]] || exit 1
  printf '%s\n' "$digest" > "$work/$name.image"
done
cp src/bootstrap/core-vm.sh "$work/core-vm.sh"
cp packaging/core-vm/guest.sh "$work/guest.sh"
cp -a src/runtime "$work/runtime"
# Reuse the launcher’s preparation Dockerfile exactly, including its EOL mirror guard.
sed -n '/^FROM ghcr.io\/games-on-whales\/lutris:edge$/,/^PREPARATION_IMAGE$/p' src/bootstrap/start.sh | sed '$d' > "$work/preparation.Dockerfile"
test -s "$work/preparation.Dockerfile"
virt-customize -a "$work/ubuntu.img" --network --memsize 4096 --smp 2 \
  --mkdir /opt/vastgame-build \
  --copy-in "$work/core-vm.sh:/opt/vastgame-build" \
  --copy-in "$work/preparation.Dockerfile:/opt/vastgame-build" \
  --copy-in "$work/runtime:/opt/vastgame-build" \
  --copy-in "$work/wolf.image:/opt/vastgame-build" \
  --copy-in "$work/lutris.image:/opt/vastgame-build" \
  --run "$work/guest.sh"
# No client identity, SSH keys, tailnet membership or game state is shipped.
virt-sysprep -a "$work/ubuntu.img" --operations ssh-hostkeys,ssh-userdir,machine-id,logfiles,tmp-files,bash-history
cp packaging/core-vm/Dockerfile "$work/Dockerfile"
printf '%s\n' '*' '!Dockerfile' '!ubuntu.img' > "$work/.dockerignore"
docker build --build-arg "BASE_IMAGE=$base" -t "$CORE_IMAGE:build-$GITHUB_SHA" "$work"
mkdir -p build
jq -n --arg base "$base" --arg commit "$GITHUB_SHA" --arg image "$CORE_IMAGE:build-$GITHUB_SHA" \
  --arg wolf "$(cat "$work/wolf.image")" --arg lutris "$(cat "$work/lutris.image")" \
  '{base_image:$base,source_commit:$commit,image:$image,wolf:$wolf,lutris:$lutris,live_validated:false}' > build/core-vm-receipt.json
echo 'Experimental image built. The working Vast template has not been changed.'

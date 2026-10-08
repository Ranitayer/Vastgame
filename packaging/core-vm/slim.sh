#!/usr/bin/env bash
# Make a local-only compact copy. Never uploads or selects it for deployment.
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
source_image=ghcr.io/ranitayer/vastgame-core@sha256:f7b5cbd83825d9e60f7b16b36555e76c4d327614141e629779284944db9d6fb7
destination=vastgame-core:slim-local-reviewed
work="$PWD/build/core-slim-local"
mkdir -p "$work"
mkdir -p "$work/tmp"
export TMPDIR="$work/tmp"
export LIBGUESTFS_BACKEND=direct
if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    export LIBGUESTFS_BACKEND_SETTINGS=force_kvm
else
    export LIBGUESTFS_BACKEND_SETTINGS=force_tcg
fi
[[ ! -e "$work/ubuntu.img" ]] || { echo 'Existing compact disk retained; use a new workspace for another run'; exit 1; }
# source.img is an independently extracted copy; the source Docker image is intact.
if [[ ! -s "$work/source.img" ]]; then
    container=$(docker create --entrypoint /bin/true "$source_image")
    trap 'docker rm "$container" >/dev/null 2>&1 || true' EXIT
    docker cp "$container:/root/images/ubuntu.img" "$work/source.img"
    docker rm "$container" >/dev/null
    trap - EXIT
fi
virt-customize -a "$work/source.img" --no-network --memsize 2048 --run-command '
    set -eu
    test "$(cat /usr/share/vastgame/core-image)" = core-image-v1
    apt-get clean
    rm -rf /var/lib/apt/lists/*
    # Preserve licenses, package records, translations and all runtime files.
    find /usr/share/doc -type f ! -name copyright ! -name "LICENSE*" ! -name "COPYING*" -delete
    find /usr/share/man /usr/share/info -type f -delete
    # Verify the frozen gaming runtime has not changed during cleanup.
    sha256sum --quiet -c /usr/share/vastgame/runtime-files.sha256
    sync
  '
# Work only on a powered-off copy; retain virtual capacity and boot partitions.
# Compression stays at the OCI/archive level to avoid double-compression on boot.
virt-sparsify --convert qcow2 "$work/source.img" "$work/sparse.img"
qemu-img convert -O qcow2 "$work/sparse.img" "$work/ubuntu.img"
rm "$work/sparse.img"
cp packaging/core-vm/Dockerfile "$work/Dockerfile"
printf '%s\n' '*' '!Dockerfile' '!ubuntu.img' > "$work/.dockerignore"
docker build --build-arg "BASE_IMAGE=$source_image" -t vastgame-core:slim-intermediate-reviewed "$work"
python3 packaging/core-vm/flatten.py vastgame-core:slim-intermediate-reviewed "$destination"
docker image rm vastgame-core:slim-intermediate-reviewed
echo 'Local compact image ready. Nothing uploaded or selected for launch.'

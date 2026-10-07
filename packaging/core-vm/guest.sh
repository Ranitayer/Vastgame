#!/usr/bin/env bash
# Executed inside the Ubuntu guest disk by virt-customize, never on a user's VM.
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
source /opt/vastgame-build/core-vm.sh
install_core_dependencies
# Install generic network clients at build time; never authenticate either one.
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.noarmor.gpg > /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.tailscale-keyring.list > /etc/apt/sources.list.d/tailscale.list
apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
apt-get install -y --no-install-recommends tailscale rclone
mkdir -p /etc/modprobe.d /etc/modules-load.d
printf '%s\n' 'options nvidia_drm modeset=1' > /etc/modprobe.d/vastgame-nvidia-drm.conf
printf '%s\n' uinput uhid > /etc/modules-load.d/vastgame-input.conf
systemctl enable docker

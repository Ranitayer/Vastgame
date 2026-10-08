#!/usr/bin/env bash
# Included in the private startup transport; never run on the client PC.
prepare_core_modeset() {
  local mode=/sys/module/nvidia_drm/parameters/modeset
  local refs=/sys/module/nvidia_drm/refcnt
  mkdir -p /etc/modprobe.d
  printf '%s\n' 'options nvidia_drm modeset=1' > /etc/modprobe.d/vastgame-nvidia-drm.conf
  if [ "$(cat "$mode" 2>/dev/null || true)" = Y ]; then
    echo '[VASTGAME] NVIDIA DRM modesetting ready'
    return 0
  fi
  if [ -r "$mode" ]; then
    # Parameters passed to modprobe do not change an already loaded module.
    # Only reload this leaf module when unused, before any gaming containers.
    if [ "$(cat "$refs" 2>/dev/null || true)" != 0 ] || ! modprobe -r nvidia_drm; then
      echo '[VASTGAME] ERROR: NVIDIA DRM modesetting disabled and module is in use; reboot this VM to apply modeset=1. No module was force-unloaded or VM rebooted.'
      return 1
    fi
  fi
  if ! modprobe nvidia_drm modeset=1; then
    echo '[VASTGAME] ERROR: Could not load NVIDIA DRM with modeset=1; check the installed GPU driver'
    return 1
  fi
  if [ "$(cat "$mode" 2>/dev/null || true)" != Y ]; then
    echo '[VASTGAME] ERROR: NVIDIA DRM modesetting remains disabled after configuration; game restore has not started'
    return 1
  fi
  echo '[VASTGAME] NVIDIA DRM modesetting enabled before game restore'
}

install_core_dependencies() {
  echo '[VASTGAME] Preparing headless Core VM dependencies'
  # Driver/library upgrades during a live session require a reload or reboot.
  # Keep other automatic security updates enabled; manage GPU upgrades between sessions.
  mkdir -p /etc/apt/apt.conf.d
  cat > /etc/apt/apt.conf.d/52vastgame-driver-stability <<'DRIVER_POLICY'
Unattended-Upgrade::Package-Blacklist {
  "^nvidia-";
  "^libnvidia-";
  "^linux-modules-nvidia-";
  "^xserver-xorg-video-nvidia-";
};
DRIVER_POLICY
  export DEBIAN_FRONTEND=noninteractive
  local item command package toolkit=0 bootstrap=0
  local version="${NVIDIA_CONTAINER_TOOLKIT_VERSION:-1.20.1-1}"
  local -a packages=()
  [[ "$version" =~ ^[A-Za-z0-9.+:~_-]+$ ]] || {
    echo '[VASTGAME] ERROR: Invalid NVIDIA_CONTAINER_TOOLKIT_VERSION'; return 1;
  }
  # Detect dependencies once; installation never upgrades an already prepared VM.
  for item in curl:curl gpg:gnupg jq:jq zstd:zstd python3:python3 ping:iputils-ping \
              lspci:pciutils glxinfo:mesa-utils modprobe:kmod docker:docker.io; do
    command="${item%%:*}"
    command -v "$command" >/dev/null || packages+=("${item#*:}")
  done
  [ -s /etc/ssl/certs/ca-certificates.crt ] || packages+=(ca-certificates)
  python3 -c 'import tomllib' 2>/dev/null || python3 -c 'import tomli' 2>/dev/null || packages+=(python3-tomli)
  if ! command -v nvidia-ctk >/dev/null; then
    toolkit=1
    # An image without HTTPS/key tools needs one prerequisite update before
    # adding NVIDIA's repository. Normal bases need only the final update below.
    command -v curl >/dev/null && command -v gpg >/dev/null && \
      [ -s /etc/ssl/certs/ca-certificates.crt ] || bootstrap=1
    if [ "$bootstrap" = 1 ]; then
      echo '[VASTGAME] Installing repository bootstrap prerequisites'
      timeout 180 apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
      timeout 300 apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends ca-certificates curl gnupg
    fi
    curl -fsSL --connect-timeout 15 --max-time 60 https://nvidia.github.io/libnvidia-container/gpgkey |
      gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL --connect-timeout 15 --max-time 60 https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
      sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    for package in nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1; do
      packages+=("$package=$version")
    done
  fi
  if [ "${#packages[@]}" -gt 0 ]; then
    timeout 180 apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
    if [ "$toolkit" = 1 ]; then
      for package in nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1; do
        if ! apt-cache show "$package=$version" >/dev/null 2>&1; then
          echo "[VASTGAME] ERROR: $package version $version unavailable in the signed NVIDIA repository; set NVIDIA_CONTAINER_TOOLKIT_VERSION to a tested available version"
          return 1
        fi
      done
    fi
    timeout 300 apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends "${packages[@]}"
  fi
  if [ "$toolkit" = 1 ]; then
    nvidia-ctk runtime configure --runtime=docker
    core_docker_restart=1
  fi
 }

prepare_core_gpu_runtime() {
  local error
  if ! error="$(timeout 30 nvidia-smi -L 2>&1)"; then
    echo "[VASTGAME] ERROR: VM GPU driver is not ready: $error"
    echo '[VASTGAME] Driver/library mismatch requires a safe driver reload while idle or a VM reboot; no reload was forced.'
    return 1
  fi
  # Refresh device definitions only after the actual GPU driver is usable.
  if systemctl cat nvidia-cdi-refresh.service >/dev/null 2>&1; then
    timeout 30 systemctl restart nvidia-cdi-refresh.service || {
      echo '[VASTGAME] ERROR: NVIDIA CDI refresh failed; inspect journalctl -u nvidia-cdi-refresh.service'
      return 1
    }
  fi
}

prepare_core_vm() {
  local core_docker_restart=0
  install_core_dependencies
  if [ "$core_docker_restart" = 1 ]; then systemctl restart docker; fi
  # Preserve SSH security; repair permissions on the injected public key only.
  if [ -f /root/.ssh/authorized_keys ]; then
    chown root:root /root/.ssh /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
  fi
  systemctl enable --now docker
  command -v nvidia-smi >/dev/null || { echo '[VASTGAME] ERROR: Base VM NVIDIA driver missing'; return 1; }
  prepare_core_gpu_runtime
  timeout 30 docker info >/dev/null || { echo '[VASTGAME] ERROR: Core VM Docker is not ready'; return 1; }
  modprobe uinput || true
  modprobe uhid || true
  if [ ! -c /dev/uinput ] || [ ! -c /dev/uhid ]; then
    echo '[VASTGAME] ERROR: Virtual input devices missing (/dev/uinput or /dev/uhid)'
    return 1
  fi
  prepare_core_modeset
  mkdir -p /srv/gaming/{games,profiles,prefixes,saves,shaders,configs,lutris}
  echo '[VASTGAME] Headless Core VM dependencies ready'
}

#!/usr/bin/env bash
set -Eeuo pipefail
dns_works() {
  local host
  for host in archive.ubuntu.com security.ubuntu.com; do
    timeout 15 getent ahosts "$host" >/dev/null || {
      dns_failure="Root cannot resolve $host"; return 1;
    }
  done
  if id _apt >/dev/null 2>&1; then
    for host in archive.ubuntu.com security.ubuntu.com; do
      runuser -u _apt -- timeout 15 getent ahosts "$host" >/dev/null || {
        dns_failure="Root DNS works, but restricted APT user cannot resolve $host"; return 1;
      }
    done
  fi
}
# DNS is read by ordinary users and APT's restricted download user too.
if [[ -f /etc/resolv.conf ]]; then chmod 0644 /etc/resolv.conf; fi
if dns_works; then exit 0; fi
if (( $# == 0 )); then
  echo 'WSL DNS failed; Windows supplied no usable DNS servers. Check Windows internet/VPN settings.' >&2
  exit 1
fi
backup="$(mktemp -d)"
had_resolver=0
if [[ -e /etc/resolv.conf || -L /etc/resolv.conf ]]; then
  cp -a /etc/resolv.conf "$backup/resolv.conf"
  had_resolver=1
fi
repaired=0
cleanup() {
  if (( ! repaired )); then
    rm -f /etc/resolv.conf
    if (( had_resolver )); then cp -a "$backup/resolv.conf" /etc/resolv.conf; fi
  fi
  rm -rf "$backup"
}
trap cleanup EXIT
for server in "$@"; do
  [[ "$server" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
  rm -f /etc/resolv.conf
  printf 'nameserver %s\noptions timeout:2 attempts:2\n' "$server" > /etc/resolv.conf
  chmod 0644 /etc/resolv.conf
  if dns_works; then
    # The supplied image has this setting; retain the rest of its WSL config.
    grep -q '^generateResolvConf=' /etc/wsl.conf || {
      echo 'WSL network configuration is missing generateResolvConf; DNS repair was not saved.' >&2
      exit 1
    }
    sed -i 's/^generateResolvConf=.*/generateResolvConf=false/' /etc/wsl.conf
    repaired=1
    echo "WSL DNS verified for root and APT using Windows DNS server $server."
    exit 0
  fi
done
echo "$dns_failure using Windows DNS servers. Check VPN/firewall connectivity; original resolver restored." >&2
exit 1

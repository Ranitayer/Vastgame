# ============================================================
# TAILSCALE
# ============================================================

verify_peer_identity() {
    local ip="$1" id="${2:-$(cat "$INSTANCE_FILE" 2>/dev/null || true)}" info label remote
    [[ "$id" =~ ^[0-9]+$ ]] || return 1
    info="$(instance_json "$id")" || return 1
    label="$(jq -r '.label // empty' <<<"$info")"
    [[ "$label" =~ ^vastgame-[0-9]+$ ]] || return 1
    jq -e --arg id "$id" '(.id | tostring) == $id' >/dev/null <<<"$info" || return 1
    remote="$(curl -fsS --connect-timeout 2 --max-time 3 "http://$ip:$STATUS_PORT/instance-label" 2>/dev/null)" || return 1
    [[ "$remote" == "$label" ]]
}

get_vast_ip() {
    local id="${1:-$(cat "$INSTANCE_FILE" 2>/dev/null || true)}" ip
    [[ "$id" =~ ^[0-9]+$ ]] || return 1
    while read -r ip; do
        verify_peer_identity "$ip" "$id" || continue
        printf '%s\n' "$ip"
        return 0
    done < <(timeout 10s tailscale status --json 2>/dev/null | jq -r '
        .Peer[]? | select(.Online == true) |
        select((.HostName // "" | startswith("vast-gaming")) or
               (.DNSName // "" | startswith("vast-gaming"))) |
        .TailscaleIPs[]? | select(startswith("100."))')
    return 1
}


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
    done < <(tailscale status --json 2>/dev/null | jq -r '
        .Peer[]? | select(.Online == true) |
        select((.HostName // "" | startswith("vast-gaming")) or
               (.DNSName // "" | startswith("vast-gaming"))) |
        .TailscaleIPs[]? | select(startswith("100."))')
    return 1
}

qualify_local_route() {
    local id="$1"
    local ip="$2"
    local tsout=""
    local out
    local direct=0
    local pingout
    local loss
    local rtt
    local avg
    local jitter
    local numeric='^(0|[1-9][0-9]*)(\.[0-9]+)?$'

    echo
    if (( VASTGAME_FORCE_ROUTE == 1 )); then
        echo
        warn "FORCE MODE — Moonlight route qualification skipped"
        echo "Continuing regardless of direct/DERP path, RTT, jitter or packet loss."
        return 0
    fi

    bold "Moonlight route qualification"

    # Prime/test Tailscale path. Prefer a direct WireGuard path.
    for _ in 1 2 3; do
        out="$(timeout 8 tailscale ping "$ip" 2>&1 || true)"
        tsout+="$out"$'\n'

        if grep -qi 'via DERP' <<<"$out"; then
            sleep 1
            continue
        fi

        if grep -qi 'pong from' <<<"$out"; then
            direct=1
            break
        fi
    done

    if (( direct == 0 )); then
        warn "No direct Tailscale path established."
        printf '%s\n' "$tsout" | tail -n 6

        record_route_history             "$id" "fail" 999 999 100

        return 1
    fi

    ok "Tailscale direct path"

    pingout="$(
        LC_ALL=C ping -c 20 -i 0.2 -W 2 "$ip" 2>&1 || true
    )"

    loss="$(
        sed -n \
            's/.*, \([0-9.]*\)% packet loss.*/\1/p' \
            <<<"$pingout" |
        tail -n1
    )"

    rtt="$(
        awk -F'= ' \
            '/^(rtt|round-trip)/ {
                sub(/ ms.*/, "", $2)
                gsub(/ /, "", $2)
                print $2
            }' <<<"$pingout" |
        tail -n1
    )"

    avg="$(cut -d/ -f2 <<<"$rtt")"
    jitter="$(cut -d/ -f4 <<<"$rtt")"

    [[ "$loss" =~ $numeric && "$avg" =~ $numeric && "$jitter" =~ $numeric ]] || {
        warn "Could not measure route quality."
        echo "$pingout"

        record_route_history             "$id" "fail" 999 999 100

        return 1
    }

    printf '  RTT avg:     %s ms\n' "$avg"
    printf '  Jitter:      %s ms\n' "$jitter"
    printf '  Packet loss: %s%%\n' "$loss"

    if ! awk \
            -v avg="$avg" \
            -v max="$LOCAL_MAX_RTT_MS" \
            'BEGIN { exit !(avg <= max) }' ||
       ! awk \
            -v loss="$loss" \
            -v max="$LOCAL_MAX_LOSS_PCT" \
            'BEGIN { exit !(loss <= max) }' ||
       ! awk \
            -v jitter="$jitter" \
            -v max="$LOCAL_MAX_JITTER_MS" \
            'BEGIN { exit !(jitter <= max) }'
    then
        record_route_history             "$id" "fail" "$avg" "$jitter" "$loss"

        return 1
    fi

    record_route_history         "$id" "pass" "$avg" "$jitter" "$loss"

    ok "Route approved for Moonlight"
    return 0
}


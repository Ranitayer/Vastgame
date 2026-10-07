# ============================================================
# FINAL BACKUP
# ============================================================

# Deploy helpers to the selected VM, validate its launch identity, then run state I/O.
verified_state_endpoint() {
    local info="$1" label="$2" host port remote_label seen=""
    while IFS=$'\t' read -r host port; do
        [[ "$host" =~ ^[a-zA-Z0-9][a-zA-Z0-9.:-]*$ && "$port" =~ ^[0-9]{1,5}$ ]] || continue
        (( 10#$port >= 1 && 10#$port <= 65535 )) || continue
        [[ "$seen" != *"|$host:$port|"* ]] || continue
        seen+="|$host:$port|"
        if ! remote_label="$(timeout 20 ssh -F /dev/null -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 \
            -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" \
            -p "$port" "root@$host" 'cat /var/lib/vast-gaming/status/instance-label' 2>/dev/null)"; then
            warn "SSH unavailable at $host:$port; trying the next Vast endpoint" >&2
            continue
        fi
        [[ "$remote_label" == "$label" ]] || { warn "Connected VM launch label differs; refusing state changes" >&2; return 1; }
        printf '%s\t%s\n' "$host" "$port"
        return 0
    done < <(jq -r '.public_ipaddr as $ip | [{host: .ssh_host, port: .ssh_port},
        (.ports["22/tcp"][]? | {host: $ip, port: .HostPort})][] |
        select(.host != null and .port != null) | [.host, (.port | tostring)] | @tsv' <<<"$info")
    warn "No verified SSH endpoint reachable; VM retained" >&2
    return 1
}

remote_state() (
    local action="$1" id="$2" wanted="${3:-}" final="${4:-}" info host port label gid temp receipt
    local KNOWN_HOSTS="$STATEDIR/known_hosts.$id"
    info="$(instance_json "$id")" || return 1
    jq -e --arg id "$id" '(.id|tostring) == $id' >/dev/null <<<"$info" || return 1
    label="$(jq -r '.label // empty' <<<"$info")"
    [[ "$label" =~ ^vastgame-[0-9]+$ ]] || { warn "Refusing state access on an unrelated instance"; return 1; }
    local endpoint
    endpoint="$(verified_state_endpoint "$info" "$label")" || return 1
    host="${endpoint%%$'\t'*}"
    port="${endpoint#*$'\t'}"
    local -a remote_ssh=(ssh -F /dev/null -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1
        -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" -p "$port" "root@$host")
    temp="$(mktemp -d "$STATEDIR/state.XXXXXX")"
    trap 'rm -rf -- "$temp"' EXIT
    local remote_label
    remote_label="$("${remote_ssh[@]}" 'cat /var/lib/vast-gaming/status/instance-label')" || return 1
    [[ "$remote_label" == "$label" ]] || { warn "Connected VM launch label differs; refusing state changes"; return 1; }
    if ! "${remote_ssh[@]}" 'cat /var/lib/vast-gaming/status/session.json' > "$temp/session.json"; then
        warn "SSH connection failed; VM retained. Check its Vast SSH endpoint/key."
        return 1
    fi
    gid="$(jq -r '.game_id // empty' "$temp/session.json")"
    valid_game_id "$gid" || { warn "VM game identity is unavailable"; return 1; }
    [[ -z "$wanted" || "$gid" == "$wanted" ]] || { warn "Selected VM is running $gid, not $wanted"; return 1; }
    [[ -f "$(game_manifest "$gid")" ]] || { warn "Local manifest missing for $gid"; return 1; }
    # The runtime archive is content-pinned during boot; deploy the same local helper
    # set here so old VMs can use the final-backup path without rebooting.
    tar -C "$RUNTIME_DIR" -cf "$temp/runtime.tar" . || return 1
    "${remote_ssh[@]}" 'mkdir -p /opt/vastgame; tar -C /opt/vastgame -xf -' < "$temp/runtime.tar" || return 1
    "${remote_ssh[@]}" "cat > /srv/gaming/profiles/$gid/manifest.json" < "$(game_manifest "$gid")" || return 1
    receipt="/srv/gaming/profiles/$gid/backup-receipt.json"
    "${remote_ssh[@]}" "python3 /opt/vastgame/game_state.py $action $gid --instance $id --label $label --config /etc/rclone/rclone.conf --receipt $receipt $final" || return 1
    if [[ "$action" == backup ]]; then
        "${remote_ssh[@]}" "cat $receipt" > "$temp/receipt.json" || return 1
        jq -e --arg instance "$id" --arg game "$gid"             '.schema == 1 and .instance_id == $instance and .game_id == $game and (.snapshot | length > 0)'             "$temp/receipt.json" >/dev/null || return 1
        mkdir -p "$STATEDIR/backups/$gid"
        cp "$temp/receipt.json" "$STATEDIR/backups/$gid/last-verified.json"
    fi
    rm -rf "$temp"
)

safe_backup() { remote_state backup "$1" "" --final; }

# ============================================================
# STOP
# ============================================================

stop_game() {
    local id
    id="$(pick_instance)" || {
        echo "No vastgame instances found."
        return 0
    }

    if safe_backup "$id"; then

        ok "Final Google Drive state backup complete"

    else

        echo
        warn "Final backup could not be confirmed."

        warn "Instance left running to protect saves. No destroy request sent."
        return 1

    fi

    echo
    echo "Destroying Vast instance $id..."

    destroy_verified "$id" || die "Destruction could not be confirmed. Check vastgame status; local identity retained."

    ok "Instance destroyed — GPU billing stopped"
}


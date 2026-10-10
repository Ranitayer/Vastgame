# ============================================================
# FINAL BACKUP
# ============================================================

# Verify the selected VM before deploying isolated state helpers or accessing saves.
verified_state_endpoint() {
    local info="$1" label="$2" host port remote_label error_file detail seen=""
    error_file="$(mktemp "$STATEDIR/ssh-error.XXXXXX")" || return 1
    while IFS=$'\t' read -r host port; do
        [[ "$host" =~ ^[a-zA-Z0-9][a-zA-Z0-9.:-]*$ && "$port" =~ ^[0-9]{1,5}$ ]] || continue
        (( 10#$port >= 1 && 10#$port <= 65535 )) || continue
        [[ "$seen" != *"|$host:$port|"* ]] || continue
        seen+="|$host:$port|"
        if ! remote_label="$(STATE_SSH_TIMEOUT=20 state_ssh "$host" "$port" 'cat /var/lib/vast-gaming/status/instance-label' 2>"$error_file")"; then
            detail="$(tail -c 1024 "$error_file")"
            warn "SSH failed at $host:$port: ${detail:-connection timed out or closed}; trying the next endpoint" >&2
            continue
        fi
        [[ "$remote_label" == "$label" ]] || { rm -f "$error_file"; warn "Connected VM launch label differs; refusing state changes" >&2; return 1; }
        rm -f "$error_file"
        printf '%s\t%s\n' "$host" "$port"
        return 0
    done < <(
        local ip id
        id="$(jq -r '.id // empty' <<<"$info")"
        ip="$(get_vast_ip "$id" 2>/dev/null || true)"
        if [[ "$ip" =~ ^100\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then printf '%s\t22\n' "$ip"; fi
        jq -r '.public_ipaddr as $ip | [{host: .ssh_host, port: .ssh_port},
            (.ports["22/tcp"][]? | {host: $ip, port: .HostPort})][] |
            select(.host != null and .port != null) | [.host, (.port | tostring)] | @tsv' <<<"$info"
    )
    rm -f "$error_file"
    warn "No verified SSH endpoint reachable; VM retained" >&2
    return 1
}

# Tailscale's local agent carries SSH bytes even when Windows WSL has no tailnet route.
state_ssh() {
    local host="$1" port="$2"; shift 2
    local -a proxy=() deadline=()
    [[ -z "${STATE_SSH_TIMEOUT:-}" ]] || deadline=(timeout "$STATE_SSH_TIMEOUT")
    if [[ "$host" =~ ^100\.[0-9]+\.[0-9]+\.[0-9]+$ && "$port" == 22 ]]; then
        proxy=(-o 'ProxyCommand=tailscale nc %h %p')
    fi
    "${deadline[@]}" ssh -F /dev/null -T -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 \
        -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" \
        "${proxy[@]}" -p "$port" "root@$host" "$@"
}

remote_state() (
    local action="$1" id="$2" wanted="${3:-}" final="${4:-}" endpoint="${5:-}" info host port label gid temp receipt helper_sha manifest_sha
    case "$action" in backup|restore|resume) ;; *) return 1 ;; esac
    [[ -z "$final" || "$final" == --final ]] || return 1
    local KNOWN_HOSTS="$STATEDIR/known_hosts.$id"
    info="$(instance_json "$id")" || return 1
    jq -e --arg id "$id" '(.id|tostring) == $id' >/dev/null <<<"$info" || return 1
    label="$(jq -r '.label // empty' <<<"$info")"
    [[ "$label" =~ ^vastgame-[0-9]+$ ]] || { warn "Refusing state access on an unrelated instance"; return 1; }
    [[ -n "$endpoint" ]] || endpoint="$(verified_state_endpoint "$info" "$label")" || return 1
    host="${endpoint%%$'\t'*}"
    port="${endpoint#*$'\t'}"
    local -a remote_ssh=(state_ssh "$host" "$port")
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
    # The guest's launch manifest is authoritative, even on a client with stale metadata.
    "${remote_ssh[@]}" "cat /srv/gaming/profiles/$gid/manifest.json" > "$temp/manifest.json" || return 1
    jq -e --arg gid "$gid" '.schema == 1 and .id == $gid' "$temp/manifest.json" >/dev/null || return 1
    manifest_sha="$(sha256sum "$temp/manifest.json" | cut -d ' ' -f 1)"
    # This self-contained helper is independent of the live /opt/vastgame runtime.
    cp "$RUNTIME_DIR/game_state.py" "$temp/game_state.py" || return 1
    helper_sha="$(sha256sum "$temp/game_state.py" | cut -d ' ' -f 1)"
    local deploy
    deploy="$(cat <<'STATE_HELPER'
set -Eeuo pipefail
sha="$1"
label="$2"
[[ "$(cat /var/lib/vast-gaming/status/instance-label)" == "$label" ]]
install -d -m 700 /opt/vastgame-state
stage=$(mktemp -d /opt/vastgame-state/.stage.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
cat > "$stage/game_state.py"
printf '%s  %s\n' "$sha" "$stage/game_state.py" | sha256sum -c - >/dev/null
python3 -c 'import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' "$stage/game_state.py"
chmod 600 "$stage/game_state.py"
if [[ -d /opt/vastgame-state/$sha ]]; then
  cmp "$stage/game_state.py" /opt/vastgame-state/$sha/game_state.py
else
  mv -T "$stage" /opt/vastgame-state/$sha
fi
STATE_HELPER
)"
    deploy="$(python3 -c 'import shlex,sys; print(shlex.quote(sys.stdin.read()))' <<<"$deploy")" || return 1
    "${remote_ssh[@]}" "bash -c $deploy -- $helper_sha $label" < "$temp/game_state.py" || return 1
    receipt="/srv/gaming/profiles/$gid/backup-receipt.json"
    "${remote_ssh[@]}" "python3 /opt/vastgame-state/$helper_sha/game_state.py $action $gid --instance $id --label $label --manifest-sha $manifest_sha --config /etc/rclone/rclone.conf --receipt $receipt $final" || return 1
    if [[ "$action" == backup ]]; then
        "${remote_ssh[@]}" "cat $receipt" > "$temp/receipt.json" || return 1
        jq -e --arg instance "$id" --arg game "$gid"             '.schema == 1 and .instance_id == $instance and .game_id == $game and (.snapshot | length > 0)'             "$temp/receipt.json" >/dev/null || return 1
        mkdir -p "$STATEDIR/backups/$gid"
        cp "$temp/receipt.json" "$STATEDIR/backups/$gid/last-verified.json"
    fi
    rm -rf "$temp"
)

safe_backup() { remote_state backup "$1" "" --final "${2:-}"; }

# ============================================================
# STOP
# ============================================================

# Freeze the verified guest before deciding whether a final backup is necessary.
startup_shutdown_state() {
    local id="$1" info="$2" label="$3" job="${4:-}" record gid="" endpoint="${5:-}" host port
    if [[ -n "$job" ]]; then
        [[ "$job" =~ ^[a-f0-9]{32}$ ]] || return 1
        record="$STATEDIR/desktop/$job/job.json"
        jq -e --arg id "$id" --arg label "$label" --arg job "$job" '.job == $job and .instance_id == $id and .label == $label' "$record" >/dev/null || return 1
        gid="$(jq -r '.game' "$record")"
        valid_game_id "$gid" || return 1
    fi
    # Current provider status and a client watcher cannot prove lifetime activity.
    local KNOWN_HOSTS="$STATEDIR/known_hosts.$id"
    [[ -n "$endpoint" ]] || endpoint="$(verified_state_endpoint "$info" "$label")" || return 1
    host="${endpoint%%$'\t'*}"; port="${endpoint#*$'\t'}"
    STATE_SSH_TIMEOUT=15 state_ssh "$host" "$port" "python3 - $label $gid" < "$RUNTIME_DIR/shutdown_gate.py"
}

stop_game() {
    local id info
    if [[ "${4:-}" == --force ]]; then
        id="${1:-}"
        [[ "$id" =~ ^[0-9]+$ && "${2:-}" =~ ^vastgame-[0-9]+$ ]] || return 1
        warn "Force shutdown requested: skipping guest access and save backup; unbacked saves may be lost."
        echo "Destroying Vast instance $id..."
        destroy_verified "$id" "$2" || { warn "Force destruction not confirmed; instance identity retained."; return 1; }
        ok "Instance destroyed — GPU billing stopped"
        return 0
    fi

    if [[ -n "${1:-}" ]]; then
        id="$1"
        info="$(instance_json "$id")" || { warn "Cannot verify exact VM; no shutdown performed"; return 1; }
        jq -e --arg id "$id" --arg label "$2" '(.id|tostring) == $id and .label == $label' >/dev/null <<<"$info" || { warn "VM identity differs; no shutdown performed"; return 1; }
    else
        id="$(pick_instance)" || { echo "No vastgame instances found."; return 0; }
    fi


    # CLI stop uses the same guest lifetime check as the desktop X.
    if [[ -z "${1:-}" ]]; then
        info="$(instance_json "$id")" || { warn "Cannot verify VM; no shutdown performed"; return 1; }
        jq -e --arg id "$id" '(.id|tostring) == $id' >/dev/null <<<"$info" || return 1
    fi
    local label startup_state="unknown" endpoint
    local KNOWN_HOSTS="$STATEDIR/known_hosts.$id"
    label="$(jq -r '.label // empty' <<<"$info")"
    [[ "$label" =~ ^vastgame-[0-9]+$ ]] || { warn "VM identity differs; no shutdown performed"; return 1; }
    endpoint="$(verified_state_endpoint "$info" "$label")" || {
        warn "Cannot read guest activity: no authenticated connection. Backup and destruction skipped; VM still billing."
        return 1
    }
    startup_state="$(startup_shutdown_state "$id" "$info" "$label" "${3:-}" "$endpoint" || true)"
    if [[ "$startup_state" == unstarted ]]; then
        ok "Game never started; skipping backup"
    elif { echo "Backing up saves..."; safe_backup "$id" "$endpoint"; }; then

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

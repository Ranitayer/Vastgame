# ============================================================
# TEMPLATE
# ============================================================

setup_template() {
    local h

    echo
    bold "VASTGAME — template setup"

    read -rp "Template hash: " h

    [[ -n "$h" ]] ||
        die "Template hash cannot be empty."

    printf '%s\n' "$h" > "$TEMPLATE_FILE"
    chmod 600 "$TEMPLATE_FILE"

    ok "Template saved"
}

# ============================================================
# VAST INSTANCE HELPERS
# ============================================================

instance_json() {
    local id="$1"
    local out

    out="$(timeout 15s vastai show instance "$id" --raw 2>/dev/null)" ||
        return 1

    jq -c '
        if type == "array"
        then (.[0] // {})
        else .
        end
    ' <<<"$out"
}

all_vastgame_instances() {
    vastai show instances --raw 2>/dev/null |
        jq '
            [
                .[] |
                select(
                    (.label // "")
                    | startswith("vastgame-")
                )
            ]
        '
}

pick_instance() {
    local data
    local count
    local pick

    data="$(all_vastgame_instances)" ||
        return 1

    count="$(jq 'length' <<<"$data")"

    (( count > 0 )) ||
        return 1

    if (( count == 1 )); then
        jq -r '.[0].id' <<<"$data"
        return 0
    fi

    echo >&2

    {
        printf "NO\tID\tGPU\tSTATUS\t$/HR\n"

        jq -r '
            to_entries[] |
            [
                (.key + 1),
                .value.id,
                (.value.gpu_name // "-"),
                (.value.actual_status // "-"),
                (
                    "$" +
                    (
                        (
                            (.value.dph_total // 0)
                            * 1000
                            | round
                        ) / 1000
                        | tostring
                    )
                )
            ] |
            @tsv
        ' <<<"$data"

    } | column -t -s $'\t' >&2

    echo >&2

    read -rp "Choose instance [1-$count] or q: " pick

    [[ "$pick" =~ ^[qQ]$ ]] &&
        return 1

    [[ "$pick" =~ ^[0-9]+$ ]] ||
        die "Invalid selection."

    (( pick >= 1 && pick <= count )) ||
        die "Invalid selection."

    jq -r ".[$((pick - 1))].id" <<<"$data"
}

# A successful destroy response is only acceptance; retain local identity until
# the provider confirms the exact contract is absent from the account listing.
destroy_verified() {
    local id="$1" info listing attempt
    info="$(instance_json "$id")" || return 1
    jq -e --arg id "$id" '(.id|tostring) == $id and (.label|test("^vastgame-[0-9]+$"))' >/dev/null <<<"$info" || return 1
    vastai destroy instance "$id" -y || return 1
    for attempt in {1..18}; do
        listing="$(vastai show instances --raw 2>/dev/null)" || return 1
        if jq -e --arg id "$id" 'type == "array" and all(.[]; (.id|tostring) != $id)' >/dev/null <<<"$listing"; then
            if [[ "$(cat "$INSTANCE_FILE" 2>/dev/null || true)" == "$id" ]]; then rm -f "$INSTANCE_FILE"; fi
            return 0
        fi
        sleep 5
    done
    warn "Destruction not yet confirmed. Instance identity retained; check vastgame status."
    return 1
}

# ============================================================
# ERROR HANDLING
# ============================================================

extract_message() {
    jq -r '
        [
            .status_msg?,
            .status_message?,
            .error_msg?,
            .error?,
            .message?
        ]
        |
        map(
            select(
                type == "string"
                and length > 0
            )
        )
        |
        unique
        |
        join(" | ")
    '
}

record_instance_event() {
    local id="$1" info="$2"
    python3 "$CLIENT_DIR/failure_report.py" event "$STATEDIR" "$id" \
        --game "$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)" <<<"$info" 2>/dev/null || true
}

collect_failure_report() {
    local id="$1" reason="$2" info
    info="$(instance_json "$id" 2>/dev/null || true)"
    if ! jq -e --arg id "$id" '(.id|tostring) == $id' >/dev/null 2>&1 <<<"$info"; then
        info="$(cat "$STATEDIR/reports/$id/instance.json" 2>/dev/null || true)"
    fi
    if ! jq -e --arg id "$id" '(.id|tostring) == $id' >/dev/null 2>&1 <<<"$info"; then
        info="$(jq -n --arg id "$id" '{id:$id}')"
    fi
    python3 "$CLIENT_DIR/failure_report.py" failure "$STATEDIR" "$id" --reason "$reason" \
        --ip "${ip:-}" --game "$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)" <<<"$info" ||
        warn "Failure report collection incomplete; VM retained."
}

# Probe before guest HTTP exists; a missing domain alone can be a normal initial lookup.
check_startup_logs() {
    local id="$1" info="$2" render="$3" now log event latest
    now="$(date +%s)"
    if [[ "${VG_LOG_INSTANCE:-}" != "$id" ]]; then
        VG_LOG_INSTANCE="$id"
        VG_LOG_CHECKED=0
    fi
    (( now - ${VG_LOG_CHECKED:-0} >= 30 )) || return 0
    VG_LOG_CHECKED="$now"
    progress_run "$render" timeout 15s vastai logs "$id" --tail 100 || return 0
    log="$VG_POLL_OUTPUT"
    printf '%s\n' "$log" | python3 "$CLIENT_DIR/failure_report.py" log "$STATEDIR" "$id" 2>/dev/null || true
    if grep -Fqi 'GPU error, unable to start instance' <<<"$log"; then
        latest="$(instance_json "$id" 2>/dev/null || true)"
        # Logs survive host retries; a currently running guest overrides an old GPU error.
        if jq -e --arg id "$id" '(.id|tostring) == $id and .actual_status == "running"' >/dev/null 2>&1 <<<"$latest"; then
            record_instance_event "$id" "$latest"
            return 0
        fi
        destroy_failed_prompt "$id" "Vast reported GPU error, unable to start instance."
    fi
    event="$(grep -E '\[VASTGAME\]|^Bootstrap requires xz$' <<<"$log" | tail -n 1 || true)"
    if [[ "$event" == *'[VASTGAME] ERROR:'* || "$event" == 'Bootstrap requires xz' ]]; then
        destroy_failed_prompt "$id" "Startup failed before guest networking: $event"
    fi
    # Missing domains are normal while Vast creates/retries a guest. Keep waiting.
}

pause_boot_wait() {
    local id="$1" reason="$2"
    progress_clear
    echo
    bold "BOOT WAIT PAUSED — VM failure is not confirmed"
    collect_failure_report "$id" "Boot wait paused: $reason"
    warn "Watcher stopped waiting; VM retained and may still be billing."
    echo "Resume the same VM: vastgame force connect"
    exit 1
}

destroy_failed_prompt() {
    local id="$1"
    local reason="$2"
    local answer

    progress_clear
    echo
    printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
    bold "STARTUP FAILED"
    printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'

    collect_failure_report "$id" "$reason"

    echo
    warn "Instance $id may still be billing."

    local info
    info="$(instance_json "$id" 2>/dev/null || true)"
    if ! jq -e '.actual_status == "loading" or .actual_status == "provisioning"' >/dev/null 2>&1 <<<"$info"; then
        warn "VM retained to protect possible saves. Use vastgame stop for a verified backup and shutdown."
        exit 1
    fi
    read -rp "Destroy this unbooted VM now? [y/N]: " answer

    if [[ "$answer" =~ ^[yY]$ ]]; then

        if destroy_verified "$id"; then
            ok "Instance destroyed"
        else
            warn "Destroy failed. Check with: vastgame status"
        fi

    else
        warn "Instance retained. Use: vastgame connect after repair."
    fi

    exit 1
}

check_instance_failure() {
    local id="$1"
    local info
    local actual
    local intended
    local msg
    local listing

    info="${2:-}"
    if (( $# < 2 )); then info="$(instance_json "$id" 2>/dev/null || true)"; fi
    if ! jq -e --arg id "$id" '(.id | tostring) == $id' >/dev/null 2>&1 <<<"$info"; then
        # Confirm absence through the account list; an API outage is not deletion.
        listing="$(timeout 15s vastai show instances --raw 2>/dev/null)" || return 0
        if jq -e --arg id "$id" 'type == "array" and all(.[]; (.id | tostring) != $id)' >/dev/null 2>&1 <<<"$listing"; then
            if [[ "$(cat "$INSTANCE_FILE" 2>/dev/null || true)" == "$id" ]]; then rm -f "$INSTANCE_FILE"; fi
            die "Vast instance $id no longer exists. Stop this watcher and start a new instance."
        fi
        return 0
    fi

    record_instance_event "$id" "$info"

    actual="$(
        jq -r '.actual_status // "provisioning"' <<<"$info"
    )"

    intended="$(
        jq -r '.intended_status // "-"' <<<"$info"
    )"

    msg="$(extract_message <<<"$info")"

    case "$actual" in
        offline)
            # Vast can briefly report offline while the host reconnects during a pull.
            local now
            now="$(date +%s)"
            if [[ "${VG_OFFLINE_INSTANCE:-}" != "$id" || "${VG_OFFLINE_SINCE:-0}" == 0 ]]; then
                VG_OFFLINE_INSTANCE="$id"
                VG_OFFLINE_SINCE="$now"
            elif (( now - VG_OFFLINE_SINCE >= 90 )); then
                pause_boot_wait "$id" "Vast status remained offline for 90 seconds; guest availability is unconfirmed."
            fi
            ;;
        exited|stopped)
            destroy_failed_prompt \
                "$id" \
                "Vast entered terminal state: $actual"
            ;;
        *) VG_OFFLINE_SINCE=0 ;;
    esac

    # A running guest overrides historical error text; a planned stop alone is not failure.
    if [[ "$actual" != running && -n "$msg" ]] &&
       grep -Eqi \
       'GPU error, unable to start instance|does not support VMs|unsupported VM|failed to start|insufficient|unable to create|invalid image' \
       <<<"$msg"
    then

        destroy_failed_prompt \
            "$id" \
            "Vast reported: $msg"
    fi
}

# Shared eligibility for CLI selection and desktop browsing; callers add view limits only.
host_offer_query() {
    printf 'num_gpus=1 verified=any rentable=true vms_enabled=true gpu_arch=nvidia gpu_ram>=6 direct_port_count>=1 disk_space>=%s\n' "$DISK_GB"
}

# Vast's implicit response limit omits offers before local region filtering.
search_host_offers() {
    timeout 60s vastai search offers "$1" --storage "$DISK_GB" \
        --limit 10000 --order dph_total --raw
}

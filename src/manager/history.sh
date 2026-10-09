# ============================================================
# HOST RESTORE HISTORY
# ============================================================

record_restore_history() (
    local id="$1" metrics="$2" info machine label tmp
    jq -e '(.restore_mbps // 0) > 0 and (.machine_id // "") != "" and (.launch_label // "") != ""' \
        >/dev/null 2>&1 <<<"$metrics" || return 0
    info="$(instance_json "$id" 2>/dev/null)" || return 0
    machine="$(jq -r '.machine_id | tostring' <<<"$info")"
    label="$(jq -r '.label // ""' <<<"$info")"
    jq -e --arg machine "$machine" --arg label "$label" \
        '.machine_id == $machine and .launch_label == $label' \
        >/dev/null <<<"$metrics" || return 0
    exec 9>"$STATEDIR/host_history.lock"
    flock 9
    [[ -s "$HISTORY_FILE" ]] || printf '{}\n' > "$HISTORY_FILE"
    tmp="$(mktemp "$STATEDIR/restore-history.XXXXXX")"
    if jq --arg key "machine:$machine" --argjson metric "$metrics" --argjson now "$(date +%s)" '
        .[$key] = ((.[$key] // {}) + {
            restore_mbps: $metric.restore_mbps,
            last_restore: $now,
            restore_source: $metric.source
        })' "$HISTORY_FILE" > "$tmp"; then
        mv "$tmp" "$HISTORY_FILE"
    fi
    rm -f "$tmp"
)


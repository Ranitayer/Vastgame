# ============================================================
# HOST / ROUTE HISTORY
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

record_route_history() (
    local id="$1"
    local result="$2"
    local avg="${3:-999}"
    local jitter="${4:-999}"
    local loss="${5:-100}"

    local info
    local machine
    local host
    local key
    local tmp
    local now

    info="$(instance_json "$id" 2>/dev/null || true)"

    machine="$(
        jq -r '.machine_id // empty' <<<"$info" 2>/dev/null ||
        true
    )"

    host="$(
        jq -r '.host_id // empty' <<<"$info" 2>/dev/null ||
        true
    )"

    [[ -n "$machine" ]] || return 0

    key="machine:$machine"
    now="$(date +%s)"

    exec 9>"$STATEDIR/host_history.lock"
    flock 9
    if [[ ! -s "$HISTORY_FILE" ]] ||
       ! jq -e 'type == "object"' "$HISTORY_FILE" >/dev/null 2>&1
    then
        printf '{}\n' > "$HISTORY_FILE"
    fi

    tmp="$(mktemp)"

    jq \
        --arg key "$key" \
        --arg result "$result" \
        --arg host "$host" \
        --argjson avg "$avg" \
        --argjson jitter "$jitter" \
        --argjson loss "$loss" \
        --argjson now "$now" '
            (.[$key] // {
                passes: 0,
                failures: 0
            }) as $old
            |
            .[$key] = (
                $old
                +
                {
                    host_id: $host,
                    last_result: $result,
                    avg_rtt_ms: $avg,
                    jitter_ms: $jitter,
                    loss_pct: $loss,
                    last_test: $now,

                    passes:
                        (
                            ($old.passes // 0)
                            +
                            (if $result == "pass" then 1 else 0 end)
                        ),

                    failures:
                        (
                            ($old.failures // 0)
                            +
                            (if $result == "fail" then 1 else 0 end)
                        )
                }
            )
        ' \
        "$HISTORY_FILE" > "$tmp" &&
        mv "$tmp" "$HISTORY_FILE"

    rm -f "$tmp" 2>/dev/null || true
)


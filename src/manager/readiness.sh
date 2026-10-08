# ============================================================
# WAIT FOR FULL GAMING STACK
# ============================================================

wait_for_gaming() {
    local id="$1"
    local start
    local now
    local e
    local ip
    local info payload event
    local last_diagnostic=0

    tailscale status >/dev/null 2>&1 ||
        die "Tailscale is not running/logged in on this PC."

    echo
    bold "Stage 2/3 — VM bootstrap + Tailscale"

    start="$(date +%s)"
    VG_TAILSCALE_WAIT_PRINTED=0

    while true; do

        progress_run tailscale_wait_frame get_vast_ip "$id" || true
        ip="$VG_POLL_OUTPUT"

        [[ -n "$ip" ]] &&
            break

        now="$(date +%s)"
        e=$((now - start))

        progress_run tailscale_wait_frame instance_json "$id" || true
        info="$VG_POLL_OUTPUT"
        check_instance_failure "$id" "$info"

        e=$(( $(date +%s) - start ))
        print_tailscale_progress "$e"

        # Report the latest bootstrap failure even before its Tailscale HTTP service exists.
        if (( e >= 30 && e - last_diagnostic >= 30 )); then
            last_diagnostic="$e"
            progress_run tailscale_wait_frame timeout 15s vastai logs "$id" --tail 80 || true
            event="$(grep -E '\[VASTGAME\]|^Bootstrap requires xz$' <<<"$VG_POLL_OUTPUT" | tail -n 1 || true)"
            if [[ "$event" == *'[VASTGAME] ERROR:'* || "$event" == 'Bootstrap requires xz' ]]; then
                destroy_failed_prompt "$id" "Bootstrap failed before Tailscale connected: $event"
            fi
        fi

        (( e < TAILSCALE_TIMEOUT )) ||
            destroy_failed_prompt \
                "$id" \
                "vast-gaming did not appear on Tailscale within $(elapsed "$TAILSCALE_TIMEOUT")."

        progress_run tailscale_wait_frame sleep 5
    done

    progress_clear
    ok "Tailscale online: $ip"

    if ! qualify_local_route "$id" "$ip"; then
        echo
        warn "Host failed local Moonlight route requirements."
        warn "Instance $id was retained to protect any existing saves; it may still be billing."
        die "Route check failed. Retry with vastgame connect, or save and stop with vastgame stop."

    fi

    echo
    bold "Stage 3/3 — Optimized restore + Wolf"

    start="$(date +%s)"
    VG_BOOTSTRAP_PAYLOAD=""
    VG_TAILSCALE_WAIT_PRINTED=0
    local last_health=0 interval=0.5
    [[ -t 1 ]] || interval=15
    VG_STRUCTURED_PROGRESS=0

    while true; do
        now="$(date +%s)"
        e=$((now - start))
        if (( e - last_health >= 15 || last_health == 0 )); then
            progress_clear
            progress_run bootstrap_wait_frame instance_json "$id" || true
            info="$VG_POLL_OUTPUT"
            check_instance_failure "$id" "$info"
            last_health=$((e + 1))
        fi
        progress_run bootstrap_wait_frame curl -fsS --connect-timeout 2 --max-time 3 "http://$ip:$STATUS_PORT/progress.json" || true
        payload="$VG_POLL_OUTPUT"
        if jq -e '.version == 1 and (.tasks | type == "object")' >/dev/null 2>&1 <<<"$payload"; then
            VG_BOOTSTRAP_PAYLOAD="$payload"
        else
            VG_BOOTSTRAP_PAYLOAD=""
        fi
        e=$(( $(date +%s) - start ))
        print_bootstrap_progress "$id" "$ip" "$e" "$payload"
        if (( VG_BOOTSTRAP_READY == 1 )) && progress_run bootstrap_wait_frame curl -fsS \
            --connect-timeout 2 --max-time 3 \
            "http://$ip:47989/serverinfo" >/dev/null 2>&1; then
            progress_clear
            ok "Restore complete; Wolf streaming server is responding"
            record_restore_history "$id" "$VG_RESTORE_METRICS" || true
            launch_moonlight "$ip" || return 1
            return 0
        fi
        if (( e >= WOLF_TIMEOUT )); then
            progress_clear
            destroy_failed_prompt "$id" "Wolf did not become ready within $(elapsed "$WOLF_TIMEOUT")."
        fi
        progress_run bootstrap_wait_frame sleep "$interval"
    done
}

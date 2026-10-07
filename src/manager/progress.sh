# ============================================================
# BOOTSTRAP PROGRESS OVER TAILSCALE HTTP
# ============================================================

bootstrap_log() {
    local ip="$1"

    curl \
        -fsS \
        --connect-timeout 2 \
        --max-time 5 \
        "http://$ip:$STATUS_PORT/bootstrap.log" \
        2>/dev/null
}

VG_PROGRESS_LINES=0
VG_STRUCTURED_PROGRESS=0
VG_BOOTSTRAP_READY=0
VG_RESTORE_METRICS='{}'

progress_clear() {
    if [[ -t 1 ]] && (( VG_PROGRESS_LINES > 0 )); then
        printf '\033[%sA\033[J' "$VG_PROGRESS_LINES"
    fi
    VG_PROGRESS_LINES=0
}

# Animate cached state while a slow probe runs; never poll the provider at frame rate.
VG_PROGRESS_ANIMATION_PID=""
progress_stop_animation() {
    if [[ -n "$VG_PROGRESS_ANIMATION_PID" ]]; then
        kill "$VG_PROGRESS_ANIMATION_PID" 2>/dev/null || true
        wait "$VG_PROGRESS_ANIMATION_PID" 2>/dev/null || true
        VG_PROGRESS_ANIMATION_PID=""
    fi
}
trap 'progress_stop_animation' EXIT
trap 'progress_stop_animation; exit 143' TERM

progress_run() {
    local render="$1" result=0
    shift
    if [[ -t 1 ]]; then
        "$render"
        (
            trap 'kill $(jobs -pr) 2>/dev/null || true; exit 0' TERM INT
            while true; do sleep 0.5 & wait $!; "$render"; done
        ) 8>&- &
        VG_PROGRESS_ANIMATION_PID=$!
    fi
    if VG_POLL_OUTPUT="$("$@" 2>/dev/null)"; then result=0; else result=$?; fi
    progress_stop_animation
    return "$result"
}

vast_wait_frame() { print_vast_progress "${actual:-provisioning}" "${msg:-}" "$(( $(date +%s) - start ))"; }
tailscale_wait_frame() { print_tailscale_progress "$(( $(date +%s) - start ))"; }
bootstrap_wait_frame() {
    local seconds="$(( $(date +%s) - start ))"
    if [[ -n "${VG_BOOTSTRAP_PAYLOAD:-}" ]]; then
        print_bootstrap_progress "$id" "$ip" "$seconds" "$VG_BOOTSTRAP_PAYLOAD"
    else
        print_tailscale_progress "$seconds" "Waiting for bootstrap progress"
    fi
}

# Vast supplies milestones, not a reliable image-pull percentage or ETA.
VG_VAST_LAST_STATUS=""
VG_VAST_ACTIVITY=""
VG_VAST_ACTIVITY_AT=0

print_vast_progress() {
    local actual="$1" message="$2" seconds="$3" phase width frame key
    case "$actual" in
        running) phase=3 ;;
        created) phase=2 ;;
        loading) phase=1 ;;
        *) phase=0 ;;
    esac
    if [[ -n "$message" && "$message" != "$VG_VAST_ACTIVITY" ]]; then
        VG_VAST_ACTIVITY="$message"
        VG_VAST_ACTIVITY_AT="$seconds"
    fi
    key="$actual|$VG_VAST_ACTIVITY"
    # Redirected output is a concise event log; terminals get a live panel.
    if [[ ! -t 1 && "$key" == "$VG_VAST_LAST_STATUS" ]]; then
        return 0
    fi
    VG_VAST_LAST_STATUS="$key"
    width="$(tput cols 2>/dev/null || echo 80)"
    frame="$(python3 - "$phase" "$seconds" "$width" "$VG_VAST_ACTIVITY" "$VG_VAST_ACTIVITY_AT" <<'PY_VAST_PROGRESS'
import sys, time
phase, seconds, width = map(int, sys.argv[1:4])
width = max(25, min(width, 120))
activity, activity_at = sys.argv[4], int(sys.argv[5])
labels = ['Allocating host', 'Preparing VM image', 'Booting VM', 'VM running']
def duration(value):
    return f'{value // 60}m {value % 60:02d}s'
def emit(value):
    print(''.join(c for c in value if c.isprintable())[:width-1])
spinner = '|/-\\'[int(time.time()*2) % 4] if phase < 3 else 'OK'
emit(f'VASTGAME  |  {labels[phase]}  |  Elapsed {duration(seconds)}')
steps = ['Host', 'Image', 'Boot']
emit('  ' + '  →  '.join(f'[{"OK" if i < phase else spinner if i == phase else " "}] {label}'
                         for i, label in enumerate(steps)))
lines = [line.strip() for line in activity.splitlines() if line.strip()]
# Keep the most recent substantive layer update instead of a truncated layer ID.
lines = [line for line in lines if not line.endswith(':')] or lines
if lines:
    age = seconds - activity_at
    prefix = f'No new host update for {duration(age)} · ' if age >= 30 and phase < 3 else ''
    emit('  ' + prefix + ' · '.join(lines[-2:]))
else:
    emit('  Waiting for the host to report startup activity')
PY_VAST_PROGRESS
)"
    progress_clear
    printf '%s\n' "$frame"
    if [[ -t 1 ]]; then
        VG_PROGRESS_LINES="$(printf '%s\n' "$frame" | wc -l)"
    fi
}

print_tailscale_progress() {
    local seconds="$1" text="${2:-Waiting for vast-gaming on Tailscale...}" width line spinner
    if [[ ! -t 1 && "${VG_TAILSCALE_WAIT_PRINTED:-0}" == 1 ]]; then
        return 0
    fi
    VG_TAILSCALE_WAIT_PRINTED=1
    width="$(tput cols 2>/dev/null || echo 80)"
    (( width > 1 )) || width=80
    spinner='|/-\\'
    local tick="$(date +%s%N)"
    tick=$((10#$tick / 500000000))
    line="[${spinner:$((tick % 4)):1}] $text | Elapsed $(elapsed "$seconds")"
    progress_clear
    printf '%.*s\n' "$((width - 1))" "$line"
    if [[ -t 1 ]]; then
        VG_PROGRESS_LINES=1
    fi
}

print_bootstrap_progress() {
    local id="$1" ip="$2" elapsed_s="${3:-0}" payload frame width reason
    VG_BOOTSTRAP_READY=0
    VG_RESTORE_METRICS='{}'
    if (( $# >= 4 )); then
        payload="$4"
    else
        payload="$(curl -fsS --connect-timeout 2 --max-time 3 \
            "http://$ip:$STATUS_PORT/progress.json" 2>/dev/null || true)"
    fi
    if ! jq -e '.version == 1 and (.tasks | type == "object")' \
        >/dev/null 2>&1 <<<"$payload"; then
        progress_clear
        if (( VG_STRUCTURED_PROGRESS == 1 )); then
            echo "Progress connection unavailable; waiting to reconnect (VM may still be working)."
            [[ ! -t 1 ]] || VG_PROGRESS_LINES=1
        else
            # Existing VMs with the old bootstrap still have the log endpoint.
            VG_BOOTSTRAP_READY=1
            print_bootstrap_progress_legacy "$id" "$ip"
        fi
        return 0
    fi
    VG_STRUCTURED_PROGRESS=1
    VG_RESTORE_METRICS="$(jq -c '.tasks.game // {}' <<<"$payload")"
    reason="$(jq -r '.tasks.error.action // empty' <<<"$payload")"
    if [[ -n "$reason" ]]; then
        progress_clear
        destroy_failed_prompt "$id" "$reason"
    fi
    if jq -e '.tasks.phase.action == "READY"' >/dev/null <<<"$payload"; then
        VG_BOOTSTRAP_READY=1
    fi
    width="$(tput cols 2>/dev/null || echo 80)"
    frame="$(python3 - "$width" "$elapsed_s" "$payload" <<'PY_RENDER'
import json, math, sys, time

data = json.loads(sys.argv[3])
tasks = data['tasks']
width = max(25, min(int(sys.argv[1]), 140))
elapsed = int(sys.argv[2])
def duration(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}m {seconds % 60:02d}s'
def number(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else 0
def emit(text):
    print(''.join(c for c in text if c.isprintable())[:width-1])

phase = tasks.get('phase', {}).get('action', 'Preparing')
emit(f'VASTGAME  |  {phase}  |  Elapsed {duration(elapsed)}')
for key, label in [('core', 'Runtime'), ('state', 'Saves / Lutris'),
                   ('identity', 'Pairing'), ('game', 'Game'),
                   ('images', 'Wolf / Lutris images'), ('proton', 'Proton'),
                   ('dx12', 'DX12'), ('prefix', 'Game prefix'), ('setup', 'GPU / streaming')]:
    item = tasks.get(key, {})
    state = item.get('state', 'pending')
    action = str(item.get('action', 'Waiting'))
    total, done = number(item.get('total')), number(item.get('bytes'))
    if state == 'done':
        emit(f'  [OK] {label}: {action}')
    elif state == 'error':
        emit(f'  [!]  {label}: {action}')
    elif total and state == 'running':
        fraction = min(done / total, 1)
        # Bytes consumed do not mean the downstream command has finished.
        transfer_only = 'streamed_bytes' in item
        pct = min(100 if transfer_only else 99, int(fraction * 100))
        filled = min(20 if transfer_only else 19, int(fraction * 20))
        emit(f'  {label}: {action}  [{"#"*filled}{"-"*(20-filled)}] {pct}%')
        speed = number(item.get('speed'))
        eta = item.get('eta')
        age = time.time() - number(item.get('updated'))
        detail = f'    {done/1e9:.2f} / {total/1e9:.2f} GB'
        if transfer_only and done >= total:
            detail += ' | Transfer complete'
        elif age > 10:
            detail += ' | awaiting fresh measurements'
        else:
            detail += f' | {speed/1e6:.1f} MB/s' if speed else ' | measuring speed'
            detail += f' | ETA {duration(eta)}' if isinstance(eta, (int, float)) and math.isfinite(eta) and eta >= 0 else ' | ETA calculating'
        emit(detail)
        if 'streamed_bytes' in item:
            emit(f'    Verified parts: {int(number(item.get("verified_parts")))}/{int(number(item.get("total_parts")))}')
            emit(f'    Extraction input consumed: {number(item["streamed_bytes"])/1e9:.2f} / {total/1e9:.2f} GB')
    else:
        marker = '|/-\\'[int(time.time()*2) % 4] if state == 'running' else '.'
        emit(f'  [{marker}]  {label}: {action}')
emit('ETA covers remaining transfer; final installation checks may take longer.')
PY_RENDER
    )" || return 0
    progress_clear
    printf '%s\n' "$frame"
    if [[ -t 1 ]]; then
        VG_PROGRESS_LINES="$(printf '%s\n' "$frame" | wc -l)"
    fi
}

print_bootstrap_progress_legacy() {
    local id="$1"
    local ip="$2"
    local log
    local phase
    local line
    local reason

    log="$(bootstrap_log "$ip" || true)"

    if [[ -z "$log" ]]; then
        echo "  VM: waiting for bootstrap progress service..."
        return 0
    fi

    # Reject bad gaming latency before the large Drive restore.
    if grep -Eq \
        '\[VASTGAME\] ERROR: Latency [0-9]+ ms exceeds [0-9]+ ms limit' \
        <<<"$log"
    then
        reason="$(
            tr '
' '
' <<<"$log" |
                grep -E \
                    '\[VASTGAME\] ERROR: Latency [0-9]+ ms exceeds [0-9]+ ms limit' |
                tail -n1 |
                sed 's/^\[VASTGAME\] ERROR: //'
        )"

        echo
        warn "$reason"
        destroy_failed_prompt "$id" "$reason"

    fi

    if grep -q '\[VASTGAME\] ERROR:' <<<"$log"; then
        echo
        echo "Bootstrap error:"
        echo

        tr '
' '
' <<<"$log" |
            tail -n 60

        destroy_failed_prompt \
            "$id" \
            "The VM bootstrap script reported an error."
    fi

    phase="$(
        grep -o \
            '\[VASTGAME\] PHASE=[A-Z]*' \
            <<<"$log" |
            tail -n1 |
            cut -d= -f2 ||
        true
    )"

    case "$phase" in

        BOOT)
            echo "  VM: starting base system and Tailscale"
            ;;

        LATENCY)
            echo "  Network: validating Moonlight latency"

            line="$(
                tr '
' '
' <<<"$log" |
                    grep -E \
                        'Latency attempt|Best latency|Latency gate passed' |
                    tail -n1 ||
                true
            )"

            [[ -n "$line" ]] &&
                printf '    %s
' "$line"
            ;;

        CORE)
            echo "  Runtime: restoring optimized core (~13 MB)"

            line="$(
                tr '
' '
' <<<"$log" |
                    grep -E 'Transferred:.*(ETA|/)' |
                    tail -n1 ||
                true
            )"

            [[ -n "$line" ]] &&
                printf '    %s
' "$line"
            ;;

        RESTORE)
            echo "  State: preparing generic game directories"

            line="$(
                tr '
' '
' <<<"$log" |
                    grep -E \
                        'Generic game state initialized|Transferred:.*(ETA|/)' |
                    tail -n1 ||
                true
            )"

            [[ -n "$line" ]] &&
                printf '    %s
' "$line"
            ;;

        DRIVE)
            echo "  Parallel restore:"

            if grep -q '\[VASTGAME\] GAME_SYNC=DONE' <<<"$log"; then
                echo "    ✓ Game library ready"
            else
                echo "    • Game library restoring"
            fi

            if grep -Eq \
                '\[VASTGAME\] GOW_SYNC=DONE|GOW images already available' \
                <<<"$log"
            then
                echo "    ✓ Wolf/Lutris images ready"
            else
                echo "    • Wolf/Lutris images restoring"
            fi

            line="$(
                tr '
' '
' <<<"$log" |
                    grep -E 'Transferred:.*(ETA|/)' |
                    tail -n2 ||
                true
            )"

            if [[ -n "$line" ]]; then
                while IFS= read -r l; do
                    printf '    %s
' "$l"
                done <<<"$line"
            else
                echo "    Waiting for transfer statistics..."
            fi
            ;;

        DOCKER)
            echo "  GPU: validating Docker/NVIDIA runtime"
            ;;

        WOLF)
            echo "  Wolf: starting streaming stack"
            ;;

        READY)
            echo "  VM: gaming stack marked ready"
            ;;

        *)
            echo "  VM: preparing gaming environment"

            line="$(
                tr '
' '
' <<<"$log" |
                    tail -n1
            )"

            [[ -n "$line" ]] &&
                printf '    %s
' "$line"
            ;;
    esac

    return 0
}


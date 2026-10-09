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
VG_PROGRESS_INLINE=0
VG_STRUCTURED_PROGRESS=0
VG_BOOTSTRAP_READY=0
VG_RESTORE_METRICS='{}'

progress_clear() {
    if [[ -t 1 ]] && (( VG_PROGRESS_INLINE == 1 )); then
        printf '\r\033[K'
    fi
    VG_PROGRESS_INLINE=0
    if [[ -t 1 ]] && (( VG_PROGRESS_LINES > 0 )); then
        printf '\033[%sA\033[J' "$VG_PROGRESS_LINES"
    fi
    VG_PROGRESS_LINES=0
}

VG_PROGRESS_LAST_KEY=""
progress_line() {
    local line="$1" key="$2"
    if [[ ! -t 1 && "$key" == "$VG_PROGRESS_LAST_KEY" ]]; then return 0; fi
    VG_PROGRESS_LAST_KEY="$key"
    progress_clear
    if [[ -t 1 ]]; then
        printf '%s' "$line"
        VG_PROGRESS_INLINE=1
    else
        printf '%s\n' "$line"
    fi
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
            # Account for rendering time instead of adding it to each 100 ms frame.
            deadline=$(( ${EPOCHREALTIME/./} + 100000 ))
            while true; do
                remaining=$(( deadline - ${EPOCHREALTIME/./} ))
                if (( remaining > 0 )); then
                    printf -v delay '0.%06d' "$remaining"
                    sleep "$delay" & wait $!
                fi
                "$render"
                deadline=$(( deadline + 100000 ))
                now_us="${EPOCHREALTIME/./}"
                (( deadline > now_us )) || deadline=$(( now_us + 100000 ))
            done
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
VG_VAST_PHASE=0

print_vast_progress() {
    local actual="$1" message="$2" seconds="$3" phase width frame key
    case "$actual" in
        running) phase=3 ;;
        created) phase=2 ;;
        loading) phase=1 ;;
        *) phase=0 ;;
    esac
    # Transient provider regressions must not reset completed milestones.
    if (( phase < VG_VAST_PHASE )); then phase="$VG_VAST_PHASE"; fi
    VG_VAST_PHASE="$phase"
    if [[ -n "$message" && "$message" != "$VG_VAST_ACTIVITY" ]]; then
        VG_VAST_ACTIVITY="$message"
        VG_VAST_ACTIVITY_AT="$seconds"
    fi
    key="$phase"
    # Redirected output is a concise event log; terminals get a live panel.
    if [[ ! -t 1 && "$key" == "$VG_VAST_LAST_STATUS" ]]; then
        return 0
    fi
    VG_VAST_LAST_STATUS="$key"
    width="$(tput cols 2>/dev/null || echo 80)"
    frame="$(python3 - "$phase" "$seconds" "$width" "$VG_VAST_ACTIVITY" "$VG_VAST_ACTIVITY_AT" <<'PY_VAST_PROGRESS'
import signal, sys, time
# Stopping the animation can close this frame's command-substitution pipe.
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
phase, seconds, width = map(int, sys.argv[1:4])
width = max(25, min(width, 120))
activity, activity_at = sys.argv[4], int(sys.argv[5])
labels = ['Allocating host', 'Preparing VM image', 'Booting VM', 'VM running']
def duration(value):
    return f'{value // 60}m {value % 60:02d}s'
def emit(value):
    print(''.join(c for c in value if c.isprintable())[:width-1])
spinner = '|/-\\'[int(time.time()*10) % 4] if phase < 3 else 'OK'
steps = ['Host', 'Image', 'Boot']
line = f'VASTGAME | {labels[phase]} | Elapsed {duration(seconds)}'
line += ' | ' + ' · '.join(f'{label}:{"OK" if i < phase else spinner if i == phase else "wait"}'
                         for i, label in enumerate(steps))
lines = [value.strip() for value in activity.splitlines() if value.strip()]
lines = [value for value in lines if not value.endswith(':')] or lines
age = seconds - activity_at
if age >= 30 and phase < 3:
    line += f' | No new host update for {duration(age)}'
elif lines:
    line += ' | ' + lines[-1]
emit(line)
PY_VAST_PROGRESS
)"
    progress_clear
    if [[ -t 1 ]]; then
        printf '%s' "$frame"
        VG_PROGRESS_INLINE=1
    else
        printf '%s\n' "$frame"
    fi
}

print_tailscale_progress() {
    local seconds="$1" text="${2:-Waiting for vast-gaming on Tailscale...}" width line spinner
    width="$(tput cols 2>/dev/null || echo 80)"
    (( width > 1 )) || width=80
    spinner='|/-\\'
    local tick="$(date +%s%N)"
    tick=$((10#$tick / 100000000))
    line="[${spinner:$((tick % 4)):1}] $text | Elapsed $(elapsed "$seconds")"
    printf -v line '%.*s' "$((width - 1))" "$line"
    progress_line "$line" "tailscale:$text"
}

print_bootstrap_progress() {
    local id="$1" ip="$2" elapsed_s="${3:-0}" payload frame width reason key
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
        if (( VG_STRUCTURED_PROGRESS == 1 )); then
            print_tailscale_progress "$elapsed_s" "Progress unavailable; waiting to reconnect"
        else
            # Existing VMs with the old bootstrap still have the log endpoint.
            VG_BOOTSTRAP_READY=1
            print_bootstrap_progress_legacy "$id" "$ip"
        fi
        return 0
    fi
    if [[ "${VASTGAME_DESKTOP:-0}" == 1 ]]; then
        local structured
        if structured="$(python3 "$CLIENT_DIR/startup_progress.py" <<<"$payload")"; then
            printf '[VASTGAME_PROGRESS]%s\n' "$structured"
        fi
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
import json, math, signal, sys, time
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

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
labels = [('game', 'Game'), ('images', 'Images'), ('core', 'Runtime'),
          ('state', 'Saves'), ('identity', 'Pairing'), ('proton', 'Proton'),
          ('dx12', 'DX12'), ('prefix', 'Prefix'), ('setup', 'GPU/stream')]
active = next(((key, label, tasks[key]) for key, label in labels
               if tasks.get(key, {}).get('state') == 'error'), None)
active = active or next(((key, label, tasks[key]) for key, label in labels
                        if tasks.get(key, {}).get('state') == 'running'), None)
spinner = '|/-\\'[int(time.time()*10) % 4]
line = f'VASTGAME | {phase} | {duration(elapsed)} | [{spinner}] '
percent = None
if active:
    key, label, item = active
    total, done = number(item.get('total')), number(item.get('bytes'))
    if total:
        transfer_only = 'streamed_bytes' in item
        percent = min(100 if transfer_only else 99, int(done/total*100))
        line += f'{label} {percent}% | {done/1e9:.2f}/{total/1e9:.2f} GB'
        if transfer_only and done >= total:
            line += ' | Transfer complete; finalizing'
        elif time.time()-number(item.get('updated')) > 10:
            line += ' | awaiting fresh measurements'
        else:
            speed, eta = number(item.get('speed')), item.get('eta')
            line += f' | {speed/1e6:.1f} MB/s' if speed else ' | measuring speed'
            line += f' ETA {duration(eta)}' if isinstance(eta, (int, float)) and math.isfinite(eta) and eta >= 0 else ' ETA --'
        if transfer_only:
            line += f' | Verified {int(number(item.get("verified_parts")))}/{int(number(item.get("total_parts")))}'
    else:
        line += f'{label}: {item.get("action", "Working")}'
else:
    line += 'Waiting for stage progress'
completed = sum(tasks.get(key, {}).get('state') == 'done' for key, _ in labels)
line += f' | Ready {completed}/{len(labels)}'
# Logs record substantive changes, not elapsed time, speed jitter or spinner frames.
signature = [phase, percent, [(key, tasks.get(key, {}).get('state'), tasks.get(key, {}).get('action')) for key, _ in labels]]
print(json.dumps(signature, separators=(',', ':')))
emit(line)
PY_RENDER
    )" || return 0
    key="${frame%%$'\n'*}"
    frame="${frame#*$'\n'}"
    progress_line "$frame" "bootstrap:$key"
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

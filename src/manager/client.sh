# ============================================================
# MOONLIGHT
# ============================================================

show_game_log() {
    local ip="${1:-$(get_vast_ip || true)}"
    [[ -n "$ip" ]] || die "No unambiguous online Vastgame peer"
    curl -fsS --connect-timeout 3 --max-time 10 "http://$ip:$STATUS_PORT/launch.json" | python3 -m json.tool || true
    curl -fsS --connect-timeout 3 --max-time 10 "http://$ip:$STATUS_PORT/game.log" || return 1
}

wait_for_game_launch() {
    local ip="$1" session_id="$2" requested="$3" start now record state action last=""
    start="$(date +%s)"
    while (( $(date +%s) - start < 660 )); do
        record="$(curl -fsS --connect-timeout 2 --max-time 3 "http://$ip:$STATUS_PORT/launch.json" 2>/dev/null || true)"
        if jq -e --arg sid "$session_id" --argjson requested "$requested" \
            '.session_id == $sid and (.updated // 0) > $requested' >/dev/null 2>&1 <<<"$record"; then
            state="$(jq -r '.state' <<<"$record")"
            action="$(jq -r '.action' <<<"$record")"
            if [[ "$action" != "$last" ]]; then echo "Game: $action"; last="$action"; fi
            case "$state" in
                running) ok "Game process detected. Use vastgame logs game for diagnostics."; return 0 ;;
                error|exited) show_game_log "$ip"; warn "Game launch did not stay running. VM retained."; return 1 ;;
            esac
        fi
        if ! kill -0 "$moonlight_pid" 2>/dev/null; then
            warn "Moonlight exited before game startup was confirmed."
            tail -n 40 "$STATEDIR/moonlight.log"
            show_game_log "$ip" || true
            return 1
        fi
        now="$(date +%s)"
        if (( (now - start) % 15 < 3 )); then echo "Waiting for the prepared game to start ($(elapsed "$((now-start))"))..."; fi
        sleep 3
    done
    warn "Game startup was not confirmed within 11 minutes. VM retained."
    show_game_log "$ip" || true
    return 1
}

native_screen_resolution() {
    if [[ "${VASTGAME_WINDOWS:-0}" == 1 ]]; then vastgame-native resolution; return; fi
    local resolution=""
    if command -v kscreen-doctor >/dev/null 2>&1; then
        resolution="$(kscreen-doctor -j 2>/dev/null | jq -r '
          [.outputs[] | select(.connected and .enabled)] | sort_by(.priority // 999) | .[0] as $o |
          $o.modes[] | select(.id == ($o.preferredModes[0] // $o.currentModeId)) |
          if ($o.rotation == 2 or $o.rotation == 8) then "\(.size.height)x\(.size.width)"
          else "\(.size.width)x\(.size.height)" end' 2>/dev/null | head -n 1 || true)"
    fi
    if [[ ! "$resolution" =~ ^[0-9]+x[0-9]+$ ]] && command -v xrandr >/dev/null 2>&1; then
        resolution="$(xrandr --current 2>/dev/null | awk '
          / connected / { connected=1; primary=($0 ~ /primary/); next }
          /^[^ ]/ { connected=0 }
          connected && /\+/ { if (!first) first=$1; if (primary) preferred=$1 }
          END { print preferred ? preferred : first }')"
    fi
    [[ "$resolution" =~ ^[0-9]+x[0-9]+$ ]] || return 1
    printf '%s\n' "$resolution"
}

native_screen_refresh() {
    if [[ "${VASTGAME_WINDOWS:-0}" == 1 ]]; then vastgame-native refresh; return; fi
    local rate=""
    if command -v kscreen-doctor >/dev/null 2>&1; then
        rate="$(kscreen-doctor -j 2>/dev/null | jq -r '
          [.outputs[] | select(.connected and .enabled)] | sort_by(.priority // 999) | .[0] as $o |
          $o.modes[] | select(.id == $o.currentModeId) | .refreshRate | round' 2>/dev/null | head -n1 || true)"
    fi
    if [[ ! "$rate" =~ ^[0-9]+$ ]] && command -v xrandr >/dev/null 2>&1; then
        rate="$(xrandr --current 2>/dev/null | awk '
          / connected / { active=1; primary=($0 ~ /primary/); next }
          /^[^ ]/ { active=0 }
          active && /\*/ { for(i=2;i<=NF;i++) if($i ~ /\*/) {
            value=$i; gsub(/[^0-9.]/,"",value); value=int(value+0.5)
            if (!first) first=value; if(primary) preferred=value
          }}
          END { print preferred ? preferred : first }')"
    fi
    [[ "$rate" =~ ^[0-9]+$ ]] && (( rate >= 10 && rate <= 1000 )) || rate=60
    printf '%s\n' "$rate"
}

stream_settings_file() {
    if [[ "${VASTGAME_WINDOWS:-0}" == 1 ]]; then
        jq -er '.application + "/stream.json"' "$CFGDIR/windows.json"
    else
        printf '%s\n' "$CFGDIR/stream.json"
    fi
}

read_stream_settings() {
    local path
    path="$(stream_settings_file)" || return 1
    python3 "$CLIENT_DIR/stream_settings.py" read "$path" "${VASTGAME_WINDOWS:-0}"
}

edit_stream_settings() {
    local path defaults
    local -a editor
    path="$(stream_settings_file)" || die "Cannot locate stream settings; complete Windows setup first"
    if [[ ! -e "$path" ]]; then
        defaults="$(read_stream_settings)" || die "Cannot create default stream settings"
        mkdir -p "$(dirname "$path")"
        printf '%s\n' "$defaults" > "$path"
        chmod 600 "$path"
    fi
    echo "Stream settings: $path"
    echo 'Save and close the editor. Reconnect Moonlight to apply changes.'
    if [[ "${VASTGAME_WINDOWS:-0}" == 1 ]]; then
        vastgame-native edit-stream "$path" || return 1
    elif [[ -n "${VISUAL:-${EDITOR:-}}" ]]; then
        defaults="$(python3 -c 'import shlex,sys; print("\n".join(shlex.split(sys.argv[1])))' "${VISUAL:-$EDITOR}")" || die "Invalid editor setting"
        mapfile -t editor <<<"$defaults"
        case "${editor[0]##*/}" in
            kate|kwrite) editor+=(--block) ;;
            code) editor+=(--wait) ;;
        esac
        "${editor[@]}" "$path" || return 1
    else
        local found=0
        for defaults in kate kwrite gedit mousepad code nano vi; do
            if command -v "$defaults" >/dev/null 2>&1; then
                case "$defaults" in
                    kate|kwrite) "$defaults" --block "$path" ;;
                    code) "$defaults" --wait "$path" ;;
                    *) "$defaults" "$path" ;;
                esac
                found=1
                break
            fi
        done
        (( found )) || die "No text editor found. Edit $path manually or set EDITOR"
    fi
    local saved
    saved="$(read_stream_settings)" || die "Stream settings were not saved as valid JSON: $path"
    printf 'Saved stream settings: %s at %s FPS\n' "$(jq -r .resolution <<<"$saved")" "$(jq -r .fps <<<"$saved")"
}

prepare_performance_hud() {
    mkdir -p "$NATIVE_DIR"
    local source="$CLIENT_DIR/moonlight_hud.cpp" menu="$CLIENT_DIR/stream_menu.cpp" header="$CLIENT_DIR/stream_menu.h" library="$NATIVE_DIR/moonlight_hud.so"
    [[ -f "$source" && -f "$menu" && -f "$header" && -f "$CLIENT_DIR/performance_hud.py" && -f "$CLIENT_DIR/vm_telemetry.py" ]] || return 1
    if [[ ! -s "$library" || "$source" -nt "$library" || "$menu" -nt "$library" || "$header" -nt "$library" ]]; then
        command -v g++ >/dev/null && command -v pkg-config >/dev/null || return 1
        local -a flags gl_flags
        read -ra flags <<<"$(pkg-config --cflags --libs sdl2 SDL2_ttf)" || return 1
        if pkg-config --exists glesv2; then
            read -ra gl_flags <<<"$(pkg-config --cflags --libs glesv2)"
            flags+=("${gl_flags[@]}" -DVASTGAME_GLES_MENU)
        fi
        g++ -std=c++17 -O2 -Wall -Wextra -shared -fPIC "$source" "$menu" -o "$library.tmp" "${flags[@]}" -ldl -pthread || return 1
        mv "$library.tmp" "$library"
    fi
    printf '%s\n' "$library"
}

sync_game_resolution() (
    local id="$1" game="$2" session="$3" resolution="$4" info label endpoint host port
    local KNOWN_HOSTS="$STATEDIR/known_hosts.$id"
    [[ "$resolution" =~ ^[0-9]+x[0-9]+$ && "$session" =~ ^[a-f0-9]{32}$ ]] || return 1
    valid_game_id "$game" || return 1
    info="$(instance_json "$id")" || return 1
    jq -e --arg id "$id" '(.id|tostring) == $id' >/dev/null <<<"$info" || return 1
    label="$(jq -r '.label // empty' <<<"$info")"
    [[ "$label" =~ ^vastgame-[0-9]+$ ]] || return 1
    endpoint="$(verified_state_endpoint "$info" "$label")" || return 1
    host="${endpoint%%$'\t'*}"; port="${endpoint#*$'\t'}"
    STATE_SSH_TIMEOUT=20 state_ssh "$host" "$port" \
        "python3 -c 'import sys; source=sys.stdin.read(); exec(source)' host $label $game $session $resolution" \
        < "$RUNTIME_DIR/display_mode.py"
)

launch_moonlight() {
    local ip="$1"
    verify_peer_identity "$ip" || die "VM launch identity changed; refusing Moonlight connection"
    local list_out
    local rc
    local app="" session="" session_id="" expected="" requested launch_record resolution refresh stream_config stream_preference settings_path
    local -a ml game_options hud_environment
    local hud_library="" hud_directory="" host_info crash_directory="" moonlight_log="$STATEDIR/moonlight.log"

    echo
    printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
'
    bold "CLOUD GAMING READY"
    printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
'

    if command -v moonlight >/dev/null 2>&1; then
        ml=(moonlight)

    elif command -v moonlight-qt >/dev/null 2>&1; then
        ml=(moonlight-qt)

    elif command -v flatpak >/dev/null 2>&1 8>&- &&
         flatpak info com.moonlight_stream.Moonlight \
             >/dev/null 2>&1
    then
        ml=(flatpak run com.moonlight_stream.Moonlight)

    else
        warn "Moonlight not found; automatic streaming failed. VM retained."
        return 1
    fi

    echo "Moonlight host: $ip"
    echo "Checking Moonlight pairing..."

    set +e
    list_out="$(
        timeout 25 \
            "${ml[@]}" list "$ip" \
            2>&1
    )"
    rc=$?
    set -e

    # Native Windows Moonlight writes CRLF; compare app titles without CR.
    list_out="$(printf '%s\n' "$list_out" | sed 's/\r$//')"

    # A local dynamic-linker failure is unrelated to Wolf pairing.
    if (( rc != 0 )) && [[ "${VASTGAME_WINDOWS:-0}" != 1 && "${ml[0]}" != flatpak ]] &&
       grep -Eq 'symbol lookup error:|error while loading shared libraries:' <<<"$list_out" &&
       command -v flatpak >/dev/null 2>&1 &&
       flatpak info com.moonlight_stream.Moonlight >/dev/null 2>&1; then
        warn "Native Moonlight has incompatible/missing libraries; using installed Flatpak Moonlight."
        python3 "$CLIENT_DIR/moonlight_settings.py" || {
            warn "Could not import existing Moonlight settings; close Moonlight and retry. VM retained."
            return 1
        }
        ml=(flatpak run com.moonlight_stream.Moonlight)
        if list_out="$(timeout 25 "${ml[@]}" list "$ip" 2>&1)"; then rc=0; else rc=$?; fi
        list_out="$(printf '%s\n' "$list_out" | sed 's/\r$//')"
    fi
    if (( rc != 0 )) && grep -Eq 'symbol lookup error:|error while loading shared libraries:' <<<"$list_out"; then
        printf '%s\n' "$list_out" | python3 "$CLIENT_DIR/failure_report.py" client "$STATEDIR" \
            "$(cat "$INSTANCE_FILE")" 2>/dev/null || true
        printf '%s\n' "$list_out" >&2
        warn "Moonlight cannot load its local libraries. Repair the client installation; VM retained."
        return 1
    fi

    if (( rc != 0 )); then
        printf '%s\n' "$list_out" | python3 "$CLIENT_DIR/failure_report.py" client "$STATEDIR" \
            "$(cat "$INSTANCE_FILE")" 2>/dev/null || true
        warn "Moonlight/Wolf pairing could not be verified."
        printf '%s
' "$list_out"
        echo "Opening Moonlight for recovery..."
        nohup "${ml[@]}" >/dev/null 2>&1 8>&- &
        return 1
    fi

    ok "Moonlight/Wolf pairing verified"

    session="$(curl -fsS --connect-timeout 3 --max-time 5 "http://$ip:$STATUS_PORT/session.json" 2>/dev/null || true)"
    expected="$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)"
    if jq -e '.game_id and .app_title and .session_id' >/dev/null 2>&1 <<<"$session"; then
        if [[ -n "$expected" && "$(jq -r '.game_id' <<<"$session")" != "$expected" ]]; then
            die "Existing VM has a different game. Selected: $expected; VM: $(jq -r '.game_id' <<<"$session"). VM kept running."
        fi
        app="$(jq -r '.app_title' <<<"$session")"
        session_id="$(jq -r '.session_id' <<<"$session")"
        if ! grep -Fqx -- "$app" <<<"$list_out"; then
            printf 'Moonlight returned this application list:\n%s\n' "$list_out" >&2
            die "Wolf does not advertise '$app'. Check vastgame logs; VM kept running."
        fi
    elif [[ -n "$expected" ]]; then
        die "This VM has no direct game launch metadata. A fresh VM using the updated bootstrap is required."
    elif grep -Fqx "Wolf UI" <<<"$list_out"; then
        app="Wolf UI"
    elif grep -Fqx "Lutris" <<<"$list_out"; then
        app="Lutris"
    else
        app="$(
            printf '%s
' "$list_out" |
                sed '/^[[:space:]]*$/d' |
                head -n1
        )"
    fi

    [[ -n "$app" ]] || {
        warn "No Moonlight application advertised."
        nohup "${ml[@]}" >/dev/null 2>&1 8>&- &
        return 1
    }

    launch_record="$(curl -fsS --connect-timeout 2 --max-time 3 "http://$ip:$STATUS_PORT/launch.json" 2>/dev/null || true)"
    requested="$(jq -r '.updated // 0' <<<"$launch_record" 2>/dev/null || echo 0)"
    [[ "$requested" =~ ^[0-9]+([.][0-9]+)?$ ]] || requested=0
    stream_preference="$(read_stream_settings)" || die "Fix stream.json before connecting. VM retained."
    stream_config="$stream_preference"
    resolution="$(jq -r '.resolution' <<<"$stream_config")"
    refresh="$(jq -r '.fps' <<<"$stream_config")"
    if [[ "$resolution" == native ]]; then
        resolution="$(native_screen_resolution)" || die "Cannot detect native screen resolution. VM retained."
    fi
    if [[ "$refresh" == native ]]; then
        refresh="$(native_screen_refresh)" || die "Cannot detect screen refresh rate. VM retained."
    fi
    settings_path="$(stream_settings_file)"
    stream_config="$(python3 "$CLIENT_DIR/stream_settings.py" resolve "$settings_path" "${VASTGAME_WINDOWS:-0}" "$resolution" "$refresh")" || die "Invalid stream settings. VM retained."
    resolution="$(jq -r '.resolution' <<<"$stream_config")"
    refresh="$(jq -r '.fps' <<<"$stream_config")"
    mapfile -t game_options < <(jq -r '.args[]' <<<"$stream_config")
    # New games get their display size from Wolf; resumed Gamescope sessions retain the old size.
    if [[ -n "$session_id" && "$(jq -r '.state // empty' <<<"$launch_record" 2>/dev/null)" =~ ^(running|starting)$ ]]; then
        if ! sync_game_resolution "$(cat "$INSTANCE_FILE")" "$(jq -r '.game_id' <<<"$session")" "$session_id" "$resolution"; then
            warn "Game display resize was not confirmed. Streaming continues; save and restart the game if higher modes remain unavailable."
        fi
    fi
    echo "Streaming '$app' from $ip at $resolution, $refresh FPS target..."
    echo "Video codec: $(jq -r '.video_codec' <<<"$stream_config"); bitrate: $(jq -r 'if .bitrate_mbps == null then "Moonlight default" else "\(.bitrate_mbps) Mbps" end' <<<"$stream_config")"
    [[ -z "$session_id" ]] || echo "Mouse mode: $(jq -r 'if .moonlight_options["absolute-mouse"] then "absolute" else "captured relative" end' <<<"$stream_config"); controller passthrough"

    hud_environment=()
    if [[ -n "$session_id" && "${ml[0]}" != flatpak && "$(jq -r ' .moonlight_options["performance-overlay"]' <<<"$stream_config")" == true ]] && readelf -d "$(command -v "${ml[0]}")" 2>/dev/null | grep -q libSDL2_ttf && hud_library="$(prepare_performance_hud)"; then
        hud_directory="$(mktemp -d "$STATEDIR/hud.XXXXXX")"
        host_info="$(instance_json "$(cat "$INSTANCE_FILE")" 2>/dev/null || echo '{}')"
        jq --argjson session "$session" --arg resolution "$resolution" --argjson fps "$refresh" \
            --arg key "${hud_directory##*/}" \
            '.public_ipaddr as $public | {machine_id, instance_id: .id, label,
              ssh_endpoints: ([{host: .ssh_host, port: .ssh_port},
                (.ports["22/tcp"][]? | {host: $public, port: .HostPort})] |
                map(select(.host != null and .port != null))),
              game_id: $session.game_id, session_id: $session.session_id,
              resolution: $resolution, target_fps: $fps, session_key: $key}' <<<"$host_info" > "$hud_directory/host.json"
        jq -r '[.resolution, (.fps | tostring),
                (if .bitrate_mbps == null then "auto" else (.bitrate_mbps | tostring) end),
                .video_codec, (.moonlight_options.vsync | if . == null then false else . end | tostring),
                (.moonlight_options["frame-pacing"] | if . == null then true else . end | tostring)] | join("|")' \
            <<<"$stream_preference" > "$hud_directory/menu.state"
        hud_environment=("LD_PRELOAD=$hud_library${LD_PRELOAD:+:$LD_PRELOAD}" "VASTGAME_HUD_DIR=$hud_directory"
            'VASTGAME_HUD_FONT=/usr/share/fonts/TTF/DejaVuSans.ttf')
        echo "Performance HUD: Ctrl+Alt+Shift+H toggle · Ctrl+Shift+Q stream menu · Alt+Tab local windows"
    elif [[ -n "$session_id" && "${VASTGAME_WINDOWS:-0}" == 1 ]]; then
        echo "Moonlight statistics: Ctrl+Alt+Shift+S toggle (native Windows overlay)"
    elif [[ -n "$session_id" && "$(jq -r '.moonlight_options["performance-overlay"]' <<<"$stream_config")" == true ]]; then
        warn "Custom HUD unavailable (requires native SDL2 Moonlight and SDL2/SDL_ttf build dependencies). Game launch continues."
    fi

    if [[ "${VASTGAME_CRASH_REPORTS:-1}" == 1 && "${VASTGAME_WINDOWS:-0}" != 1 && "${ml[0]}" != flatpak &&
          -f "$NATIVE_DIR/crashpad/vastgame_crashpad.so" && -x "$NATIVE_DIR/crashpad/crashpad_handler" ]] &&
          readelf -h "$(command -v "${ml[0]}")" >/dev/null 2>&1; then
        if crash_directory="$(python3 "$CLIENT_DIR/crash_reports.py" prepare --root "$STATEDIR/crashes" --game "$expected" --session "$session_id")"; then
            local preload="$NATIVE_DIR/crashpad/vastgame_crashpad.so${LD_PRELOAD:+:$LD_PRELOAD}"
            [[ -z "$hud_library" ]] || preload="$hud_library:$preload"
            hud_environment+=("LD_PRELOAD=$preload" "VASTGAME_CRASH_DIR=$crash_directory"
                "VASTGAME_CRASH_HANDLER=$NATIVE_DIR/crashpad/crashpad_handler")
            moonlight_log="$crash_directory/client.log"
            ln -sfn -- "$moonlight_log" "$STATEDIR/moonlight.log"
            echo "Native crash reports: local only · $crash_directory"
        else
            crash_directory=""
            warn "Crash reporting unavailable; streaming continues"
        fi
    fi

    # A disabled/unavailable reporter must not overwrite an older session's log
    # through the convenience symlink left by a previously instrumented stream.
    if [[ -z "$crash_directory" && -L "$STATEDIR/moonlight.log" ]]; then
        rm -f -- "$STATEDIR/moonlight.log"
    fi

    if [[ "${VASTGAME_DESKTOP:-0}" == 1 ]]; then printf '[VASTGAME_GAME_REQUESTED]\n'; fi
    nohup \
        env "${hud_environment[@]}" "${ml[@]}" stream "${game_options[@]}" "$ip" "$app" \
        >"$moonlight_log" 2>&1 8>&- &
    local moonlight_pid=$!
    if [[ -n "$crash_directory" ]]; then
        nohup python3 "$CLIENT_DIR/crash_reports.py" watch --directory "$crash_directory" \
            --log "$moonlight_log" --pid "$moonlight_pid" > "$crash_directory/monitor.log" 2>&1 8>&- &
    fi
    if [[ -n "$hud_directory" ]]; then
        nohup python3 "$CLIENT_DIR/performance_hud.py" --directory "$hud_directory" --ip "$ip" \
            --pid "$moonlight_pid" --fps "$refresh" --history "$HISTORY_FILE" --settings "$settings_path" \
            --known-hosts "$STATEDIR/known_hosts.$(cat "$INSTANCE_FILE")" \
            > "$hud_directory/collector.log" 2>&1 8>&- &
    fi
    sleep 1
    if kill -0 "$moonlight_pid" 2>/dev/null; then
        ok "Moonlight launched (stream connection is handled by Moonlight)"
        if [[ -n "$session_id" ]]; then
            wait_for_game_launch "$ip" "$session_id" "$requested" || return 1
        fi
    else
        warn "Moonlight exited early. See $STATEDIR/moonlight.log"
        tail -n 40 "$STATEDIR/moonlight.log"
        return 1
    fi
    return 0
}

# Shared by CLI selection and the read-only desktop catalog; no browsing caps leak into value scoring.
rank_host_offers() {
    local input="$1" cap="$2" count="$3" settings resolution fps
    settings="$(read_stream_settings)" || return 1
    resolution="$(jq -r '.resolution' <<< "$settings")"
    fps="$(jq -r '.fps' <<< "$settings")"
    if [[ "$resolution" == native ]]; then
        if ! resolution="$(native_screen_resolution 2>/dev/null)"; then
            resolution="1920x1080"
            warn "Screen size unavailable; ranking assumes 1920x1080. Set a resolution with vastgame streamedit for accurate ranking." >&2
        fi
    fi
    if [[ "$fps" == native ]]; then
        fps="$(native_screen_refresh)"
    fi
    settings="$(python3 "$CLIENT_DIR/stream_settings.py" resolve "$(stream_settings_file)" "${VASTGAME_WINDOWS:-0}" "$resolution" "$fps")" || return 1
    jq --argjson max "$count" --argjson cap "$cap" --argjson value_cap "$MAX_PRICE" \
        --arg selected_game "${4-$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)}" \
        --arg native_resolution "$(jq -r .resolution <<< "$settings")" \
        --argjson native_fps "$(jq -r .fps <<< "$settings")" \
        --slurpfile hist <(if jq -e 'type == "object"' "$HISTORY_FILE" >/dev/null 2>&1; then cat "$HISTORY_FILE"; else printf '{}\n'; fi) \
        -L "$APP_ROOT/src/providers/vast" -f "$APP_ROOT/src/providers/vast/rank.jq" "$input"
}

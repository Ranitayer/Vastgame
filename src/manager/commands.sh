# ============================================================
# CONNECT / LOGS
# ============================================================

connect_game() {
    local id info expected="${2:-}"

    if [[ -n "$expected" ]]; then
        id="$1"
        info="$(instance_json "$id")" || die "Cannot verify the selected VM. No connection opened."
        jq -e --arg id "$id" --arg label "$expected" '(.id | tostring) == $id and .label == $label' >/dev/null <<<"$info" ||
            die "Selected VM identity changed. No connection opened."
    else
        id="$(pick_instance)" || die "No vastgame instance found."
    fi

    printf '%s\n' "$id" > "$INSTANCE_FILE"

    # A reachable peer is not proof that game/runtime/save preparation finished.
    wait_for_gaming "$id"
}

show_logs() {
    local id
    local ip
    local log

    id="$(pick_instance)" ||
        die "No vastgame instance found."

    ip="$(get_vast_ip "$id" || true)"

    [[ -n "$ip" ]] ||
        die "vast-gaming is not online on Tailscale yet."

    log="$(bootstrap_log "$ip" || true)"

    [[ -n "$log" ]] ||
        die "Bootstrap progress service is not ready yet."

    printf '%s\n' "$log"
}

usage() {
    cat <<'USAGE'
Vastgame — multi-game Vast cloud gaming manager

In-game performance HUD (native Linux Moonlight):
  Ctrl+Alt+Shift+H                  Show/hide the top-left HUD
  Ctrl+Shift+Q                  Open stream settings menu (arrows, Enter, Escape)
  Alt+Tab                          Switch local windows during gameplay
  Session logs: ~/.local/state/vastgame/hud.*/metrics.jsonl

VM lifecycle:
  vastgame                         Find a host, start a VM, wait for Wolf, open Moonlight
  vastgame start <game-id>          Start a VM and prepare the selected game
    --offer-id <id> [--machine-id <id>] --max-price <$/hr> --yes
                                   Use this exact eligible offer without interactive prompts
  vastgame force ...                Compatibility alias for the same command
  vastgame stop --force --instance-id ID --label LABEL
                                  Destroy the exact rig without backup; unbacked saves are lost
  vastgame connect                  Resume monitoring an existing Vastgame VM
  vastgame status                   Show current Vast instances
  vastgame hosts --json [--game ID] Browse scored NVIDIA VM offers; all regions, no price cap
  vastgame logs                     Show the selected VM bootstrap log
  vastgame logs game                Show game launch status and Lutris/Proton log tail
  vastgame logs report              Show the latest redacted failure report and its folder
  vastgame stop                     Save verified state, then destroy VM
    --instance-id <id> --label <label>
                                   Save and stop only the exact identified VM
  vastgame setup                    Save or change the Vast template hash
  vastgame streamedit               Edit stream resolution, FPS, bitrate and Moonlight options
                                    Rig ranking uses these targets and favors affordable performance
  vastgame cleanup                  Preview expired, inactive local artifacts
  vastgame cleanup --apply          Remove previewed artifacts; preserve saves and releases
  vastgame update                   Install the latest Windows release; keep accounts/settings

Stream settings apply on reconnect. The running game's virtual display follows
the selected resolution; some games need restarting to refresh available modes.

Game catalog:
  vastgame game add <folder> [id]   Detect an executable and create a manifest
  vastgame ingest <URL> [id]        Import and publish a direct portable-game ZIP
    --exe <path> --dlss --sha256 <hash> --keep-staging
                                   Resolve EXE ambiguity, enable NGX, verify source, retain staging
    --connections <1-8>             ZIP download connections (default 8; safely falls back to 1)
  vastgame add ... --dlss           Enable NVIDIA compatibility; choose effects in-game
  vastgame details <app-id>         Read cached Steam game information
  vastgame artwork <app-id> cover|banner
                                   Fetch cached Steam library artwork
  vastgame artwork --game <id> cover|banner
                                   Resolve a library game and cache its Steam artwork
  vastgame game list [--json]       List registered games; JSON for the desktop library
  vastgame game inspect <id>        Print a game's manifest
  vastgame game validate <id>       Validate its manifest and executable
  vastgame game dlss <id>           Configure NVAPI/NGX compatibility for an existing game
  vastgame saves <id>              Discover known save/config locations (also automatic on add)
    --title <exact title>           Resolve an unknown/ambiguous Ludusavi match
    --refresh                       Update the cached catalog (requires Python PyYAML)
  vastgame crashes                 Show local native Linux client crash reports
  vastgame game select <id>         Select the default game
  vastgame game package <id>        Archive, checksum, and upload the game
  vastgame game remove <id>         Remove local metadata and remote game/state data

Persistent state:
  vastgame state backup <id>        Save and verify game saves, configs and shaders
  vastgame state restore <id>       Restore verified state while the game is closed
  vastgame state resume <id>        Release a retained shutdown block; no backup or destroy

Short game aliases:
  vastgame add <folder> [id]        Same as `vastgame game add`
  vastgame list                     Same as `vastgame game list`
  vastgame inspect <id>             Same as `vastgame game inspect`
  vastgame validate <id>            Same as `vastgame game validate`
  vastgame select <id>              Same as `vastgame game select`
  vastgame package <id>             Same as `vastgame game package`
  vastgame remove <id>              Same as `vastgame game remove`
  vastgame dlss <id>                Configure NVAPI/NGX compatibility for an existing game
  vastgame backup <id>              Same as `vastgame state backup`
  vastgame restore <id>             Same as `vastgame state restore`

Examples:
  vastgame game add ~/Games/Portal portal
  vastgame game validate portal
  vastgame game package portal
  vastgame start portal
  vastgame state backup portal
  vastgame stop

Local paths:
  Manifests: ~/.config/vastgame/games/<id>/manifest.json
  Runtime state: ~/.local/state/vastgame/
  Bootstrap: ~/.config/vastgame/vast-gaming-start-v2.sh

Run `vastgame help` to show this reference.
USAGE
}

# Normalize long and short forms once; every command has one dispatch path.
command="${1:-start}"
if (( $# > 0 )); then shift; fi
case "$command" in
    game)
        case "${1:-}" in
            add|ingest|list|inspect|validate|select|package|remove|dlss) command="$1"; shift ;;
            *) usage; exit 2 ;;
        esac
        ;;
    state)
        case "${1:-}" in backup|restore|resume) command="$1"; shift ;; *) usage; exit 2 ;; esac
        ;;
esac
# Lifecycle operations serialize independently from catalog publication.
case "$command" in
    start|connect|stop|add|select|package|remove|dlss|saves|backup|restore|resume|setup)
        if [[ "$command" == stop && "$#" == 5 && "$1" == --force && "$2" == --instance-id && "$3" =~ ^[0-9]+$ && "$4" == --label && "$5" =~ ^vastgame-[0-9]+$ ]]; then
            # Explicit force cannot wait behind the backup it is meant to interrupt.
            exec 9>"$STATEDIR/force-stop.$3.lock"
            flock -n 9 || die "Force shutdown already active for this rig"
        else
            exec 8>"$STATEDIR/lifecycle.lock"
            if [[ "$command" == stop && "${1:-}" == --instance-id ]]; then
                flock -w 90 8 || die "Previous launch has not released the lifecycle lock; VM retained"
            else
                flock -n 8 || die "Another Vastgame operation is active. Wait for it to finish."
            fi
        fi
        ;;
esac
# Imports may overlap VM startup, but never another catalog writer/removal.
case "$command" in
    add|ingest|package|remove|dlss|saves)
        exec 7>"$STATEDIR/catalog.lock"
        flock -n 7 || die "Another Vastgame catalog operation is active. Wait for it to finish."
        ;;
esac
case "$command" in
    desktop-launch)
        [[ "$#" == 5 ]] || die "Invalid desktop launch request"
        exec python3 "$CLIENT_DIR/desktop_launch.py" launch "$@"
        ;;
    desktop-watch)
        [[ "$#" == 1 ]] || die "Invalid desktop progress request"
        exec python3 "$CLIENT_DIR/desktop_launch.py" watch "$@"
        ;;
    desktop-session)
        [[ "$#" == 0 || ( "$#" == 1 && "$1" =~ ^[a-f0-9]{32}$ ) ]] || die "Invalid launch identity"
        exec python3 "$CLIENT_DIR/desktop_launch.py" current "$@"
        ;;
    desktop-shutdown)
        [[ "$#" == 1 || ( "$#" == 2 && "$2" == --force ) ]] || die "Invalid desktop shutdown request"
        exec python3 "$CLIENT_DIR/desktop_launch.py" stop "$@"
        ;;
    desktop-connect)
        [[ "$#" == 1 ]] || die "Invalid desktop connection request"
        exec python3 "$CLIENT_DIR/desktop_launch.py" connect "$@"
        ;;
    quote)
        [[ "$#" == 3 ]] && valid_game_id "$1" && [[ "$2" =~ ^[0-9]+$ && "$3" =~ ^[0-9]+$ ]] || die "Usage: vastgame quote GAME OFFER MACHINE"
        python3 "$CLIENT_DIR/offer_quote.py" "$(game_manifest "$1")" "$2" "$3"
        ;;
    details)
        [[ "$#" == 1 ]] || die "Usage: vastgame details STEAM_APP_ID"
        python3 "$CLIENT_DIR/game_details.py" "$1"
        ;;
    artwork)
        [[ "$#" == 2 || ( "$#" == 3 && "$1" == --game ) ]] || die "Usage: vastgame artwork STEAM_APP_ID cover|banner, or --game GAME_ID cover|banner"
        python3 "$CLIENT_DIR/game_artwork.py" "$@"
        ;;
    hosts)
        [[ "${1:-}" == --json && ( "$#" == 1 || ( "$#" == 3 && "${2:-}" == --game ) ) ]] || die "Usage: vastgame hosts --json [--game ID]"
        DISK_GB=60
        host_game="$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)"
        if (( $# == 3 )); then host_game="$3"; fi
        if [[ -n "$host_game" ]]; then
            valid_game_id "$host_game" || die "Invalid game ID"
            DISK_GB="$(python3 "$CLIENT_DIR/disk_capacity.py" "$(game_manifest "$host_game")")" || die "Package this game before filtering Hosts"
        fi
        query="$(host_offer_query)"
        search_host_offers "$query" |
            rank_host_offers /dev/stdin 1e99 2147483647 "$host_game" |
            python3 "$APP_ROOT/src/providers/vast/desktop_hosts.py" "$DISK_GB"
        ;;
    update)
        [[ "${VASTGAME_WINDOWS:-0}" == 1 ]] || die "Windows updater only. On Linux, update your Vastgame source checkout."
        vastgame-native update
        ;;
    cleanup)
        python3 "$CLIENT_DIR/cleanup.py" --app "$APP_ROOT" --state "$STATEDIR" \
            --data "${XDG_DATA_HOME:-$HOME/.local/share}/vastgame" "$@"
        ;;
    saves) game_discover_saves "$@" ;;
    crashes)
        printf 'Local native client reports: %s/crashes\n' "$STATEDIR"
        [[ ! -d "$STATEDIR/crashes" ]] || find "$STATEDIR/crashes" -type f -name '*.dmp' -print
        ;;
    add) game_add "$@" ;;
    ingest) game_ingest "$@" ;;
    list) game_list "$@" ;;
    inspect) game_inspect "${1:-}" ;;
    validate) game_validate "${1:-}" ;;
    select) game_select "${1:-}" ;;
    package) game_package "${1:-}" ;;
    remove) game_remove "${1:-}" ;;
    dlss) game_enable_dlss "${1:-}" ;;
    backup) state_backup "${1:-}" ;;
    restore) state_restore "${1:-}" ;;
    resume) state_resume "${1:-}" ;;
    setup) setup_template ;;
    streamedit) edit_stream_settings ;;
    stop)
        if (( $# == 0 )); then stop_game
        elif [[ "$#" == 5 && "$1" == --force && "$2" == --instance-id && "$3" =~ ^[0-9]+$ && "$4" == --label && "$5" =~ ^vastgame-[0-9]+$ ]]; then stop_game "$3" "$5" "" --force
        elif [[ "$#" == 4 && "$1" == --instance-id && "$3" == --label && "$2" =~ ^[0-9]+$ && "$4" =~ ^vastgame-[0-9]+$ ]]; then stop_game "$2" "$4"
        elif [[ "$#" == 6 && "$1" == --instance-id && "$3" == --label && "$5" == --startup-job && "$2" =~ ^[0-9]+$ && "$4" =~ ^vastgame-[0-9]+$ && "$6" =~ ^[a-f0-9]{32}$ ]]; then stop_game "$2" "$4" "$6"
        else die "Usage: vastgame stop [--instance-id ID --label LABEL] or stop --force --instance-id ID --label LABEL"; fi
        ;;
    status) vastai show instances ;;
    connect)
        read_stream_settings >/dev/null || die "Fix stream.json before connecting"
        if (( $# == 0 )); then connect_game
        elif [[ "$#" == 4 && "$1" == --instance-id && "$3" == --label && "$2" =~ ^[0-9]+$ && "$4" =~ ^vastgame-[0-9]+$ ]]; then connect_game "$2" "$4"
        else die "Usage: vastgame connect [--instance-id ID --label LABEL]"; fi
        ;;
    logs)
        if [[ "${1:-}" == game ]]; then show_game_log
        elif [[ "${1:-}" == report ]]; then
            report="$(cat "$STATEDIR/latest-report" 2>/dev/null || true)"
            [[ "$report" == "$STATEDIR/reports/"* && -f "$report/summary.txt" ]] || die "No failure report saved yet."
            cat "$report/summary.txt"
            printf '\nReport: %s\n' "$report"
        else show_logs; fi ;;
    help|-h|--help) usage ;;
    start|"")
        read_stream_settings >/dev/null || die "Fix stream.json before starting a VM; no rental submitted"
        active="$(all_vastgame_instances)" || die "Cannot check existing VMs; no new VM rented"
        jq -e 'length == 0' >/dev/null <<<"$active" || die "A Vastgame VM already exists. Use connect or stop before starting another."
        requested_game="${1:-}"
        [[ -z "$requested_game" ]] || { valid_game_id "$requested_game" || die "Invalid game ID"; shift; }
        VASTGAME_EXPLICIT_OFFER=0
        VASTGAME_OFFER_ID=""
        VASTGAME_MACHINE_ID=0
        VASTGAME_OFFER_PRICE=""
        confirmed=0
        while (( $# > 0 )); do
            case "$1" in
                --offer-id) [[ "${2:-}" =~ ^[0-9]+$ ]] || die "Invalid offer ID"; VASTGAME_OFFER_ID="$2"; shift 2 ;;
                --machine-id) [[ "${2:-}" =~ ^[0-9]+$ ]] || die "Invalid machine ID"; VASTGAME_MACHINE_ID="$2"; shift 2 ;;
                --max-price) [[ "${2:-}" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "Invalid price ceiling"; VASTGAME_OFFER_PRICE="$2"; shift 2 ;;
                --yes) confirmed=1; shift ;;
                *) die "Unknown start option: $1" ;;
            esac
        done
        if [[ -n "$VASTGAME_OFFER_ID$VASTGAME_OFFER_PRICE" ]] || (( confirmed )); then
            [[ -n "$requested_game" && -n "$VASTGAME_OFFER_ID" && -n "$VASTGAME_OFFER_PRICE" && "$confirmed" == 1 ]] || die "Exact offer launch requires game ID, --offer-id, --max-price and --yes"
            VASTGAME_EXPLICIT_OFFER=1
        fi
        [[ -z "$requested_game" ]] || game_select "$requested_game" >/dev/null
        # Host selection expects the original start <id> arguments.
        set -- start "$requested_game"
        if (( VASTGAME_EXPLICIT_OFFER )); then source "$APP_ROOT/src/manager/selected_offer.sh"
        else source "$APP_ROOT/src/manager/hosts.sh"; fi
        source "$APP_ROOT/src/manager/launch.sh"
        ;;
    *) usage; exit 2 ;;
esac

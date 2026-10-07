# ============================================================
# CONNECT / LOGS
# ============================================================

connect_game() {
    local id

    id="$(pick_instance)" ||
        die "No vastgame instance found."

    printf '%s\n' "$id" > "$INSTANCE_FILE"

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
  Alt+Tab                          Switch local windows during gameplay
  Session logs: ~/.local/state/vastgame/hud.*/metrics.jsonl

VM lifecycle:
  vastgame                         Find a host, start a VM, wait for Wolf, open Moonlight
  vastgame start <game-id>          Start a VM and prepare the selected game
  vastgame force                    Start without route-quality checks
  vastgame force start <game-id>    Start a selected game without route checks
  vastgame connect                  Resume monitoring an existing Vastgame VM
  vastgame status                   Show current Vast instances
  vastgame logs                     Show the selected VM bootstrap log
  vastgame logs game                Show game launch status and Lutris/Proton log tail
  vastgame stop                     Save verified state, then destroy VM
  vastgame setup                    Save or change the Vast template hash

Game catalog:
  vastgame game add <folder> [id]   Detect an executable and create a manifest
  vastgame add ... --dlss           Enable NVIDIA compatibility; choose effects in-game
  vastgame game list                List registered games
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
            add|list|inspect|validate|select|package|remove|dlss) command="$1"; shift ;;
            *) usage; exit 2 ;;
        esac
        ;;
    state)
        case "${1:-}" in backup|restore) command="$1"; shift ;; *) usage; exit 2 ;; esac
        ;;
esac
# One local writer owns lifecycle/catalog changes; readers remain available.
case "$command" in
    start|connect|stop|add|select|package|remove|dlss|saves|backup|restore|setup)
        exec 8>"$STATEDIR/lifecycle.lock"
        flock -n 8 || die "Another Vastgame operation is active. Wait for it to finish."
        ;;
esac
case "$command" in
    saves) game_discover_saves "$@" ;;
    crashes)
        printf 'Local native client reports: %s/crashes\n' "$STATEDIR"
        [[ ! -d "$STATEDIR/crashes" ]] || find "$STATEDIR/crashes" -type f -name '*.dmp' -print
        ;;
    add) game_add "$@" ;;
    list) game_list ;;
    inspect) game_inspect "${1:-}" ;;
    validate) game_validate "${1:-}" ;;
    select) game_select "${1:-}" ;;
    package) game_package "${1:-}" ;;
    remove) game_remove "${1:-}" ;;
    dlss) game_enable_dlss "${1:-}" ;;
    backup) state_backup "${1:-}" ;;
    restore) state_restore "${1:-}" ;;
    setup) setup_template ;;
    stop) stop_game ;;
    status) vastai show instances ;;
    connect) connect_game ;;
    logs) if [[ "${1:-}" == game ]]; then show_game_log; else show_logs; fi ;;
    help|-h|--help) usage ;;
    start|"")
        active="$(all_vastgame_instances)" || die "Cannot check existing VMs; no new VM rented"
        jq -e 'length == 0' >/dev/null <<<"$active" || die "A Vastgame VM already exists. Use connect or stop before starting another."
        [[ -z "${1:-}" ]] || game_select "$1" >/dev/null
        # Host selection expects the original start <id> arguments.
        set -- start "$@"
        source "$APP_ROOT/src/manager/hosts.sh"
        source "$APP_ROOT/src/manager/launch.sh"
        ;;
    *) usage; exit 2 ;;
esac

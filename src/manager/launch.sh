# ============================================================
# CREATE VM
# ============================================================

[[ -s "$BOOTSTRAP_FILE" ]] ||
    die "Missing bootstrap v2: $BOOTSTRAP_FILE"

bash -n "$BOOTSTRAP_FILE" ||
    die "Bootstrap v2 syntax validation failed."

label="vastgame-$(date +%s%N)"


echo
bold "Stage 1/3 — Creating Vast VM"

echo "Submitting selected offer directly to Vast..."
if [[ -s "$CFGDIR/core-image.json" ]]; then
    echo "Using the pinned prebuilt Core VM image."
    warn "Custom image guest launch is not verified on Vast; the previous trial failed before Tailscale."
fi

# The full bootstrap has grown beyond Vast's request-size limit.
# Compress it locally and send a tiny self-extracting wrapper.
packed_onstart="$STATEDIR/vastgame-onstart-packed.sh"
publish_runtime
export RUNTIME_SHA
export VASTGAME_FORCE_ROUTE
VASTGAME_CLIENT_TSIP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
export VASTGAME_CLIENT_TSIP

VASTGAME_BOOTSTRAP_CONFIG="$BOOTSTRAP_CONFIG" python3 "$APP_ROOT/src/bootstrap/pack.py" "$BOOTSTRAP_FILE" "$packed_onstart" "$label" "$(jq -r ".[$idx].machine_id // empty" "$sorted")" "$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)"

chmod 600 "$packed_onstart"

# Never rent a VM with a syntactically broken startup wrapper.
if ! sh -n "$packed_onstart"; then
    die "Generated packed bootstrap wrapper failed syntax validation."
fi

ok "Packed bootstrap wrapper syntax valid"

bootstrap_bytes="$(
    wc -c < "$BOOTSTRAP_FILE"
)"

packed_bytes="$(
    wc -c < "$packed_onstart"
)"

printf \
    'Bootstrap payload: %s bytes -> %s bytes packed\n' \
    "$bootstrap_bytes" \
    "$packed_bytes"

# Keep the packed script below 15 KiB, leaving 1 KiB below the 16 KiB limit.
if (( packed_bytes > 15360 )); then
    die \
        "Packed bootstrap is still too large (${packed_bytes} bytes)."
fi

set +e

create_out="$(
    if [[ -s "$CFGDIR/core-image.json" ]]; then
        timeout --foreground 90s python3 "$APP_ROOT/src/manager/create_vm.py" \
            "$CFGDIR/core-image.json" "$TEMPLATE_HASH" "$offer_id" "$DISK_GB" "$label" "$packed_onstart"
    else
        timeout --foreground 90s python3 "$APP_ROOT/src/manager/create_vm.py" \
            - "$TEMPLATE_HASH" "$offer_id" "$DISK_GB" "$label" "$packed_onstart"
    fi 2>&1
)"

create_rc=$?

set -e

echo
echo "Vast create exit code: $create_rc"

if [[ -n "${create_out//[[:space:]]/}" ]]; then
    echo "Vast create response:"
    printf '%s\n' "$create_out" | sed -E "s/(['\"]?instance_api_key['\"]?[[:space:]]*:[[:space:]]*)['\"][^'\"]*['\"]/\\1'[redacted]'/g"
else
    warn "Vast CLI returned an empty create response."
fi

# Vast CLI can return exit code 0 even when the API response
# itself contains an HTTP error. Treat the response as authoritative.

if grep -Eqi \
    'unavailable|not available|already rented|not rentable|offer.*not found' \
    <<<"$create_out"
then
    warn "Selected offer became unavailable during creation."
    echo "Refreshing ranked offers..."
    if (( VASTGAME_FORCE_ROUTE == 1 )); then
        exec "$0" force
    fi
    exec "$0"
fi

if (( create_rc == 124 )); then
    warn "Vast create request timed out after 90 seconds."
    warn "Checking by launch label in case the contract was created server-side..."
elif (( create_rc != 0 )) ||
   grep -Eqi \
       'Failed with error|error [0-9]{3}/|Invalid args:' \
       <<<"$create_out"
then
    die "Vast API rejected the instance creation request."
fi

# Vast create output is not trusted for contract identification.
# Recover only the exact unique launch label from the account listing.
instance_id=""

# Vast can successfully accept create but return no new_contract.
if [[ -z "$instance_id" ]]; then

    echo \
        "Vast returned no instance ID; checking whether a contract was actually created..."

    for attempt in {1..10}; do

        instances="$(
            vastai show instances --raw 2>/dev/null ||
            true
        )"

        if ! jq -e \
            'type == "array"' \
            >/dev/null 2>&1 \
            <<<"$instances"
        then
            sleep 2
            continue
        fi

        # ----------------------------------------------------
        # Method 1 — our unique vastgame launch label
        # ----------------------------------------------------

        candidate="$(
            jq -r \
                --arg label "$label" '
                    [
                        .[] |
                        select(
                            (.label // "") == $label
                        )
                    ]
                    |
                    if length == 1
                    then .[0].id
                    else empty
                    end
                ' \
                <<<"$instances"
        )"

        if [[ -n "$candidate" ]]; then
            instance_id="$candidate"

            echo \
                "Recovered contract by launch label: $instance_id"

            break
        fi

        # ----------------------------------------------------
        # Only an exact unique launch label may identify the contract.
        sleep 2
    done

    echo
fi

if [[ -z "$instance_id" ]]; then
    echo
    warn "No new Vast contract appeared after the create request."

    echo
    echo "Create exit code: $create_rc"

    if [[ -n "${create_out//[[:space:]]/}" ]]; then
        echo "Create response:"
        printf '%s\n' "$create_out" | sed -E "s/(['\"]?instance_api_key['\"]?[[:space:]]*:[[:space:]]*)['\"][^'\"]*['\"]/\\1'[redacted]'/g"
    else
        echo "Create response: <EMPTY>"
    fi

    die "Vast did not create a contract. Not retrying automatically."
fi

printf '%s\n' "$instance_id" > "$INSTANCE_FILE"

trap '
    progress_stop_animation
    progress_clear
    echo
    warn "Local watcher interrupted. Instance '"$instance_id"' may still be billing."
    echo "Resume: vastgame connect"
    echo "Stop:   vastgame stop"
    exit 130
' INT

ok "Instance created: $instance_id"

# ============================================================
# WAIT FOR VAST
# ============================================================

start="$(date +%s)"
VG_VAST_LAST_STATUS=""
VG_VAST_ACTIVITY=""
VG_VAST_ACTIVITY_AT=0
api_errors=0
actual=provisioning
msg=""

while true; do

    now="$(date +%s)"
    e=$((now - start))

    if progress_run vast_wait_frame instance_json "$instance_id"; then rc=0; else rc=$?; fi
    info="$VG_POLL_OUTPUT"
    e=$(( $(date +%s) - start ))

    if (( rc != 0 )) ||
       [[ -z "$info" ]]
    then

        api_errors=$((api_errors + 1))

        progress_clear
        warn \
            "Could not read Vast status ($api_errors/5)"

        (( api_errors < 5 )) ||
            pause_boot_wait \
                "$instance_id" \
                "Vast status API failed repeatedly."

        progress_run vast_wait_frame sleep 5
        continue
    fi

    api_errors=0

    actual="$(
        jq -r \
            '.actual_status // "provisioning"' \
            <<<"$info"
    )"

    msg="$(
        extract_message <<<"$info"
    )"

    print_vast_progress "$actual" "$msg" "$e"
    check_instance_failure "$instance_id" "$info"
    if [[ "$actual" != running ]]; then
        check_startup_logs "$instance_id" "$info" vast_wait_frame
    fi

    if [[ "$actual" == running ]]; then
        progress_clear
        ok "Vast VM is running (elapsed $(elapsed "$e"))"
        break
    fi

    (( e < VAST_START_TIMEOUT )) ||
        pause_boot_wait \
            "$instance_id" \
            "Vast did not reach running within $(elapsed "$VAST_START_TIMEOUT")."

    progress_run vast_wait_frame sleep 5
done

wait_for_gaming "$instance_id"

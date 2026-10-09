# Size the VM disk from the selected game's real local footprint.
calculate_disk_requirement

# ============================================================
# EXISTING TEMPLATE
# ============================================================

[[ -s "$TEMPLATE_FILE" ]] ||
    setup_template

TEMPLATE_HASH="$(
    cat "$TEMPLATE_FILE"
)"

# ============================================================
# DON'T RENT TWICE
# ============================================================

existing="$(all_vastgame_instances)" ||
    die "Could not query Vast instances."

active_count="$(
    jq '
        [
            .[] |

            select(
                (.actual_status // "provisioning") as $s |

                (
                    $s == "running"
                    or
                    $s == "loading"
                    or
                    $s == "created"
                    or
                    $s == "rebooting"
                    or
                    $s == "frozen"
                    or
                    $s == "provisioning"
                )
            )
        ] |
        length
    ' <<<"$existing"
)"

if (( active_count > 0 )); then

    echo
    echo \
        "A vastgame VM already exists; connecting instead of renting another."

    connect_game
    exit 0
fi

# ============================================================
# SEARCH
# ============================================================

echo
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
bold "VASTGAME — EUROPE VM GAMING RIGS ≤ \$${MAX_PRICE}/hr"
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'

echo \
    "Searching VM-capable offers with ${DISK_GB}GB storage..."

query="$(host_offer_query) dph_total<=$MAX_PRICE geolocation in $EU_COUNTRIES"

raw="$(mktemp)"
sorted="$(mktemp)"

trap 'rm -f "$raw" "$sorted"' EXIT

set +e

search_out="$(
    search_host_offers "$query" 2>&1
)"

search_rc=$?

set -e

(( search_rc == 0 )) || {
    echo "$search_out"
    die "Vast offer search failed."
}

jq -e . >/dev/null 2>&1 <<<"$search_out" || {
    echo "$search_out"
    die "Vast returned invalid JSON."
}

printf '%s\n' "$search_out" > "$raw"

# ============================================================
# FINAL FILTER + ALGERIA GAMING SCORE
# ============================================================

if [[ ! -s "$HISTORY_FILE" ]] ||
   ! jq -e 'type == "object"' "$HISTORY_FILE" >/dev/null 2>&1
then
    printf '{}\n' > "$HISTORY_FILE"
fi

rank_host_offers "$raw" "$MAX_PRICE" "$MAX_RESULTS" > "$sorted"

count="$(
    jq 'length' "$sorted"
)"

(( count > 0 )) ||
    die \
        "No robust European gaming rigs are currently available under \$${MAX_PRICE}/hr."

# ============================================================
# TABLE
# ============================================================

echo
echo "Best value for $(jq -r '.[0]._vg | .target_resolution + " @ " + (.target_fps | tostring) + " FPS"' "$sorted")"
echo
{
    printf 'NO\tSCORE\tGPU\tVRAM\t$/HR\tCOUNTRY\tDOWN\tUP\n'
    jq -r 'to_entries[] | [(.key + 1), .value._vg.score,
        (.value.gpu_name // "-"),
        (((.value.gpu_ram // 0) / 1024 | round | tostring) + "GB"),
        ((.value.dph_total * 1000 | round) / 1000),
        ((.value.geolocation // "-") | gsub("_"; " ")),
        ((.value.inet_down // 0 | floor | tostring) + "M"),
        ((.value.inet_up // 0 | floor | tostring) + "M")] | @tsv' "$sorted"
} | column -t -s $'\t'
echo
echo "Higher scores favor affordable target performance, route and reliability."
echo "DOWN / UP = advertised download / upload speed in Mbps."
echo "Game presets affect FPS; country proximity is only a route estimate."

# ============================================================
# SELECT
# ============================================================

echo
read -rp \
    "Choose rig [1-$count] or q: " \
    pick

[[ "$pick" =~ ^[qQ]$ ]] &&
    exit 0

[[ "$pick" =~ ^[0-9]+$ ]] ||
    die "Invalid choice."

(( pick >= 1 && pick <= count )) ||
    die "Invalid choice."

idx=$((pick - 1))

offer_id="$(
    jq -r ".[$idx].id" "$sorted"
)"

gpu="$(
    jq -r ".[$idx].gpu_name" "$sorted"
)"

price_raw="$(
    jq -r ".[$idx].dph_total" "$sorted"
)"

price="$(
    printf "%.3f" "$price_raw"
)"

country="$(
    jq -r ".[$idx].geolocation" "$sorted" |
        tr '_' ' '
)"

down="$(
    jq -r ".[$idx].inet_down" "$sorted"
)"

up="$(
    jq -r ".[$idx].inet_up" "$sorted"
)"

tier="$(
    jq -r ".[$idx]._vg.tier" "$sorted"
)"

score="$(
    jq -r ".[$idx]._vg.score" "$sorted"
)"

breakdown="$(
    jq -r '
        .['"$idx"']._vg
        |
        "TARGET \(.gpu)/35  VALUE \(.cost)/20  ROUTE \(.alg)/15  REL \(.rel)/10  RESTORE \(.net)/10  VRAM \(.vram)/5  CPU \(.cpu)/5  HISTORY \(.hist)"
    ' "$sorted"
)"

echo
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
bold "SELECTED"
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'

printf \
    'Tier:     %s\nScore:    %s/100\nGPU:      %s\nCountry:  %s\nPrice:    $%s/hr\nStorage:  %s GB\nNetwork:  %s↓ / %s↑ Mbps\nOffer ID: %s\nBreakdown: %s\n\n' \
    "$tier" \
    "$score" \
    "$gpu" \
    "$country" \
    "$price" \
    "$DISK_GB" \
    "$down" \
    "$up" \
    "$offer_id" \
    "$breakdown"

jq -r --argjson idx "$idx" '
    .[$idx] |
    "Restore ranking rate: \((._vg.restore_mbps * 10 | round) / 10) Mbps (recent measured rate when available; otherwise advertised).",
    "Host disk read benchmark: \(.disk_bw // 0) MB/s. Actual writes and source throughput may differ."
' "$sorted"
echo "Fast restore will measure source throughput on the new VM before the full download."

read -rp \
    "Start this rig? [Y/n]: " \
    answer

if [[ "$answer" =~ ^[nN]$ ]]; then
    exit 0
fi

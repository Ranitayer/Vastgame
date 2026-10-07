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

query="num_gpus=1 verified=any rentable=true vms_enabled=true gpu_arch=nvidia gpu_ram>=6 direct_port_count>=1 dph_total<=$MAX_PRICE disk_space>=$DISK_GB geolocation in $EU_COUNTRIES"

raw="$(mktemp)"
sorted="$(mktemp)"

trap 'rm -f "$raw" "$sorted"' EXIT

set +e

search_out="$(
    vastai search offers "$query" \
        --storage "$DISK_GB" \
        --limit 200 \
        --raw \
        2>&1
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

jq \
    --argjson max "$MAX_RESULTS" \
    --argjson cap "$MAX_PRICE" \
    --arg selected_game "$(cat "$SELECTED_GAME_FILE" 2>/dev/null || true)" \
    --arg native_resolution "$(native_screen_resolution 2>/dev/null || true)" \
    --argjson native_fps "$(native_screen_refresh)" \
    --slurpfile hist "$HISTORY_FILE" \
    -f "$APP_ROOT/src/providers/vast/rank.jq" "$raw" > "$sorted"

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
echo "Best rigs — Algeria gaming suitability"
echo

{
    printf \
        "NO\tTIER\tSCORE\tGPU\tVRAM\tPRICE\tCOUNTRY\tALG\tDOWN\tUP\tREL\tHIST\n"

    jq -r '

        to_entries[]

        |

        [
            (.key + 1),

            .value._vg.tier,

            (
                (.value._vg.score | tostring)
            ),

            (.value.gpu_name // "-"),

            (
                (
                    (
                        (.value.gpu_ram // 0)
                        / 1024
                    )
                    | round
                    | tostring
                )
                + "GB"
            ),

            (
                "$"
                +
                (
                    (
                        (.value.dph_total // 0)
                        * 1000
                        | round
                    )
                    / 1000
                    | tostring
                )
            ),

            (
                (.value.geolocation // "-")
                | gsub("_"; " ")
            ),

            (
                (.value._vg.alg | tostring)
                + "/15"
            ),

            (
                (
                    (.value.inet_down // 0)
                    | floor
                    | tostring
                )
                + "M"
            ),

            (
                (
                    (.value.inet_up // 0)
                    | floor
                    | tostring
                )
                + "M"
            ),

            (
                (
                    (
                        (.value.reliability // 0)
                        * 1000
                        | round
                    )
                    / 10
                    | tostring
                )
                + "%"
            ),

            (
                if .value._vg.hist > 0
                then "+" + (.value._vg.hist | tostring)

                else (.value._vg.hist | tostring)
                end
            )
        ]

        |

        @tsv

    ' "$sorted"

} | column -t -s $'\t'

echo
echo \
    "S+ 93+ | S 87+ | A 80+ | B 72+ | C 64+ | D <64"

echo \
    "ALG = Algeria proximity prior; measured local RTT/loss/jitter always overrides score."

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
        "GFX \(.gpu)/40  ALG \(.alg)/15  NET+DISK \(.net)/12  REL \(.rel)/12  VRAM \(.vram)/8  CPU \(.cpu)/6  COST \(.cost)/7  HIST \(.hist)"
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

# Reuse disk sizing, exact quote validation and ranking without interactive prompts.
calculate_disk_requirement
[[ -s "$TEMPLATE_FILE" ]] || die "Complete Vastgame setup before using Play"
TEMPLATE_HASH="$(cat "$TEMPLATE_FILE")"
raw="$(mktemp)"
sorted="$(mktemp)"
trap 'rm -f "$raw" "$sorted"' EXIT
response="$(python3 "$CLIENT_DIR/offer_quote.py" "$(game_manifest "$requested_game")" "$VASTGAME_OFFER_ID" "$VASTGAME_MACHINE_ID" "$VASTGAME_OFFER_PRICE" "$raw")"
if jq -e '.error' >/dev/null <<<"$response"; then
    failure="$(jq -c '.error' <<<"$response")"
    if [[ "${VASTGAME_DESKTOP:-0}" == 1 ]]; then printf '[VASTGAME_ERROR]%s\n' "$failure"; fi
    die "[$(jq -r '.code' <<<"$failure")] $(jq -r '.message' <<<"$failure")"
fi
jq -e '.quote' >/dev/null <<<"$response" || die "Quote validation failed; no VM rented"
[[ -s "$HISTORY_FILE" ]] || printf '{}\n' > "$HISTORY_FILE"
rank_host_offers "$raw" 1e99 1 > "$sorted" || die "Could not validate selected rig; no VM rented"
[[ "$(jq length "$sorted")" == 1 ]] || die "Selected rig no longer meets Vastgame requirements"
idx=0
offer_id="$VASTGAME_OFFER_ID"
echo "Quote verified: $(jq -r '.quote.price' <<<"$response") USD/h with $DISK_GB GB allocated"

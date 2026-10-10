# Session history

The shared CLI/desktop engine records managed rentals and launch attempts under
`~/.local/state/vastgame/sessions/vastgame-<launch-label>/`. The Sessions tab uses
these records. There is no new database, dependency, idle polling or service.

Each session has a private `session.json` and compressed `logs.jsonl.gz`.
Summaries include the game, original desktop job ID when available, permanent
provider instance ID, launch label, rig specifications, allocated disk, quoted
or observed hourly rate, start/end times, first game-running observation,
startup stage times, last error, backup outcome and billing observations.
New desktop sessions accumulate time between observed game-running and game-exit
states. The displayed play time is based on those observations, not a continuous
guest monitor; older missing measurements remain unknown.
Reconnect and game exit remain part of the same rental. Backup failure keeps
the session open; only provider-confirmed absence ends a rental. An uncertain
create request remains unresolved instead of being recorded as a free failure.

## Commands

```sh
vastgame sessions --json
vastgame sessions --json --limit 50 --offset 50
vastgame sessions --json --refresh-billing
vastgame sessions --json --days 7 --status Starting --sort highest-cost
vastgame sessions show vastgame-<label> --json
vastgame sessions logs vastgame-<label>
vastgame sessions logs vastgame-<label> --json
vastgame sessions refresh vastgame-<label> --json
```

Listing without `--refresh-billing`, details and log reading work offline. Lists default to 50 summaries,
with a maximum page size of 200. Log export streams all retained compressed
messages; JSON output includes their observation time. The existing app log
format and its 500-event visible limit are unchanged.

Empty, closed imported records without rig, instance, rate, play-time or charge
information are omitted from listings before pagination. Their saved records
and log archives remain accessible by ID. New attempts, live/unresolved rentals,
and older records containing useful details are kept visible.

Time and state filters and sorting apply to the full ledger before pagination.
Time ranges are rolling 1, 3, 7, 30 or 365 days based on session start time.
States include Starting, Running, Failed, Retained and Shutdown. In-progress
operations show Starting even before the provider returns an instance ID.
Cost sorting uses provider-reported totals when available, otherwise the
compute/storage estimate; unknown costs sort last in either direction.
Longest/shortest time sort by observed play time, with missing measurements last.
The app omits the estimate suffix but identifies estimates in the cost tooltip.

CLI lifecycle output is recorded through an output-only pseudo-terminal when
the original output is a terminal. Its interactive input, live progress and
terminal sizing remain available. Redirected commands use a pipe. The desktop
reuses its existing engine output capture, without a second recorder process.
The legacy `force` command alias is normalized before capture; only start,
connect and stop enter lifecycle recording. Non-lifecycle aliases do not create
empty failed sessions. Both remove terminal escapes, redact credentials/signed URLs and suppress
multiline private-key contents before writing compressed logs. File locking
serializes concurrent startup, normal shutdown and force-shutdown writers.

Records are atomically replaced and synced to disk. Session directories use
mode 0700; records, locks and logs use 0600. Terminal session state cannot be
revived by a late startup writer. History failures warn without canceling or
changing a paid lifecycle operation.

## Costs

`estimated_compute_storage_usd` is a decimal-string estimate based on the known
hourly rate and rental time. Provider `start_date` takes precedence when
available; otherwise creation-confirmation time is explicitly marked as an
observation. This estimate excludes bandwidth, discounts, refunds and price
changes and is never presented as an invoice. Unknown inputs remain null.

After confirmed destruction, one detached billing worker reads the fixed public
[Vast charges endpoint](https://docs.vast.ai/api-reference/billing/show-charges).
It uses the same default account key location as Vast CLI, sends credentials
only in the HTTPS authorization header and refuses redirects. There is no
provider request during offline history browsing.

The worker matches `source: instance-<exact ID>`, checks the launch label when
the provider supplies it, and records provider-reported totals plus the GPU,
storage, bandwidth or other component types supplied in the breakdown. It never
sums both parent and child amounts. Decimal arithmetic avoids binary rounding;
repeated refreshes replace observations rather than accumulating charges.
Identical duplicate rows are ignored; conflicting or overlapping intervals
remain an error instead of becoming an inflated total.

Charge reads include complete UTC boundary days and paginate with a 20-page,
8 MiB total response limit and a 30-second request budget with a maximum
10-second blocking socket operation. Incomplete pages, invalid amounts,
permission errors, timeouts and missing rows never become a zero cost. Existing
reported amounts are preserved as stale when refresh fails or loses visibility.
The worker holds no lifecycle lock and cannot prevent destruction.

Billing states are `pending`, `reported`, `stale` or `unavailable`. Reported
charges are a provider observation, not a promise that billing has settled;
`final` stays false. Delayed charges can be refreshed explicitly. Refresh reads
through the current day, including later adjustments for the same instance.

## Retention and older sessions

Ordinary cleanup and disposable job pruning never remove the ledger or its
logs. Logs are compressed, not silently rotated away. History therefore grows
with usage; listing is paginated and log reads stream from disk.

New CLI and desktop rentals atomically reserve their canonical `vastgame-…`
identity before creation. Even two calls with the same nanosecond clock value
receive different IDs. Reconnects and shutdowns keep the original rental ID.

Selecting a Sessions card opens the information panel on the right, using Home's shared `DetailsPanel` surface and
width. Compact
cards show the country flag beside GPU/VRAM. The panel shows the saved host CPU,
download/upload, session timestamps and elapsed time; it does not invent guest
health or retention measurements. The shared panel heading shows Session details and a circular close X in every view. Closing clears selection and returns focus to the session card without changing the rig. The summary reserves heading space and fits without panel scrolling. Events
and Logs are closed surface-color pills. Opening either fills only the existing right-side panel
with the shared Home log viewer inside the root inset. Cards and filters remain
visible; panel width stays unchanged. Panel status uses text only, with the
colored dot kept on cards. No additional viewer header or
extra card padding surrounds the viewer; native scrollbars remain hidden while
wheel and keyboard scrolling work. Compress sits directly left of Copy and
returns to the summary. A Load more control reads further log archive pages.

Events reads a separate private compressed stage journal in chronological
order, plus observed session start/termination. Reconnects preserve repeated
phase transitions; unchanged progress samples do not create events. Guest
progress stages use the same canonical names as Home. These events never
write synthetic console lines or change the engine phase. Initial older
journals use only the first observations saved in their summaries and mark
missing historical transitions explicitly. Stage-archive failures never
prevent saving the rental identity or other session data. Full console output
remains separate in Logs; it is never copied into Events.

The three-dot menu copies the canonical session ID or every available archived
log message. Archive reads use complete rows, an uncompressed-byte cursor, at
most 200 rows and approximately 1 MiB per response under the writer's lock. Copy
loads all pages, not only the visible preview. A 32 MiB clipboard limit fails
explicitly rather than copying partial output; larger logs remain exportable
with `vastgame sessions logs ID`. Imported archives warn when older output was
not originally saved. Browsing these details never contacts the provider.

The first local listing imports surviving older desktop jobs once. Job pruning
also archives identified older jobs before deleting their disposable records.
Imported sessions set `logs_complete: false`: output already rotated away,
missing exact instance IDs and destruction times were never saved and cannot
be recovered safely. Unknown times/costs stay null. Import performs no provider
or guest request and never changes a VM. Older unlabelled jobs cannot be mapped
to a rental reliably.

The Windows backend package includes these modules through its existing source
allowlist. The matching native desktop and backend ship together in tagged Windows
releases; existing installations receive both through `vastgame update`.


Settings can explicitly delete session history after confirmation. Per-session
locks serialize deletion with archive writers. Summaries are replaced by hidden
identity tombstones, compressed logs/stages are erased, and readers reject deleted
archives. Identity-only lifecycle updates remain possible for active rigs; late
billing/log writers and legacy imports cannot recreate deleted history. Disposable
job identities remain available for controlling live rigs. New rental IDs keep
recording normally. Settings force shutdown is separate: it checks provider IDs
and canonical Vastgame labels, interrupts only owned workers, blocks new rentals
under the existing lifecycle lock, and uses the shared force-stop path without
SSH or backup. Each destruction must be confirmed by provider absence.

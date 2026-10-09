Implementation follow-up: all three must-fix and seven should-fix findings below have source changes documented in [the fix report](2026-10-09-fixes.md). This review describes the earlier behavior; see the follow-up for current validation limits.

What this repo does: Vastgame rents a GPU VM, restores a packaged game and saves, and streams it through Wolf and Moonlight. The desktop adds host browsing, a game library and explicit launch/shutdown controls over the same CLI engine.

This review assumes one person, one active rental, repeated starts/stops, ordinary network failures and a growing game library. Reviewed on 2026-10-09. Findings below come from source inspection; failure cases were not reproduced against paid VMs.

## Cleanup completed

- Removed seven unused frontend model fields: game version, default selection, installed size, runner, NVIDIA compatibility, developer and publisher fields. Backend JSON contracts remain intact for CLI callers and existing tests.
- Replaced three Rust game-ID validation copies with one validator that matches the backend's first-character rule.
- Merged duplicate banner styling. Removed the incorrect “Previous offers are shown” message after a failed/empty host request.
- Game panels now show only their own launch logs. Starting another Play request clears its old notice.
- Launch and shutdown now update the latest job record under one file lock. A successful shutdown is terminal; late startup writes cannot restore the destroyed VM's identity or overwrite that result.
- Retained-rig restoration no longer depends on valid library presentation metadata. Broken metadata uses the label “Game” and preserves the controls.
- Rewrote desktop documentation around current code ownership and data flow. Removed obsolete read-only/no-launch claims and the nonexistent `CoverArtwork.svelte` reference. Contributor rules now have one canonical home. Desktop README/rules decreased from 179 to 132 lines.
- Preserved intentional empty tabs, the inactive settings gear, dynamic country assets and deployed runtime helpers. No whole source file was proven dead; none was deleted on guesswork.
- Added focused regression cases for terminal job updates, metadata-independent rig restoration and game-ID validation. They were not run, as requested.

## Architecture assessment

The architecture suits the lightweight goal. Svelte handles local state and presentation; Rust exposes fixed commands; Python/shell own accounts, quotes, rentals and save operations. Shared `Button`, `Dropdown`, `Popover`, `BrowsePage`, `SearchRefresh` and `ScrollArea` avoid a second UI system. Hosts and Library share catalog data and the root spacing token.

The existing backend remains authoritative for disk sizing, compatibility, scoring and final price validation. Selecting a card does not rent anything. A price increase requires explicit approval; startup validates again. Exact VM/label checks, lifecycle locks, backup verification and provider-confirmed destruction are useful protections to retain.

The current production frontend is 120.97kB JavaScript and 21.91kB CSS before compression, excluding separate flag assets. This measures shipped frontend files, not total application RAM or CPU. No dependencies were added during cleanup. There is no present need for another framework, router, database or always-running service.

## Must fix

1. **Early shutdown treats current provisioning status as proof that no game ever ran.** [Source](/home/riad/Projects/vastgame/src/manager/persistence.sh:103)
   - **What this is:** The desktop can skip backup for its exact job when `game_requested` is false and Vast reports loading/provisioning.
   - **Problem:** That is local watcher history plus current provider status, not a lifetime activity record. If the desktop watcher ended before requesting the game, CLI reconnect later launched it, and the provider subsequently reports loading again, this condition still permits destruction without backup.
   - **Fix:** Authorize the fast path using trustworthy first-boot evidence or the verified guest's frozen activity guard. Treat missing evidence as unknown and retain the backup requirement.
   - **If we skip it:** Previously created saves can be lost in this recovery case. A faster shutdown must not depend on assuming that “loading” means “never used.”

2. **An uncertain create result loses the identity needed for later recovery.** [Creation recovery](/home/riad/Projects/vastgame/src/manager/launch.sh:116), [desktop restoration](/home/riad/Projects/vastgame/src/client/desktop_launch.py:255)
   - **What this is:** Startup tries to find a created contract by its unique label, then records the VM ID for the desktop.
   - **Problem:** If creation was accepted but its response and all recovery lookups fail, the CLI says no contract was created. Desktop records have no VM ID or persisted pre-create label; reopening skips those jobs even if a later provider lookup finds the billing VM.
   - **Fix:** Persist the unique label before creation. Report an unknown result, then reconcile that exact label on explicit recovery/reopen; never automatically create a replacement.
   - **If we skip it:** A rental may continue billing while the app offers no controls for it. The provider dashboard or CLI becomes necessary to recover it.

3. **Play can race restoration of an existing rental.** [Play](/home/riad/Projects/vastgame/desktop/src/session/launch.svelte.ts:37), [restore](/home/riad/Projects/vastgame/desktop/src/session/launch.svelte.ts:91)
   - **What this is:** Opening the app starts asynchronous restoration of the retained job.
   - **Problem:** A user can click Play before the provider lookup finishes. Play assigns a new job ID, so restoration's `!launch.jobId` condition ignores the real retained rental; the CLI rejects the new start, leaving the existing rig absent from desktop controls.
   - **Fix:** Complete the one restoration attempt before accepting Play, and keep restoration errors distinguishable from “no rig exists.” The shared CLI must continue blocking duplicate rentals.
   - **If we skip it:** A normal fast click during a slow lookup can hide the shutdown target until the user recovers it elsewhere or reopens the app.

## Should fix

4. **Frontend caches preserve failed loads and grow without a memory limit.** [Artwork](/home/riad/Projects/vastgame/desktop/src/library/artwork.ts:2), [details](/home/riad/Projects/vastgame/desktop/src/library/details.ts:6)
   - **What this is:** Frontend maps retain image and metadata request results for reuse.
   - **Problem:** An offline image request caches `null` for the rest of the app session; Refresh does not invalidate it. A successful but empty metadata response is cached for 24 hours. Image data URLs stay in memory after leaving cards; the backend's 64MiB disk cap does not bound this frontend map.
   - **Fix:** Keep in-flight deduplication, bound completed image storage, avoid long caching of failed/partial results, and let manual Refresh retry visible failures. Reuse the existing backend disk cache.
   - **If we skip it:** Reconnecting can leave artwork/reviews missing, and browsing many games keeps increasing memory use.

5. **The game dropdown cannot fit a larger library.** [Shared dropdown](/home/riad/Projects/vastgame/desktop/src/components/Dropdown.svelte:40)
   - **What this is:** Every option is rendered in an absolutely positioned menu with no height bound.
   - **Problem:** At the minimum 600px window, roughly 15 or more game choices exceed the usable height. The menu has neither viewport placement nor a way to reach all choices inside its visible bounds with the mouse.
   - **Fix:** Reuse the shared popup placement logic and add search plus bounded pages for the game picker. This can preserve the requested no-scroll interaction and existing theme.
   - **If we skip it:** A supported library size makes some games difficult or impossible to select by pointer.

6. **“Game running” is a last startup observation, not current status.** [Watcher completion](/home/riad/Projects/vastgame/src/client/desktop_launch.py:230), [game-start wait](/home/riad/Projects/vastgame/src/manager/client.sh:15)
   - **What this is:** The engine confirms startup, then the desktop watcher exits. A reopened app checks VM identity once.
   - **Problem:** Closing the game or destroying the rig externally does not update the open app's running pill. If the startup worker crashes before writing a completion record, its restored inotify watcher can also wait indefinitely for a file event that never comes.
   - **Fix:** Distinguish last-confirmed activity from live state. Add explicit session reconciliation and detect owned-worker exit; use event-driven updates if continuous status is later needed.
   - **If we skip it:** Status and controls can remain stale, hiding that a game stopped or that a retained VM still needs attention.

7. **Changing games rapidly starts overlapping host lookups.** [Host refresh](/home/riad/Projects/vastgame/desktop/src/hosts/HostsPage.svelte:33)
   - **What this is:** A revision number prevents old responses from replacing newer host results.
   - **Problem:** It does not stop the old commands. Choosing five games quickly starts five provider searches and backend processes; only the last result is useful.
   - **Fix:** Allow one active host lookup and keep only the latest queued selection. Preserve the revision guard and game-specific quote validation.
   - **If we skip it:** Slow connections waste requests and CPU, and provider throttling can make the final useful request fail.

8. **Job retention is bounded per launch but unlimited overall.** [Job creation](/home/riad/Projects/vastgame/src/client/desktop_launch.py:163), [history scan](/home/riad/Projects/vastgame/src/client/desktop_launch.py:242)
   - **What this is:** Every launch creates a persistent directory with identity and up to two 2MiB log files.
   - **Problem:** There is no overall pruning policy. Hundreds of retired jobs accumulate, and restoration scans/sorts every job record each time the app opens.
   - **Fix:** Prune only confirmed-stopped jobs under a conservative count/age limit. Never delete live or unresolved identity, account data, manifests or saves.
   - **If we skip it:** Long-term use consumes disk and makes recovery increasingly slow.

9. **Rust response limits apply after full capture, and read-only commands lack an outer deadline.** [Runner](/home/riad/Projects/vastgame/desktop/src-tauri/src/backend.rs:9)
   - **What this is:** Rust collects backend stdout/stderr, then rejects stdout over 8MiB.
   - **Problem:** The limit does not bound memory during capture. A stalled WSL/backend command never reaches the later check and can leave loading active indefinitely; a backend diagnostic failure is reduced to a generic catalog message.
   - **Fix:** Bound stdout/stderr while reading and add deadlines to read-only calls. Return safe specific diagnostics. Keep lifecycle workers independent so closing the UI cannot cancel a paid operation.
   - **If we skip it:** A hung backend has no reliable UI recovery, and unusually large output can exceed the intended memory guard.

10. **The native desktop is absent from the Windows release.** [Public package](/home/riad/Projects/vastgame/packaging/windows/build_update.py:16), [Tauri bundling](/home/riad/Projects/vastgame/desktop/src-tauri/tauri.conf.json)
    - **What this is:** Windows distribution packages the CLI, WSL backend and native streaming tools.
    - **Problem:** The package allowlist contains no Tauri desktop executable, and the release workflow does not build it. A new Windows user cannot install this interface through the current download.
    - **Fix:** Build the desktop on Windows and ship it alongside the same backend version, with WebView2/WSL prerequisites handled in setup.
    - **If we skip it:** Shared frontend source exists, but the actual Windows desktop installation remains incomplete.

## Ten improvements, in priority order

1. **Make fast shutdown evidence-based.** Keep instant teardown for a proven unused VM, with protected backup for unknown or used rigs.
2. **Add a useful Sessions page.** Show the exact retained rig, current/last-confirmed state, and explicit Resume, Refresh status and safe Shutdown actions; recover uncertain creation by its persisted label.
3. **Make browsing use one useful request.** Serialize host refreshes, keep the latest game choice and bound read-only backend responses/timeouts.
4. **Make artwork recover and stay memory-bounded.** Keep cached disk assets, retry visible failures on Refresh, and evict unused frontend image entries.
5. **Add a searchable game picker.** Reuse the themed dropdown/popup and bounded pages so large libraries fit without scrolling or an extra UI framework.
6. **Improve value ranking with actual game results.** Feed observed FPS/frame times into the existing scorer, cap reward once the chosen stream target is met, and weigh game-specific total hourly price. Keep one obvious Best value choice.
7. **Show startup progress by useful stages.** Reuse structured backend progress for boot, total game restore, save restore and game start. Show whole-stage bytes/percentage; use ETA only where throughput/history supports it.
8. **Add a small billing summary.** Show allocated hourly price, elapsed cost estimate and transfer fees. Label estimates clearly and reconcile actual charges through the provider when available.
9. **Expose existing stream settings in Settings.** Reuse the current `stream.json` schema and validator for resolution, FPS, bitrate and codec; explain which changes need reconnecting.
10. **Ship matched Linux/Windows desktop releases.** Package the native app and backend together, provide clear dependency/setup errors, and connect updates to the existing safe updater.

## Validation and limits

The Linux production frontend and native app built successfully. That compiles Rust and Svelte output; it does not prove TypeScript correctness, race behavior, save recovery or UI layout. The build script is Vite-only and does not run a separate TypeScript/Svelte checker.

No tests, lint, typechecks, broad checks, live rentals, shutdowns, backups or provider requests were run for this review. Focused regressions were added but remain unexecuted. No GitHub release or commit was created.

Reviewed all desktop source modules and their critical command/quote/identity/shutdown connections, relevant tests by reading, and Windows release/update boundaries. Not read line by line: the full import/package implementation, every game-state archive/restore branch, Proton/NVIDIA compatibility code, native C++ HUD/crash reporting, all installer scripts and generated flag SVGs. Native Windows execution, game streaming, large-library layout and resource usage were not measured.

Verdict: Keep the architecture. Fix findings 1–3 before expanding paid lifecycle features.

Lean: Seven unused frontend fields and one duplicate CSS rule removed; three validators merged; desktop rules/README reduced by 47 lines; zero dependencies added.

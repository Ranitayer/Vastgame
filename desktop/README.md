# Vastgame desktop

A lightweight Tauri 2 window with Svelte 5, TypeScript and custom CSS. Linux and Windows share the same interface; Windows commands run through the Vastgame WSL backend. Home combines the game library, hosts and game panel. Standalone Hosts and Library pages and tabs are removed. Sessions, Billing and Settings are placeholders.

## Run and build

Install/configure the Vastgame CLI first. Linux expects `~/.local/bin/vastgame`; Windows expects distribution `Vastgame`, user `vastgame` and `/home/vastgame/.local/bin/vastgame` inside WSL.

From this directory, use Node.js 20.19+ or 22.12+, pnpm, Rust and the platform's Tauri 2 build prerequisites. The webview is WebKitGTK on Linux and WebView2 on Windows.

```sh
pnpm install --frozen-lockfile
pnpm tauri dev
pnpm tauri build --no-bundle
```

The Linux binary is `src-tauri/target/release/vastgame-desktop`; Windows produces `src-tauri/target/release/vastgame-desktop.exe`. Native Tauri bundling is disabled; the Windows release workflow builds the native executable and packages it with matching CLI/WSL source. The packager refuses a missing or mismatched executable. Manual workflow runs produce artifacts; tagged runs publish releases. The installer creates a desktop-app Start menu shortcut and installs WebView2 using the signed Microsoft bootstrapper if needed. See [Microsoft distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). Existing Windows users install the app and matching backend with `vastgame update`.

## Code ownership

| Path | Responsibility |
| --- | --- |
| `src/App.svelte` | Native frame, active tab and one selected rig |
| `src/navigation.ts` | Tab definitions and order |
| `src/theme.css` | Palette, shared spacing, sizes and responsive frame |
| `src/components/` | Buttons, dropdowns, notices, popovers, search/refresh and passive scroll indicator |
| `src/home/` | Three-column composition of shared library, host pills and game panel |
| `src/hosts/` | Shared host request queue, local filters/sorting, pills, reusable specs and selected-rig presentation |
| `src/library/` | Shared game catalog, artwork/metadata loading, cover cards, details, Play and Logs |
| `src/session/` | One launch controller, panel progress and shared shutdown interaction |
| `src-tauri/src/backend.rs` | Fixed platform command runner and shared game-ID validation |
| `src-tauri/src/hosts.rs`, `library.rs`, `launch.rs` | Narrow catalog, artwork, quote and lifecycle commands |
| `../src/client/desktop_launch.py` | Redacted engine events, private job identity and restoration watcher |
| `../src/client/offer_quote.py`, `disk_capacity.py` | Shared offer checks and safe game storage sizing |
| `../src/manager/`, `../src/runtime/` | Existing rental, startup, streaming and save engine |

## Data flow

Home invokes `vastgame hosts --json --game ID` for its selected game. CLI and desktop share provider queries, eligibility and the scorer. GPU, continent, price and sorting filter the returned offers locally; changing them makes no network request. `hosts/catalog.svelte.ts` keeps one active request and only the latest queued game choice. Superseded responses never update the host list. Selecting a rig changes UI state only.

Home keeps three columns side by side. The left column has three cover-only game cards per row and centered search/refresh. The middle displays all matching host pills without a Show more limit. Clicking a pill toggles the single rig selection and brightens its surface; a separate circular arrow instantly expands four hardware/network cards in a 2×2 grid within that pill. GPU/continent filters sit above the list; ranking opens upward beside the price slider below. Best value uses the backend score. Prices, including /h, use bold palette green. Narrow host summaries hide download speed first, then VRAM, keeping flag, GPU and full price.

The right column contains the game panel and a centered selected-rig pill matching the dropdown height. During startup, this pill displays stage, activity or measured transfer progress, and fresh ETA side by side on one line. Hover or keyboard focus reveals the launch-time rig snapshot; leaving restores progress. The slot keeps its height. Later rig choices cannot replace the launch snapshot, and recovered sessions cannot invent missing rig information.

The shared game catalog invokes `vastgame list --json`. Manifests describe packages; separate `~/.config/vastgame/library.json` presentation metadata supplies readable titles and Steam IDs. Game covers retain 48-entry batches with Show more. Public Steam artwork uses a 64MiB backend disk cache, two concurrent frontend requests and visibility loading. The completed frontend image cache holds at most 32 entries or 8MiB of encoded characters; offscreen covers release images. Successful description/review summaries retain at most 128 entries for 24 hours. Failed/partial loads remain retryable through Refresh. Remote HTML is converted to plain text.

Play requests a game-specific quote, shows typed failures and asks for another explicit click if the total hourly price increased. Startup revalidates the exact approved offer before using the existing CLI launcher. There is no replacement rig or separate desktop rental pipeline.

`desktop_launch.py` streams redacted JSON events through a Tauri channel. The frontend holds one job and batches at most 500 visible log lines. Per-job records/logs live under `~/.local/state/vastgame/desktop/<job>/`; each log rotates at 2MiB with one previous file. Job updates use a file lock, and completed shutdown cannot be overwritten by late launch progress.

Before creation, the backend persists a unique rental label. Unknown creation results retain that label and block replacement until reconciliation. Opening the app restores identity with one provider lookup; Play waits for it, and lookup failure blocks a new rental. Refresh and window focus reconcile provider identity and, when reachable, exact-label guest game state. Running activity is labelled last confirmed with its observation time. Startup watching uses inotify and owned-process exit events; a one-second PID fallback applies only while startup is active. There is no idle provider polling. Missing library presentation metadata falls back to “Game” without hiding VM controls.

Startup reports five stages: boot, game restore, runtime preparation, save restore and game start. Structured guest tasks supply whole-stage bytes and percentage. Transfer ETA uses remaining bytes divided by measured throughput only while that measurement is at most ten seconds old. Boot/runtime and overall completion have no guessed ETA. The active progress timer stops with startup. Local Moonlight route qualification and guest latency limits are removed; poor network quality does not block preparation or streaming attempts. Identity, runtime and save checks still apply.

Job cleanup removes only stopped records whose worker and engine have exited: retain at least 24 hours, then the newest 50 for up to 30 days. Unresolved rental identities remain protected. Each read-only native command has a 75-second inner deadline and an 85-second outer deadline, with bounded capture of 8MiB stdout and 64KiB stderr. Lifecycle commands have no read-only timeout and retain bounded event lines.

The title bar has no rig/status pills. A ready/running rig shows Vast Connect in place of Play and a matching circular X beside it. X remains available after VM creation even when startup fails. Connect uses the stored job identity to verify the same VM ID and label before reopening Moonlight; it cannot rent a replacement. Its events update Logs without overwriting startup/shutdown state. Shutdown requires two clicks on the shared X control. The backend verifies job, VM ID and label. The existing engine protects possible saves with verified backup before destruction and confirms the provider contract disappeared. Only the verified guest path can prove no game activity: it uses a durable activity marker and an exclusive launch lock. Provider loading status and local watcher state cannot skip backup. Missing or unreachable proof uses protected backup; if that cannot be verified, the rig remains running to protect saves. Closing the window never destroys a VM.

## Interface rules

`AGENTS.md` is the canonical contributor/UI rule file; do not duplicate it here. The current design uses the supplied palette, Material You surfaces, shared buttons and one page-margin token. Game cards show artwork without a text footer, with an inactive circular gear inside the bottom-right corner. Game names remain available in accessible labels and hover titles. Covers never zoom or change size when details open. Host details expand instantly within their pills. Only color fades, timed popup fading, an active-start/connect loading arc animate. Notices are direct popups rather than buttons; notices and shutdown confirmations close after two seconds. Dropdowns remain open for selection. Notices open beside their button with viewport-safe placement. Long-lived error details remain available in Logs. Native frame changes remain instant.

Large dropdowns share popup placement and use search with bounded pages, keeping every choice reachable without scrolling. See [the fix report](../docs/reviews/2026-10-09-fixes.md) for resolved review findings and remaining validation limits.

## Security and operational boundaries

The webview receives public summaries, redacted logs and validated operation results. It has no arbitrary shell/filesystem capability or account credentials. Native IPC exposes fixed commands; quote validation, lifecycle locks, exact identities, save protection and destruction verification stay in the shared engine.

Game-settings buttons and empty tabs are deliberate placeholders. Do not remove flags or runtime helpers merely because they have no static import: flags are loaded dynamically, and shell/bootstrap/package paths deploy backend helpers.

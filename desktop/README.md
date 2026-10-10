# Vastgame desktop

A local Tauri 2 app built with Svelte 5, TypeScript and custom CSS. Linux uses the
installed CLI; Windows uses the same engine in the Vastgame WSL distribution.
The release embeds its interface and does not require a local web server.

[ARCHITECTURE.md](ARCHITECTURE.md) explains UI ownership, every fixed native API,
state, lifecycle, caches and Windows deployment. [AGENTS.md](AGENTS.md) holds
contributor/UI rules. [Sessions](../docs/sessions.md) defines history and billing.
The [current review](../docs/reviews/2026-10-10-project-review.md) records remaining
issues and twenty ranked improvements.

## Build and open

```sh
cd desktop
pnpm install --frozen-lockfile
pnpm build:app
./src-tauri/target/release/vastgame-desktop
```

Use `pnpm tauri dev` with Vite for development. Use `pnpm build:app` for production.
Bare `cargo build --release` can retain the development URL and fail with a refused
localhost connection when Vite is absent. A build alone does not configure the
backend account, stream client or runtime dependencies.

Linux outputs `src-tauri/target/release/vastgame-desktop`; Windows outputs
`src-tauri/target/release/vastgame-desktop.exe`. Tauri bundling is disabled.
The tagged Windows workflow builds the native executable and packages the matching
CLI/WSL source. Manual workflow runs create artifacts; tagged runs publish releases.

## Current interface

- Home combines cover-only games, every matching host pill and the shared right
  game panel. One game-sized host request supplies local GPU/continent/price/sort
  filters. A separate arrow expands specs inside each selectable host pill.
- Explicit Play refreshes the exact quote and asks for another click after a price
  increase. Vast Connect resumes the existing VM's readiness checks. X uses
  protected shutdown during ordinary play, or explicit force during startup,
  reconnect or another shutdown click. Closing the window never destroys a rig.
- Progress and elapsed time share the panel-header pill; hover/focus reveals the
  rig. Full redacted Logs use the common viewer and Copy. Sessions archives retain
  output beyond the 500-entry live buffer.
- Sessions shows banner cards, observed play time, GPU/VRAM/flag, state and total
  cost. Local filters, the three-dot copy menu and the reused right details panel
  share existing controls. Logs/Events expand only inside that panel. Historical
  Connect searches the same machine/GPU within 110% of the previous rate.
- Settings keeps adjacent Streaming/Hosts boxes without scrolling. Height/width
  sizing preserves controls and margins. Streaming fills above Sensitive settings,
  whose bottom ends at the page margin. Save/Reset sit beside the tab. Save keeps
  Saved until another edit; Reset persists streaming/host defaults only.
- Available account credit appears beside the centered tabs. Focus refreshes use
  a cooldown and one active request; a failed refresh preserves the last value.

Streaming settings edit the same `stream.json` consumed by Moonlight on the next
connection. Existing unrelated options are preserved. Verified/capacity minimums
filter hosts; country proximity and preferred GPU influence Best value. Geography
is not measured latency. The spending-limit field is deliberately inactive.

Sensitive actions require confirmation. Force shutdown all targets canonical
Vastgame-labelled account rigs, skips backup, verifies identities and confirms
provider absence. Delete history erases summaries/archives but keeps hidden
identity tombstones and live controls. Detailed results use the shared popup.
These actions never run automatically on browsing, preference save or reset.

Billing remains empty, cover gears are intentionally inactive, and standalone
Hosts/Library tabs are removed. Shared flags/runtime files are dynamically loaded
or deployed and must not be removed as apparently unused imports.

## Artwork, platforms and updates

New PCs resolve game identity and automatically cache visible public Steam
covers/banners. Unique exact matches are required; unknown names stay placeholders.
Two concurrent image requests and bounded caches avoid loading the whole library.
Descriptions/reviews use their own cached request, separate from artwork.

Windows uses native stock Moonlight and the included settings editor. Linux's
Ctrl+Shift+Q overlay, custom HUD and Crashpad hooks do not run inside stock Windows
Moonlight. Running means a detected game process, not proven rendering. Poor
network quality does not block setup; exact identity, integrity, readiness and
save protections remain.

Existing Windows users run `vastgame update`. Fresh installs extract `Vastgame.zip`
and run `Vastgame.cmd`, with their separate private account bundle/enrollment.
The installer creates the desktop shortcut and verifies Microsoft's WebView2
bootstrapper when needed. Public releases contain no account bundles. Updates
preserve accounts, games and stream preferences, with native/backend rollback and
recovery paths. Updating never rents, restarts or destroys a rig.

Build success does not imply live GPU, save-roundtrip or clean-machine Windows
acceptance. The current review records exactly what was and was not validated.

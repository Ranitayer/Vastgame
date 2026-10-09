# Vastgame desktop architecture

Vastgame uses a modular monolith: one existing gaming engine, with a small desktop
interface in front of it. The interface does not implement a second VM manager,
package publisher, save system or scoring algorithm.

The desktop currently provides window controls, six navigation tabs and a live,
read-only Hosts browser. Home, Library, Sessions, Billing and Settings remain
empty. Clicking a host shows specifications; it does not rent it. Closing the
window does not stop a VM or terminate Moonlight.

## The three layers

| Layer | Implementation | Responsibility |
| --- | --- | --- |
| Presentation | Svelte 5, TypeScript and custom CSS | Tabs, filters, host cards, details and keyboard interaction |
| Native bridge | Tauri 2 and Rust | Native window controls and a fixed host-browsing command |
| Gaming engine | Existing Bash, Python and jq modules | Provider access, scoring, VM lifecycle, games, saves and streaming |

Linux renders the interface with WebKitGTK; Windows uses WebView2. Release builds
embed compiled HTML, CSS, JavaScript and local artwork in the native executable.
Node, pnpm and Vite are build/development tools, not production services. The
existing backend still needs its own tools and account configuration.

## Files and ownership

```text
desktop/
  src/
    main.ts                   Mount Svelte and load the shared theme
    App.svelte                Window shell, title bar and active tab
    navigation.ts             Tab IDs, labels and icons
    theme.css                 Shared colors, spacing and shell styles
    components/
      TabBar.svelte           Accessible tab navigation
      Dropdown.svelte         Shared themed menus and keyboard behavior
      ScrollArea.svelte       Scrolling with a passive indicator
    hosts/
      HostsPage.svelte        Fetching, local state, filtering and sorting
      HostFilters.svelte     Search, refresh, continent, sort and price controls
      HostCard.svelte        Compact offer summary
      HostDetails.svelte     Selected host's specification cards
      DetailIcon.svelte      Icons used by the specification cards
      CountryLabel.svelte    Location text and local flag artwork
      continents.ts          Local country-to-continent grouping
      types.ts               UI models and display formatting
      flags/                 Licensed local SVG assets
  src-tauri/
    src/main.rs              Register the native command and start Tauri
    src/hosts.rs             Invoke the installed backend safely
    capabilities/main.json  Allowed window/event operations
    tauri.conf.json          Window, content security and build configuration
  AGENTS.md                  Palette, component and interaction rules
```

Shared components own their interaction behavior. Host components own host
presentation. HostsPage connects them; individual cards do not call the provider
or own a separate offer cache.

The existing engine lives outside desktop:

| Location | Responsibility |
| --- | --- |
| `bin/vastgame` | Load the shared engine and dispatch commands |
| `src/manager/` | Commands, locks, provider operations, readiness, persistence and client launch |
| `src/providers/vast/` | Provider-specific scoring and sanitized desktop summaries |
| `src/bootstrap/` | Guest startup and bootstrap payload preparation |
| `src/runtime/` | Game preparation, sessions, saves, display setup and guest telemetry |
| `src/client/` | Catalog, ingestion, publication, stream preferences, diagnostics and native Moonlight HUD/menu |
| `packaging/` | Windows installation/updates, templates and Core VM image construction |

The desktop UI and in-stream Moonlight HUD/menu are separate interfaces. The
webview does not decode game video or draw the gameplay HUD. Streaming remains
in native Moonlight; Wolf and the game runtime run on the rented VM.

## What happens when Hosts opens

1. HostsPage fetches once on its first activation, calling the fixed Tauri command
   `browse_hosts`. Further searches are manual through Refresh.
2. Rust runs `~/.local/bin/vastgame hosts --json` on Linux. On Windows it runs the
   installed backend through `wsl.exe`, distribution Vastgame, user vastgame.
   Windows does not display an extra command console.
3. The backend calculates required disk space using selected-game sizing, or
   60 GB without a selected game, and searches Vast offers.
4. `rank_host_offers` uses the same `rank.jq` scorer as CLI selection. It resolves
   saved stream settings and reads selected-game/machine history.
5. `desktop_hosts.py` serializes already-filtered offers into allowlisted public fields,
   including the score. Rust rejects unsuccessful commands, invalid JSON,
   missing offer arrays and output larger than 8 MiB.
6. Svelte stores the catalog in memory and renders an initial batch of 48 cards.
   Show more exposes the remaining returned offers without creating every card
   element at first paint.

Browsing has no application price, region or 15-result shortlist cap. Both views
use search_host_offers with an explicit 10,000-offer request ceiling, avoiding
the provider’s smaller implicit response. The provider may still impose limits. CLI and app use one provider eligibility
query in host_offer_query and one local eligibility/ranking implementation in
rank_host_offers/rank.jq. Both require NVIDIA VM offers with at least 6 GB VRAM,
four effective CPU cores, one GPU, direct ports and sufficient disk. The app has
no separate consumer-only whitelist, CPU architecture rule, rented flag rule or
history exclusion. Workstation/datacenter models follow the CLI rules too.
Recent provider GPU failures lower the shared score instead of disappearing
only from the app. These eligibility rules do not guarantee successful rental.

CLI selection adds its existing Europe, price and shortlist limits. App browsing
keeps worldwide results and applies the visible continent/search/price controls
locally. Counts can still differ with view limits, provider snapshots or cached
results; eligibility no longer differs between the two interfaces.

## State, filters and sorting

The active tab belongs to App. Host catalog, selected host, loading/error state,
filters and visible-card count belong to HostsPage. Svelte's reactive derived
values calculate matches and ordering; there is no global store, router, SQLite
database or background polling service.

Search matches GPU, location and CPU text. Continent choices come from the fetched
catalog using a local map; unknown locations remain visible under All continents.
Price filtering and sorting happen locally, without new requests for every
keystroke or slider movement. Sort sits left of the price slider in one
non-wrapping group; the whole group can move to the next row on a narrow window.

Lowest price is the default. Highest price reverses price order. Best value uses
the backend's existing overall gaming score, including target fit, price,
location, network/storage, CPU, VRAM, reliability and recent machine history.
The desktop does not recreate that formula. Uncapped browsing does not alter the
scorer's CLI price reference. Equal scores prefer lower prices, then offer ID
for stable ordering. Missing scores sort behind scored offers.

Refresh after changing the selected game or stream settings to obtain updated
scores. Hardware estimates are not guaranteed FPS. Advertised network speeds are
not measured latency to the user.

Leaving Hosts removes its card DOM, closes the details panel and retains the
catalog and filter state in memory. Returning does not refetch automatically.
Closing and reopening the application starts a new UI session. A failed refresh
keeps previous offers visible and reports an error.

## Layout and theme

Theme CSS owns semantic palette tokens and the shared 24 px page margin. The
surface is `#151d28`, neutral controls use `#202e37` and `#394a50`, and selected
tabs use `#884b2b`. Components consume these tokens rather than separate themes.
System fonts, inline icons and bundled flags avoid runtime asset downloads.
Flag artwork retains its original semantic colors and MIT attribution.

The title bar centers compact tabs between the draggable brand area and native
window controls. Windowed mode has rounded corners. Maximized/fullscreen mode
uses square edges with no outer gap. Native resize events update this treatment;
there is no custom window animation or continuous resize polling.

Host cards use a responsive CSS grid. VRAM sits beside the GPU name; vCPU count
and system RAM sit below. Selecting a host creates a neighboring details column,
not an overlay. Selecting it again, Escape or Close removes that column. Choosing
another host updates the same open panel. Layout changes are instant, with no
FLIP, sliding, fading or delayed animation state.

Details fill the available column height. Each specification has a rounded tonal
card with centered icon/label, value and secondary information. Cards use their
content height, except Memory matches the adjacent Storage card. Long hardware
names have hover titles where compact layouts truncate them. The minimum native
window size is 600×600; compact styles reduce padding and text size on smaller
windows. The details panel does not scroll.

The card list scrolls normally with wheel, touchpad, touch or keyboard. Its passive
scroll indicator is centered in the shared gutter; it has no hover, drag, click
or selection behavior. Scroll events and ResizeObserver update it, not timers.
Menus share one component, use neutral rounded surfaces and 4 px choice gaps,
and support arrows, Home/End, Escape and visible keyboard focus.

## Security and failure boundaries

The frontend supplies no executable path, shell string, provider arguments or
credentials. Rust exposes one fixed read-only host command. Account access stays
in the installed backend, and raw API records and raw failure output are not
forwarded to the webview. UI models describe only fields the interface consumes;
additional backend API fields remain compatible with existing consumers.

Tauri capabilities grant required native window and resize-event operations.
The content security policy restricts scripts/assets to local content and
connections to Tauri IPC. Host browsing does not acquire a VM lifecycle lock,
rent an instance, change game saves or stop an existing session.

Errors appear in the interface instead of silently replacing valid data. Full
operational diagnostics remain the existing backend's responsibility; native
Moonlight crash reporting is separate from this desktop shell.

## Building and platform limits

From desktop:

```sh
pnpm install --frozen-lockfile
pnpm tauri dev
pnpm tauri build --no-bundle
```

Use tauri dev for development and tauri build --no-bundle for the native
executable; they are separate workflows. Linux output is
`src-tauri/target/release/vastgame-desktop`; Windows output has an `.exe` suffix.
Build on each target platform. Linux requires GTK 3/WebKitGTK 4.1; Windows requires
WebView2 and native C++ build tools for source builds. Shared UI code does not
remove OS compositor, font or webview differences.

Rust release settings optimize size, strip symbols and use link-time optimization.
No UI framework, remote font library, database or bundled Chromium runtime is
added. Keep both dependency lockfiles. node_modules, dist and Rust build outputs
are generated artifacts, not source; deleting the release executable's build
directory also removes the executable used by the local launcher.

This desktop build is not yet a Windows installer or automatic desktop updater.
Existing Windows backend installation/update packaging is a separate workflow.

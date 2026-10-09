# Vastgame desktop rules

- Use Tauri 2, Svelte 5, TypeScript and custom CSS. Keep Rust integration thin.
- Reuse the existing Vastgame engine; never duplicate lifecycle, game, save or account logic.
- Hosts has read-only live NVIDIA GPU cards and a details drawer. All other pages are empty. Do not add rental actions, other page contents, databases, plugins, services or background polling until requested.
- Keep search, icon refresh, available-continent selection and live price filtering in `HostFilters.svelte`. Continent options come only from fetched offers using the local country map. Use shared `components/Dropdown.svelte` for all dropdowns, with 4px between choices and neutral themed surfaces, never the native select popup; show every option without scrolling. Unknown locations remain visible under All continents. Filtering and sorting are local and never make requests per slider movement. Keep the price slider and sort dropdown in one non-wrapping group, with sort on the left and the slider on the right; wrap the whole group on narrow windows. Sort by lowest price, highest price or best value. Best value consumes the existing backend scorer, using saved stream targets and game history, never a frontend scoring formula.
- Hosts has no page heading. Put filters directly beneath the title bar; search and continent controls share a compact width. Dropdowns and slider use neutral palette surfaces, not the selected-tab accent. Keep a visible gutter between cards and their scrollbar.
- All pages use `--page-margin` for equal space below the title bar, at the left, right and bottom. Page and card gaps share this token; avoid independent outer padding.
- Host details fill the available column height, with individual Pixel-style icon-labelled specification cards. Center each card’s icon, label, value and secondary detail. Use content-height cards, except Memory matches the adjacent Storage card height; network cards include transfer prices. No tabs, latency or repeated GPU/location/price fields. The panel does not scroll. Minimum native window size is 600×600.
- Use `ScrollArea.svelte` for a passive scroll indicator, centered in the shared card/panel gutter. It must have no hover, pointer or selection behavior. Preserve wheel, touchpad, touch and keyboard scrolling, and use scroll/resize events rather than polling.
- Host details occupy a column beside the cards, never a modal overlay. Toggle closed when the selected card is clicked again; switching cards updates the existing panel without restarting its layout animation. Keep opening and closing atomic, with no card movement animations, delayed layout state or panel opacity/fly transitions. Show essential specifications, no offer/machine IDs, power/PCIe details or requested disk.
- Host cards show muted VRAM beside the GPU name; CPU and system RAM stay below.
- Country flags use locally bundled, MIT-licensed SVGs through `CountryLabel.svelte`. Their original flag colors are permitted semantic artwork. Load images lazily as separate local assets, without a remote service or new runtime library.
- Keep host models, cards, details and page coordination in `src/hosts/`. Fetch only on first opening Hosts and manual refresh. Show no invented latency. Backend browsing has no price/region/15-result shortlist cap; use shared `search_host_offers` with an explicit 10,000-offer request ceiling instead of provider defaults and must not change CLI launch filters, accounts, selected games or VMs.
- Keep tab definitions in `src/navigation.ts` and navigation presentation/keyboard behavior in `src/components/TabBar.svelte`. Keep one active tab in the app; do not add a router for these local pages.
- Center compact tabs within the full title bar using equal left/right layout columns. No tab panel background: hover uses `#394a50`, selection uses the accent `#884b2b`. Keep window controls separate from tab input. Use labelled icons on narrow windows and preserve keyboard navigation.
- Use only the supplied palette below. Default window surface is the selected `#151d28`.
- Keep shared semantic colors in `src/theme.css`; components consume those tokens.
- Follow Material You principles: rounded surfaces, restrained tonal hierarchy, generous spacing and simple, consistently centered controls. No heavy UI framework, blur, animated background or permanent animation loop.
- Use system fonts and inline SVG icons. No remote fonts, icons or runtime CDN assets.
- Preserve keyboard access, visible focus, accessible button names and readable contrast. Respect reduced motion when adding animation.
- Use layout units that adapt to window size and OS scaling. Keep Linux and Windows styling shared; isolate unavoidable platform behavior.
- Maximized and fullscreen windows must fill their bounds with square corners and no outer border or gap. Restore rounded corners in windowed mode. React to native window events, never poll continuously.
- Keep window frame changes instant, with no custom animation. Never animate native window bounds manually or stretch the webview content; the OS compositor owns the resize behavior.
- Do not expose arbitrary shell execution, filesystem or account credentials to the webview. Grant only required Tauri capabilities.
- UI closing must not stop or destroy a VM. Future operations must retain existing locking, identity and save guarantees.

## Supplied palette

```text
#172038 #253a5e #3c5e8b #4f8fba #73bed3 #a4dddb
#19332d #25562e #468232 #75a743 #a8ca58 #d0da91
#4d2b32 #7a4841 #ad7757 #c09473 #d7b594 #e7d5b3
#341c27 #602c2c #884b2b #be772b #de9e41 #e8c170
#241527 #411d31 #752438 #a53030 #cf573c #da863e
#1e1d39 #402751 #7a367b #a23e8c #c65197 #df84a5
#090a14 #10141f #151d28 #202e37 #394a50 #577277
#819796 #a8b5b2 #c7cfcc #ebede9
```

Transparency is permitted for the outer rounded corners. It is not an additional theme color.

- CLI and app must share `host_offer_query` and `rank_host_offers` eligibility. The desktop serializer only validates public fields; never add a separate GPU whitelist, architecture rule or history exclusion. View price/region/shortlist limits may differ.

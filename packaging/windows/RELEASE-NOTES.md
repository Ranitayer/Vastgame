Vastgame 1.1.6 fixes Windows updates and includes the current shared backend.

- Fixes `System.Byte` / `Trim` errors when downloading the release checksum. The updater reads the checksum file as UTF-8 text and retains SHA-256 verification and safe ZIP handling.
- CLI selection and desktop host browsing share provider eligibility, fetching and scoring. An explicit larger offer request avoids missing rigs from the provider's default response.
- Ranking uses saved stream resolution/FPS targets and recent matching game measurements, with price/value weighting and expiring route history penalties.
- Adds the read-only `vastgame hosts --json` command. The experimental Tauri desktop interface is available in source; this ZIP installs the Windows CLI/backend and native Moonlight.

Fresh install: extract `Vastgame.zip` and run `Vastgame.cmd`. Setup still requires a private account bundle and matching Tailscale enrollment.

Existing install: extract `Vastgame.zip` and run `Update-Vastgame.cmd` from that extracted folder. Installations with the broken updater must use this manual route once; subsequent `vastgame update` calls use the fixed script.

Accounts, game profiles, stream preferences and running VMs are preserved. No credentials, account bundles, games or saves are included in the public release. Publishing or applying this update does not rent, restart or destroy a VM.

Automated tests and Windows hardware validation were not run for this release, at the user's request.

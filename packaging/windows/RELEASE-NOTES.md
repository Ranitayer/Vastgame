# Vastgame 1.1.7 — Windows desktop

- Includes the native Windows desktop, built from the same source commit as the WSL backend. Setup installs Microsoft WebView2 when missing and the Start-menu shortcut opens the app. The CLI remains available through `vastgame`.
- Home combines cover-art game browsing, selectable rigs, game details and launch controls. The standalone Hosts and Library tabs and title-bar status pills are removed.
- Running rigs show Vast Connect and a matching shutdown button. Connect verifies the existing VM identity and reopens its Moonlight stream without renting another VM.
- Removes local Moonlight route qualification, guest latency gates and route-history ranking adjustments. Network quality no longer blocks startup; identity, runtime, storage and save checks remain.
- Dependency installation waits up to ten minutes for Ubuntu's package-manager lock, within a fifteen-minute install deadline. Failure reports identify lock timeouts and retain guest startup-console evidence after the VM starts.
- Uses the verified guest activity guard for backup-free shutdown. Unknown activity retains save protection.
- Persists rental identity before creation and reconciles uncertain results by the exact label. Play waits for retained-session restoration.
- Adds bounded artwork/metadata caches with failed-load retries, searchable paged dropdowns and one active host lookup with the latest selection queued.
- Adds whole-stage startup measurements for boot, game restore, runtime preparation, saves and game start. ETA appears only for fresh measured transfers.
- Refresh and window focus reconcile retained sessions without idle polling. Historical stopped jobs have bounded retention; live and unresolved identities are preserved.
- Read-only backend requests have output and time limits. Lifecycle workers remain independent of the desktop window.

Fresh install: extract `Vastgame.zip` and run `Vastgame.cmd`. Setup requires the existing private account bundle and matching Tailscale enrollment. Public downloads contain no accounts, games or saves.

Existing install: extract the ZIP and run `Update-Vastgame.cmd`, or use `vastgame update`. The updater closes only the local desktop window before replacing its binary. If it cannot close, it asks you to close that window and retry. Running VMs, accounts, game profiles and stream preferences are preserved.

Publishing and applying this release do not rent, restart or destroy a VM. Automated tests and Windows hardware validation remain unrun at the user's request; release publication requires the native Windows build to succeed.

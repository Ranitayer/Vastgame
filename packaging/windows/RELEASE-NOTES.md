Faster ZIP ingestion with the same public download for installation and updates.

- Large ZIPs use up to eight parallel connections when safe HTTP ranges are available.
- Range responses must match their exact byte positions, total and strong ETag.
- Downloads retain a resumable contiguous prefix and fall back to one connection when necessary.
- Use `--connections 1` to disable parallel downloading, or `--connections 4` for fewer connections.
- Progress continues to refresh every 0.1 seconds, including the combined download speed.

- Extract `Vastgame.zip`, then run `Vastgame.cmd` to install or `Update-Vastgame.cmd` to update.
- Afterwards, run `vastgame update` to get the newest release.
- Fresh installation downloads pinned official dependencies and imports your private account bundle separately.
- Updates preserve accounts, game profiles, stream settings, Moonlight pairing and running VMs.
- Updates coordinate with imports and other commands; failures roll back changed files.
- Includes current startup, diagnostics, persistence and cleanup fixes.

No account keys, games or saves are included in the public download. A fresh installation needs the private account bundle described in the included README. Syntax and packaging checks were performed; tests and real download-speed measurements were not run. Windows installation and streaming require validation on Windows hardware.

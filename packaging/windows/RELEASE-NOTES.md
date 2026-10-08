Vastgame 1.1.5 fixes access to the active game display when changing stream resolution.

- The display helper uses the running game's user and X11 environment instead of Docker's root identity. This fixes local Xwayland display authorization without changing permissions or replacing the game runtime.
- Resize failures now show a short diagnostic instead of printing the entire helper program.

Includes the stream controls, telemetry and import progress improvements from 1.1.4:

- Reconnecting to a running game applies the selected stream resolution to its Gamescope virtual screen. The operation verifies the VM and game session, uses Gamescope's built-in mode control, and leaves the active runtime, game settings and saves intact. Games that cache display modes may need a game restart. If resizing is unavailable, streaming continues with a warning.
- Native Linux Moonlight gains the bottom-left stream menu, with the requested dark palette, centered button text and a working Ctrl+Alt+Shift+M shortcut. The HUD stays sized to the local display when stream resolution changes. Menu preferences use the existing stream settings file.
- VM telemetry survives brief gaps and can use a verified SSH fallback when the status connection fails. Older readings show their age and do not enter performance scores.
- Ingest upload progress uses the full measured archive size, overall percentage and an ETA for remaining bytes. A bounded local compression pass measures the total once and caches it for retries; previously verified chunks do not inflate upload speed.
- The Windows ZIP includes the updated shared backend. Windows uses its native Moonlight overlay and the existing stream settings editor; the custom menu and transparent Vastgame HUD remain native Linux features.

Install/update: download `Vastgame.zip`, extract it, then run `Vastgame.cmd` or `Update-Vastgame.cmd`. Existing installations can run `vastgame update`. Existing accounts, profiles and stream settings are preserved.

No account credentials, games or saves are included in the public ZIP. Tests and extra validation were not run for this release at the user's request. Applying the client update does not restart or destroy an existing VM; display resizing is requested on the next stream connection.

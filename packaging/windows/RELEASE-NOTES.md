# Vastgame 1.1.9 — Reliable reconnect, force shutdown and full logs

- Vast Connect resumes the same rig's Tailscale, bootstrap, game, runtime and save readiness checks before opening Moonlight. It never rents a replacement or treats an online peer as a fully prepared rig.
- First X attempts protected shutdown. Another explicit X click during backup or after failure force-destroys that exact rig without SSH or save backup. Force cancels only the owned shutdown worker, bypasses its busy lock, verifies the provider VM ID/label and waits for confirmed destruction. Unbacked saves may be lost. Old worker events cannot revive a stopped rig.
- Protected shutdown tries the verified Tailscale SSH route before public Vast endpoints and shows actual SSH errors. CLI stop and desktop X share the guest lifetime guard. New rigs publish cancellation evidence before dependency installation, allowing confirmed unused games to skip backup.
- Logs show full redacted output, including progress, precise values, errors and traceback indentation. Text fills the box with a slight inset and palette colors, without timestamps, generated INFO/RIG labels, headings or row dividers. Copy includes every retained message and shows Copied for one second.
- Native Linux's existing in-stream settings menu now opens with Ctrl+Shift+Q. Moonlight's Ctrl+Alt+Shift+Q quit shortcut remains available. Windows continues using the included stream settings editor; this release does not add the Linux overlay to Windows.
- Includes the matching native Windows desktop and WSL backend. Automatic covers, banners, game metadata and bounded caches remain available on new PCs.

Existing installs: run `vastgame update`, or extract the ZIP and run `Update-Vastgame.cmd`. The updater preserves account data, games, saves and stream preferences. Fresh installs: extract `Vastgame.zip` and run `Vastgame.cmd`; the private account bundle and matching Tailscale enrollment are still required.

Publishing and applying the update do not rent, restart or destroy a VM. Automated tests and live streaming/VM checks remain unrun at the user's request. Publication requires a successful native Windows build from the same source commit as the packaged backend.

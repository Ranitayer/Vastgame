# Runtime

`vastgame start <id>` publishes a verified runtime bundle and hash-pinned launch
manifest, creates the selected Vast VM, checks its launch identity over Tailscale,
then waits for restore/preparation and Wolf readiness before opening Moonlight.
GE-Proton, Steam Runtime, DXVK/VKD3D and the prefix prepare during setup.

Multipart restore downloads up to eight parts, verifies each part, feeds the
ordered stream into extraction and deletes consumed inputs. The game is
published only after the whole compressed stream, executable and working
directory pass validation. Progress reports download/extraction separately;
transfer ETA excludes final checks. Terminal panels and spinners redraw every
0.1 seconds even while status requests are slow. Rendering time is included in
the frame schedule; slower terminals may display fewer frames. Provider queries retain their
normal cadence; animation never invents download measurements. Completed progress retains measured total
restore throughput and exact machine/launch identity for host history.

Save discovery uses the bundled Ludusavi catalog. Use `vastgame saves <id>
--title "Exact title"` if name matching is ambiguous. Store-dependent paths may
require the manifest's `store` field or explicit `state.saves` paths. Entries
can specify `base` (`prefix`, `game`, `saves`, `configs`, `shaders`), relative
`path`, and `required: true`. Required paths must exist and contain files.
Supported user registry is saved as per-prefix `user.reg`/`userdef.reg`; system
registry and unresolved store paths are not guessed.

Live checkpoints on new VMs back up mapped saves/configs every two minutes
following completion of the previous attempt. They never stop gameplay.
Inventory hashes before and after capture reject changing data. Stable shader caches are captured too; if a cache changes, checkpoints
reuse the prior compatible shader object. Final exit captures shaders again. Check the VM journal for deferred/failed checkpoints. A sudden VM loss
can lose changes made after its last successful checkpoint.

`vastgame backup <id>` closes the game and verifies saves/configs/shaders without
destroying the VM. `vastgame stop` performs that final backup, verifies the
receipt against the selected instance/game, then requests destruction and
waits for account listing confirmation. Failures retain management identity
and avoid a false billing-stopped message. `vastgame restore <id>` requires an
idle game and verifies every object/member before changing live files. Save and
shader writes use unique private temporary files, ownership through the open
descriptor and atomic replacement. Each file replacement is atomic; a disk
failure midway through a multi-file restore still requires retry/recovery.

Snapshots use `state/<id>/snapshots/<timestamp-uuid>/COMMITTED.json`; objects
are per-game content-addressed archives. Shader state keys include actual
GPU/driver, game identity and prepared runner/component builds. Driver-specific
NGX DLLs are freshly provisioned and cannot enter state backups. Wolf pairing
remains in `system/v1/wolf-identity-v1.tar.gz`.

Native Linux Moonlight supports the transparent top-left HUD and optional
local-only Crashpad reports. Windows uses stock Moonlight telemetry; our native
HUD/Crashpad hooks do not run there. Alt+Tab remains local. Display mode uses
the client's detected native resolution and current refresh rate.

Source updates apply to future VM setup. Existing VMs keep their deployed
bootstrap; the final backup command can deploy updated state helpers safely.
Windows releases require rebuilding from source. No live GPU/Windows test is
implied by passing offline regression tests.

Game launch waits up to five minutes for a checkpoint or restore to release the
state lock. It reports the wait in launch status. Final-backup markers still
block launch immediately; lock files are never deleted to bypass persistence.

Boot, Tailscale and restore use a single in-place terminal line. Redirected
restore logs record stage/action/percentage changes rather than repeating
completed tasks or elapsed-time updates. This also avoids scrollback duplication
in short terminal windows.

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
half-second even while status requests are slow. Provider queries retain their
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
idle game and verifies every object/member before changing live files.

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

# Vastgame system architecture

Vastgame is a modular monolith: one CLI engine serves Linux, Windows/WSL and the
native desktop. `bin/vastgame` resolves its installed source, normalizes the legacy
force alias before lifecycle capture, loads manager modules and dispatches one
command. Only a start request loads host selection and creation. Windows packages
the same source; private account configuration is separate.

Read the [app architecture](../desktop/ARCHITECTURE.md) for detailed UI ownership,
fixed native commands, state and deployment; [runtime](runtime.md) for preparation
and saves; [sessions](sessions.md) for history/billing; and the
[Ubuntu CLI template](core-vm-template.md) for the current official VM image.
Old Core filenames are compatibility names, not a second custom image pipeline.

## Ownership

| Layer | Responsibility |
| --- | --- |
| `desktop/src/` | Presentation, request queues, drafts and one rig controller |
| `desktop/src-tauri/src/` | Validated fixed IPC, native process transport/window controls |
| `src/manager/` | CLI, locks, provider calls, startup, streaming and shutdown |
| `src/providers/vast/` | Shared eligibility/scoring, public summaries, credit and charges |
| `src/client/` | Quotes, local jobs/history/preferences, evidence, artwork, ingestion/publication and overlays |
| `src/bootstrap/` | Private packed payload, guest dependency/GPU setup and status service |
| `src/runtime/` | Verified restores, Proton/Lutris, launch guards, telemetry and game state |
| `packaging/windows/` | Public installer/update, native integrations and separate private export tooling |

The app never duplicates provider scoring, rentals or save logic. Native commands
pass fixed argument lists; the webview cannot choose shell commands or read
credentials. Public artwork requests happen in Python. The guest status service
exposes progress and launch identity over Tailscale. Hostnames alone never prove
identity.

## Lifecycle and concurrency

Explicit Play/start reads stream targets, verifies account/package state, sizes
storage, refreshes the exact offer and approves its total hourly rate. The manager
publishes hash-verified runtime/manifest objects, reserves a unique rental label,
and requests `vm: true` using the saved template. Unknown creation responses retain
identity and block replacements. Contract ID plus launch label bind routes, logs,
streaming, state access and history.

Startup waits for guest/Tailscale identity and game/runtime/save/Wolf readiness.
Connect resumes the same pipeline on the existing VM; it never rents. Network
quality does not gate startup. Compatibility, storage, integrity and readiness
checks remain. Detected game processes do not prove successful rendering.

Protected stop freezes new game launches, closes only the selected game, verifies
Wine registry flush/idle state and a committed save snapshot, then destroys the
original ID/label and waits for provider absence. A verified guest lifetime guard
can skip backup for an unused game. Missing guest access or uncertain saves retains
the VM. Explicit force skips guest/backup work but retains identity/absence checks;
unbacked saves can be lost. App closure never destroys a VM.

`lifecycle.lock` serializes local lifecycle operations. `catalog.lock` serializes
imports/publication/removal; ingestion can overlap a session. Explicit force uses
an exact-instance lock to bypass a busy protected backup. Force shutdown all
cancels owned workers and holds the local lifecycle lock while handling its
provider snapshot. Detached clients close inherited lock descriptors. These locks
do not cover different PCs sharing the same account: concurrent clients can race
an initially empty account check.

Guest state has per-game locks and durable stopping/activity markers. Failed final
shutdown keeps its launch block; explicit state resume releases it without backup,
launch or destruction. Job writes are serialized. Stopped state is terminal, and
late launch/reconnect/quote results cannot revive it or submit replacement rentals.

## Data lifetimes

- Immutable game parts use SHA256 version directories. The full stream and launch
  paths are verified before publication; a new package never overwrites its old version.
- Hash-pinned launch manifests define the package, runner and save policy.
- Per-game snapshots publish unique `COMMITTED.json` markers only after verifying
  every remote object. Saves/configs remain separate from game binaries.
- Shader objects include GPU/driver/runtime/game compatibility. Unknown identity
  disables shader reuse without disabling save persistence.
- Wolf pairing is generic infrastructure, separate from per-game state.
- The durable session ledger, compressed logs/stages, receipts and billing survive
  disposable desktop-job pruning. History deletion keeps hidden identity tombstones
  so stale workers/imports cannot recreate erased history or lose live controls.
- Build/transfer workspaces and presentation caches are disposable. Active or
  unresolved identities and user saves are not cleanup candidates.

Restore validates objects, members and destinations before applying files. Saves
and shaders share unique private temporary files with atomic per-file replacement;
old predictable temporary symlinks cannot redirect privileged writes. A multi-file
restore is not one transaction. Live snapshots validate file stability, but cannot
prove application-level consistency across independently written save files.

## Preferences and observability

`desktop-settings` shares Moonlight's existing `stream.json` and privately stores
host preferences. Both groups validate under a settings lock, each file is replaced
atomically, and reported failures roll back. A process/power failure between two
replacements is not covered by a durable transaction journal. Other Moonlight
options are preserved; preferences apply on the next connection. Country scoring
uses bundled representative locations, not latency. Verified/capacity filters work;
the spending-limit value is deliberately inactive.

Session records contain exact rental identity, rig/quote, milestones, observed game
time, backup state, errors and charge observations. Charge attribution checks exact
instance IDs/labels and uses decimal totals. Pending/reported/stale are distinct.
Compute/storage estimates exclude network/adjustments and are not invoices. Explicit
charge refresh is bounded and read-only.

Startup exposes five stages with fresh measured transfer progress. Logs retain
redacted original output; Events retains stage/lifecycle transitions. Failure
evidence is private, bounded and never uploaded automatically. Read-only native
calls have fixed time/capture limits; lifecycle operations stream without those
deadlines. History/log retention is deliberately separate from active-job rotation.

## Windows deployment

The tagged workflow builds x64 Tauri on Windows and packages the matching
executable/checksum/source descriptor with allowlisted engine/installer files.
Private account exports never enter the public ZIP. `vastgame update` checks the
release/archive, closes the app window, coordinates native/backend activation under
locks, preserves private data, and reports rollback/recovery paths. Hashes establish
integrity relative to the GitHub release; the app/update payload is not independently
signed. Live VMs keep their deployed bootstrap until a future rental.

The [current review](reviews/2026-10-10-project-review.md) records remaining issues,
cleanup, validation limits and twenty prioritized improvements. Older reviews remain
dated records, not current contributor rules.

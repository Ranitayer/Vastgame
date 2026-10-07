# Architecture

Vastgame is a modular monolith. `bin/vastgame` loads manager modules and one
command dispatcher; `hosts.sh` and `launch.sh` run only for a start request.
Linux links to the source. Windows packages the same entry point/modules into
its WSL environment, with account configuration packaged separately.

The manager owns provider calls and user interaction. The verified runtime
bundle owns VM preparation, game launch and state I/O. Client helpers own
local save discovery, package publication, HUD rendering and crash reports.
The VM's small Tailscale status server exposes progress and its launch identity.

State has separate lifetimes:

- Game parts are immutable under a SHA256 version directory.
- Launch manifests are immutable hash-pinned metadata objects.
- Per-game snapshots publish a unique commit only after verifying their objects.
- Shader objects are keyed by GPU/driver/runtime/game compatibility.
- Wolf pairing is generic infrastructure, separate from game state.
- Local history, receipts and instance identity are durable management data.
- Build workspaces, temporary state transfer directories and old session logs
  are disposable once their processes have exited.

Local mutating operations share `lifecycle.lock`; background client processes
close that descriptor before detaching. VM state operations have a separate
per-game lock. Live checkpoints never stop a game. Final shutdown stops it,
verifies persistent state and polls the provider for destruction completion.

Provider contract ID plus unique launch label bind routing, logs, streaming,
state access and restore-history attribution. A hostname is only a candidate
hint. Identity or network ambiguity fails safely rather than choosing another VM.

# Vastgame

A multi-game Vast cloud-gaming manager using Wolf, Lutris/GE-Proton,
Tailscale and Moonlight. One modular source tree serves Linux and Windows/WSL.

## Use

```sh
python3 scripts/install.py
vastgame add /path/to/game my-game
vastgame inspect my-game
vastgame saves my-game --title "Exact game title"
vastgame package my-game
vastgame start my-game
vastgame stop
```

`vastgame help` lists all commands. Short commands and `vastgame game ...`
share one implementation. The host list remains interactive. `force` skips
route-quality checks, while identity, integrity and persistence checks still apply.

Host searches include unverified rigs and all NVIDIA GPU families, including
RTX 3060/3070 Ti and professional/datacenter models, with at least 6 GB VRAM.
Bandwidth and reliability affect ranking without excluding offers. Price,
region, storage and VM compatibility requirements still apply; GPU streaming
support is checked during setup.

If native Linux Moonlight fails to load its shared libraries, the launcher retries
an already installed Flatpak Moonlight and imports the native client identity
and settings while Moonlight is closed. Previous Flatpak settings are backed up
locally. The custom native HUD and Crashpad are unavailable through Flatpak.

The experimental prebuilt Core VM build is defined in
[the Core VM guide](docs/core-vm-template.md). It prepares the actual guest disk
and can be built locally or through GitHub Actions. The first image is published
and passed local boot/runtime checks. A local `core-image.json` selects its pinned
digest for a fresh Vast launch; public package access is required. Fresh Vast
GPU/streaming acceptance remains pending.

## Source layout

| Folder | Owns |
|---|---|
| `bin/` | CLI entry point |
| `src/manager/` | Catalog, lifecycle, host selection, networking, progress, persistence and client coordination |
| `src/providers/vast/` | Offer scoring, including recent measured delivery and restore performance |
| `src/bootstrap/` | VM preflight, packed transport and setup |
| `src/runtime/` | Verified restore, Proton preparation, Lutris launch, telemetry and game state |
| `src/client/` | Save discovery, immutable package publication, Linux HUD and Crashpad |
| `packaging/windows/` | Installer source and native Windows/WSL bridge |
| `scripts/` | Linux installation and private Core VM template management |
| `tests/` | Regression tests; no rental required |
| `docs/` | Current architecture, runtime and Core VM template reference |

Linux installation links to this checkout. Windows installers embed the same
source. Generated Windows workspaces and dependency downloads are disposable;
recreating a release requires reacquiring its build tools/assets. Existing
installer releases do not receive these source changes automatically.

## Guarantees and limits

- One local lifecycle/catalog writer at a time. An existing Vastgame VM blocks
  another rental. Game removal requires no Vastgame VMs in the account.
- Connections verify the selected contract ID and its unique launch label;
  peer names alone never select a streaming host.
- New packages use SHA256 version directories. Remote part hashes and commit
  contents are verified before the local manifest selects the new version.
  Existing `v1` packages remain readable; repackaging publishes a new immutable
  version without overwriting them. Launch manifests are separately hash-pinned.
- Setup prepares Proton, DX12 and the prefix before streaming. Downloads and
  extraction overlap; executable and checksum checks precede publication.
- Save coverage must be declared or matched to actual catalog save locations.
  Unresolved store paths block final shutdown unless explicit save paths cover
  them. Wine user registry, configs and compatible shaders persist separately
  from game binaries and driver DLLs.
- New VMs take verified live checkpoints every two minutes after the previous
  attempt finishes. Checkpoints capture mapped saves/configs without closing the
  game and capture stable shaders, reusing a prior compatible object when changing. Final shutdown captures
  shaders and the broader Wine user-data safety net after a clean game exit.
- Changing files, failed uploads, missing saves or unavailable SSH keep the VM.
  Destruction is reported complete only after Vast confirms the contract is gone.
- Unexpected VM loss can lose progress since the last successful checkpoint.
  File-level validation is not an application-level transaction across multiple
  independently written save files. Checkpoint failures are in the VM journal:
  `journalctl -u vastgame-checkpoint.service`.
- Restore throughput is measured by the active multipart pipeline and recorded
  against its machine/launch identity. Linux HUD sessions already record actual
  gameplay/delivery measurements for scoring. Missing measurements receive no
  invented performance bonus.
- Disk sizing allows installed bytes, eight compressed parts in flight (or a
  complete legacy archive), 15% headroom and a 35 GiB system/runtime/state reserve,
  with a 60 GB minimum. Vast uses decimal GB. Large unusual state needs extra room.

## Accounts and local data

Vast API access, an authenticated rclone Drive remote, Tailscale, SSH keys and
Moonlight are required. The private Core VM template supplies bootstrap auth.
Optional `~/.config/vastgame/bootstrap.json` accepts `TS_AUTHKEY` and
`RCLONE_CONFIG_B64`; keep it private with mode `600`. Personal Windows installers
contain account configuration and must remain private.

| Path | Contents |
|---|---|
| `~/.config/vastgame/` | Template, manifests, local packages and private bootstrap overrides |
| `~/.local/state/vastgame/` | Selected instance/game, locks, host history, backup receipts and session logs |
| `~/.local/share/vastgame/native/` | Installed HUD/Crashpad binaries |
| `~/.cache/vastgame/` | Save-discovery catalog and disposable build inputs |
| `~/.config/vastai/`, `~/.config/rclone/`, `~/.ssh/` | Accounts and authentication |

XDG overrides are honored. Wolf identity is independent at
`VastGaming/system/v1/wolf-identity-v1.tar.gz`. Game data lives under
`games/<id>/`; verified snapshots and state objects live under `state/<id>/`.
Removal purges those two namespaces only. Verified recovery snapshots are
retained; they are not temporary logs.

## Validation

```sh
python3 -B -m unittest discover -s tests -v
```

Native socket checks require an unrestricted local runner. Executed Windows
PowerShell checks require `pwsh`; Windows installer source checks run without it.
Fresh-VM gameplay and Windows installation must still be tested on their target
systems after a release change. Changes here do not patch or restart existing VMs.

See [runtime](docs/runtime.md), [architecture](docs/architecture.md) and
[Core VM template](docs/core-vm-template.md).

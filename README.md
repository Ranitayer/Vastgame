# Vastgame

A multi-game Vast cloud-gaming manager using Wolf, Lutris/GE-Proton,
Tailscale and Moonlight. One modular source tree serves Linux and Windows/WSL.

## Use

Startup and client failures save private, redacted evidence under
`~/.local/state/vastgame/reports/<instance-id>/`. Run `vastgame logs report` to read
the latest summary and locate its files. Reports include status transitions and
messages, image/machine/game identity, provider and host-daemon logs, and guest
bootstrap, preparation, Proton, NVIDIA, service and Wolf logs when a verified
connection is reachable. Local Moonlight output and references to matching
Crashpad sessions provide client context; reports are never uploaded automatically.

Summaries name the evidence files and distinguish a reported condition from an
unknown underlying cause. A missing VM domain does not prove why VM creation
failed. Probes have time limits; provider logs request up to 20,000 lines, each
capture is capped at 16 MiB, and journal/container/game tails are labelled.
Unavailable logs and collector exit codes are recorded rather than hidden.
Credential fields, private keys and URLs are redacted; inspect a report before
sharing because arbitrary game output can contain personal information.

Explicit GPU preparation errors are recorded once per instance. Ranking applies a seven-day penalty of
18 points for one failed rental or 30 for repeated failures. App errors do not
penalize hosts. Missing-domain logs and planned `next_state` transitions do not abort
boot. The 15-minute boot budget pauses the local watcher, retains the VM and saves
evidence; it does not prove VM failure or penalize the host. Resume with
`vastgame force connect`. Confirmed `running` status clears a prior provisioning
penalty for that same instance. Reports flag provisioning failures on multiple machines using the
same image within 24 hours as a compatibility investigation, not a proven diagnosis.
Bootstrap command failures include source file, line, exit code and command name;
expanded arguments are omitted to keep credentials out of logs.

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
and passed local boot/runtime checks. A configured `core-image.json` selects its pinned digest; removing that selection
uses the template image. The custom-image Vast launch integration remains
unverified. The launcher warns when it is selected.
Changing image selection does not modify an existing VM. Fresh Vast GPU/streaming
acceptance remains pending.

All rental requests explicitly send `vm: true`, including template-based launches.
The installed Vast CLI does not expose this field; the shared API helper preserves
the template's image and environment unless a custom image is selected.
Boot and Tailscale waits check provider logs every 30 seconds. Explicit bootstrap
errors stop the watcher. Missing-domain messages alone do not stop boot. Current
provider GPU errors are reported even when a stop is planned; confirmed running
status takes precedence over historical errors. Timeouts retain the VM.

Core VM startup excludes NVIDIA driver packages from unattended updates to keep
loaded drivers and libraries consistent during play. Other automatic security
updates remain enabled. Upgrade NVIDIA drivers between sessions and reboot or
safely reload them before launching a game. The guest GPU check refreshes CDI
device definitions and reports driver errors before starting game downloads.

## Stream settings

Run `vastgame streamedit` to open the settings in a Linux editor or Windows
Notepad. It creates defaults if the file is missing and performs no VM operations.
Edit `~/.config/vastgame/stream.json` on Linux. Windows uses `stream.json` in the
installed app folder, normally `%LOCALAPPDATA%\Vastgame`; open the included
`Edit-Stream-Settings.cmd`. Save before `vastgame start` or `vastgame connect`.
Disconnect and reconnect Moonlight to apply changes; no new VM is needed.

```json
{
  "resolution": "1920x1080",
  "fps": 60,
  "bitrate_mbps": 30,
  "video_codec": "AV1",
  "video_decoder": "auto",
  "display_mode": "fullscreen",
  "moonlight_options": {
    "vsync": true,
    "frame-pacing": true,
    "hdr": false,
    "yuv444": false,
    "audio-config": "stereo",
    "absolute-mouse": false,
    "multi-controller": true,
    "capture-system-keys": "never",
    "performance-overlay": true
  }
}
```

`resolution` and `fps` default to `"native"`, following the detected screen at each
connection. `bitrate_mbps: null` leaves bitrate to Moonlight's existing settings;
30 means 30 Mbps (passed as 30000 Kbps). Codec accepts `auto`, `AV1`, `HEVC`, or
`H.264`; decoder accepts `auto`, `hardware`, or `software`. Display mode accepts
`fullscreen`, `borderless`, or `windowed`. Windows defaults to AV1; Linux to auto.
Malformed or unsupported settings fail before a rental or connection.

`moonlight_options` supports Moonlight's stream CLI toggles: `vsync`,
`multi-controller`, `quit-after`, `absolute-mouse`, `mouse-buttons-swap`,
`touchscreen-trackpad`, `game-optimization`, `audio-on-host`, `frame-pacing`,
`mute-on-focus-loss`, `background-gamepad`, `reverse-scroll-direction`,
`swap-gamepad-buttons`, `keep-awake`, `performance-overlay`, `hdr`, and `yuv444`.
Each takes true/false. `audio-config` accepts `stereo`, `5.1-surround`, or
`7.1-surround`; `capture-system-keys` accepts `never`, `fullscreen`, or `always`.
`packet-size` accepts 256–1400 bytes. Omitted options retain Moonlight defaults,
except relative mouse, multiple controllers, local system shortcuts and the
performance overlay, which retain Vastgame's defaults.

These are stream targets, not a guarantee of game FPS or hardware support.
In-game graphics, DLSS and frame generation remain controlled inside the game.
Moonlight GUI-only preferences still use Moonlight's own settings screen.
Updates preserve an existing stream.json instead of overwriting your choices.

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

- Lifecycle operations and catalog writers have separate locks. Ingestion can
  overlap VM startup/connect/stop; catalog edits, packaging and removal cannot
  overlap an import. An existing Vastgame VM blocks another rental. Game removal
  requires no Vastgame VMs in the account.
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
- Backup/restore use the existing VM launch manifest, not another computer's local
  save mappings. Its checksum is rechecked under the guest state lock. State tools
  are staged and verified at `/opt/vastgame-state/<sha256>/`; they never replace
  the running game/checkpoint runtime at `/opt/vastgame`. Matching container probes
  execute through stdin without installing files. Local save-policy changes apply
  to future launches; an existing VM's policy is not silently migrated.
- Ordinary backup clears its temporary launch block on close, upload or receipt
  failure. Final shutdown retains its block on failure so another game cannot
  start during a shutdown retry. Retry `vastgame stop`, or deliberately abandon
  that shutdown with `vastgame state resume <game-id>`. Resume only releases the
  launch block; it performs no backup, game launch or destruction.
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

## Local cleanup

Run `vastgame cleanup` to preview expired local artifacts. Run
`vastgame cleanup --apply` to remove the currently eligible inactive folders.
The command rechecks eligibility and process use; a changed preview is not an
authorization to delete active data. Apply acquires lifecycle, catalog and build
locks. Unreadable processes keep candidates whose inactivity cannot be established;
the command reports the process ID instead of aborting the preview. An empty
preview skips process inspection entirely.

Cleanup keeps the newest ten HUD sessions, crash sessions and failure reports,
plus all sessions/reports used within seven days. The latest failure report,
selected instance report and current Moonlight log directory are protected.
Only older recognized Windows backend backups are removed, retaining the newest
valid recovery backend; unknown backups are retained. Known Core/Windows build,
state-transfer and abandoned update workspaces require at least 24 hours of
inactivity. Active process references and live session PIDs protect folders.
HUD metrics rotate at 16 MiB, retaining one previous file per session.

Cleanup never contacts Vast or Drive. It excludes save backups/snapshots, account
configuration, host history, current backends, release files, dependency assets
and ingest staging. It does not prune Docker images. The same command is available
in updated Windows/WSL packages; existing installers require rebuilding/updating
to receive it. Completed build receipts at the root of `build/` are retained.

## Accounts and local data

Vast API access, an authenticated rclone Drive remote, Tailscale, SSH keys and
Moonlight are required. The private Core VM template supplies bootstrap auth.
Optional `~/.config/vastgame/bootstrap.json` accepts `TS_AUTHKEY` and
`RCLONE_CONFIG_B64`; keep it private with mode `600`. Windows releases contain no
account data; private account exports must never be published.

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


### Import a game from a direct ZIP URL

```bash
vastgame ingest 'https://example.com/portable-game.zip' my-game
vastgame ingest 'https://example.com/portable-game.zip' my-game --exe Game/Game.exe --sha256 <ZIP-SHA256>
vastgame start my-game
```

The importer accepts direct HTTP(S) ZIP downloads containing portable or already
installed Windows games. It downloads into private local staging, checks ZIP paths
and entry types, extracts with CRC verification, and uses the same executable
detector, manifest validator, save discovery and publisher as `vastgame add` and
`vastgame package`. One executable continues automatically; multiple plausible
executables require a choice or `--exe` relative to the ZIP root. Installers,
HTML/login pages, encrypted ZIPs, split archives and self-extracting executables
are unsupported. Portable detection does not guarantee a game's Wine compatibility.

Repeat the same URL after a failure to reuse staging. Partial downloads resume
only when the server provides a strong ETag or Last-Modified validator and a valid
range response; otherwise the download restarts. Signed URLs are not saved in
staging metadata. `--sha256` verifies the original ZIP against a checksum you trust;
transport and package hashes alone do not establish source authenticity.

Large ZIP downloads use up to eight parallel HTTP range connections when the
server supplies a strong ETag and known length. Every range must match its exact
offset, length, total and ETag. A bounded window of at most eight 32 MiB pieces is
appended in order and discarded; no second full archive is assembled. Failures
retain the contiguous ZIP prefix for the existing resume path. Servers that
ignore/reject ranges, lack suitable validators or limit concurrent requests use
one connection instead. Use `--connections 1` to force a single connection, or
`--connections 4` for a smaller window. A server-wide bandwidth cap still applies.
The progress line shows the connection mode and combined throughput. This change
applies to new ingest processes; it does not change an import already running.
Parallel mode needs another 32 MiB of free headroom while committing a piece;
otherwise it falls back to a single connection. Range handling follows
[HTTP semantics](https://www.rfc-editor.org/rfc/rfc9110.html#name-range).

Staging needs space for the downloaded ZIP, extracted game and 576 MiB of upload
workspace. Packaging streams tar/zstd into at most two 256 MiB chunks. Each chunk
is hash-addressed, uploaded immutably, verified against Drive's MD5, then discarded.
The publisher creates and checks the destination folder before parallel uploads,
preventing competing Google Drive folder creation. Existing duplicate folders stop
publication early with a repair message; they are never merged or deleted automatically.
The restore path also verifies SHA256 for every chunk and the complete stream.
Failed uploads retain verified receipts for retry. Package commits and the remote
manifest verify before the local catalog entry becomes visible. Existing packages
remain readable. Imports leave the catalog unchanged on failure and delete their
staging after success; use `--keep-staging` to retain it. Staging is under
`~/.cache/vastgame/ingest/`; no VM is rented or modified during import.

The same backend works in the Windows WSL installation when its app files are
updated. URL ingestion is local; a cloud worker and source-specific adapters are
not included.

Import progress refreshes every 0.1 seconds in an interactive terminal, independently
of blocking reads or uploads. It shows the current stage, byte progress, measured
MiB/s, ETA and elapsed time through download, hashing, extraction, detection,
packaging/upload, verified publication and cleanup. Upload percentages initially
cover only the compressed data produced so far; the final compressed total is
unknown until packaging finishes. Its ETA is explicitly for queued data until
then. Verification and cleanup show activity instead of an invented percentage.
Redirected output emits periodic snapshots every five seconds instead of terminal
control codes. Executable selection pauses rendering so prompts remain readable.

ZIP ingestion supports stored, Deflate, Bzip2 and LZMA entries. On Python 3.14
or newer it also supports Zstandard ZIP entries (method IDs 93 and legacy 20).
Older Python installations report the requirement and retain the downloaded ZIP.


### Actual game performance in the Vastgame HUD

Fresh VM setup installs MangoHud in the same Lutris container image used for
preparation and gameplay (including 32-bit support when the repository supplies
it). At launch, Vastgame enables its Vulkan layer with a hidden overlay and
starts logging through a per-launch abstract Unix control socket. This avoids
hidden-overlay/autostart behavior in older MangoHud versions. It does not enable
DLSS, change resolution, or apply a new FPS cap; existing user caps are retained.

The VM reads fresh, complete CSV samples for the configured executable. Each
launch gets its own private log directory, so other executables and old sessions
cannot supply its FPS. MangoHud supplies measured game FPS and frametime, plus
CPU temperature and GPU power/clocks where supported. VM CPU/RAM and NVIDIA
GPU/VRAM/temperature stats remain independently measured. The collector reads
at 0.5-second intervals and caches NVIDIA hardware probes for two seconds.

The existing transparent top-left HUD shows game FPS separately from Moonlight
stream FPS. VM packets must match the current game/session and be fresh before
the client merges them. Missing or stale game data stays unknown with an explicit
status; stream FPS is never substituted for it. Session history continues to
store the measured game metrics. The client refreshes merged metrics roughly
once a second, subject to network response times.

This integrates with native Linux Moonlight's existing custom HUD. Windows and
Flatpak clients retain their stock overlays; MangoHud server collection alone
does not add VM FPS to those overlays. Source changes apply on the next VM setup;
existing VMs need the updated container image and runtime before relaunching.

## Windows releases and updates

Download [Vastgame.zip](https://github.com/Ranitayer/Vastgame/releases/latest/download/Vastgame.zip),
extract it and run `Vastgame.cmd` for a fresh installation or `Update-Vastgame.cmd`
for an existing installation. Fresh setup downloads pinned official dependencies;
updates reuse them. Afterward, your friend runs `vastgame update` or uses the
Update Vastgame shortcut. There is one public download name across versions.

The public release contains no account credentials, private configuration or game
profiles. Fresh installations import a private `Vastgame-Accounts.tar` separately.
Export it on your configured Linux computer with:

```sh
python3 packaging/windows/export_accounts.py --output ~/Downloads/Vastgame-Accounts.tar
```

Transfer that account bundle privately; never attach it to a GitHub release.
Existing Windows installations keep their accounts and profiles during updates.
The updater verifies download/file checksums, holds lifecycle and catalog locks,
stages the backend and restores changed files if installation fails.

To publish later changes from this checkout, commit the intended source changes,
then run `bash scripts/release-windows.sh 1.1.3` with a new version. GitHub builds
and publishes `Vastgame.zip` automatically from that exact tag. Account bundles,
dependency downloads and local build workspaces are excluded. Review
`packaging/windows/RELEASE-NOTES.md` before publishing. No VM is changed by release
publication or client updates.

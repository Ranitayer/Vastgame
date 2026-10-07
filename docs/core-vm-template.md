# Vastgame Core VM

The private Vast template is named **Vastgame Core VM**. Its source definition is
`packaging/templates/core-vm.json`; the verified account receipt is
`~/.config/vastgame/core-vm-template.json`.

It uses `docker.io/vastai/kvm:ubuntu_cli_22.04-2025-11-21`, SSH direct mode and a
50 GB template minimum. Vastgame overrides disk capacity with the selected game's
calculated requirement. The template requires VM-capable hosts and one GPU;
the CLI retains its normal budget, regional and hardware-quality filters.

## Startup

- Boots a headless Ubuntu 22.04 VM; no local desktop/login manager is needed for
  Wolf's per-game streaming session.
- Checks and installs missing basic dependencies, Docker and NVIDIA Container
  Toolkit. A single dependency pass batches the missing packages into one install
  after one APT update. If HTTPS/key tools are missing, a prerequisite installation
  requires an initial update before adding NVIDIA's repository. Prepared VMs skip
  APT completely. Fresh toolkit installation defaults to `1.20.1-1`, configurable
  with `NVIDIA_CONTAINER_TOOLKIT_VERSION`; all four package versions are checked
  before installation. Unavailable versions fail clearly without silently using
  another release. Existing compatible toolkit installations remain.
- Validates GPU/daemon availability and virtual input devices before the large
  game restore; repairs injected SSH public-key permissions without disabling
  strict SSH checks. Failed module loading is tolerated only when the actual input
  devices exist; missing devices produce an explicit diagnostic.
- Sets persistent `options nvidia_drm modeset=1` and verifies the live parameter
  before game/image restore. A disabled, unused DRM module is reloaded without
  force; a busy module produces a reboot-required diagnostic. No reboot, process
  termination or unloading of the core NVIDIA driver is performed automatically.
  This handles the headless base loading DRM with modesetting disabled; passing
  new parameters to an already loaded module alone does not enable it.
- Runs the existing checksummed core/image restore and concurrent game restore,
  Proton/DX12/prefix preparation, verified state restoration and direct Wolf launch.
- Keeps per-game state and Wolf pairing separate. No game-specific content is
  embedded in the template.
- Injects the current client's Tailscale address and the selected force policy
  into the compressed startup script. Force mode skips both network-quality gates;
  normal mode retains its limit. Authentication and startup failures still stop.

The official base is version-tagged; this is not a newly baked custom VM disk.
Missing dependencies and Proton/runtime downloads can still occur on first boot.
Performance improvements must be measured during a real startup. VM inventory
remains limited to hosts that support VMs.

## Test and rollback

```sh
vastgame force start still
```

Choose a rig as usual. An existing Vastgame instance takes precedence and causes
the launcher to reconnect; that does not test the new template. Complete a safe
stop of the previous instance before testing a fresh deployment.

The previous account template remains available. To select it again:

```sh
vastgame setup
# Paste the hash stored in ~/.config/vastgame/template_hash.before-core-vm
```

For account setup/recreation, run `python3 scripts/create-core-template.py`.
To update the existing owned private template from the current source, add
`--update`; saved settings are read back before the local hash is replaced.
It uses the Vast CLI, copies only required authentication fields from the current
private template, creates no duplicates when the existing definition matches,
verifies privacy/image/mode/filter/environment readback before selection, and
never rents or destroys a VM. Template definitions contain no account secrets.
Do not publish the account template containing inherited authentication values.

Template creation, readback, force-mode behavior and failure guards have local
regression coverage. Fresh headless VM startup/gameplay remains a live acceptance
test; no VM was launched during setup.

The old exported desktop launch command is not the Core VM definition: it includes
desktop/VNC portals, an obsolete embedded bootstrap and fixed 150 GB storage.
Use the launcher so the selected template, verified runtime and game disk estimate
are applied together. The updated startup transport and template onstart have
one top-level shebang and preserve shebangs inside generated runtime scripts.

## Experimental prebuilt guest image

The manual `Build experimental Vastgame Core VM` workflow in
`Ranitayer/Vastgame` publishes `ghcr.io/ranitayer/vastgame-core:build-<commit>`.
It does not select a template or rent a VM. GitHub's scoped Actions token publishes
only the image; Vast, Drive, Tailscale and Moonlight credentials are never build
inputs. The repository and package may remain private during validation; Vast
will then need registry pull authentication for the eventual test template.

`packaging/core-vm/build.sh` extracts the official wrapper's Ubuntu guest disk,
grows its root filesystem, and installs dependencies *inside that disk* using
libguestfs. It preserves the official supervisor, entrypoint, environment and working directory.
The final wrapper is flattened so the overwritten original guest disk is not
also downloaded as a hidden parent layer. Wrapper configuration is compared before
publication. An existing prepared image can be flattened by supplying its full
registry digest in the workflow, without repeating runtime installation. The official base and
Wolf/Lutris images are resolved to content digests and recorded in the build
receipt; a new manual build can resolve newer upstream digests. The resulting
published image must be selected by its registry digest for a live test, not by
a mutable tag. The receipt records the exact source commit and package inventory
is embedded at `/usr/share/vastgame/core-packages.txt`.

Container preparation runs after a local boot of the real guest kernel and systemd.
Temporary SSH access listens only on localhost; its keys, cloud-init override and
network settings are removed before publication.

The guest caches Wolf/Lutris and the preparation image in Docker's overlay2 store.
It runs the existing Lutris preparation path with a disposable `cmd.exe` probe to
warm UMU, GE-Proton, Steam Runtime, DXVK and VKD3D. A build fails if that preparation
fails or does not resolve an installed Proton executable. The test prefix, Lutris
library, settings and telemetry are removed; only reusable runtime downloads
survive. SSH host/client identities and machine identity are cleared with
virt-sysprep. No games, saves, user pairing or host-specific NGX DLLs are included.

At runtime the bootstrap copies the seed into each game's existing bind mounts,
validates the cached Proton executable and avoids alias-based Proton updates.
Custom Wine runners bypass the GE-Proton seed. Each real game still gets its own
prefix, state restore, graphics checks and readiness validation. Game files,
Wolf identity and the small generic core archive still restore separately.

**Acceptance is pending a successful image build and fresh Vast launch.**
A successful CI build validates the guest filesystem and runtime preparation, not
Vast's host-specific KVM launch protocol, GPU passthrough, encoding or gameplay.
The working official-image template remains selected until those checks succeed.
Software virtualization is used during disk preparation so a builder does not
need a physical GPU; the final wrapper still uses Vast's KVM launcher.

### Local image builds

The same builder can run on an x86_64 Linux workstation with Docker,
libguestfs tools, QEMU, jq and Python installed. Run it as an ordinary user
with access to Docker. It defaults to disk-backed `build/core-vm-work`,
requires 40 GiB free, and places guest networking sockets in a private `/tmp`
directory for the duration of the build. It does not change the desktop's
runtime directory or disable AppArmor.

```bash
CORE_IMAGE=ghcr.io/ranitayer/vastgame-core \
GITHUB_SHA=$(git rev-parse HEAD) bash packaging/core-vm/build.sh
```

Upload the resulting `build-<commit>` image to GHCR using an account authorized
to write that package. Record its registry digest in the build receipt.
Publishing is not live acceptance: test the resulting image on Vast before
selecting it as the default.

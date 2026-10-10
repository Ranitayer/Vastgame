# Vastgame Ubuntu CLI VM

The private Vast template is named **Vastgame Ubuntu CLI**. Its source definition is
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
- Dependency installation waits up to ten minutes for the package-manager lock,
  within a fifteen-minute install deadline. Existing automatic updates are left
  running; no lock files are deleted or package processes killed. Reports retain
  guest bootstrap console evidence even when Vast reports the VM as running,
  so a lock timeout is diagnosed as a blocked dependency installation.
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
- Starts without client-route qualification or VM latency limits. Network quality
  does not block game preparation. Authentication and genuine startup failures still stop.

The official base is version-tagged; this is not a newly baked custom VM disk.
Missing dependencies and Proton/runtime downloads can still occur on first boot.
Performance improvements must be measured during a real startup. VM inventory
remains limited to hosts that support VMs.

## Test and rollback

```sh
vastgame start still
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
private template, reuses the former Core VM template when migrating its name, creates no duplicates,
verifies privacy/image/mode/filter/environment readback before selection, and
never rents or destroys a VM. Template definitions contain no account secrets.
Do not publish the account template containing inherited authentication values.

Template creation, readback and failure guards have local
regression coverage. Fresh headless VM startup/gameplay remains a live acceptance
test; no VM was launched during setup.

The old exported desktop launch command is not the Core VM definition: it includes
desktop/VNC portals, an obsolete embedded bootstrap and fixed 150 GB storage.
Use the launcher so the selected template, verified runtime and game disk estimate
are applied together. The updated startup transport and template onstart have
one top-level shebang and preserve shebangs inside generated runtime scripts.

## Image and template cleanup

The experimental custom guest image and its builder have been retired. Launches
use the official image defined above; old local custom-image selection files are
ignored. The latest desktop gaming template is retained only as a rollback option.
Older gaming templates must not be selected. The unrelated Windows VM template
is outside this cleanup.

The official Docker Hub tag was confirmed active on 2026-10-10, with digest
`sha256:a6f350dcd5616f3b98ce239ce3fdd534c1ddd59f6fcbebbe1db4c5f8a1f721ba`.
The template uses the version tag supplied by Vast. No VM was rented for this
configuration update. Configuration readback verifies the image, SSH mode, VM
filter, private environment and startup command; it does not prove GPU passthrough
or game streaming on a particular host.

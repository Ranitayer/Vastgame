VASTGAME FOR WINDOWS - PERSONAL INSTALLER

1. Run Vastgame-Setup-Personal.exe and enter the separate installer password.
2. Leave Finish WSL setup and account checks enabled on the final page.
3. Approve Windows prompts for WSL/Tailscale. WSL may require a restart.
   After a restart, open Complete Vastgame Setup from the Start menu.
   Setup checks hardware virtualization, enables the required Windows features,
   enables hypervisor boot when disabled and starts the Host Compute Service.
   It pauses before importing Vastgame whenever those changes need a restart.
4. Enroll this Windows device in your existing Tailscale account when prompted.
   A reusable enrollment key supplied when building skips this sign-in.
5. Open Vastgame from the Start menu or a new Command Prompt:
     vastgame list
     vastgame start pragmata
     vastgame start still
     vastgame force connect
     vastgame stop
     vastgame add "D:\Games\My Game" my-game
     vastgame package my-game

Your current Vast API key, Drive OAuth configuration, template, SSH credentials,
game manifests and Moonlight client pairing are included in the encrypted
installer. It is PERSONAL: keep the password separate and do not distribute
this installer to other people. Local game binaries are not bundled. Already
uploaded games can start immediately; their Linux source folders are removed
from imported manifests because those paths are unavailable on Windows.

Windows Moonlight runs natively using the primary screen's current physical
resolution and refresh rate. It uses relative mouse mode, controller passthrough
and local Windows Alt+Tab. The Windows version uses Moonlight's native statistics
(Ctrl+Alt+Shift+S); the Linux custom HUD is not included on Windows.

The backend runs in a separate WSL 2 distribution named Vastgame. Existing WSL
installations and their default settings are left alone. Native Windows
Tailscale is used, including any existing login into the expected tailnet.
The setup verifies Drive and Vast access without renting any VM.

The installer is not code-signed and Windows may show a publisher warning.
Dependencies are pinned and checksummed when built; Tailscale's installer
signature is also checked on Windows. Setup needs internet for WSL and Linux
package installation. Revoked/expired account tokens require reauthorization.

Uninstall removes Windows app files, but deliberately retains the Vastgame WSL
distribution, its account configuration and all remote games/saves. It does not
stop or destroy a Vast instance, delete remote data or uninstall Tailscale.
Do not remove the WSL distribution while packaging or backing up a game.

If setup fails, its console shows the cause. Run Complete Vastgame Setup again.
Logs from the backend are in /home/vastgame/.local/state/vastgame inside WSL.

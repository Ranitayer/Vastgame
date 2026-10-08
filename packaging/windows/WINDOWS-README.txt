VASTGAME FOR WINDOWS

Download Vastgame.zip from https://github.com/Ranitayer/Vastgame/releases/latest
Extract the whole folder. Double-click Vastgame.cmd.

Existing installation:
  Double-click Update-Vastgame.cmd to apply this release.
  Afterwards use `vastgame update` or Start > Vastgame > Update Vastgame.
  Existing accounts, game profiles, stream settings and running VMs are preserved.
  Imports/other commands block updates. Failed updates roll back changed files.

Fresh installation:
  Vastgame downloads pinned official Moonlight, Tailscale and Ubuntu dependencies.
  Windows may request administrator approval and a restart for WSL 2.
  After restarting, open Complete Vastgame Setup or run Vastgame.cmd again.
  Choose your PRIVATE Vastgame-Accounts.tar when asked, then enroll in the matching
  Tailscale account. It is never included in the public app or GitHub release.
  Setup verifies accounts without renting a VM. WSL data remains local.

Export the account bundle on your configured Linux PC:
  python3 packaging/windows/export_accounts.py --output ~/Downloads/Vastgame-Accounts.tar
Transfer this file privately, separately from the public release. It contains
Vast/Drive keys, SSH keys, template configuration and uploaded game profiles.
Do not put it in GitHub, a public download folder or screenshots.

Commands:
  vastgame list
  vastgame start GAME
  vastgame connect
  vastgame stop
  vastgame streamedit
  vastgame cleanup
  vastgame update

`vastgame streamedit` and `Edit-Stream-Settings.cmd` edit the installed settings.
Save and close Notepad; Vastgame confirms the saved resolution and FPS.
The Windows client uses native Moonlight, AV1 by default, local Alt+Tab and the
screen's configured resolution/refresh targets. Ctrl+Alt+Shift+S shows Moonlight
statistics. The native Linux Vastgame HUD is not included on Windows.

Update failures retain one or more recovery backends in the WSL Vastgame data
folder. `vastgame cleanup` previews eligible old backups before removal.
No updater rents, stops or destroys VMs. Saves and cloud snapshots are untouched.
The public ZIP is not code-signed. Dependency hashes verify downloads; Tailscale's
Windows installer signature is also checked. Actual Windows installation and
streaming still require testing on Windows hardware.

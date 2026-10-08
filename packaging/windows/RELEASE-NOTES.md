Vastgame 1.1.3 fixes VM game FPS collection and stream settings editing.

- Lutris now launches the selected game through MangoHud. Its transparent collector avoids MangoHud versions where a hidden overlay prevents logging.
- The collector accepts MangoHud's Wine game filenames and keeps game FPS separate from Moonlight stream FPS.
- `vastgame streamedit` waits for the editor, validates the saved file, and confirms the selected resolution/FPS. The Windows editor opens the installed settings even when started from an extracted release folder.
- The Windows ZIP carries these backend fixes. Windows stock Moonlight still shows its own stream statistics; the transparent Vastgame HUD runs on native Linux Moonlight.

Install/update: download `Vastgame.zip`, extract it, then run `Vastgame.cmd` or `Update-Vastgame.cmd`. Existing installations can run `vastgame update`. Existing accounts, profiles, and stream settings are preserved.

No account keys, games, or saves are in the public ZIP. VM game FPS requires a new VM with the updated bootstrap. Existing VMs are not modified by the update. Syntax and package checks were performed; tests and fresh-VM gameplay were not run.

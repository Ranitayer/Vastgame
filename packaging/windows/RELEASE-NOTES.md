# Vastgame 1.1.12 — Complete title-bar dragging

- The empty title-bar space between the navigation tabs and native window buttons is draggable. Only the actual minimize/maximize/close buttons are excluded.
- Tab dragging no longer leaves stale click suppression after native pointer cancellation/release. A normal first click after moving works; keyboard activation and mouse focus remain available.
- Grab and move the title bar over its tabs, account balance, Save/Reset buttons or empty navigation space. A small movement threshold preserves normal clicks and keyboard navigation; releasing a drag does not activate the tab/button. Native minimize/maximize/close controls retain their own behavior.
- All shared popups appear and disappear instantly, including notices, dropdowns, Settings errors and Sensitive settings confirmations/results. Ordinary notices still close after two seconds. Menus and destructive confirmations keep their existing dismissal and confirmation rules.
- Failed rentals remain Failed in cards, details and the Failed filter after confirmed shutdown. A durable failure marker survives successful reconnects and stops; actual destruction time, costs and exact-rig actions still use the closed rental identity. Successful sessions and canceled startup workers do not gain a failure marker merely from shutdown.
- Includes all 1.1.10 Sessions, Settings, lifecycle safety and documentation updates, with the matching native x64 Windows app and WSL backend.

Existing installs: run `vastgame update`, then reopen the app. Alternatively extract `Vastgame.zip` and run `Update-Vastgame.cmd`. Updates preserve private account settings, games and saves.

Linux and Windows compilation are build checks, not live native drag/streaming acceptance. Automated tests/type checks/lint remain unrun under the current user preference; focused drag regressions were added. Publishing does not launch, restart or destroy a VM.

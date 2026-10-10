# Project review — 2026-10-10

What this repo does: Vastgame rents an exact Vast GPU VM, prepares a packaged
Windows game under Proton/Wolf, streams through Moonlight and persists verified
saves. Its native desktop and CLI share that engine, session history, quotes,
preferences and provider billing helpers.

The expected load is one active rental per local installation, tens/hundreds of
games and an accumulating session history. Different PCs may share an account;
that case needs separate account-level coordination. This is a source review,
not live GPU/Windows acceptance or proof that every provider host works.

## Changes made during this review

- Settings now fills the left column down to the unified bottom page margin.
  Streaming uses the remaining height; Sensitive settings stays below it with
  more comfortable action padding in taller windows. Compact windows retain both
  columns, margins and height-aware controls without page scrolling.
- A quote arriving after Force shutdown all cannot submit a late rental or
  overwrite shutdown state. Success and failure regression cases were added in
  `desktop/tests/launch-cancel.mjs` without a new dependency.
- Protected shutdown now passes the original launch label to final destruction,
  preventing a renamed provider contract from being destroyed after backup.
- The old `force` spelling is normalized once, before lifecycle capture.
  Non-lifecycle aliases no longer create false failed sessions.
- Save/shader restores now share `replace_state_file`, using unique private
  temporary files, descriptor-based ownership and atomic replacement. A
  pre-existing predictable temporary symlink cannot redirect a privileged write.
  Failure cleanup and an end-to-end symlink regression were added.
- Removed the unused `cache_identity` wrapper, the duplicate derived connection
  alias and an unreachable repeated error-state branch. All Svelte components
  have callers. Dynamic flags, runtime tools, public CLI aliases and historical
  compatibility paths were retained after checking their deployment/call sites.
- Consolidated desktop README content into a concise entry point and a detailed
  `desktop/ARCHITECTURE.md`. Root README/system architecture/contributor rules
  now reflect Sessions, Settings, credit, current IPC and deployment boundaries.

No dependencies were added. No account/config history, cache, save data, VM or
image was deleted during cleanup. Existing release protection and archive
completeness handling were retained.

## Must fix when an account is shared

1. **Two computers can rent at the same time**
   ([command dispatch](../../src/manager/commands.sh), start admission and local lifecycle lock).
   - **What this is:** Each installation checks whether its Vast account already
     contains a Vastgame VM before submitting creation.
   - **Problem:** Two PCs can both observe an empty account and then each rent.
     A local file lock cannot coordinate another computer.
   - **Fix:** Use one shared, atomic account lease, with a unique creation token
     and explicit recovery for an unknown create result. Preserve the local lock.
   - **If skipped:** Shared-account concurrent Play clicks can create two billable
     VMs. Separate accounts or a single launching client avoid this specific race.

## Should fix

2. **A multi-file restore can stop halfway through**
   ([restore](../../src/runtime/game_state.py), `restore`).
   - **What this is:** All snapshot objects and destinations are checked before
     individual live files are atomically replaced.
   - **Problem:** Disk failure on a later replacement leaves earlier files new and
     later files old. There is no whole-restore rollback/recovery journal.
   - **Fix:** Preserve old files in a private recovery directory and commit a
     durable restore journal; recover before allowing the next game launch.
   - **If skipped:** The verified remote snapshot remains recoverable, but local
     saves/configs can be mixed until a successful retry. The unique-temp fix
     removes one write-redirection bug; it does not make all files one transaction.

3. **Preference save is not atomic across both files**
   ([preferences](../../src/client/desktop_settings.py), `preferences`).
   - **What this is:** Stream and host settings validate under one lock and each
     file is atomically replaced; reported errors roll back originals.
   - **Problem:** Process termination or power loss between replacements bypasses
     that rollback. One group can be new while the other remains old.
   - **Fix:** Journal the old/new pair before replacement and complete/revert an
     unfinished transaction on the next settings read.
   - **If skipped:** Crash-time preference inconsistency remains possible; ordinary
     validation/write failures are already handled.

4. **The same source does not reproduce the same guest runtime**
   ([bootstrap](../../src/bootstrap/start.sh), Wolf `stable` and Lutris `edge`;
   [preparation](../../src/runtime/prepare_game.py), runtime updates).
   - **What this is:** Guest startup obtains container images and runner components
     from upstream releases while preparing the game.
   - **Problem:** Mutable tags/components can change without a Vastgame commit.
     A previously working launch can receive different runtime bytes later.
   - **Fix:** Pin tested image digests/component versions and record resolved
     versions in a runtime receipt, advancing them after acceptance.
   - **If skipped:** New guest compatibility failures can be difficult to reproduce.
     Existing deployed VMs keep their already-installed runtime.

5. **Large archived-log copies repeatedly decompress old data**
   ([archive reads](../../src/client/session_history.py), `archive_rows`;
   [copy pagination](../../desktop/src/sessions/archive.ts), `allEntries`).
   - **What this is:** Each page starts a new process and seeks into a compressed
     gzip stream using its uncompressed byte cursor.
   - **Problem:** gzip seeking rereads the prefix. Repeated pages of a large
     archive repeat that work and hold the same writer lock while reading.
   - **Fix:** Use bounded compressed segments with a small cursor/index, or one
     bounded streaming export for Copy. Keep validation and completeness flags.
   - **If skipped:** Long session exports get progressively slower and can delay
     a writer even though each response itself is bounded.

6. **Interrupted archive writes need explicit recovery diagnostics**
   ([history reader](../../src/client/session_history.py), `archive_rows`/`main`).
   - **What this is:** Logs append separate gzip members, serialized with readers.
   - **Problem:** A killed writer can leave a truncated final member. `EOFError`
     from the primary log read is not handled by the CLI's final error branch.
   - **Fix:** Identify valid completed members and expose a typed incomplete-archive
     result. Offer recovery/export without claiming lost bytes were recorded.
   - **If skipped:** An interrupted archive can produce a traceback/generic native
     failure instead of useful saved-prefix diagnostics. Normal locked reads are
     protected against a writer currently appending.

7. **Durable history has no disk budget**
   ([ledger](../../src/client/session_history.py), `LogWriter`/listing;
   [cleanup](../../src/client/cleanup.py), candidates).
   - **What this is:** Complete compressed session logs deliberately outlive job
     rotation and normal cleanup.
   - **Problem:** History grows indefinitely; listings scan local records, and a
     noisy game can eventually consume substantial disk space.
   - **Fix:** Show usage and add explicit opt-in age/size retention or export.
     Never evict active/unresolved identity or silently erase requested logs.
   - **If skipped:** Users must manage old history manually; disk exhaustion can
     prevent new logging and other local writes.

8. **Old-session billing can exceed the account-wide query budget**
   ([billing refresh](../../src/client/session_history.py), `refresh`/`refresh_page`;
   [charges](../../src/providers/vast/charges.py), `fetch_charges`).
   - **What this is:** One bounded query spans the earliest displayed rental to
     today, then attributes its account-wide rows to exact instances.
   - **Problem:** Old sessions on a busy account can require more than 20 pages or
     8MiB even when the desired instance has few rows.
   - **Fix:** Filter exact instances if the provider contract permits it, or split
     bounded time windows and retain a reconciliation cursor for later adjustments.
   - **If skipped:** Old totals remain pending/stale after the explicit limit error;
     the implementation correctly avoids inventing zero charges.

9. **Non-JSON backend failures lose their safe cause at native IPC**
   ([native runner](../../desktop/src-tauri/src/backend.rs), `read`).
   - **What this is:** Structured quote/settings errors retain typed messages.
     Other failed read processes are represented by an exit-code error.
   - **Problem:** Captured stderr is discarded. For those commands, safe known
     configuration/API/permission diagnostics never reach the UI.
   - **Fix:** Return a shared, allowlisted JSON error envelope from every fixed
     read helper. Do not expose arbitrary raw stderr or account responses.
   - **If skipped:** Some browse/history/account failures remain harder to diagnose
     than the already-specific quote and lifecycle errors.

10. **The release workflow builds without running regressions**
    ([workflow](../../.github/workflows/windows-release.yml), build/package jobs).
    - **What this is:** Tagged releases compile the native app and bind it to the
      packaged backend source.
    - **Problem:** Compile success cannot prove lifecycle races, save behavior,
      updater recovery or settings persistence. Added tests are currently unrun
      under the user's existing preference.
    - **Fix:** When test execution is authorized, run the focused offline safety
      suite and a mocked UI smoke suite before release packaging.
    - **If skipped:** This remains an untested behavioral release even when both
      native build and publication succeed. No live destruction is needed for
      the offline regression cases.

## Nice to have

11. **Windows streaming features differ from Linux**
    ([native integration](../../src/manager/client.sh),
    [Windows bridge](../../packaging/windows/windows-bridge.sh)).
    - **What this is:** Windows uses stock native Moonlight; Linux can load the
      custom Ctrl+Shift+Q menu, HUD and Crashpad hooks.
    - **Problem:** Those custom overlays do not run in stock Windows Moonlight.
    - **Fix:** Add a maintained Windows integration or clearly keep the included
      settings editor as the supported route. Do not promise an unavailable hotkey.
    - **If skipped:** Windows still applies saved stream settings on reconnect,
      but lacks these in-stream convenience features.

12. **Release hashes do not independently authenticate the publisher**
    ([updater](../../packaging/windows/Check-Updates.ps1),
    [packager](../../packaging/windows/build_update.py)).
    - **What this is:** HTTPS, ZIP/member hashes and matching source descriptors
      protect download/package integrity relative to the GitHub release.
    - **Problem:** The app/update payload is not independently signed; a compromise
      able to replace the release can replace its checksum too.
    - **Fix:** Sign release metadata with a pinned verification key and sign the
      Windows executable when an appropriate signing identity is available.
    - **If skipped:** Trust continues to depend on the release repository and its
      access controls. Microsoft's separately verified WebView2 installer is not
      the missing Vastgame payload signature.

## Twenty improvements, ranked

These are recommendations, not features activated during this cleanup. The
intentionally inactive spending limit remains inactive.

| Rank | Improvement | Practical result |
| --- | --- | --- |
| 1 | Shared-account creation lease | Prevent two PCs renting concurrently |
| 2 | Recoverable multi-file save restore | Never resume from a half-applied snapshot |
| 3 | Crash recovery journal for settings | Keep both preference groups consistent |
| 4 | Pin guest images/runner versions and receipts | Reproduce a successful runtime |
| 5 | Focused offline safety checks in release CI, when authorized | Catch identity/save/cancellation regressions before shipping |
| 6 | Clean-PC Windows install/update acceptance | Catch WSL, WebView2, path and permission failures |
| 7 | Signed release metadata and Windows executable | Authenticate the update publisher |
| 8 | Segmented/indexed log archives | Faster pages and full-log exports |
| 9 | Interrupted-archive recovery with completeness reporting | Preserve readable history after a killed writer |
| 10 | Explicit session disk budget/retention/export | Keep history from exhausting disk |
| 11 | One typed error envelope across fixed commands | Useful exact failure explanations everywhere |
| 12 | Bounded retry/backoff for safe read-only requests | Recover transient API outages without retrying rental creation blindly |
| 13 | Desktop/backend protocol-version handshake | Diagnose a manually mismatched or partial installation immediately |
| 14 | Separate process, stream-ready and frame-observed state | Explain black screens without restoring the removed network gate |
| 15 | Session backup receipt/checkpoint visibility | Show what can be recovered and when it was verified |
| 16 | Batch local startup data into one fixed backend read | Reduce Windows WSL process launches without duplicating provider work |
| 17 | Cancel queued artwork after it leaves view | Avoid unnecessary Steam work after rapid scrolling/tab changes |
| 18 | Bounded disk metadata/identity refresh policy | Keep presentation cache behavior consistent across long-lived installs |
| 19 | Windows streaming menu/HUD parity | Change quality during play using a supported native integration |
| 20 | Implement Billing using existing charge helpers | Explain daily spend, bandwidth, adjustments and pending charges |

## Verification and coverage

The source review traced the desktop shell, shared controls and data queues,
native IPC, exact offers, creation/restore/reconnect/cancellation/shutdown,
session writes/archive reads/billing, preferences/sensitive actions, package/save
verification, bootstrap readiness and Windows installer/update/release paths.
Tests were read for these boundaries; regression cases were written for changes.
Native Linux HUD/menu/Crashpad entry points and platform differences were reviewed;
their rendering/driver behavior was not exercised.

The embedded Linux app build passed. A browser preview of that built UI used
mocked backend responses, with lifecycle/sensitive actions disabled. At 600×600,
1080×720 and 1600×1000, Sensitive settings ended at the same bottom inset as the
Settings page (13, 13 and 25 pixels respectively); page content fit its height.
This verifies presentation at those sizes, not real native/backend behavior. Tagged Windows
publication requires its separate matching x64 build and package. Build-only
validation is not behavioral acceptance. Automated tests, type checks and lint
remain unrun under the user's preference. No paid provider launch, shutdown,
live SSH probe, history deletion/reset or save mutation was performed. No real
Windows streaming/install/update session or fresh-template GPU acceptance was
performed. Generated binaries, third-party libraries, flag SVG artwork and the
Ludusavi data catalog were not audited line by line.

Verdict: shared engine boundaries and identity/save protection are sound enough
to build on, with the concrete fixes above applied. Shared-account concurrency,
crash transactions, runtime reproducibility and unrun behavioral validation are
the most important remaining work. This is not a claim that the app is bug-free.

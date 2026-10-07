# CPA quota widget

The Python collector reads account metadata from CPA Manager Plus and requests provider quota endpoints through its existing authenticated `api-call` proxy. CPA injects the OAuth token on the server. No provider token or management key is sent to the Hub or the desktop. The standalone Node Hub uses the existing Token Monitor wire protocol; no Hub API changes or provider registration changes are required.

The collector currently supports Codex, Claude and Antigravity. It discovers accounts on every minute tick, probes each enabled account at most every five minutes, retains its last quota snapshot on errors, and backs off for at least 15 minutes on upstream 429 responses. Manager quota snapshots seed the initial display but do not establish account availability until the upstream probe succeeds. Cache files contain quota snapshots and opaque account keys, not credentials. A failed account-list read stops publishing so the device becomes stale instead of appearing empty or healthy.

Quota reads do not consume reset credits, send inference requests, change account enablement, or select a different active local login. They can trigger CPA's normal OAuth refresh and quota reconciliation. Refresh ownership stays with CPA.

## Pool interpretation

The Limits view and tray tooltip summarize devices whose IDs begin with `cpa-`. Each provider retains its individual account rows. Unknown, failed, unauthenticated and stale readings never count as available; disabled accounts are shown separately. Codex and Claude require their primary quotas to remain below 100%; named additional model quotas do not exhaust the whole account. For Antigravity all windows within a model group must remain available, but independent model groups can still serve traffic. Counts represent observed quota availability, not a promise that every model/request will succeed. Pool percentages are intentionally not averaged across different subscriptions.

## Server

Deploy the source to `/opt/token-monitor`, install Node production dependencies with `npm ci --omit=dev --no-audit --no-fund`, and install the two units from `systemd/`. Create a private `.env` with:

```dotenv
TOKEN_MONITOR_HOST=127.0.0.1
TOKEN_MONITOR_PORT=17321
TOKEN_MONITOR_HUB_URL=http://127.0.0.1:17321
TOKEN_MONITOR_SECRET=<dedicated random Hub secret>
CPA_MANAGER_URL=http://127.0.0.1:18317
CPA_DEVICE_ID=cpa-maxim
```

The collector unit reads the existing `/opt/cpa-manager-plus/.env` on the server for `CPA_MANAGER_ADMIN_KEY`. If that deployment uses a file-based admin key, configure the unit accordingly; do not copy the management credential to Windows. Both services start at boot and restart after failures. Check `systemctl status token-monitor-hub token-monitor-cpa` and `journalctl -u token-monitor-cpa -n 20`.

## Windows

Build the app with `npm run dist:win:dir`. Run `node integrations/cpa/setup-windows.js` to configure the existing credential store and Hub Client mode, then `powershell -NoProfile -ExecutionPolicy Bypass -File integrations/cpa/install-windows-startup.ps1` to create the Desktop and Startup shortcuts. `hubRemoteOnly: true` selects hybrid mode: this PC keeps Token Monitor's native local collection (sessions, projects, tokens, history) and uploads it to the Hub, while its own quota polling is switched off because limits come from the CPA device. The mode also hides the zero token totals in the remote-only Limits view and skips upstream update checks that could replace this custom build. CPA tokens are not added to the local totals, which avoids counting the same requests twice. Setup preserves existing UI preferences and only restores collection options that an earlier remote-only setup had disabled. The supervisor maintains a private SSH forward through the existing `maxim` host alias, reconnecting after network interruptions. The built-in app-only startup setting remains off to avoid duplicate launches. Logs are under `data/`; no SSH password or provider login is requested.

The installed desktop shortcut and Startup launcher both invoke the same supervisor; its named mutex prevents duplicate supervisors and tunnels. Closing the widget leaves the tunnel alive. Launch the app executable to reopen it. To disable autostart, remove the `Token Monitor CPA` shortcut from the Windows Startup folder; stop the matching supervisor and its child SSH process if stopping the current session is also required.

## Verification

```powershell
npm run verify
python -m unittest discover -s integrations/cpa -p 'test_*.py'
npm run dist:win:dir
```

The server API remains on loopback. Runtime configuration, credentials, cache, logs and packaged binaries are excluded from Git. UI changes follow the existing widget tokens and typography; the Modern Web Guidance `accessible-error-announcement` guide was checked, but this read-only status surface adds no validation form or focus-stealing announcements.

The deployed Windows setup was verified against all discovered CPA accounts, with a connected Hub stream, per-account meters, the pool summary, and no horizontal overflow in the compact widget. The owned SSH tunnel recovered 10 seconds after deliberate termination; both server services survived a restart and remain enabled at boot. Unauthenticated Hub stats requests return 401, and its listener is bound to `127.0.0.1`.

On this Windows host, the full upstream suite is not clean: macOS symlink fixtures fail with `EPERM` (reproduced in an unmodified upstream worktree), and several local-collector timing tests failed under the default parallel run; a stalled upstream worker was stopped. The focused quota, Hub, synchronization, layout, tray and updater checks pass, as do the Python collector checks, ESLint and the Windows build. Verification logs and UI captures are retained in the Git-ignored `tmp/` directory.

## Quota source

The collector reads the account inventory from CPAMP and probes provider quotas through CPA's pi-call, which injects tokens on the server. CPAMP's stored quota snapshots are used only as an initial fallback: they refresh in the background for Codex alone, and a live check showed most Claude and Antigravity accounts had no snapshot or one that was hours old with the panel closed.

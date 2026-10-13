# Qwinty/token-monitor fork

A fork of [Javis603/token-monitor](https://github.com/Javis603/token-monitor), rebased on upstream `v0.69.0` plus later `main` commits. It adds four things on top; everything else is upstream.

The changes are additive and opt-in. With default settings the app behaves like upstream.

| Change | What it does |
|---|---|
| CPA quota pool widget | Shows the state of a pool of [CPA](integrations/cpa/README.md) accounts (Codex, Claude, Antigravity) in the Limits view and the tray tooltip |
| Hybrid Hub Client mode (`hubRemoteOnly`) | Keeps local usage collection, but takes quotas from the Hub instead of polling providers from this PC |
| On-demand usage collection (`collectionMode: 'manual'`) | No background tokscale scans; a scan runs only when something on screen needs the numbers |
| Edge dock throttling | Opening a dock card no longer drives periodic scans |

## CPA quota pool widget

`integrations/cpa/collector.py` runs on the server next to CPA Manager Plus. It lists accounts from the manager and reads each provider's quota endpoint through CPA's authenticated `api-call` proxy, so the OAuth token is injected on the server and never reaches the Hub or the desktop. It then posts the result to a standalone Token Monitor Hub as a normal device (`cpa-*`) over the existing wire protocol. No Hub API or provider registration changes.

- Accounts are discovered every minute and each enabled account is probed at most every five minutes. The last snapshot is kept on errors, and an upstream 429 backs the account off for at least 15 minutes.
- If the account list cannot be read, the collector stops publishing, so the device goes stale instead of looking empty or healthy.
- Quota reads do not send inference requests, spend reset credits, or change which account is active.

In the app, `src/electron/renderer/limits/cpaPoolSummary.js` summarizes every device whose id starts with `cpa-`: how many accounts are available per provider, how many are disabled, and the same line in the tray tooltip. Unknown, failed, unauthenticated and stale readings never count as available. Percentages are not averaged across different subscriptions. Details and the exact availability rules are in [integrations/cpa/README.md](integrations/cpa/README.md).

Server and Windows deployment files live in `integrations/cpa/`: two systemd units (Hub and collector), a deploy script, a Windows setup script, and a supervisor that keeps an SSH port-forward to the Hub alive. They contain deployment defaults of the author's setup (`maxim` SSH alias, `cpa-maxim` device id, `/opt/...` paths); change them for your environment.

## Hybrid Hub Client mode

Setting `hubMode: 'client'` together with `hubRemoteOnly: true`:

- local collection (sessions, projects, tokens, history) keeps running and uploads to the Hub;
- this PC's own limits polling is off (`limitsEnabled = false`), because quotas come from the CPA device on the Hub;
- the zero token totals in the remote-only Limits view are hidden;
- upstream update checks are skipped, so a custom build is not replaced by an upstream release.

CPA tokens are not added to local totals, so the same requests are not counted twice. `node integrations/cpa/setup-windows.js` writes these settings.

## On-demand usage collection

Upstream collects in the background in every mode (`live`, `smart`, `interval`). This fork adds a fourth Collection mode, `manual` ("On demand (when a usage view opens)"), which passes `backgroundCollection: false` to the collector: no watcher, no startup scan, no interval loop, so an idle widget never starts tokscale (a scan costs about 30 s of CPU). A scan runs only when:

- the main window shows a view other than Limits/Status, becomes visible on such a view, or changes view or period;
- the dashboard opens;
- an edge-dock card stays open for 1.5 s;
- the refresh button is pressed (always a forced full scan).

A scan younger than 60 s is reused (5 min for dock cards, because the dock opens whenever the pointer brushes the screen edge). A request made while a scan is running joins it instead of queueing a second one, and failed scans count toward the reuse window. Limits refresh and the Hub stream keep their own cadence. See "On-demand collection" in [docs/architecture.md](docs/architecture.md).

To enable it, pick "On demand" as the Collection mode in settings; the CPA Windows setup does this by default.

## Build

The fork does not publish releases, so build from source (Node 22.15+):

```bash
npm ci
npm run dist:win:dir        # or the dist script for your platform
```

For the full server and client setup, follow [integrations/cpa/README.md](integrations/cpa/README.md).

## Verification

`npm run lint` is clean and the touched test files pass (`tests/electron/cpaPoolSummary.test.js`, `tests/electron/edgeDockController.test.js`, `tests/shared/usageRuntime.test.js`, plus `python -m unittest discover -s integrations/cpa -p 'test_*.py'`). On Windows the full `npm test` can stall on timing-sensitive tests and fails on macOS symlink fixtures; run the touched files on their own, since they pass alone but can fail under heavy parallel load.

## Staying in sync

`main` here is upstream `main` with these commits on top. To update:

```bash
git remote add upstream https://github.com/Javis603/token-monitor.git
git fetch upstream
git rebase upstream/main
```

Conflicts have so far been limited to `src/electron/main.js` and `src/electron/edgeDock/controller.js`, where both sides add options next to each other.

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { CredentialStore, writePrivateJsonAtomic } = require('../../src/shared/credentialStore');
const { loadDotEnv } = require('../../src/shared/config');

loadDotEnv();
if (!process.env.TOKEN_MONITOR_SECRET) throw new Error('Create the dedicated Hub secret in the private .env before setup.');
const profile = path.join(process.env.APPDATA, 'Token Monitor');
fs.mkdirSync(profile, { recursive: true });
const settingsPath = path.join(profile, 'settings.json');
const saved = fs.existsSync(settingsPath) ? JSON.parse(fs.readFileSync(settingsPath, 'utf8')) : {};
const store = new CredentialStore(profile);
if (fs.existsSync(settingsPath)) fs.copyFileSync(settingsPath, `${settingsPath}.pre-cpa-${Date.now()}.bak`);
if (fs.existsSync(store.filePath)) fs.copyFileSync(store.filePath, `${store.filePath}.pre-cpa-${Date.now()}.bak`);
store.replaceSettingsCredentials({ ...store.settingsCredentials(), secret: process.env.TOKEN_MONITOR_SECRET });
// Required for the hybrid mode: local usage/sessions/projects from this PC, quotas from CPA via the Hub.
const required = {
  hubMode: 'client', hubUrl: 'http://127.0.0.1:17321', deviceId: 'windows-cpa-widget',
  limitsEnabled: true, limitProviders: 'codex,claude,antigravity', limitProviderOrder: 'codex,claude,antigravity',
  automaticAppUpdates: false, hubRemoteOnly: true
};
// Cosmetic defaults apply only when the user has not chosen a value yet.
const defaults = {
  language: 'en', lastViewState: { period: 'today', breakdown: 'limits' }, startAtLogin: false,
  windowBehavior: 'floating', showTrayIcon: true, trayContent: 'limitsAllSessions',
  showLimitSource: true, maskLimitAccountEmails: false,
  // Quotas stream from the Hub; local tokscale scans run only when a usage view opens.
  collectionMode: 'manual'
};
const next = { ...saved, ...required };
for (const [key, value] of Object.entries(defaults)) if (next[key] === undefined) next[key] = value;
// An earlier remote-only setup switched local collection off; restore the stock behavior.
for (const key of ['projectsEnabled', 'historyEnabled', 'sessionUsageArchiveEnabled', 'wslScanEnabled']) {
  if (next[key] === false) delete next[key];
}
writePrivateJsonAtomic(settingsPath, next);
console.log(`CPA widget settings configured at ${profile}`);

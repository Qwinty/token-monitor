'use strict';

(function expose(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TokenMonitorCpaPoolSummary = api;
})(typeof window !== 'undefined' ? window : null, function createApi() {
  function accountState(account, stale, now) {
    if (account.status === 'disabled') return 'disabled';
    if (stale || account.stale || !Date.parse(account.updatedAt) || now - Date.parse(account.updatedAt) > 600000) return 'unknown';
    if (account.status === 'unauthorized') return 'auth';
    if (account.status === 'rateLimited') return 'limited';
    if (account.status !== 'ok') return 'unknown';
    const windows = (account.windows || []).filter((item) => !item.additional && Number.isFinite(item.usedPercent));
    if (!windows.length) return 'unknown';
    // Independent Antigravity model groups can still serve traffic when one is exhausted.
    if (account.provider === 'antigravity') {
      const groups = new Map();
      for (const item of windows) {
        const label = item.label || 'Models';
        groups.set(label, Boolean(groups.get(label)) || item.usedPercent >= 100);
      }
      return [...groups.values()].some((exhausted) => !exhausted) ? 'available' : 'limited';
    }
    const required = windows.filter((item) => !item.label || item.label === 'codex' || item.label === 'all' || item.label === 'CPA cooldown');
    if (!required.length) return 'unknown';
    return required.some((item) => item.usedPercent >= 100) ? 'limited' : 'available';
  }

  function summarize(stats, now = Date.now()) {
    const devices = (stats?.devices || []).filter((device) => String(device.deviceId).startsWith('cpa-'));
    if (!devices.length) return null;
    const accounts = new Map();
    for (const device of devices) {
      for (const account of device.limits?.providers || []) {
        const key = `${account.provider}:${account.accountKey}`;
        const previous = accounts.get(key);
        if (!previous || Date.parse(account.updatedAt) > Date.parse(previous.account.updatedAt)) accounts.set(key, { account, stale: device.stale });
      }
    }
    const groups = new Map();
    for (const { account, stale } of accounts.values()) {
      if (!groups.has(account.provider)) groups.set(account.provider, { provider: account.provider, total: 0, available: 0, limited: 0, auth: 0, disabled: 0, unknown: 0, nextReset: null });
      const group = groups.get(account.provider);
      const state = accountState(account, stale, now);
      group.total += 1;
      group[state] += 1;
      if (state === 'limited') {
        const required = (account.windows || []).filter((item) => item.usedPercent >= 100 && !item.additional && (account.provider === 'antigravity' || !item.label || item.label === 'codex' || item.label === 'all' || item.label === 'CPA cooldown'));
        const scopes = new Map();
        for (const item of required) {
          const scope = account.provider === 'antigravity' ? item.label || 'Models' : 'Main';
          if (!scopes.has(scope)) scopes.set(scope, []);
          scopes.get(scope).push(Date.parse(item.resetsAt));
        }
        // Every blocking window of a model group must recover. Another independent group can recover first.
        const recoveries = [...scopes.values()].filter((resets) => resets.every((value) => value > now)).map((resets) => Math.max(...resets));
        if (recoveries.length) {
          const reset = Math.min(...recoveries);
          group.nextReset = group.nextReset === null ? reset : Math.min(group.nextReset, reset);
        }
      }
    }
    const pools = [...groups.values()].sort((left, right) => ['codex', 'claude', 'antigravity'].indexOf(left.provider) - ['codex', 'claude', 'antigravity'].indexOf(right.provider));
    const total = pools.reduce((sum, pool) => sum + pool.total, 0);
    const available = pools.reduce((sum, pool) => sum + pool.available, 0);
    const activePools = pools.filter((pool) => pool.total > pool.disabled);
    const status = !activePools.length || activePools.every((pool) => pool.unknown === pool.total - pool.disabled) ? 'unknown'
      : activePools.every((pool) => pool.available === pool.total - pool.disabled) ? 'healthy'
        : activePools.some((pool) => pool.available > 0) ? 'degraded' : 'unavailable';
    return { pools, total, available, status };
  }

  function tooltip(stats) {
    const summary = summarize(stats);
    if (!summary) return '';
    return [`CPA ${summary.available}/${summary.total} available`, ...summary.pools.map((pool) => `${pool.provider}: ${pool.available}/${pool.total}`)].join('\n');
  }

  function render(stats, { document, formatDuration, now = Date.now() }) {
    const summary = summarize(stats, now);
    if (!summary) return null;
    const section = document.createElement('section');
    section.className = `cpa-pool-summary cpa-pool-${summary.status}`;
    section.setAttribute('aria-label', 'CPA account pool');
    const title = document.createElement('div');
    title.className = 'cpa-pool-heading';
    title.textContent = `CPA · maxim — ${summary.available}/${summary.total} available`;
    section.append(title);
    for (const pool of summary.pools) {
      const row = document.createElement('div');
      row.className = 'cpa-pool-row';
      const label = document.createElement('span');
      label.textContent = { codex: 'Codex', claude: 'Claude', antigravity: 'Antigravity' }[pool.provider] || pool.provider;
      const value = document.createElement('span');
      value.className = 'cpa-pool-count';
      value.textContent = `${pool.available}/${pool.total}`;
      row.append(label, value);
      const details = [];
      if (pool.limited) details.push(`${pool.limited} limited`);
      if (pool.auth) details.push(`${pool.auth} sign-in needed`);
      if (pool.unknown) details.push(`${pool.unknown} unknown / stale`);
      if (pool.disabled) details.push(`${pool.disabled} disabled`);
      if (pool.nextReset) details.push(`Recovery in ${formatDuration(pool.nextReset - now)}`);
      if (details.length) {
        const detail = document.createElement('div');
        detail.className = 'cpa-pool-detail';
        detail.textContent = details.join(' · ');
        row.append(detail);
      }
      section.append(row);
    }
    return section;
  }

  return { accountState, summarize, tooltip, render };
});

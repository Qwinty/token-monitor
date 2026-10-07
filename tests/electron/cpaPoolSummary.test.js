'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { summarize } = require('../../src/electron/renderer/limits/cpaPoolSummary');
const now = Date.parse('2026-10-03T20:00:00Z');
const make = (provider, accountKey, windows, status = 'ok', updatedAt = new Date(now).toISOString()) => ({ provider, accountKey, status, updatedAt, windows });
const quota = (usedPercent, label = '', resetsAt = null) => ({ usedPercent, label, resetsAt });
const stats = (providers, stale = false) => ({ devices: [{ deviceId: 'cpa-maxim', stale, limits: { providers } }] });

test('a failed Claude pool degrades the global pool even with healthy Codex accounts', () => {
  const result = summarize(stats([make('codex', '1', [quota(20), quota(40)]), make('claude', '2', [quota(100)])]), now);
  assert.equal(result.status, 'degraded');
  assert.equal(result.available, 1);
  assert.equal(result.pools[1].limited, 1);
});

test('additional Codex and Claude model limits do not exhaust the main account pool', () => {
  const result = summarize(stats([make('codex', '1', [quota(20), { ...quota(100), additional: true }]), make('claude', '2', [quota(20), quota(100, 'Opus')])]), now);
  assert.equal(result.available, 2);
  assert.equal(result.status, 'healthy');
});

test('unknown quotas, stale devices and expired observations never count as available', () => {
  assert.equal(summarize(stats([make('codex', '1', [])]), now).available, 0);
  assert.equal(summarize(stats([make('codex', '1', [quota(0)])], true), now).status, 'unknown');
  assert.equal(summarize(stats([make('codex', '1', [quota(0)], 'ok', new Date(now - 660000).toISOString())]), now).status, 'unknown');
});

test('Antigravity keeps independent model groups available', () => {
  const result = summarize(stats([make('antigravity', '1', [quota(100, 'Claude'), quota(20, 'Gemini Pro')])]), now);
  assert.equal(result.available, 1);
});

test('one available weekly window cannot override an exhausted short window of the same model group', () => {
  const result = summarize(stats([make('antigravity', '1', [quota(100, 'Claude'), quota(20, 'Claude')])]), now);
  assert.equal(result.available, 0);
});

test('recovery waits for every exhausted required window of a Codex account', () => {
  const result = summarize(stats([make('codex', '1', [quota(100, '', new Date(now + 60000).toISOString()), quota(100, '', new Date(now + 3600000).toISOString())])]), now);
  assert.equal(result.pools[0].nextReset, now + 3600000);
});

test('Antigravity recovery waits for both windows of a model group', () => {
  const result = summarize(stats([make('antigravity', '1', [quota(100, 'Claude', new Date(now + 60000).toISOString()), quota(100, 'Claude', new Date(now + 3600000).toISOString())])]), now);
  assert.equal(result.pools[0].nextReset, now + 3600000);
});

test('an exhausted window with an unknown reset cannot promise recovery', () => {
  const result = summarize(stats([make('codex', '1', [quota(100, '', new Date(now + 60000).toISOString()), quota(100)])]), now);
  assert.equal(result.pools[0].nextReset, null);
});

test('duplicate CPA device records do not double count an account', () => {
  const input = stats([make('codex', '1', [quota(20)])]);
  input.devices.push({ ...input.devices[0], deviceId: 'cpa-other' });
  assert.equal(summarize(input, now).total, 1);
  assert.equal(summarize({ devices: [{ deviceId: 'local', limits: input.devices[0].limits }] }, now), null);
});

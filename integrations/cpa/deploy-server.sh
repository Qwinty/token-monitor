#!/usr/bin/env bash
set -euo pipefail
target=/opt/token-monitor
if [[ "$target" != /opt/token-monitor ]]; then exit 1; fi
install -d -m 700 "$target" "$target/data"
tar -xzf /tmp/token-monitor-cpa-deploy.tar.gz -C "$target"
if [[ -f "$target/.env" ]]; then cp -p "$target/.env" "$target/.env.pre-deploy-$(date +%Y%m%d-%H%M%S).bak"; fi
install -m 600 /tmp/token-monitor-cpa.env "$target/.env"
cd "$target"
npm ci --omit=dev --ignore-scripts --no-audit --no-fund
install -m 644 integrations/cpa/systemd/token-monitor-hub.service /etc/systemd/system/token-monitor-hub.service
install -m 644 integrations/cpa/systemd/token-monitor-cpa.service /etc/systemd/system/token-monitor-cpa.service
systemctl daemon-reload
systemctl enable --now token-monitor-hub.service token-monitor-cpa.service
systemctl is-active token-monitor-hub token-monitor-cpa
rm -f /tmp/token-monitor-cpa.env

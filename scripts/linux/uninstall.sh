#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root to remove the service." >&2; exit 1; }
systemctl disable --now remote-fs-browser.service || true
rm -f /etc/systemd/system/remote-fs-browser.service
systemctl daemon-reload
# Preserve the private configuration unless explicitly requested.
rm -f /opt/remote-fs-browser/.deployment-success
if [ "${1:-}" = '--purge' ]; then rm -rf /opt/remote-fs-browser; fi

#!/usr/bin/env bash
set -euo pipefail
systemctl disable --now remote-fs-browser.service || true
rm -f /etc/systemd/system/remote-fs-browser.service
systemctl daemon-reload
# Preserve the private configuration unless explicitly requested.
if [ "${1:-}" = '--purge' ]; then rm -rf /opt/remote-fs-browser; fi

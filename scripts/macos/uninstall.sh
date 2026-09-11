#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root to remove the service." >&2; exit 1; }
launchctl bootout system/org.remote-fs-browser 2>/dev/null || true
rm -f /Library/LaunchDaemons/org.remote-fs-browser.plist
rm -f /opt/remote-fs-browser/.deployment-success
if [ "${1:-}" = '--purge' ]; then rm -rf /opt/remote-fs-browser; fi

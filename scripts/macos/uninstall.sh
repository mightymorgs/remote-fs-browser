#!/usr/bin/env bash
set -euo pipefail
launchctl bootout system/org.remote-fs-browser 2>/dev/null || true
rm -f /Library/LaunchDaemons/org.remote-fs-browser.plist
if [ "${1:-}" = '--purge' ]; then rm -rf /opt/remote-fs-browser; fi

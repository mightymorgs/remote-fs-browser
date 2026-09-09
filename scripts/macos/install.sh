#!/usr/bin/env bash
set -euo pipefail
CONFIG=${1:?Pass a private service config JSON file}
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
PREFIX=/opt/remote-fs-browser
[ "$(id -u)" = 0 ] || { echo 'Run with sudo to install launchd service.' >&2; exit 1; }
BREW_USER=${SUDO_USER:?Run through sudo from the Homebrew user account}
if [ -x /opt/homebrew/bin/brew ]; then BREW=/opt/homebrew/bin/brew; else BREW=/usr/local/bin/brew; fi
if [ ! -x "$BREW" ]; then
  INSTALLER=$(mktemp)
  curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$INSTALLER"
  chmod 755 "$INSTALLER"
  sudo -u "$BREW_USER" env NONINTERACTIVE=1 /bin/bash "$INSTALLER"
  rm "$INSTALLER"
fi
sudo -u "$BREW_USER" "$BREW" install python@3.12 libnfs
BREW_PREFIX=$(sudo -u "$BREW_USER" "$BREW" --prefix)
install -d -m 700 "$PREFIX"
"$BREW_PREFIX/opt/python@3.12/bin/python3.12" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install "$SOURCE"
install -m 600 "$CONFIG" "$PREFIX/config.json"
cat > /Library/LaunchDaemons/org.remote-fs-browser.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>org.remote-fs-browser</string>
<key>ProgramArguments</key><array><string>$PREFIX/venv/bin/remotefs</string><string>serve</string><string>--no-defaults</string><string>--config</string><string>$PREFIX/config.json</string></array>
<key>EnvironmentVariables</key><dict><key>LIBNFS_LIBRARY</key><string>$BREW_PREFIX/lib/libnfs.dylib</string></dict>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>5</integer>
</dict></plist>
EOF
chmod 644 /Library/LaunchDaemons/org.remote-fs-browser.plist
launchctl bootout system/org.remote-fs-browser 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/org.remote-fs-browser.plist

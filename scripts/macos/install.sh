#!/usr/bin/env bash
set -euo pipefail
CONFIG=${1:?Pass a private service config JSON file}; shift
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
PREFIX=/opt/remote-fs-browser
source "$SOURCE/scripts/unix-options.sh"
LIBRARY=
[ "$(id -u)" = 0 ] || { echo 'Run with sudo to install launchd service.' >&2; exit 1; }
if [ "$INSTALL_DEPENDENCIES" = 1 ]; then
  BREW_USER=${SUDO_USER:?Run through sudo from the Homebrew user account}
  if [ -x /opt/homebrew/bin/brew ]; then BREW=/opt/homebrew/bin/brew; else BREW=/usr/local/bin/brew; fi
  [ -x "$BREW" ] || { echo 'Install Homebrew as the deployment user first.' >&2; exit 1; }
  PACKAGES=(python@3.12)
  [ "$WITH_NFS" = 0 ] || PACKAGES+=(libnfs)
  sudo -u "$BREW_USER" "$BREW" install "${PACKAGES[@]}"
  BREW_PREFIX=$(sudo -u "$BREW_USER" "$BREW" --prefix)
  PYTHON="$BREW_PREFIX/opt/python@3.12/bin/python3.12"
  [ "$WITH_NFS" = 0 ] || LIBRARY="$BREW_PREFIX/lib/libnfs.dylib"
else
  PYTHON=${REMOTE_FS_PYTHON:-python3}
  if [ "$WITH_NFS" = 1 ]; then
    LIBRARY=${LIBNFS_LIBRARY:?Set LIBNFS_LIBRARY with --skip-dependencies, or use --without-nfs}
    [ -f "$LIBRARY" ] || { echo 'libnfs library does not exist.' >&2; exit 1; }
  fi
fi
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
install -d -m 700 "$PREFIX"
if [ -x "$PREFIX/venv/bin/python" ]; then
  if "$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$CONFIG" --destination "$PREFIX/config.json" "${BOOTSTRAP_ARGS[@]}" --check; then :
  else [ "$?" = 2 ] || exit 1; fi
fi
launchctl bootout system/org.remote-fs-browser 2>/dev/null || true
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade "$SOURCE"
"$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$CONFIG" --destination "$PREFIX/config.json" "${BOOTSTRAP_ARGS[@]}"
"$PREFIX/venv/bin/python" - "$LIBRARY" <<'PYTHON'
import plistlib, sys
from pathlib import Path
prefix = '/opt/remote-fs-browser'
service = {'Label':'org.remote-fs-browser', 'ProgramArguments':[prefix+'/venv/bin/remotefs','serve','--no-defaults','--config',prefix+'/config.json'], 'RunAtLoad':True, 'KeepAlive':True, 'ThrottleInterval':5, 'Umask':63, 'StandardOutPath':prefix+'/service.log', 'StandardErrorPath':prefix+'/service-error.log'}
if sys.argv[1]: service['EnvironmentVariables']={'LIBNFS_LIBRARY':sys.argv[1]}
Path('/Library/LaunchDaemons/org.remote-fs-browser.plist').write_bytes(plistlib.dumps(service))
PYTHON
chmod 644 /Library/LaunchDaemons/org.remote-fs-browser.plist
launchctl bootout system/org.remote-fs-browser 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/org.remote-fs-browser.plist

"$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$PREFIX/config.json" --health-check

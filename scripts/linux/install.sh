#!/usr/bin/env bash
set -euo pipefail
# Run from an unpacked checkout: sudo scripts/linux/install.sh /path/to/private-config.json
CONFIG=${1:?Pass a private service config JSON file}; shift
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
PREFIX=/opt/remote-fs-browser
source "$SOURCE/scripts/unix-options.sh"
PYTHON=${REMOTE_FS_PYTHON:-python3}
if [ "$(id -u)" != 0 ]; then echo 'Run as root to install the system service.' >&2; exit 1; fi
if [ "$INSTALL_DEPENDENCIES" = 1 ]; then
if command -v apt-get >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv git cmake build-essential
elif command -v dnf >/dev/null; then
  dnf install -y python3 python3-pip git cmake gcc make
else
  echo 'Install Python 3.11+, a C compiler, CMake and Git for this distribution.' >&2; exit 1
fi
fi
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
install -d -m 700 "$PREFIX"
if [ -x "$PREFIX/venv/bin/python" ]; then
  if "$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$CONFIG" --destination "$PREFIX/config.json" "${BOOTSTRAP_ARGS[@]}" --check; then :
  else [ "$?" = 2 ] || exit 1; fi
fi
systemctl stop remote-fs-browser.service 2>/dev/null || true
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade "$SOURCE"
"$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$CONFIG" --destination "$PREFIX/config.json" "${BOOTSTRAP_ARGS[@]}"
LIBRARY=
if [ "$WITH_NFS" = 1 ]; then
if [ ! -d "$PREFIX/libnfs-src/.git" ]; then git clone https://github.com/sahlberg/libnfs.git "$PREFIX/libnfs-src"; fi
git -C "$PREFIX/libnfs-src" fetch origin c69a48c8116fd50287875decd50474685937a4af
git -C "$PREFIX/libnfs-src" checkout --detach c69a48c8116fd50287875decd50474685937a4af
cmake -S "$PREFIX/libnfs-src" -B "$PREFIX/libnfs-build" -DCMAKE_INSTALL_PREFIX="$PREFIX/native" -DBUILD_SHARED_LIBS=ON -DENABLE_UTILS=OFF -DENABLE_TLS=OFF
cmake --build "$PREFIX/libnfs-build" --parallel 2
cmake --install "$PREFIX/libnfs-build"
LIBRARY=$(find "$PREFIX/native" -name 'libnfs.so' -print -quit)
[ -n "$LIBRARY" ]
fi
WRITE_PATHS=$("$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$PREFIX/config.json" --systemd-write-paths)
cat > /etc/systemd/system/remote-fs-browser.service <<EOF
[Unit]
Description=Remote filesystem browser
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=$PREFIX/venv/bin/remotefs serve --no-defaults --config $PREFIX/config.json
Environment=LIBNFS_LIBRARY=$LIBRARY
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
$WRITE_PATHS
[Install]
WantedBy=multi-user.target
EOF
chmod 644 /etc/systemd/system/remote-fs-browser.service
systemctl daemon-reload
systemctl enable remote-fs-browser
systemctl restart remote-fs-browser

systemctl is-active --quiet remote-fs-browser
"$PREFIX/venv/bin/python" "$SOURCE/scripts/deployment.py" --config "$PREFIX/config.json" --health-check

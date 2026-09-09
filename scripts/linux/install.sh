#!/usr/bin/env bash
set -euo pipefail
# Run from an unpacked checkout: sudo scripts/linux/install.sh /path/to/private-config.json
CONFIG=${1:?Pass a private service config JSON file}
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
PREFIX=/opt/remote-fs-browser
if [ "$(id -u)" != 0 ]; then echo 'Run as root to install the system service.' >&2; exit 1; fi
if command -v apt-get >/dev/null; then
  apt-get update
  apt-get install -y python3 python3-venv git cmake build-essential
elif command -v dnf >/dev/null; then
  dnf install -y python3 python3-pip git cmake gcc make
else
  echo 'Install Python 3.11+, a C compiler, CMake and Git for this distribution.' >&2; exit 1
fi
install -d -m 700 "$PREFIX"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install "$SOURCE"
if [ ! -d "$PREFIX/libnfs-src/.git" ]; then git clone https://github.com/sahlberg/libnfs.git "$PREFIX/libnfs-src"; fi
git -C "$PREFIX/libnfs-src" fetch origin c69a48c8116fd50287875decd50474685937a4af
git -C "$PREFIX/libnfs-src" checkout --detach c69a48c8116fd50287875decd50474685937a4af
cmake -S "$PREFIX/libnfs-src" -B "$PREFIX/libnfs-build" -DCMAKE_INSTALL_PREFIX="$PREFIX/native" -DBUILD_SHARED_LIBS=ON -DENABLE_UTILS=OFF -DENABLE_TLS=OFF
cmake --build "$PREFIX/libnfs-build" --parallel 2
cmake --install "$PREFIX/libnfs-build"
LIBRARY=$(find "$PREFIX/native" -name 'libnfs.so' -print -quit)
[ -n "$LIBRARY" ]
install -m 600 "$CONFIG" "$PREFIX/config.json"
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
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable remote-fs-browser
systemctl restart remote-fs-browser

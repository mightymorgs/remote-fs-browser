# syntax=docker/dockerfile:1.7
#
# remotefs as a container: the browser file manager and its API on one port,
# browsing whatever is mounted under /data.
#
#   docker build -t remotefs .
#   docker run --rm -p 8080:8080 -v "$PWD:/data" -v remotefs-config:/config \
#     -e REMOTEFS_USERNAME=admin -e REMOTEFS_PASSWORD='at least 12 chars' remotefs
#
# Three stages: a pinned libnfs build (NFS needs libnfs 6+, and Debian's
# package is older), a virtualenv holding the package and its Python deps,
# and a slim runtime that copies both in and runs as an unprivileged user.
# The browser frontend needs no build step: the bundled JavaScript under
# src/remote_fs_browser/web is committed and shipped as package data.

ARG PYTHON_VERSION=3.12
ARG DEBIAN_RELEASE=bookworm

# ── libnfs ──────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS libnfs
# The same commit CI, the Windows build and scripts/linux/install.sh pin.
ARG LIBNFS_REF=c69a48c8116fd50287875decd50474685937a4af
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git cmake build-essential \
 && rm -rf /var/lib/apt/lists/*
RUN git init -q /src/libnfs \
 && git -C /src/libnfs remote add origin https://github.com/sahlberg/libnfs.git \
 && git -C /src/libnfs fetch -q --depth 1 origin "$LIBNFS_REF" \
 && git -C /src/libnfs checkout -q --detach FETCH_HEAD \
 && cmake -S /src/libnfs -B /src/libnfs/build -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/libnfs -DCMAKE_INSTALL_LIBDIR=lib \
      -DBUILD_SHARED_LIBS=ON -DENABLE_UTILS=OFF -DENABLE_TLS=OFF \
 && cmake --build /src/libnfs/build --parallel \
 && cmake --install /src/libnfs/build \
 && test -e /opt/libnfs/lib/libnfs.so \
 # libnfs is LGPL-2.1: ship its licence and say exactly which source built it.
 && mkdir -p /opt/libnfs/share/doc/libnfs \
 && cp /src/libnfs/COPYING /src/libnfs/LICENCE-*.txt /opt/libnfs/share/doc/libnfs/ 2>/dev/null; \
    printf 'Built from https://github.com/sahlberg/libnfs at commit %s\n' "$LIBNFS_REF" \
      > /opt/libnfs/share/doc/libnfs/SOURCE \
 && rm -rf /opt/libnfs/include /opt/libnfs/lib/pkgconfig /opt/libnfs/lib/cmake

# ── Python package ──────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS package
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/remotefs
WORKDIR /src
COPY . .
# impacket (SMB share listing) is a default dependency on Linux.
RUN /opt/remotefs/bin/pip install . \
 && /opt/remotefs/bin/remotefs --version

# ── runtime ─────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE}
ARG TARGETARCH
# rclone powers cloud connections; set INSTALL_RCLONE=false for a smaller image.
ARG INSTALL_RCLONE=true
# kubectl powers the Kubernetes endpoint; an empty version leaves it out.
ARG KUBECTL_VERSION=v1.34.1
ARG UID=1000
ARG GID=1000

LABEL org.opencontainers.image.title="remote-fs-browser" \
      org.opencontainers.image.description="A browser file manager for local, NAS and cloud storage" \
      org.opencontainers.image.source="https://github.com/mightymorgs/remote-fs-browser" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && if [ "$INSTALL_RCLONE" = "true" ]; then apt-get install -y --no-install-recommends rclone; fi \
 && rm -rf /var/lib/apt/lists/*

RUN if [ -n "$KUBECTL_VERSION" ]; then \
      arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
      && base="https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}" \
      && curl -fsSLo /usr/local/bin/kubectl "$base/kubectl" \
      && echo "$(curl -fsSL "$base/kubectl.sha256")  /usr/local/bin/kubectl" | sha256sum -c - \
      && chmod 0755 /usr/local/bin/kubectl; \
    fi

COPY --from=libnfs /opt/libnfs /opt/libnfs
COPY --from=package /opt/remotefs /opt/remotefs

RUN groupadd --gid "$GID" remotefs \
 && useradd --uid "$UID" --gid "$GID" --home-dir /home/remotefs --create-home --shell /usr/sbin/nologin remotefs \
 && mkdir -p /data /config \
 && chown remotefs:remotefs /data /config \
 && chmod 0700 /config

COPY --chmod=0755 <<'EOF' /usr/local/bin/remotefs-container
#!/bin/sh
# Container entrypoint. `serve` (the default command, or any leading flag)
# seeds the account from the environment and starts the service; any other
# command runs as given, so `docker run IMAGE remotefs --help` works.
set -eu

if [ $# -gt 0 ] && [ "$1" != serve ] && [ "${1#-}" = "$1" ]; then
  exec "$@"
fi
[ "${1:-}" = serve ] && shift

config="${REMOTEFS_CONFIG:-/config/config.json}"
username="${REMOTEFS_USERNAME:-admin}"

# A password from the environment (or a mounted secret file) replaces the
# stored one on every start, so the source of truth stays outside the
# container. Without one, an account already in the config is kept.
password="${REMOTEFS_PASSWORD:-}"
if [ -z "$password" ] && [ -n "${REMOTEFS_PASSWORD_FILE:-}" ]; then
  password="$(cat "$REMOTEFS_PASSWORD_FILE")"
fi
if [ -n "$password" ]; then
  printf '%s\n' "$password" | remotefs account --config "$config" --username "$username" --password-stdin >/dev/null
  echo "remotefs: account '$username' set from the environment"
elif [ ! -f "$config" ]; then
  echo "remotefs: no account yet; set REMOTEFS_PASSWORD or REMOTEFS_PASSWORD_FILE (12+ characters)" >&2
  exit 64
fi
unset password REMOTEFS_PASSWORD

set -- --config "$config" --bind "${REMOTEFS_BIND:-0.0.0.0}" --port "${REMOTEFS_PORT:-8080}" --no-defaults "$@"
# Comma-separated lists: browse roots, and the SMB/NFS ranges the service may
# reach (none by default, which disables SMB/NFS until you name a network).
old_ifs="$IFS"; IFS=,
for root in ${REMOTEFS_ROOTS:-/data}; do [ -n "$root" ] && set -- "$@" --root "$root"; done
for net in ${REMOTEFS_ALLOW_NETWORK:-}; do [ -n "$net" ] && set -- "$@" --allow-network "$net"; done
IFS="$old_ifs"
case "${REMOTEFS_READ_ONLY:-false}" in true|1|yes) set -- "$@" --read-only ;; esac

exec remotefs serve "$@"
EOF

ENV PATH="/opt/remotefs/bin:${PATH}" \
    LIBNFS_LIBRARY=/opt/libnfs/lib/libnfs.so \
    PYTHONUNBUFFERED=1 \
    HOME=/home/remotefs \
    REMOTEFS_CONFIG=/config/config.json \
    REMOTEFS_PORT=8080 \
    REMOTEFS_ROOTS=/data

USER remotefs
WORKDIR /data
VOLUME ["/config"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('REMOTEFS_PORT', '8080'), timeout=4)"
ENTRYPOINT ["/usr/local/bin/remotefs-container"]
CMD ["serve"]

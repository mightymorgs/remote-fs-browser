#!/usr/bin/env bash
# Disposable demo lab for recording the feature tour on a throwaway Linux container (run as root).
# Creates three SMB hosts on 192.168.50.0/24 (loopback aliases), a local S3-compatible server,
# a libvirt test-driver pool, demo files, and a remotefs config. Never run this on a real machine:
# it adds loopback addresses, a routing rule and /etc/hosts entries.
#
# Needs: iproute2, samba (smbd/nmbd), rclone, fuse3 (for the mount chapter), a venv with remote-fs-browser[libvirt], moto[server], pillow.
#   LAB=/tmp/rfs-lab VENV=/opt/rfv scripts/video/demo_lab.sh
set -euo pipefail
LAB=${LAB:-/tmp/rfs-lab}
HOME_DIR=${HOME_DIR:-/home/morgan}
STAGING=${STAGING:-/srv/remotefs/staging}
VENV=${VENV:-/opt/rfv}
PASS=${DEMO_PASSWORD:-demo-password-2026}
SMB_USER=studio SMB_PASS=${SMB_PASSWORD:-harbour-lane-demo}
HERE=$(cd "$(dirname "$0")" && pwd)

mkdir -p "$LAB" /run/samba
id "$SMB_USER" >/dev/null 2>&1 || useradd -M -s /usr/sbin/nologin "$SMB_USER"

# Unused addresses in the demo subnet fail fast instead of waiting for the probe timeout.
ip route replace unreachable 192.168.50.0/24
# name ip dns-name shares...
HOSTS=(
  "STUDIO-NAS 192.168.50.10 studio-nas.lan Projects Media Archive"
  "BACKUP-BOX 192.168.50.23 - Backups"
  "RECEPTION 192.168.50.41 reception-pc.lan Scans"
)
sed -i '/# rfs-demo-lab$/d' /etc/hosts
for row in "${HOSTS[@]}"; do
  read -r nb ip dns shares <<<"$row"
  ip addr replace "$ip/32" dev lo
  [ "$dns" = - ] || echo "$ip $dns # rfs-demo-lab" >>/etc/hosts
  dir=$LAB/smb/$nb; mkdir -p "$dir"/{run,lock,state,private,cache,log,ncalrpc}
  {
    echo "[global]"
    echo "netbios name = $nb"; echo "workgroup = HARBOUR"
    echo "interfaces = $ip/32"; echo "bind interfaces only = yes"
    echo "pid directory = $dir/run"; echo "lock directory = $dir/lock"; echo "state directory = $dir/state"
    echo "private dir = $dir/private"; echo "cache directory = $dir/cache"; echo "log file = $dir/log/%m.log"
    echo "passdb backend = tdbsam:$dir/private/passdb.tdb"; echo "ncalrpc dir = $dir/ncalrpc"
    echo "server min protocol = SMB2"; echo "disable spoolss = yes"; echo "load printers = no"
    echo "server role = standalone server"; echo "map to guest = never"
    for share in ${shares}; do
      mkdir -p "$LAB/shares/$nb/$share"
      echo "[$share]"; echo "path = $LAB/shares/$nb/$share"; echo "read only = no"
      echo "valid users = $SMB_USER"; echo "force user = root"
    done
  } >"$dir/smb.conf"
  printf '%s\n%s\n' "$SMB_PASS" "$SMB_PASS" | smbpasswd -c "$dir/smb.conf" -s -a "$SMB_USER" >/dev/null
  pkill -f "smbd.*$dir/smb.conf" || true; pkill -f "nmbd.*$dir/smb.conf" || true
  smbd -D -s "$dir/smb.conf"
  nmbd -D -s "$dir/smb.conf"
done

# Demo content: a small creative studio's files.
mkdir -p "$STAGING"
"$VENV/bin/python" "$HERE/demo_lab_files.py" "$LAB" "$HOME_DIR"

# Local S3-compatible server (moto) with an empty bucket.
pkill -f "moto_server.*9000" || true
nohup "$VENV/bin/moto_server" -H 127.0.0.1 -p 9000 >"$LAB/s3.log" 2>&1 &
for _ in $(seq 50); do curl -s -o /dev/null http://127.0.0.1:9000/ && break; sleep 0.2; done
curl -s -X PUT http://127.0.0.1:9000/studio-archive >/dev/null

# Libvirt test driver with a VM image pool.
cat >"$LAB/libvirt.xml" <<'EOF'
<node>
  <pool type='dir'>
    <name>vm-images</name>
    <uuid>35bb2ad9-388a-cdfe-461a-b8907f6e53fe</uuid>
    <capacity>536870912000</capacity><allocation>171798691840</allocation><available>365072220160</available>
    <target><path>/var/lib/libvirt/images</path></target>
    <volume><name>render-node-01.qcow2</name><key>/var/lib/libvirt/images/render-node-01.qcow2</key>
      <capacity>107374182400</capacity><allocation>41875931136</allocation>
      <target><path>/var/lib/libvirt/images/render-node-01.qcow2</path><format type='qcow2'/></target></volume>
    <volume><name>asset-server.qcow2</name><key>/var/lib/libvirt/images/asset-server.qcow2</key>
      <capacity>68719476736</capacity><allocation>22548578304</allocation>
      <target><path>/var/lib/libvirt/images/asset-server.qcow2</path><format type='qcow2'/></target></volume>
    <volume><name>ubuntu-24.04.iso</name><key>/var/lib/libvirt/images/ubuntu-24.04.iso</key>
      <capacity>2773483520</capacity><allocation>2773483520</allocation>
      <target><path>/var/lib/libvirt/images/ubuntu-24.04.iso</path><format type='raw'/></target></volume>
  </pool>
</node>
EOF

# remotefs configuration: demo roots, the demo subnet and a libvirt endpoint.
CONF=$LAB/config/config.json; mkdir -p "$(dirname "$CONF")"
printf '%s\n' "$PASS" | "$VENV/bin/remotefs" account --config "$CONF" --username morgan --password-stdin >/dev/null
"$VENV/bin/python" - "$CONF" "$LAB" "$STAGING" <<'EOF'
import json, sys
path, lab, staging = sys.argv[1:]
config = json.load(open(path))
policy = config.setdefault('policy', {})
policy['endpoints'] = {'hypervisor': {'type': 'libvirt', 'uri': f'test://{lab}/libvirt.xml', 'pools': ['vm-images']}}
config['staging_stores'] = {'Studio scratch': staging}
json.dump(config, open(path, 'w'), indent=2)
EOF
echo "Lab ready. Start the service with:"
echo "  $VENV/bin/remotefs serve --config $CONF --no-defaults --read-write --root $HOME_DIR --root $STAGING --allow-network 192.168.50.0/24 --port 8080 --allow-mounts --mount-folder $HOME_DIR/remotefs"
echo "Sign in as morgan / $PASS. SMB login: $SMB_USER / $SMB_PASS"

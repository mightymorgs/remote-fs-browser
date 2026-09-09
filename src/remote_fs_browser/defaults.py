"""Zero-configuration defaults: what this machine can see, bounded for safe discovery."""
import ipaddress
import os
import socket
import sys
from pathlib import Path

REAL_FILESYSTEMS = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs', 'f2fs', 'jfs', 'vfat', 'exfat', 'ntfs', 'ntfs3',
                    'fuseblk', 'cifs', 'smb3', 'nfs', 'nfs4', 'hfsplus', 'apfs'}
LINUX_PREFIXES = ('/mnt/', '/media/', '/run/media/', '/srv/', '/data/', '/home/')
RFC1918 = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
# Container, VM, tunnel and link-layer helper interfaces: their subnets are not the LAN.
VIRTUAL_INTERFACES = ('docker', 'br-', 'veth', 'virbr', 'vmnet', 'vboxnet', 'utun', 'tun', 'tap', 'feth', 'bridge',
                      'llw', 'awdl', 'anpi', 'lo', 'zt', 'tailscale', 'wg', 'lxc', 'lxd', 'cni', 'flannel', 'cali', 'kube')


def home_root():
    return str(Path.home())


def mounted_volumes(platform=None, partitions=None, volumes='/Volumes'):
    """Mounted storage a person would expect under "This Computer", excluding system volumes."""
    platform = platform or sys.platform
    if platform == 'darwin':
        try:
            entries = list(os.scandir(volumes))
        except OSError:
            return []
        # The boot volume appears as a symlink to / and is skipped with every other link.
        return sorted(item.path for item in entries if item.is_dir(follow_symlinks=False) and not item.name.startswith('.'))
    if partitions is None:
        import psutil
        partitions = psutil.disk_partitions(all=False)
    rows = set()
    for part in partitions:
        mount = part.mountpoint
        if platform.startswith('win'):
            if not part.fstype or 'cdrom' in part.opts.split(','):
                continue
            rows.add(mount)
            continue
        if part.fstype not in REAL_FILESYSTEMS or part.device.startswith('/dev/loop'):
            continue
        if mount.startswith(('/boot', '/var/lib', '/snap')) or not (mount + '/').startswith(LINUX_PREFIXES):
            continue
        rows.add(mount)
    return sorted(rows)


def local_subnets(max_prefix=24, addresses=None):
    """RFC1918 IPv4 networks on this host's physical interfaces, narrowed to at most a /24 each.

    `addresses` rows are (interface, address, netmask); a two-item (address, netmask) row is accepted too.
    """
    if addresses is None:
        import psutil
        addresses = [(name, item.address, item.netmask) for name, group in psutil.net_if_addrs().items() for item in group
                     if item.family == socket.AF_INET and item.netmask]
    networks = set()
    for row in addresses:
        name, address, netmask = row if len(row) == 3 else ('', *row)
        if name.lower().startswith(VIRTUAL_INTERFACES):
            continue
        try:
            ip = ipaddress.ip_address(address)
            network = ipaddress.ip_network(f'{address}/{netmask}', strict=False)
        except ValueError:
            continue
        if ip.version != 4 or not any(ip in block for block in RFC1918):
            continue
        if network.prefixlen >= 32:
            continue
        if network.prefixlen < max_prefix:
            network = ipaddress.ip_network(f'{address}/{max_prefix}', strict=False)
        networks.add(network)
    return [str(network) for network in sorted(networks)]


def readable_dirs(paths):
    """Existing, readable directories, resolved and deduplicated, in the order given."""
    rows = []
    for path in paths:
        try:
            resolved = Path(path).resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_dir() or not os.access(resolved, os.R_OK | os.X_OK):
            continue
        if str(resolved) not in rows:
            rows.append(str(resolved))
    return rows

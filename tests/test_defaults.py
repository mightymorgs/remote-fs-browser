from collections import namedtuple
import os
import pytest
from remote_fs_browser.defaults import local_subnets, mounted_volumes, readable_dirs

Partition = namedtuple('Partition', 'device mountpoint fstype opts')


def test_linux_volumes_keep_real_mounts_only():
    partitions = [
        Partition('/dev/nvme0n1p2', '/', 'ext4', 'rw'),
        Partition('/dev/nvme0n1p1', '/boot/efi', 'vfat', 'rw'),
        Partition('/dev/sdb1', '/mnt/media', 'xfs', 'rw'),
        Partition('/dev/sdc1', '/mnt', 'ext4', 'rw'),
        Partition('nas:/exports/photos', '/media/photos', 'nfs4', 'rw'),
        Partition('/dev/loop3', '/mnt/loop', 'ext4', 'ro'),
        Partition('tmpfs', '/mnt/scratch', 'tmpfs', 'rw'),
        Partition('/dev/sdd1', '/var/lib/docker', 'ext4', 'rw'),
        Partition('/dev/sde1', '/home', 'btrfs', 'rw'),
    ]
    assert mounted_volumes(platform='linux', partitions=partitions) == ['/home', '/media/photos', '/mnt', '/mnt/media']


def test_windows_volumes_skip_optical_and_empty_drives():
    partitions = [
        Partition('C:\\', 'C:\\', 'NTFS', 'rw,fixed'),
        Partition('D:\\', 'D:\\', '', 'cdrom'),
        Partition('E:\\', 'E:\\', 'exFAT', 'rw,removable'),
    ]
    assert mounted_volumes(platform='win32', partitions=partitions) == ['C:\\', 'E:\\']


def test_macos_volumes_skip_links_and_hidden(tmp_path):
    (tmp_path / 'Media').mkdir()
    (tmp_path / '.hidden').mkdir()
    try:
        (tmp_path / 'Macintosh HD').symlink_to('/')
    except OSError:
        pytest.skip('Creating symlinks requires Windows developer mode')
    assert mounted_volumes(platform='darwin', volumes=str(tmp_path)) == [str(tmp_path / 'Media')]
    assert mounted_volumes(platform='darwin', volumes=str(tmp_path / 'absent')) == []


def test_local_subnets_filter_and_narrow():
    addresses = [
        ('127.0.0.1', '255.0.0.0'),
        ('192.168.0.205', '255.255.255.0'),
        ('172.28.23.36', '255.255.0.0'),
        ('10.1.2.3', '255.255.254.0'),
        ('169.254.10.4', '255.255.0.0'),
        ('100.109.99.119', '255.255.255.255'),
        ('203.0.113.9', '255.255.255.0'),
        ('192.168.0.9', '255.255.255.0'),
        ('fe80::1', 'ffff:ffff:ffff:ffff::'),
        ('not-an-ip', '255.255.255.0'),
        ('docker0', '172.17.0.1', '255.255.0.0'),
        ('br-5c4d2f507049', '172.19.0.1', '255.255.0.0'),
        ('feth351', '172.30.1.2', '255.255.0.0'),
        ('utun4', '10.9.9.9', '255.255.255.0'),
        ('eno1', '10.44.0.7', '255.255.255.0'),
    ]
    assert local_subnets(addresses=addresses) == ['10.1.2.0/24', '10.44.0.0/24', '172.28.23.0/24', '192.168.0.0/24']
    assert local_subnets(addresses=[('192.168.4.7', '255.255.255.255')]) == []


def test_readable_dirs_filters_and_dedupes(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'file').write_text('x')
    rows = readable_dirs([tmp_path / 'a', str(tmp_path / 'a'), tmp_path / 'missing', tmp_path / 'file'])
    assert rows == [str((tmp_path / 'a').resolve())]
    if os.name != 'nt' and os.geteuid() != 0:
        (tmp_path / 'locked').mkdir(mode=0)
        assert readable_dirs([tmp_path / 'locked']) == []

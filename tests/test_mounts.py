import configparser
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from remote_fs_browser import Policy
from remote_fs_browser import mounts
from remote_fs_browser.http import create_app
from remote_fs_browser.mounts import MountError, MountManager, remote_for
from remote_fs_browser.policy import HOST_OPERATIONS, READ_OPERATIONS, WRITE_OPERATIONS

TOKEN = 'test-token-with-at-least-32-characters'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def plain_obscure(monkeypatch):
    monkeypatch.setattr(mounts, 'obscure', lambda binary, secret: 'obscured:' + secret[::-1])


def test_smb_remote_uses_obscured_password_and_share_path(plain_obscure):
    section, path = remote_for({'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/Jobs/2026'},
                               {'username': 'studio', 'password': 'pa55', 'domain': 'HARBOUR'}, None, 'rclone')
    assert section == {'type': 'smb', 'host': '192.0.2.5', 'user': 'studio', 'pass': 'obscured:55ap', 'domain': 'HARBOUR'}
    assert path == 'Projects/Jobs/2026'
    with pytest.raises(MountError):
        remote_for({'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/'}, None, None, 'rclone')


def test_rclone_remote_copies_the_connection_and_joins_its_root(tmp_path):
    conf = tmp_path / 'cloud.conf'
    conf.write_text('[remote]\ntype = s3\nprovider = Other\naccess_key_id = key\n')
    section, path = remote_for({'type': 'rclone', 'endpoint': 'cloud-1', 'path': '/photos'}, None,
                               {'config': str(conf), 'remote': 'remote', 'root': '/bucket/team'}, 'rclone')
    assert section['type'] == 's3' and section['access_key_id'] == 'key'
    assert path == 'bucket/team/photos'


@pytest.mark.parametrize('descriptor', [{'type': 'local', 'root': '/srv'}, {'type': 'nfs', 'host': 'nas', 'export': '/x'},  # NFS needs its bridge
                                        {'type': 'libvirt', 'endpoint': 'kvm'}])
def test_unmountable_types_explain_themselves(descriptor):
    with pytest.raises(MountError):
        remote_for({**descriptor, 'path': '/'}, None, None, 'rclone')


def manager(tmp_path, system):
    return MountManager(tmp_path / 'state', base=tmp_path / 'mnt', binary='rclone', system=system)


@pytest.mark.parametrize('system,verb,extra', [('win32', 'mount', '--network-mode'), ('darwin', 'nfsmount', '--nfs-cache-type'),
                                               ('linux', 'mount', None)])
def test_command_per_platform_keeps_the_rc_password_out_of_argv(tmp_path, system, verb, extra):
    m = manager(tmp_path, system)
    row = {'label': 'Projects', 'target': 'Z:' if system == 'win32' else '/mnt/p', 'read_only': True,
           'rc_port': 5572, 'rc_pass': 'secret-rc-password'}
    argv = m.command(row, 'Projects', tmp_path / 'c.conf', tmp_path / 'l.log')
    assert argv[:3] == ['rclone', verb, 'remote:Projects'] and argv[3] == row['target']
    assert '--read-only' in argv and 'full' in argv and '--rc' in argv
    assert 'secret-rc-password' not in ' '.join(argv)
    if extra:
        assert extra in argv
    assert ('--network-mode' in argv) == (system == 'win32')
    assert ('locallocks' in argv) == (system == 'darwin')  # rclone's NFS server has no lock manager
    assert ('FileSecurity=D:P(A;;FRFX;;;WD)' in argv) == (system == 'win32')  # read-only rights on Windows


def test_folder_targets_stay_inside_the_mount_folder_and_never_collide(tmp_path):
    m = manager(tmp_path, 'linux')
    first = m.choose_target('Projects')
    assert Path(first) == tmp_path / 'mnt' / 'Projects'
    (Path(first) / 'occupied').write_text('x')
    assert Path(m.choose_target('Projects')) == tmp_path / 'mnt' / 'Projects 2'
    assert Path(m.choose_target('x', '../../etc')).parent == tmp_path / 'mnt'


def test_drive_letters_are_validated(tmp_path, monkeypatch):
    m = manager(tmp_path, 'win32')
    monkeypatch.setattr(os.path, 'exists', lambda path: path.startswith('Z:'))
    assert m.choose_target('x') == 'Y:'
    assert m.choose_target('x', 'q:') == 'Q:'
    for bad in ('C:', 'AB', '1'):
        with pytest.raises(MountError):
            m.choose_target('x', bad)
    with pytest.raises(MountError):
        m.choose_target('x', 'Z:')


def test_prerequisites_report_what_is_missing(monkeypatch):
    monkeypatch.setattr(mounts, 'rclone_version', lambda binary: (1, 60))
    monkeypatch.setattr(mounts, 'winfsp_installed', lambda: False)
    assert [m['name'] for m in mounts.prerequisites('rclone', 'darwin')['missing']] == ['rclone 1.65+']
    assert [m['name'] for m in mounts.prerequisites('rclone', 'win32')['missing']] == ['WinFsp']
    monkeypatch.setattr(mounts, 'rclone_binary', lambda: None)
    assert mounts.prerequisites(None, 'win32')['missing'][0]['name'] == 'rclone'


class FakeProcess:
    pid = 4242

    def __init__(self):
        self.code = None

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.code = 0
        return 0

    def send_signal(self, value):
        self.code = 0

    terminate = kill = send_signal


def test_mount_and_unmount_lifecycle_waits_for_uploads(tmp_path, monkeypatch, plain_obscure):
    started, calls, pending = [], [], [2, 1, 0]
    m = MountManager(tmp_path / 'state', base=tmp_path / 'mnt', binary='rclone', system='linux',
                     popen=lambda argv, **kw: started.append((argv, kw)) or FakeProcess())
    monkeypatch.setattr(mounts, 'prerequisites', lambda *a: {'available': True, 'missing': []})
    monkeypatch.setattr(m, 'mounted', lambda target: True)

    def rc(row, command, timeout=5, **params):
        calls.append(command)
        if command == 'vfs/stats':
            return {'diskCache': {'uploadsInProgress': pending.pop(0) if pending else 0, 'uploadsQueued': 0}}
        m.processes[next(iter(m.processes))].code = 0
        return {}
    monkeypatch.setattr(m, 'rc', rc)
    monkeypatch.setattr(mounts.time, 'sleep', lambda s: None)
    row = m.mount('alice', {'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/', 'credential_id': 'c1'},
                  {'username': 'u', 'password': 'p'}, None, 'Projects', read_only=False)
    argv, kw = started[0]
    assert kw['env']['RCLONE_RC_PASS'] and 'credential_id' not in row['descriptor']
    conf = configparser.RawConfigParser()
    conf.read(tmp_path / 'state' / f"{row['id']}.conf")
    assert conf['remote']['pass'] == 'obscured:p'
    if os.name != 'nt':
        assert (tmp_path / 'state' / f"{row['id']}.conf").stat().st_mode & 0o077 == 0
    assert [r['id'] for r in m.list('alice')] == [row['id']] and m.list('bob') == []
    with pytest.raises(PermissionError):
        m.unmount('bob', row['id'])
    assert m.unmount('alice', row['id']) == {'unmounted': True}
    assert calls.count('vfs/stats') >= 3 and 'core/quit' in calls
    assert not (tmp_path / 'state' / f"{row['id']}.conf").exists() and m.list('alice') == []


def test_unmount_refuses_while_uploading_unless_forced(tmp_path, monkeypatch):
    m = MountManager(tmp_path / 'state', base=tmp_path / 'mnt', binary='rclone', system='linux')
    m.records['mount-1'] = {'principal': 'alice', 'target': str(tmp_path / 'mnt' / 'x'), 'rc_port': 1, 'rc_pass': 'p'}
    m.processes['mount-1'] = FakeProcess()
    monkeypatch.setattr(m, 'status', lambda key: {'state': 'mounted', 'pending_uploads': 3})
    monkeypatch.setattr(m, 'rc', lambda *a, **k: m.processes['mount-1'].send_signal(0) or {})
    with pytest.raises(MountError, match='3 file'):
        m.unmount('alice', 'mount-1', wait=0)
    assert 'mount-1' in m.records
    assert m.unmount('alice', 'mount-1', force=True) == {'unmounted': True}


class FakeManager:
    method = 'fuse'
    binary = 'rclone'
    directory = Path('.')

    def __init__(self):
        self.calls = []

    def list(self, principal):
        return []

    def mount(self, principal, descriptor, credentials, endpoint_config, label, read_only, target=None):
        self.calls.append(dict(descriptor=descriptor, credentials=credentials, label=label, read_only=read_only))
        raise MountError('Local folders are already on this computer')

    def shutdown(self):
        pass


def test_http_mounts_are_off_unless_the_service_allows_them(tmp_path):
    policy = Policy(local_roots=[str(tmp_path)], operations=READ_OPERATIONS + WRITE_OPERATIONS)
    with TestClient(create_app(policy, token=TOKEN, mount_manager=FakeManager()), raise_server_exceptions=False) as client:
        assert client.get('/api/mounts', headers=HEADERS).json() == {'enabled': False, 'mounts': []}
        session = client.post('/api/sessions', headers=HEADERS, json={'descriptor': {'type': 'local', 'root': str(tmp_path)}}).json()
        response = client.post('/api/mounts', headers=HEADERS, json={'session': session['id']})
        assert response.status_code == 403 and '--allow-mounts' in response.json()['detail']


def test_http_mount_defaults_to_read_write_and_passes_the_session_location(tmp_path, monkeypatch):
    monkeypatch.setattr(mounts, 'prerequisites', lambda *a: {'method': 'fuse', 'available': True, 'missing': [], 'rclone': '1.75'})
    fake = FakeManager()
    policy = Policy(local_roots=[str(tmp_path)], operations=READ_OPERATIONS + WRITE_OPERATIONS + HOST_OPERATIONS)
    (tmp_path / 'Jobs').mkdir()
    with TestClient(create_app(policy, token=TOKEN, mount_manager=fake), raise_server_exceptions=False) as client:
        info = client.get('/api/mounts', headers=HEADERS).json()
        assert info['enabled'] and info['available'] and info['notice'] is None
        session = client.post('/api/sessions', headers=HEADERS, json={'descriptor': {'type': 'local', 'root': str(tmp_path)}}).json()
        response = client.post('/api/mounts', headers=HEADERS, json={'session': session['id'], 'path': '/Jobs'})
        assert response.status_code == 422 and 'already on this computer' in response.json()['detail']
        call = fake.calls[0]
        assert call['read_only'] is False and call['label'] == 'Jobs' and call['descriptor']['path'] == '/Jobs'
        client.post('/api/mounts', headers=HEADERS, json={'session': session['id'], 'read_only': True})
        assert fake.calls[1]['read_only'] is True
        assert client.post('/api/mounts', headers=HEADERS, json={'session': 'missing'}).status_code == 404


def test_allow_mounts_flag_adds_the_host_operation():
    from argparse import Namespace
    from remote_fs_browser.cli import build_policy
    args = Namespace(root=['/'], allow_network=['192.0.2.0/24'], no_defaults=True, read_only=True, read_write=False, allow_mounts=True)
    policy, _ = build_policy(args, {})
    assert policy.operations == READ_OPERATIONS + ['mount']


@pytest.mark.skipif(not (os.environ.get('REMOTEFS_TEST_FUSE') and shutil.which('rclone') and Path('/dev/fuse').exists()),
                    reason='set REMOTEFS_TEST_FUSE=1 on a host with rclone and FUSE to run a real mount')
def test_real_fuse_mount_of_a_cloud_connection(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'hello.txt').write_text('hello')
    conf = tmp_path / 'local.conf'
    conf.write_text('[remote]\ntype = alias\nremote = ' + str(source) + '\n')
    m = MountManager(tmp_path / 'state', base=tmp_path / 'mnt')
    row = m.mount('alice', {'type': 'rclone', 'endpoint': 'local', 'path': '/'}, None,
                  {'config': str(conf), 'remote': 'remote', 'root': '/'}, 'Local', read_only=False)
    try:
        target = Path(row['target'])
        assert (target / 'hello.txt').read_text() == 'hello'
        (target / 'new.txt').write_text('written through the mount')
    finally:
        m.unmount('alice', row['id'])
    assert (source / 'new.txt').read_text() == 'written through the mount'
    assert not target.exists()


def test_eject_removes_the_empty_mount_folder_even_after_finder_touched_it(tmp_path):
    m = manager(tmp_path, 'darwin')
    target = m.choose_target('Projects')
    (Path(target) / '.DS_Store').write_bytes(b'finder')
    (Path(target) / '._Icon').write_bytes(b'appledouble')
    m.release(target)
    assert not Path(target).exists()
    kept = m.choose_target('Projects')
    (Path(kept) / 'real.txt').write_text('never deleted')
    m.release(kept)
    assert (Path(kept) / 'real.txt').exists()

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


def test_smb_remote_splits_a_domain_typed_into_the_username(plain_obscure):
    section, _ = remote_for({'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/'},
                            {'username': 'NAS\\studio', 'password': 'pa55'}, None, 'rclone')
    assert section['user'] == 'studio' and section['domain'] == 'NAS'


def test_smb_login_qualifies_a_bare_name_only_on_windows():
    from remote_fs_browser.backends import smb_username
    assert smb_username('192.0.2.5', 'studio', windows=True) == '192.0.2.5\\studio'
    assert smb_username('192.0.2.5', 'studio', windows=False) == 'studio'
    assert smb_username('192.0.2.5', 'studio', 'HARBOUR', windows=False) == 'HARBOUR\\studio'
    assert smb_username('nas', 'NAS\\studio', 'IGNORED', windows=True) == 'NAS\\studio'
    assert smb_username('nas', 'studio@example.com', windows=True) == 'studio@example.com'
    assert smb_username('nas', '', windows=True) == ''


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
           'rc_port': 5572, 'rc_pass': 'secret-rc-password', 'owner_sid': 'S-1-5-21-7-1001'}
    argv = m.command(row, 'Projects', tmp_path / 'c.conf', tmp_path / 'l.log')
    assert argv[:3] == ['rclone', verb, 'remote:Projects'] and argv[3] == row['target']
    assert '--read-only' in argv and 'full' in argv and '--rc' in argv
    assert 'secret-rc-password' not in ' '.join(argv)
    if extra:
        assert extra in argv
    assert ('--network-mode' in argv) == (system == 'win32')
    assert ('locallocks' in argv) == (system == 'darwin')  # rclone's NFS server has no lock manager
    assert ('FileSecurity=D:P(A;;FRFX;;;S-1-5-21-7-1001)' in argv) == (system == 'win32')  # owner only, read-only


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

    def mount(self, principal, descriptor, credentials, endpoint_config, label, read_only, target=None, auto=False):
        self.calls.append(dict(descriptor=descriptor, credentials=credentials, label=label, read_only=read_only, auto=auto))
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


class FakeSessions:
    """Stands in for winsession: one signed-in owner, whose token starts processes."""

    def __init__(self, tmp_path, signed_in=True):
        self.tmp_path, self.signed_in, self.started, self.closed = tmp_path, signed_in, [], 0

    def session_of(self, account):
        return 3 if self.signed_in and account.lower().endswith('morgan') else None

    def current_sid(self):
        return 'S-1-5-18'

    def UserSession(self, session):
        api = self

        class Session:
            def sid(self):
                return 'S-1-5-21-7-1001'

            def profile(self):
                return str(api.tmp_path / 'Users' / 'morgan')

            def environment(self):
                return {'USERPROFILE': self.profile(), 'RCLONE_CONFIG': 'ignored'}

            def start(self, argv, env, cwd):
                api.started.append((argv, env, cwd))
                return FakeProcess()

            def close(self):
                api.closed += 1
        return Session()


def windows_service(monkeypatch, tmp_path, owner, sessions):
    monkeypatch.setattr(mounts, 'windows_system_account', lambda: True)
    monkeypatch.setattr(mounts, 'prerequisites', lambda *a: {'available': True, 'missing': []})
    monkeypatch.setattr(mounts, 'obscure', lambda binary, secret: 'obscured')
    m = MountManager(tmp_path / 'state', binary='rclone', system='win32', owner=owner, sessions=sessions,
                     popen=lambda *a, **k: pytest.fail('the SYSTEM service must not start rclone as itself'))
    monkeypatch.setattr(m, 'choose_target', lambda label, requested=None: 'Z:')
    return m


SMB = ({'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/'}, {'username': 'u', 'password': 'p'})


def test_windows_service_mounts_only_in_the_owners_session(tmp_path, monkeypatch):
    sessions = FakeSessions(tmp_path)
    m = windows_service(monkeypatch, tmp_path, 'PC\\morgan', sessions)
    monkeypatch.setattr(m, 'rc', lambda row, command, **kw: {'diskCache': {}})
    row = m.mount('alice', *SMB, None, 'Projects', read_only=False)
    argv, env, cwd = sessions.started[0]
    files = tmp_path / 'Users' / 'morgan' / 'AppData' / 'Local' / 'remotefs' / 'mounts'
    assert cwd == str(files) and (files / f"{row['id']}.conf").exists()
    assert 'FileSecurity=D:P(A;;FA;;;S-1-5-21-7-1001)' in argv and not any('WD)' in a or 'AU)' in a for a in argv)
    assert argv[argv.index('--cache-dir') + 1] == str(files / 'cache')
    assert env['RCLONE_RC_PASS'] and 'RCLONE_CONFIG' not in env and env['USERPROFILE']
    assert sessions.closed == 1 and row['status']['state'] == 'mounted'


def test_windows_service_refuses_without_an_owner_or_when_they_are_signed_out(tmp_path, monkeypatch):
    with pytest.raises(MountError, match='mount_owner'):
        windows_service(monkeypatch, tmp_path, None, FakeSessions(tmp_path)).mount('alice', *SMB, None, 'P', read_only=False)
    with pytest.raises(MountError, match='Sign in to Windows as PC'):
        windows_service(monkeypatch, tmp_path, 'PC\\morgan', FakeSessions(tmp_path, signed_in=False)).mount(
            'alice', *SMB, None, 'P', read_only=False)


def test_account_names_match_with_or_without_the_computer_name():
    from remote_fs_browser.winsession import same_account
    assert same_account('PC\\Morgan', 'morgan') and same_account('morgan', 'pc\\morgan')
    assert not same_account('PC\\morgan', 'OTHER\\morgan') and not same_account('PC\\morgan', 'PC\\sam')


@pytest.mark.skipif(os.name != 'nt', reason='Windows API binding')
def test_windows_api_binding_reads_this_accounts_sid():
    from remote_fs_browser import winsession
    assert winsession.current_sid().startswith('S-1-5-')


# ---------------------------------------------------------------- reconnecting mounts
def reconnecting(tmp_path, monkeypatch, system='linux', resolver=None, **kw):
    started = []
    monkeypatch.setattr(mounts, 'prerequisites', lambda *a: {'available': True, 'missing': []})
    monkeypatch.setattr(mounts, 'obscure', lambda binary, secret: 'obscured')
    monkeypatch.setattr(mounts.time, 'sleep', lambda s: None)
    m = MountManager(tmp_path / 'state', base=tmp_path / 'mnt', binary='rclone', system=system,
                     popen=lambda argv, **k: started.append(argv) or FakeProcess(),
                     resolver=resolver or (lambda principal, descriptor: ({'username': 'u', 'password': 'p'}, None, True)), **kw)
    monkeypatch.setattr(m, 'rc', lambda row, command, **k: {'diskCache': {}} if command == 'vfs/stats' else None)
    monkeypatch.setattr(m, 'mounted', lambda target: True)
    return m, started


SAVED_SMB = {'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/Jobs', 'credential_id': 'login-1'}


def test_a_reconnecting_mount_comes_back_after_rclone_exits(tmp_path, monkeypatch):
    seen = []
    m, started = reconnecting(tmp_path, monkeypatch, resolver=lambda p, d: seen.append((p, d)) or ({'username': 'u', 'password': 'p'}, None, True))
    row = m.mount('alice', SAVED_SMB, {'username': 'u', 'password': 'p'}, None, 'Jobs', read_only=False, auto=True)
    assert row['auto'] and m.saved[row['id']]['descriptor']['credential_id'] == 'login-1'
    target = row['target']
    m.processes[row['id']].code = 1  # rclone exited
    m.reconnect(now=0)
    assert len(started) == 2 and seen == [('alice', SAVED_SMB)]
    assert [(r['id'], r['target'], r['status']['state']) for r in m.list('alice')] == [(row['id'], target, 'mounted')]


def test_a_mount_without_reconnect_is_not_brought_back(tmp_path, monkeypatch):
    m, started = reconnecting(tmp_path, monkeypatch)
    row = m.mount('alice', SAVED_SMB, {'username': 'u', 'password': 'p'}, None, 'Jobs', read_only=False)
    assert not row['auto'] and not (tmp_path / 'state' / 'saved-mounts.json').exists()
    m.processes[row['id']].code = 1
    m.reconnect(now=0)
    assert len(started) == 1 and m.list('alice')[0]['status']['state'] == 'stopped'


def test_remembered_mounts_survive_a_service_restart_until_ejected(tmp_path, monkeypatch):
    m, _ = reconnecting(tmp_path, monkeypatch)
    row = m.mount('alice', SAVED_SMB, {'username': 'u', 'password': 'p'}, None, 'Jobs', read_only=True, target='Jobs', auto=True)
    m.shutdown(wait_uploads=0)
    assert m.list('alice')[0]['status']['state'] == 'waiting'
    again, started = reconnecting(tmp_path, monkeypatch)
    listed = again.list('alice')
    assert [(r['id'], r['status']['state'], r['read_only']) for r in listed] == [(row['id'], 'waiting', True)]
    assert 'credential_id' not in listed[0]['descriptor'] and again.list('bob') == []
    again.reconnect(now=0)
    assert len(started) == 1 and '--read-only' in started[0] and again.list('alice')[0]['status']['state'] == 'mounted'
    with pytest.raises(PermissionError):
        again.unmount('bob', row['id'])
    assert again.unmount('alice', row['id']) == {'unmounted': True}
    assert again.list('alice') == [] and reconnecting(tmp_path, monkeypatch)[0].list('alice') == []


def test_a_waiting_mount_can_be_ejected_before_it_reconnects(tmp_path, monkeypatch):
    m, _ = reconnecting(tmp_path, monkeypatch)
    m.saved['mount-1'] = dict(principal='alice', descriptor=SAVED_SMB, label='Jobs', read_only=False, target=str(tmp_path / 'mnt' / 'Jobs'))
    assert m.unmount('alice', 'mount-1') == {'unmounted': True} and m.saved == {}


def test_reconnect_backs_off_and_shows_why(tmp_path, monkeypatch):
    def refuse(principal, descriptor):
        raise PermissionError('Saved location not found')
    m, started = reconnecting(tmp_path, monkeypatch, resolver=refuse)
    m.saved['mount-1'] = dict(principal='alice', descriptor=SAVED_SMB, label='Jobs', read_only=False, target=str(tmp_path / 'mnt' / 'Jobs'))
    m.reconnect(now=0)
    first = m.retries['mount-1']
    assert first[0] == 15 and 'Saved location not found' in m.list('alice')[0]['status']['reason']
    m.reconnect(now=1)  # not due yet
    m.reconnect(now=15)
    assert m.retries['mount-1'][1] == 30 and started == []
    for n in range(10):
        m.reconnect(now=10_000 * (n + 1))
    assert m.retries['mount-1'][1] == 300


def test_writes_follow_the_policy_when_a_mount_reconnects(tmp_path, monkeypatch):
    m, started = reconnecting(tmp_path, monkeypatch, resolver=lambda p, d: ({'username': 'u', 'password': 'p'}, None, False))
    m.saved['mount-1'] = dict(principal='alice', descriptor=SAVED_SMB, label='Jobs', read_only=False, target=str(tmp_path / 'mnt' / 'Jobs'))
    m.reconnect(now=0)
    assert '--read-only' in started[0]


def test_windows_mounts_wait_for_the_owner_then_reconnect_in_their_session(tmp_path, monkeypatch):
    sessions = FakeSessions(tmp_path)
    m = windows_service(monkeypatch, tmp_path, 'PC\\morgan', sessions)
    m.resolver = lambda principal, descriptor: ({'username': 'u', 'password': 'p'}, None, True)
    monkeypatch.setattr(m, 'rc', lambda row, command, **kw: {'diskCache': {}})
    row = m.mount('alice', *SMB, None, 'Projects', read_only=False, auto=True)
    sessions.signed_in = False
    m.processes[row['id']].code = 1  # signing out ends the owner's processes
    m.reconnect(now=0)
    waiting = m.list('alice')[0]
    assert waiting['status'] == {'state': 'waiting', 'reason': 'Waiting for PC\\morgan to sign in to Windows', 'pending_uploads': 0}
    m.reconnect(now=15)
    assert len(sessions.started) == 1 and m.retries[row['id']][1] == 15  # waiting is not a failure: no backoff
    sessions.signed_in = True
    m.reconnect(now=30)
    assert len(sessions.started) == 2 and m.list('alice')[0]['status']['state'] == 'mounted'
    assert m.list('alice')[0]['target'] == 'Z:'


def test_the_watcher_stops_with_the_service(tmp_path, monkeypatch):
    m, _ = reconnecting(tmp_path, monkeypatch, interval=0.01)
    m.start()
    assert m.watcher.is_alive()
    watcher = m.watcher
    m.shutdown(wait_uploads=0)
    assert not watcher.is_alive() and m.watcher is None


class SavedHosts:
    def __init__(self):
        self.added = []

    def add_host(self, principal, host, credentials):
        self.added.append((principal, host, credentials))
        return 'login-9'

    def get(self, principal, reference):
        return {'kind': 'host'}

    def resolve_host(self, principal, reference, host):
        return {'username': 'u', 'password': 'p'}

    def resolve(self, principal, reference):
        return {}

    def hosts(self, principal):
        return []


def test_http_keeps_a_typed_login_so_the_mount_can_reconnect(tmp_path, monkeypatch):
    from remote_fs_browser import sessions as sessions_module
    monkeypatch.setattr(mounts, 'prerequisites', lambda *a: {'method': 'fuse', 'available': True, 'missing': [], 'rclone': '1.75'})

    class SMBSession:
        id, closed, policy = 'smb-1', False, Policy(operations=READ_OPERATIONS + WRITE_OPERATIONS)
        _descriptor = {'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects'}

        def descriptor(self, path='/'):
            return {**self._descriptor, 'path': path}

        async def close(self):
            pass

    async def connect(self, descriptor, credentials=None, *, endpoint_config=None):
        self.sessions['smb-1'] = SMBSession()
        return self.sessions['smb-1']
    monkeypatch.setattr(sessions_module.Browser, 'connect', connect)
    fake, store = FakeManager(), SavedHosts()
    policy = Policy(network_ranges=['192.0.2.0/24'], operations=READ_OPERATIONS + WRITE_OPERATIONS + HOST_OPERATIONS)
    login = {'username': 'u', 'password': 'p'}
    with TestClient(create_app(policy, token=TOKEN, mount_manager=fake, saved_locations=store), raise_server_exceptions=False) as client:
        sid = client.post('/api/sessions', headers=HEADERS, json={'descriptor': {'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects'}}).json()['id']
        client.post('/api/mounts', headers=HEADERS, json={'session': sid, 'credentials': login})
        client.post('/api/mounts', headers=HEADERS, json={'session': sid, 'credentials': login, 'auto': False})
    assert [c['auto'] for c in fake.calls] == [True, False]
    assert fake.calls[0]['descriptor']['credential_id'] == 'login-9' and store.added == [('token-user', '192.0.2.5', login)]
    assert 'credential_id' not in fake.calls[1]['descriptor']


@pytest.mark.parametrize('detail,expected', [
    ('nfs_mount_async failed. NFS4ERR_PERM', 'insecure'),
    ('mount/mnt call failed with "RPC error: Server rejected the call: AUTH_ERROR (AUTH_TOOWEAK)"', 'refused this computer'),
    ('mount_cb: NFS4ERR_NOENT', 'no export named /tank/data'),
    ('Failed to connect: Connection refused', 'Nothing on nas is accepting'),
    ('timed out', 'did not answer'),
    ('', 'Could not connect to /tank/data on nas'),
])
def test_nfs_connection_errors_say_what_to_fix(detail, expected):
    from remote_fs_browser.nfs import connect_error
    error = connect_error('nas', '/tank/data', detail)
    assert isinstance(error, ValueError) and error.shown and expected in str(error)
    assert (detail in str(error)) if detail else not str(error).endswith(')')


class FakeWindowsShares:
    """mpr + netapi32 stand-ins: one IPC$ connection, then NetShareEnum's SHARE_INFO_1 array."""

    def __init__(self, add_result=0, shares=(('review', 0, 'Review'), ('IPC$', 3, 'IPC'), ('media', 0, None))):
        import ctypes
        from ctypes import wintypes
        self.add_result, self.calls, self.freed = add_result, [], 0

        class Row(ctypes.Structure):
            _fields_ = [('shi1_netname', wintypes.LPWSTR), ('shi1_type', wintypes.DWORD), ('shi1_remark', wintypes.LPWSTR)]
        self.array = (Row * len(shares))(*[Row(*share) for share in shares])

    def WNetAddConnection2W(self, resource, password, user, flags):
        self.calls.append(('add', resource._obj.lpRemoteName, user, password))
        return self.add_result

    def WNetCancelConnection2W(self, remote, flags, force):
        self.calls.append(('cancel', remote))
        return 0

    def NetShareEnum(self, server, level, buffer, maximum, read, total, resume):
        import ctypes
        self.calls.append(('enum', server, level))
        buffer._obj.value = ctypes.addressof(self.array)
        read._obj.value = total._obj.value = len(self.array)
        return 0

    def NetApiBufferFree(self, buffer):
        self.freed += 1


def test_windows_lists_disk_shares_with_its_own_api_and_closes_the_connection():
    from remote_fs_browser.discovery import windows_smb_shares
    fake = FakeWindowsShares()
    result = windows_smb_shares('192.0.2.5', {'username': 'morgs', 'password': 'pw'}, api=(fake, fake))
    assert result == {'shares': [{'name': 'review', 'description': 'Review'}, {'name': 'media', 'description': ''}], 'truncated': False}
    assert fake.calls == [('add', '\\\\192.0.2.5\\IPC$', '192.0.2.5\\morgs', 'pw'), ('enum', '\\\\192.0.2.5', 1),
                          ('cancel', '\\\\192.0.2.5\\IPC$')]
    assert fake.freed == 1


def test_windows_share_listing_explains_a_bad_login():
    from remote_fs_browser.discovery import DiscoveryError, windows_smb_shares
    fake = FakeWindowsShares(add_result=1326)
    with pytest.raises(DiscoveryError, match='Incorrect username or password') as caught:
        windows_smb_shares('nas', {'username': 'morgs', 'password': 'wrong'}, api=(fake, fake))
    assert caught.value.shown and [c[0] for c in fake.calls] == ['add']
    with pytest.raises(DiscoveryError, match='Windows error 999'):
        windows_smb_shares('nas', {'username': 'morgs', 'password': 'x'}, api=(FakeWindowsShares(add_result=999),) * 2)

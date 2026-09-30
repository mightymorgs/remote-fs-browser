import base64
import http.client
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from remote_fs_browser import mounts
from remote_fs_browser.backends import LocalFilesystem
from remote_fs_browser.davbridge import USER, Server
from remote_fs_browser.mounts import MountManager, remote_for


class LocalBridgeFilesystem(LocalFilesystem):
    """A local folder standing in for an NFS export; `move` mirrors NFSFilesystem.move."""

    def move(self, source, destination, overwrite=False):
        if overwrite:
            self.remove(destination)
        return self.rename(source, destination)


class LocalBridge:
    """Same interface as davbridge.Bridge, serving a local folder in this process."""

    def __init__(self, folder, root='/'):
        self.fs = LocalBridgeFilesystem({'root': str(folder)})
        self.password = 'bridge-password'
        self.server = Server(self.fs, root, self.password)
        self.url = self.server.url
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.stopped = False

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.fs.close()
        self.stopped = True


@pytest.fixture
def bridge(tmp_path):
    folder = tmp_path / 'export'
    (folder / 'Jobs' / 'old').mkdir(parents=True)
    (folder / 'Jobs' / 'plan.txt').write_bytes(b'0123456789')
    (folder / 'Jobs' / '.remotefs-abc.part').write_bytes(b'staged')
    (folder / 'outside.txt').write_text('not shared')
    running = LocalBridge(folder, '/Jobs')
    yield running, folder
    if not running.stopped:
        running.stop()


def call(bridge, method, path, body=None, password=None, **headers):
    connection = http.client.HTTPConnection('127.0.0.1', bridge.server.server_address[1], timeout=10)
    token = base64.b64encode(f'{USER}:{password or bridge.password}'.encode()).decode()
    connection.request(method, path, body=body, headers={'Authorization': 'Basic ' + token, **headers})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def test_requests_need_the_bridge_password(bridge):
    running, _ = bridge
    response, _ = call(running, 'PROPFIND', '/', password='wrong', Depth='0')
    assert response.status == 401


def test_listing_is_scoped_to_the_mounted_folder_and_hides_staged_uploads(bridge):
    running, _ = bridge
    response, data = call(running, 'PROPFIND', '/', Depth='1')
    assert response.status == 207
    text = data.decode()
    assert '<d:href>/</d:href>' in text and '<d:href>/plan.txt</d:href>' in text and '<d:href>/old/</d:href>' in text
    assert '<d:getcontentlength>10</d:getcontentlength>' in text and 'getlastmodified' in text
    assert '.remotefs-' not in text and 'outside' not in text
    assert call(running, 'PROPFIND', '/missing', Depth='0')[0].status == 404
    assert call(running, 'GET', '/../outside.txt')[0].status == 403


def test_reads_support_ranges(bridge):
    running, _ = bridge
    response, data = call(running, 'GET', '/plan.txt')
    assert response.status == 200 and data == b'0123456789'
    response, data = call(running, 'GET', '/plan.txt', Range='bytes=2-5')
    assert response.status == 206 and data == b'2345' and response.getheader('Content-Range') == 'bytes 2-5/10'
    assert call(running, 'GET', '/plan.txt', Range='bytes=-3')[1] == b'789'
    assert call(running, 'GET', '/plan.txt', Range='bytes=20-')[0].status == 416
    response, data = call(running, 'HEAD', '/plan.txt')
    assert response.status == 200 and data == b'' and response.getheader('Content-Length') == '10'


def test_writes_folders_moves_and_deletes(bridge):
    running, folder = bridge
    jobs = folder / 'Jobs'
    assert call(running, 'PUT', '/new.bin', body=b'x' * 3_000_000)[0].status == 201
    assert (jobs / 'new.bin').stat().st_size == 3_000_000
    assert call(running, 'PUT', '/plan.txt', body=b'replaced')[0].status == 204
    assert (jobs / 'plan.txt').read_bytes() == b'replaced'
    assert call(running, 'MKCOL', '/Drafts')[0].status == 201 and (jobs / 'Drafts').is_dir()
    assert call(running, 'MKCOL', '/Drafts')[0].status == 405
    base = f'http://127.0.0.1:{running.server.server_address[1]}'
    assert call(running, 'MOVE', '/new.bin', Destination=base + '/Drafts/moved.bin')[0].status == 201
    assert (jobs / 'Drafts' / 'moved.bin').exists() and not (jobs / 'new.bin').exists()
    assert call(running, 'MOVE', '/Drafts', Destination=base + '/Final')[0].status == 201
    assert (jobs / 'Final' / 'moved.bin').exists()
    assert call(running, 'MOVE', '/plan.txt', Destination=base + '/Final', Overwrite='T')[0].status == 412
    assert call(running, 'DELETE', '/Final')[0].status == 409  # not empty
    assert call(running, 'DELETE', '/Final/moved.bin')[0].status == 204
    assert call(running, 'DELETE', '/Final')[0].status == 204 and not (jobs / 'Final').exists()
    assert call(running, 'DELETE', '/')[0].status == 403


def test_chunked_uploads_are_accepted(bridge):
    running, folder = bridge
    body = (b'5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n')
    response, _ = call(running, 'PUT', '/chunked.txt', body=body, **{'Transfer-Encoding': 'chunked'})
    assert response.status == 201 and (folder / 'Jobs' / 'chunked.txt').read_bytes() == b'hello world'


def test_nfs_remote_points_rclone_at_the_bridge(monkeypatch):
    monkeypatch.setattr(mounts, 'obscure', lambda binary, secret: 'obscured:' + secret)
    fake = type('B', (), {'url': 'http://127.0.0.1:4000/', 'password': 'pw'})()
    section, path = remote_for({'type': 'nfs', 'host': '192.0.2.9', 'export': '/srv', 'path': '/media'}, None, None, 'rclone', fake)
    assert section == {'type': 'webdav', 'url': 'http://127.0.0.1:4000/', 'vendor': 'other', 'user': 'remotefs',
                       'pass': 'obscured:pw'}
    assert path == ''


class FakeProcess:
    pid = 4242

    def __init__(self):
        self.code = None

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.code = 0
        return 0


def test_nfs_mount_owns_its_bridge_and_stops_it_on_eject(tmp_path, monkeypatch):
    monkeypatch.setattr(mounts, 'prerequisites', lambda *a: {'available': True, 'missing': []})
    monkeypatch.setattr(mounts, 'obscure', lambda binary, secret: 'obscured')
    started = []

    class FakeBridge:
        url, password = 'http://127.0.0.1:4000/', 'pw'

        def __init__(self, descriptor):
            self.descriptor, self.stopped = descriptor, False
            started.append(self)

        def stop(self):
            self.stopped = True

    m = MountManager(tmp_path / 'state', base=tmp_path / 'mnt', binary='rclone', system='linux',
                     popen=lambda argv, **kw: FakeProcess(), bridge=FakeBridge)
    monkeypatch.setattr(m, 'mounted', lambda target: True)
    monkeypatch.setattr(m, 'rc', lambda row, command, **kw: m.processes[next(iter(m.processes))].__setattr__('code', 0) or {}
                        if command == 'core/quit' else {'diskCache': {}})
    row = m.mount('alice', {'type': 'nfs', 'host': '192.0.2.9', 'export': '/srv', 'version': 4, 'path': '/media'},
                  None, None, 'Media', read_only=False)
    assert started[0].descriptor['path'] == '/media' and not started[0].stopped
    assert row['read_only'] is False
    m.unmount('alice', row['id'])
    assert started[0].stopped

    # A mount that fails after the bridge started does not leave the bridge running.
    m.popen = lambda argv, **kw: (_ for _ in ()).throw(OSError('no rclone'))
    with pytest.raises(mounts.MountError):
        m.mount('alice', {'type': 'nfs', 'host': '192.0.2.9', 'export': '/srv', 'version': 4, 'path': '/'},
                None, None, 'Media', read_only=False)
    assert started[1].stopped and m.list('alice') == []


def rclone():
    return os.environ.get('REMOTEFS_RCLONE') or shutil.which('rclone')


@pytest.mark.skipif(not rclone(), reason='needs rclone')
def test_rclone_webdav_backend_round_trip(bridge, tmp_path):
    running, folder = bridge
    obscured = subprocess.run([rclone(), 'obscure', running.password], capture_output=True, text=True, check=True).stdout.strip()
    conf = tmp_path / 'rclone.conf'
    conf.write_text(f'[bridge]\ntype = webdav\nurl = {running.url}\nvendor = other\nuser = {USER}\npass = {obscured}\n')

    def run(*args):
        return subprocess.run([rclone(), '--config', str(conf), *args], capture_output=True, text=True, timeout=60, check=True).stdout

    rows = {row['Name']: row for row in json.loads(run('lsjson', 'bridge:'))}
    assert set(rows) == {'plan.txt', 'old'} and rows['plan.txt']['Size'] == 10 and rows['old']['IsDir']
    assert run('cat', 'bridge:plan.txt', '--offset', '3', '--count', '4') == '3456'
    local = tmp_path / 'big.bin'
    local.write_bytes(os.urandom(5_000_000))
    run('copyto', str(local), 'bridge:in/big.bin')
    assert (folder / 'Jobs' / 'in' / 'big.bin').read_bytes() == local.read_bytes()
    run('moveto', 'bridge:in/big.bin', 'bridge:old/big.bin')
    assert (folder / 'Jobs' / 'old' / 'big.bin').exists()
    run('deletefile', 'bridge:old/big.bin')
    run('rmdir', 'bridge:in')
    assert sorted(p.name for p in (folder / 'Jobs').iterdir()) == ['.remotefs-abc.part', 'old', 'plan.txt']


@pytest.mark.skipif(not (os.environ.get('REMOTEFS_TEST_FUSE') and rclone() and Path('/dev/fuse').exists()),
                    reason='set REMOTEFS_TEST_FUSE=1 on a host with rclone and FUSE to run a real mount')
def test_real_fuse_mount_through_the_bridge(tmp_path):
    folder = tmp_path / 'export'
    folder.mkdir()
    (folder / 'hello.txt').write_text('hello')
    bridges = []
    m = MountManager(tmp_path / 'state', base=tmp_path / 'mnt', binary=rclone(),
                     bridge=lambda descriptor: bridges.append(LocalBridge(folder, descriptor['path'])) or bridges[-1])
    row = m.mount('alice', {'type': 'nfs', 'host': '127.0.0.1', 'export': '/export', 'version': 4, 'path': '/'},
                  None, None, 'NFS', read_only=False)
    try:
        target = Path(row['target'])
        assert (target / 'hello.txt').read_text() == 'hello'
        (target / 'sub').mkdir()
        (target / 'sub' / 'new.txt').write_text('written through the mount')
        (target / 'hello.txt').rename(target / 'sub' / 'hello.txt')
    finally:
        m.unmount('alice', row['id'])
    assert (folder / 'sub' / 'new.txt').read_text() == 'written through the mount'
    assert (folder / 'sub' / 'hello.txt').read_text() == 'hello'
    assert bridges[0].stopped and not target.exists()

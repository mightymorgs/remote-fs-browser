"""CLI integration against a real HTTP server and filesystem worker."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from remote_fs_browser.auth import make_account
from remote_fs_browser.client_cli import execute, parser
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS


@pytest.fixture
def server(tmp_path):
    root = tmp_path / 'files'
    root.mkdir()
    (root / 'hello.txt').write_text('hello from HTTP\n')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'account': make_account('tester', 'temporary-test-password'),
        'storage_key': 'temporary-test-vault-key', 'policy': {'local_roots': [str(root)],
        'network_ranges': ['127.0.0.1/32'], 'operations': READ_OPERATIONS + WRITE_OPERATIONS},
        'port': port}))
    # Windows pipes can fill on a single Uvicorn error traceback. Keep logs in a
    # file so expected HTTP failures cannot deadlock the server under test.
    log = (tmp_path / 'server.log').open('w+')
    proc = subprocess.Popen([sys.executable, '-m', 'remote_fs_browser', 'serve', '--config', str(config)],
                            stdout=subprocess.DEVNULL, stderr=log)
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if proc.poll() is not None:
                log.seek(0)
                pytest.fail(log.read())
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        else:
            pytest.fail('Server failed to start')
        def run(*args, stdin=None, ok=True):
            result = subprocess.run([sys.executable, '-m', 'remote_fs_browser', *args,
                '--url', url, '--auth-file', str(tmp_path / 'client.json')],
                input=stdin, capture_output=True, text=True, timeout=20)
            if ok:
                assert result.returncode == 0, result.stderr
                return json.loads(result.stdout) if result.stdout else None
            assert result.returncode != 0
            return result
        run('login', '--username', 'tester', '--password-stdin', stdin='temporary-test-password\n')
        yield run, root, tmp_path
    finally:
        proc.terminate()
        proc.communicate(timeout=10)
        log.close()


def test_file_manager_round_trip(server):
    run, root, tmp = server
    auth = tmp / 'client.json'
    assert 'temporary-test-password' not in auth.read_text()
    if os.name != 'nt':
        assert auth.stat().st_mode & 0o777 == 0o600
    assert run('discover')['roots'][0]['root'] == str(root)
    sid = run('connect', '--type', 'local', '--root', str(root))['id']
    assert run('ls', sid)['entries'][0]['name'] == 'hello.txt'
    run('mkdir', sid, '/nested')
    assert run('select', sid, '/nested')['path'] == '/nested'
    source = tmp / 'upload.txt'
    source.write_text('uploaded content')
    run('put', sid, '/nested/a.txt', str(source))
    assert run('stat', sid, '/nested/a.txt')['size'] == 16
    run('rename', sid, '/nested/a.txt', '/nested/b.txt')
    run('copy', sid, '/nested/b.txt', '/nested/c.txt')
    dest = tmp / 'download.txt'
    run('get', sid, '/nested/c.txt', str(dest))
    assert dest.read_text() == 'uploaded content'
    run('get', sid, '/hello.txt', str(dest), ok=False)
    assert dest.read_text() == 'uploaded content'
    run('get', sid, '/missing', str(dest), '--overwrite', ok=False)
    assert dest.read_text() == 'uploaded content'
    run('remove', sid, '/nested', '--recursive')
    assert not (root / 'nested').exists()
    run('disconnect', sid)
    run('ls', sid, ok=False)


def test_saved_locations_and_auth(server):
    run, root, tmp = server
    row = run('saved', 'add', '--type', 'local', '--root', str(root), '--label', 'Test root')
    rows = run('saved', 'list')['locations']
    assert rows[0]['label'] == 'Test root'
    sid = run('connect', '--saved-id', row['id'])['id']
    assert run('ls', sid)['entries']
    run('saved', 'remove', '--id', row['id'])
    assert run('saved', 'list')['locations'] == []
    assert run('credentials', 'list')['credentials'] == []
    cred = run('credentials', 'add', '--host', '127.0.0.1', '--username', 'nas-user',
               '--password-stdin', stdin='private-nas-password\n')
    listed = run('credentials', 'list')['credentials']
    assert listed[0]['id'] == cred['id']
    assert 'private-nas-password' not in json.dumps(listed)
    assert 'private-nas-password' not in (tmp / 'saved.json').read_text()
    run('credentials', 'remove', '--id', cred['id'])
    assert run('downloads', 'list')['jobs'] == []
    run('logout')
    assert json.loads((tmp / 'client.json').read_text()) == {}
    result = run('discover', ok=False)
    assert '401' in result.stderr
    assert 'Traceback' not in result.stderr


def test_scan_pagination_and_multiple_ranges(capsys):
    class Fake:
        calls = []
        def request(self, method, route, data=None):
            self.calls.append(data)
            return {'next_offset': 256 if data['offset'] == 0 else None, 'hosts': []}
    client = Fake()
    execute(parser().parse_args(['scan', '--ranges', '10.10.0.0/23,192.168.2.8', '--ranges', '172.16.0.0/24', '--all']), client)
    assert client.calls == [
        {'ranges': ['10.10.0.0/23', '192.168.2.8/32', '172.16.0.0/24'], 'offset': 0},
        {'ranges': ['10.10.0.0/23', '192.168.2.8/32', '172.16.0.0/24'], 'offset': 256}]
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_default_scan_uses_server_networks():
    class Fake:
        def request(self, method, route, data=None):
            if method == 'GET':
                return {'scan_ranges': ['10.20.0.0/24']}
            assert data == {'ranges': ['10.20.0.0/24'], 'offset': 0}
            return {'hosts': []}
    assert execute(parser().parse_args(['scan']), Fake()) == {'hosts': []}


def test_archive_download_round_trip(server):
    import zipfile
    run, root, tmp = server
    sid = run('connect', '--type', 'local', '--root', str(root))['id']
    assert run('downloads', 'estimate', '--session', sid, '--paths', '/hello.txt')['entries'] == 1
    job = run('downloads', 'create', '--session', sid, '--paths', '/hello.txt', '--store', 'Downloads')
    for _ in range(20):
        current = run('downloads', 'list')['jobs'][0]
        if current['stage'] != 'packing':
            break
        time.sleep(.05)
    assert current['stage'] == 'ready'
    target = tmp / 'archive.zip'
    run('downloads', 'part', '--id', job['id'], '--index', '0', '--file', str(target))
    with zipfile.ZipFile(target) as archive:
        assert archive.read('hello.txt') == (root / 'hello.txt').read_bytes()
    run('downloads', 'purge', '--id', job['id'])
    run('downloads', 'forget', '--id', job['id'])
    assert run('downloads', 'list')['jobs'] == []
    run('disconnect', sid)


def test_client_rejects_credential_bearing_urls(tmp_path):
    from remote_fs_browser.client_cli import Client
    with pytest.raises(ValueError, match='without credentials'):
        Client('http://name:password@localhost:8080', tmp_path / 'auth.json', 1)


def test_network_and_root_policy_cannot_be_bypassed(server):
    run, root, tmp = server
    # Worker connection failures are wrapped and surfaced as HTTP 422.
    assert '422' in run('connect', '--type', 'local', '--root', str(tmp), ok=False).stderr
    assert '422' in run('scan', '--ranges', '192.0.2.0/24', ok=False).stderr


def test_truncated_download_preserves_existing_file(tmp_path):
    import io
    from remote_fs_browser.client_cli import Client, download
    client = Client('http://127.0.0.1:8080', tmp_path / 'auth.json', 1)
    class Response(io.BytesIO):
        headers = {'Content-Length': '100'}
    class Opener:
        def open(self, *args, **kwargs):
            return Response(b'partial')
    client.opener = Opener()
    target = tmp_path / 'existing'
    target.write_text('keep me')
    with pytest.raises(ValueError, match='Incomplete download'):
        download(client, 'sessions/example/file', str(target), True)
    assert target.read_text() == 'keep me'
    assert not list(tmp_path.glob('.remotefs-*'))


def test_javascript_client_against_live_api(server):
    import shutil
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the JavaScript API integration check')
    run, root, tmp = server
    script = tmp / 'client-check.mjs'
    module = (Path(__file__).resolve().parents[1] / 'frontend/browser.js').as_uri()
    script.write_text('''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => true };
const { RemoteFsClient } = await import(process.argv[2]);
const [url, cookie] = Object.entries(JSON.parse(readFileSync(process.argv[3], 'utf8')))[0];
const c = new RemoteFsClient(url + '/api', () => ({ Cookie: 'remote_fs_session=' + cookie, Origin: url }));
const sid = (await c.connect({ type: 'local', root: process.argv[4] })).id;
try {
  await c.mkdir(sid, '/js-folder');
  await c.copy(sid, '/hello.txt', '/js-folder/copy.txt');
  await c.rename(sid, '/js-folder/copy.txt', '/js-folder/renamed.txt');
  assert.equal(await (await c.file(sid, '/js-folder/renamed.txt')).text(), readFileSync(join(process.argv[4], 'hello.txt'), 'utf8'));
  const credential = await c.saveHostCredentials('127.0.0.1', { username: 'test', password: 'not-a-real-password' });
  assert.equal((await c.hostCredentials()).credentials[0].id, credential.id);
  await c.forgetHostCredentials(credential.id);
  assert.equal((await c.estimateDownload(sid, ['/js-folder'])).entries, 2);
  const job = await c.createDownload(sid, ['/js-folder'], 'Downloads');
  let current;
  for (let i = 0; i < 100; i++) {
    current = (await c.downloads()).jobs.find(row => row.id === job.id);
    if (current.stage !== 'packing') break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.equal(current.stage, 'ready');
  const part = await c.downloadPart(job.id, 0, 'bytes=0-1');
  assert.equal(part.status, 206);
  assert.equal(await part.text(), 'PK');
  await c.purgeDownload(job.id);
  await c.controlDownload(job.id, 'forget');
  assert.equal((await c.downloads()).jobs.length, 0);
  await c.remove(sid, '/js-folder', true);
} finally { await c.close(sid); }
''')
    result = subprocess.run(['node', str(script), module, str(tmp / 'client.json'), str(root)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not (root / 'js-folder').exists()


@pytest.mark.parametrize('reference', ['-h0Nh5D6vO_VXw-A', '--' + 'a' * 14])
def test_dash_prefixed_opaque_references_are_not_options(reference):
    assert parser().parse_args(['connect', '--saved-id', reference]).saved_id == reference
    assert parser().parse_args(['shares', 'nas', '--credential-id', reference]).credential_id == reference
    assert parser().parse_args(['saved', 'remove', '--id', reference]).id == reference


def test_dash_prefixed_session_and_real_options():
    sid = '-' + 'a' * 42
    args = parser().parse_args(['ls', sid, '/', '--timeout', '5'])
    assert args.session == sid and args.timeout == 5
    assert parser().parse_args(['login', '--username', 'user', '--password-stdin']).password_stdin
    with pytest.raises(SystemExit):
        parser().parse_args(['ls', 'sid', '--unknown-option'])

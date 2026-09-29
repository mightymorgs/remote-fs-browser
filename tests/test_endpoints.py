import asyncio
import json
import shutil
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Browser, Policy
from remote_fs_browser.http import create_app
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS
from remote_fs_browser.sessions import clean_descriptor
from remote_fs_browser.endpoints import LibvirtFilesystem


def endpoint_policy(tmp_path, read_only=True):
    root = tmp_path / 'data'
    root.mkdir(exist_ok=True)
    (root / 'hello.txt').write_text('hello cloud')
    config = tmp_path / 'rclone.conf'
    config.write_text(f'[fixture]\ntype = alias\nremote = {root}\n')
    return Policy(endpoints={'cloud': {'type': 'rclone', 'remote': 'fixture', 'root': '/',
                                      'config': str(config), 'read_only': read_only}},
                  operations=READ_OPERATIONS + WRITE_OPERATIONS, operation_timeout=20)


def test_descriptors_cannot_supply_provider_configuration():
    for kind in ('rclone', 'libvirt'):
        assert clean_descriptor({'type': kind, 'endpoint': 'safe', 'config': '/etc/private',
                                 'uri': 'qemu+ssh://attacker/system', 'password': 'secret'}) == {'type': kind, 'endpoint': 'safe'}
        with pytest.raises(ValueError):
            clean_descriptor({'type': kind, 'endpoint': ':local,/etc'})


@pytest.mark.parametrize('config', [
    {'type': 'rclone', 'remote': ':local', 'config': '/tmp/test'},
    {'type': 'rclone', 'remote': 's3', 'config': 'relative'},
    {'type': 'rclone', 'remote': 's3', 'config': '/tmp/test', 'root': '../escape'},
    {'type': 'libvirt', 'uri': 'test:///default', 'pools': ['../escape']},
    {'type': 'libvirt', 'uri': 'test:///default', 'pools': []},
])
def test_invalid_endpoint_policy(config):
    with pytest.raises(ValueError):
        Policy(endpoints={'safe': config})


@pytest.mark.skipif(not shutil.which('rclone'), reason='rclone is optional')
@pytest.mark.asyncio
async def test_real_rclone_read_write_ranges_copy_and_cleanup(tmp_path):
    policy = endpoint_policy(tmp_path, read_only=False)
    policy.local_roots = [str(tmp_path)]
    async with Browser(policy) as browser:
        cloud = await browser.connect({'type': 'rclone', 'endpoint': 'cloud'})
        local = await browser.connect({'type': 'local', 'root': str(tmp_path)})
        assert (await cloud.list())['entries'][0]['name'] == 'hello.txt'
        assert b''.join([c async for c in cloud.stream('/hello.txt', 2, 5)]) == b'llo c'
        async def chunks():
            yield b'uploaded content'
        await cloud.mkdir('/new')
        await cloud.write('/new/file.txt', chunks())
        with pytest.raises(FileExistsError):
            await cloud.write('/new/file.txt', chunks())
        await cloud.copy('/new/file.txt', '/copied.txt', target=local)
        assert (tmp_path / 'copied.txt').read_bytes() == b'uploaded content'
        await cloud.remove('/new', recursive=True)
        assert not (tmp_path / 'data/new').exists()
        with pytest.raises(PermissionError):
            await cloud.rename('/hello.txt', '/renamed.txt')
        with pytest.raises(ValueError):
            await cloud.list('/../escape')
        scratch = cloud.worker.scratch.name
    from pathlib import Path
    assert not Path(scratch).exists()


@pytest.mark.skipif(not shutil.which('rclone'), reason='rclone is optional')
def test_endpoint_api_hides_secrets_and_enforces_read_only(tmp_path):
    policy = endpoint_policy(tmp_path)
    app = create_app(policy, token='endpoint-test-token-at-least-32-chars')
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers['Authorization'] = 'Bearer endpoint-test-token-at-least-32-chars'
        discovery = client.get('/api/discover').json()
        assert discovery['endpoints'] == [{'type': 'rclone', 'endpoint': 'cloud', 'label': 'cloud'}]
        response = client.post('/api/sessions', json={'descriptor': {'type': 'rclone', 'endpoint': 'cloud'}})
        assert response.status_code == 200, response.text
        session = response.json()
        assert 'write' not in session['operations']
        assert 'config' not in json.dumps(session)
        assert client.put(f"/api/sessions/{session['id']}/file?path=/bad", content=b'bad').status_code == 403
        assert client.post('/api/sessions', json={'descriptor': {'type': 'rclone', 'endpoint': 'missing'}}).status_code == 403
        response = client.get(f"/api/sessions/{session['id']}/file?path=/hello.txt", headers={'Range': 'bytes=1-3'})
        assert response.status_code == 206 and response.content == b'ell'


def test_libvirt_pool_allowlist_and_volume_metadata(monkeypatch):
    class Pool:
        def info(self): return (2, 100, 30, 70)
        def listVolumes(self): return ['disk.qcow2']
        def storageVolLookupByName(self, name):
            assert name == 'disk.qcow2'
            return SimpleNamespace(info=lambda: (0, 50, 20))
    opened = []
    connection = SimpleNamespace(storagePoolLookupByName=lambda name: Pool(), close=lambda: opened.append('closed'))
    monkeypatch.setitem(sys.modules, 'libvirt', SimpleNamespace(openReadOnly=lambda uri: opened.append(uri) or connection))
    fs = LibvirtFilesystem({'uri': 'test:///default', 'pools': ['allowed']})
    assert fs.list('/', 10)['entries'][0]['available'] == 70
    assert fs.list('/allowed', 10)['entries'][0]['type'] == 'other'
    assert fs.stat('/allowed/disk.qcow2')['allocation'] == 20
    with pytest.raises(PermissionError): fs.list('/private', 10)
    with pytest.raises(FileNotFoundError): fs.stat('/allowed/disk.qcow2/etc')
    fs.close()
    assert opened == ['test:///default', 'closed']


@pytest.mark.asyncio
async def test_real_libvirt_test_driver():
    pytest.importorskip('libvirt')
    policy = Policy(endpoints={'hv': {'type': 'libvirt', 'uri': 'test:///default', 'pools': ['default-pool']}},
                    operations=READ_OPERATIONS + WRITE_OPERATIONS)
    async with Browser(policy) as browser:
        fs = await browser.connect({'type': 'libvirt', 'endpoint': 'hv'})
        rows = (await fs.list('/'))['entries']
        assert rows[0]['name'] == 'default-pool'
        assert rows[0]['capacity'] > 0
        assert set(fs.policy.operations) == {'discover', 'list', 'stat'}
        with pytest.raises(PermissionError):
            await fs.mkdir('/bad')
        with pytest.raises(PermissionError):
            await anext(fs.stream('/default-pool/disk'))


@pytest.mark.skipif(not shutil.which('rclone'), reason='rclone is optional')
@pytest.mark.asyncio
async def test_rclone_multichunk_download_and_explicit_overwrite(tmp_path):
    policy = endpoint_policy(tmp_path, read_only=False)
    content = bytes(range(256)) * 17000
    (tmp_path / 'data/large.bin').write_bytes(content)
    async with Browser(policy) as browser:
        fs = await browser.connect({'type': 'rclone', 'endpoint': 'cloud'})
        assert b''.join([c async for c in fs.stream('/large.bin', 99)]) == content[99:]
        async def chunks(): yield b'replacement'
        await fs.write('/hello.txt', chunks(), overwrite=True)
        assert (tmp_path / 'data/hello.txt').read_bytes() == b'replacement'
        await fs.write('/new.txt', chunks(), overwrite=True)
        assert (tmp_path / 'data/new.txt').read_bytes() == b'replacement'
        await fs.mkdir('/folder')
        with pytest.raises(OSError):
            await fs.write('/folder', chunks(), overwrite=True)


def test_endpoint_cli_descriptors_and_saved_locations(tmp_path):
    from remote_fs_browser.client_cli import parser, location
    from remote_fs_browser.store import SavedLocations
    store = SavedLocations(tmp_path/'saved.json', 'fixture-only-private-storage-key')
    for kind in ('rclone', 'libvirt'):
        args = parser().parse_args(['connect', '--type', kind, '--endpoint', 'approved', '--path', '/folder'])
        descriptor = location(args, None)
        assert descriptor == {'type': kind, 'endpoint': 'approved', 'path': '/folder'}
        store.add('owner', descriptor)
    records = store.list('owner')
    assert len(records) == 2
    assert all(record['label'] == 'approved' and not record['has_credentials'] for record in records)
    assert not store.list('someone-else')

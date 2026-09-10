import asyncio
import os
import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Browser, Policy
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS
from remote_fs_browser.http import create_app
from remote_fs_browser.backends import LocalFilesystem

ALL = READ_OPERATIONS + WRITE_OPERATIONS
TOKEN = 'mutation-test-token-' * 3

async def chunks(*values):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_write_copy_move_delete_and_conflicts(tmp_path):
    policy = Policy(local_roots=[str(tmp_path)], operations=ALL)
    async with Browser(policy) as browser:
        session = await browser.connect({'type': 'local', 'root': str(tmp_path)})
        await session.mkdir('/folder')
        await session.write('/folder/file', chunks(b'abc', b'\x00' * 300000))
        with pytest.raises(FileExistsError):
            await session.write('/folder/file', chunks(b'wrong'))
        assert (tmp_path / 'folder/file').read_bytes() == b'abc' + b'\x00' * 300000
        await session.write('/folder/file', chunks(b'edited'), overwrite=True)
        await session.copy('/folder', '/copy')
        assert (tmp_path / 'copy/file').read_bytes() == b'edited'
        await session.rename('/copy', '/moved')
        with pytest.raises(FileExistsError):
            await session.rename('/moved/file', '/folder/file')
        with pytest.raises(ValueError):
            await session.copy('/folder', '/folder/nested')
        await session.remove('/moved', recursive=True)
        assert not (tmp_path / 'moved').exists()
        with pytest.raises(PermissionError):
            await session.remove('/', recursive=True)
    assert not list(tmp_path.rglob('*.part'))


@pytest.mark.asyncio
async def test_failed_upload_preserves_original_and_cleans_stage(tmp_path):
    (tmp_path / 'file').write_bytes(b'original')
    async with Browser(Policy(local_roots=[str(tmp_path)], operations=ALL, max_write_bytes=4)) as browser:
        session = await browser.connect({'type': 'local', 'root': str(tmp_path)})
        with pytest.raises(ValueError):
            await session.write('/file', chunks(b'123', b'45'), overwrite=True)
        async def cancelled():
            yield b'x'
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await session.write('/file', cancelled(), overwrite=True)
        assert (tmp_path / 'file').read_bytes() == b'original'
        assert sorted(p.name for p in tmp_path.iterdir()) == ['file']


@pytest.mark.asyncio
async def test_readonly_policy_denies_every_mutation(tmp_path):
    (tmp_path / 'file').write_text('keep')
    async with Browser(Policy(local_roots=[str(tmp_path)])) as browser:
        session = await browser.connect({'type': 'local', 'root': str(tmp_path)})
        for call in (session.write('/file', chunks(b'bad')), session.mkdir('/new'),
                     session.rename('/file', '/new'), session.remove('/file'), session.copy('/file', '/new')):
            with pytest.raises(PermissionError):
                await call
    assert (tmp_path / 'file').read_text() == 'keep'


def test_local_writes_reject_links_and_no_replace_is_atomic(tmp_path):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    root.mkdir(); outside.mkdir()
    (outside / 'file').write_text('private')
    (root / 'link').symlink_to(outside, target_is_directory=True)
    fs = LocalFilesystem({'root': str(root)})
    try:
        with pytest.raises((OSError, PermissionError)):
            fs.begin_write('/link/file', True)
        writer = fs.begin_write('/file')
        writer.write(b'upload')
        (root / 'file').write_text('concurrent')
        with pytest.raises(FileExistsError):
            writer.commit()
        writer.abort()
        assert (root / 'file').read_text() == 'concurrent'
        assert (outside / 'file').read_text() == 'private'
    finally:
        fs.close()


def test_http_upload_auth_cross_session_copy_and_limits(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    policy = Policy(local_roots=[str(a), str(b)], operations=ALL, max_write_bytes=500000)
    app = create_app(policy, token=TOKEN)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        ids = [client.post('/api/sessions', json={'descriptor': {'type': 'local', 'root': str(root)}}).json()['id'] for root in (a,b)]
        url = f'/api/sessions/{ids[0]}'
        response = client.put(url+'/file', params={'path': '/data'}, content=b'hello' * 50000)
        assert response.status_code == 200, response.text
        assert client.put(url+'/file', params={'path': '/data'}, content=b'bad').status_code == 409
        response = client.post(url+'/copy', json={'source': '/data', 'destination': '/copied', 'target_session': ids[1]})
        assert response.status_code == 200, response.text
        assert (b / 'copied').read_bytes() == b'hello' * 50000
        assert client.put(url+'/file', params={'path': '/huge'}, content=b'x'*500001).status_code == 413
        assert not (a / 'huge').exists()
        assert client.delete(url+'/entry', params={'path':'/data'}).status_code == 200
        assert not (a / 'data').exists()
        assert client.put(url+'/file', params={'path':'/../outside'}, content=b'bad').status_code == 422


def test_recursive_delete_authorizes_every_child_before_removing(tmp_path):
    folder = tmp_path / 'folder'; folder.mkdir()
    (folder / 'keep').write_text('keep')
    (folder / 'other').write_text('other')
    def authorize(principal, operation, descriptor):
        return not (operation == 'delete' and descriptor and descriptor['path'].endswith('/keep'))
    app = create_app(Policy(local_roots=[str(tmp_path)], operations=ALL), token=TOKEN, authorize=authorize)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        sid = client.post('/api/sessions', json={'descriptor': {'type': 'local','root':str(tmp_path)}}).json()['id']
        response = client.delete(f'/api/sessions/{sid}/entry', params={'path':'/folder','recursive':True})
        assert response.status_code == 403, response.text
    assert sorted(p.name for p in folder.iterdir()) == ['keep','other']

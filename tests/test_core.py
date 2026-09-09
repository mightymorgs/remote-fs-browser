import asyncio
import os
from pathlib import Path
import pytest
from remote_fs_browser import Browser, Policy
from remote_fs_browser.policy import normalize
from remote_fs_browser.backends import LocalFilesystem


@pytest.mark.parametrize('path', ['../x', '/a/../b', '/x\\y', '/x\x00y', '/x:stream', './x'])
def test_bad_paths(path):
    with pytest.raises(ValueError): normalize(path)


def test_grouped_discovery_places_hosts_by_protocol(tmp_path):
    from remote_fs_browser.discovery import grouped
    policy = Policy(local_roots=[str(tmp_path)])
    roots = [{'type': 'local', 'root': str(tmp_path / 'Media'), 'kind': 'volume'}]
    hosts = [{'host': '192.0.2.5', 'protocols': ['smb', 'nfs']}, {'host': '192.0.2.9', 'protocols': ['nfs']}]
    groups = grouped(policy, roots, hosts, scanned=True)
    assert groups[0]['items'][0]['label'] == 'Media'
    assert [item['host'] for item in groups[1]['items']] == ['192.0.2.5']
    assert [item['host'] for item in groups[2]['items']] == ['192.0.2.5', '192.0.2.9']
    assert groups[1]['hint'] is None
    assert grouped(policy, roots, [], scanned=False)[1]['hint'].startswith('No networks')


def test_policy_denies_by_default(tmp_path):
    policy = Policy()
    with pytest.raises(PermissionError): policy.local_root(tmp_path)
    with pytest.raises(PermissionError): policy.host('127.0.0.1')


async def test_local_sdk_and_cleanup(tmp_path):
    (tmp_path / 'folder with spaces').mkdir()
    (tmp_path / 'file.bin').write_bytes(b'0123456789')
    async with Browser(Policy(local_roots=[str(tmp_path)])) as browser:
        session = await browser.connect({'type': 'local', 'root': str(tmp_path), 'password': 'never-save'})
        listed = await session.list('/')
        assert len(listed['entries']) == 2 and listed['skipped'] == 0
        assert (await session.stat('/file.bin'))['size'] == 10
        assert b''.join([c async for c in session.stream('/file.bin', 3, 4)]) == b'3456'
        assert 'password' not in session.descriptor()
        await session.close()
        assert not session.worker.process.is_alive()


async def test_idle_cleanup(tmp_path):
    browser = Browser(Policy(local_roots=[str(tmp_path)], idle_seconds=0.1))
    session = await browser.connect({'type': 'local', 'root': str(tmp_path)})
    await asyncio.sleep(0.3)
    await browser.expire()
    assert not browser.sessions
    assert not session.worker.process.is_alive()
    await browser.close()


def test_symlink_escape(tmp_path):
    root = tmp_path / 'root'; root.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'secret').write_text('not readable')
    try:
        (root / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Creating symlinks requires Windows developer mode')
    fs = LocalFilesystem({'root': str(root)})
    try:
        assert fs.list('/', 100)['entries'] == []
        with pytest.raises((OSError, ValueError)):
            fs.open('/link/secret')
    finally:
        fs.close()


async def test_truncation_and_operation_policy(tmp_path):
    for n in range(4): (tmp_path / str(n)).mkdir()
    async with Browser(Policy(local_roots=[str(tmp_path)], max_entries=2, operations=['list'])) as browser:
        async with await browser.connect({'type': 'local', 'root': str(tmp_path)}) as session:
            result = await session.list('/')
            assert result['truncated'] and len(result['entries']) == 2
            with pytest.raises(PermissionError): await session.stat('/')


async def test_stream_chunks_and_early_close(tmp_path):
    from remote_fs_browser.sessions import CHUNK
    (tmp_path / 'large.bin').write_bytes(b'x' * (CHUNK * 3 + 17))
    async with Browser(Policy(local_roots=[str(tmp_path)])) as browser:
        async with await browser.connect({'type':'local','root':str(tmp_path)}) as session:
            chunks = [chunk async for chunk in session.stream('/large.bin')]
            assert sum(map(len,chunks)) == CHUNK*3+17
            assert max(map(len,chunks)) <= CHUNK
            for _ in range(6):
                stream = session.stream('/large.bin')
                assert len(await anext(stream)) == CHUNK
                await stream.aclose()  # Does not exhaust the worker's four-handle limit.


@pytest.mark.skipif(os.name == 'nt', reason='Colons and backslashes cannot appear in Windows file names')
def test_listing_skips_unsupported_names(tmp_path):
    (tmp_path / 'normal.txt').write_text('ok')
    (tmp_path / 'Title: Subtitle.mkv').write_text('x')
    (tmp_path / 'back\\slash.txt').write_text('x')
    fs = LocalFilesystem({'root': str(tmp_path)})
    try:
        result = fs.list('/', 100)
        assert [item['name'] for item in result['entries']] == ['normal.txt']
        assert result['skipped'] == 2
    finally:
        fs.close()


def test_local_file_handle_read(tmp_path):
    (tmp_path / 'file.bin').write_bytes(b'handle validation')
    fs = LocalFilesystem({'root': str(tmp_path)})
    try:
        with fs.open('/file.bin') as stream:
            assert stream.read() == b'handle validation'
    finally:
        fs.close()


def test_scan_is_capped_with_a_note(monkeypatch):
    from remote_fs_browser import discovery
    probed = []
    monkeypatch.setattr(discovery.socket, 'create_connection', lambda *a, **kw: probed.append(a[0]) or (_ for _ in ()).throw(OSError()))
    policy = Policy(network_ranges=['192.0.2.0/24', '198.51.100.0/24', '10.0.1.0/24', '10.0.2.0/24', '10.0.3.0/24'])
    result = discovery.discover(policy, scan=True)
    assert len({host for host, port in probed}) == 1024 and result['hosts'] == []
    assert any('first 1024 of 1270' in note for note in result['notes'])

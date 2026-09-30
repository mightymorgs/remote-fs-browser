import asyncio
import base64
import http.client
import secrets
import tempfile
import zipfile
from remote_fs_browser.davbridge import USER, Bridge
from remote_fs_browser.jobs import ArchiveJobs
from remote_fs_browser import Browser, Policy
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS

async def chunks(data):
    yield data[:200000]
    yield data[200000:]

async def run():
    async with Browser(Policy(network_ranges=['127.0.0.0/8'], operations=READ_OPERATIONS+WRITE_OPERATIONS, operation_timeout=20)) as browser:
        for descriptor, credentials in [({'type':'smb','host':'127.0.0.1','share':'files'},{'username':'tester','password':'protocol-test-password'}), ({'type':'nfs','host':'127.0.0.1','export':'/files','version':4},None)]:
            session = await browser.connect(descriptor, credentials)
            prefix='/exercise-'+descriptor['type']+'-'+secrets.token_hex(3)
            data=b'binary\x00payload\xff'*30000
            await session.mkdir(prefix)
            await session.write(prefix+'/file', chunks(data))
            received=b''.join([chunk async for chunk in session.stream(prefix+'/file')])
            assert received==data,(descriptor['type'],len(received))
            try:
                await session.write(prefix+'/file', chunks(b'bad'))
            except FileExistsError:
                pass
            else:
                raise AssertionError('Overwrote an existing file')
            with tempfile.TemporaryDirectory() as stage:
                jobs = ArchiveJobs({'test': stage})
                async def allow(*args):
                    pass
                job = await jobs.create('test', session, [prefix], 'test', 0, allow)
                await jobs.tasks[job['id']]
                result = jobs.get('test', job['id'])
                assert result['stage'] == 'ready', result
                with zipfile.ZipFile(jobs.directory(result) / result['parts'][0]['name']) as archive:
                    assert archive.read(prefix.lstrip('/') + '/file') == data
                await jobs.purge('test', job['id'])
            await session.write(prefix+'/file', chunks(b'edited'), overwrite=True)
            await session.copy(prefix, prefix+'-copy')
            await session.rename(prefix+'-copy', prefix+'-moved')
            assert b''.join([c async for c in session.stream(prefix+'-moved/file')])==b'edited'
            await session.remove(prefix+'-moved',recursive=True)
            await session.remove(prefix,recursive=True)
            print(descriptor['type'], 'real-server write/read/archive/conflict/replace/copy/folder-move/delete passed', flush=True)

def bridge_exercise():
    """The WebDAV bridge that NFS mounts use, against the real NFS server."""
    folder='exercise-bridge-'+secrets.token_hex(3)
    setup=Bridge({'host':'127.0.0.1','export':'/files','version':4,'path':'/'})
    def call(method, path, body=None, **headers):
        connection=http.client.HTTPConnection('127.0.0.1', int(bridge.url.rsplit(':',1)[1].strip('/')), timeout=30)
        token=base64.b64encode(f'{USER}:{bridge.password}'.encode()).decode()
        connection.request(method, path, body=body, headers={'Authorization':'Basic '+token, **headers})
        response=connection.getresponse(); data=response.read(); connection.close()
        return response.status, data
    bridge=setup
    try:
        assert call('MKCOL','/'+folder)[0]==201
    finally:
        bridge.stop()
    bridge=Bridge({'host':'127.0.0.1','export':'/files','version':4,'path':'/'+folder})
    try:
        data=b'bridge\x00payload'*50000  # the test server's in-memory files hold up to 1,114,112 bytes
        assert call('PUT','/file.bin',data)[0]==201
        assert call('PUT','/file.bin',data[::-1])[0]==204
        status, body=call('GET','/file.bin',Range='bytes=10-19')
        assert status==206 and body==data[::-1][10:20], status
        assert call('MKCOL','/sub')[0]==201
        assert call('MOVE','/file.bin',Destination=bridge.url+'sub/file.bin')[0]==201
        assert call('MOVE','/sub',Destination=bridge.url+'moved')[0]==201
        status, body=call('PROPFIND','/moved',Depth='1')
        assert status==207 and b'/moved/file.bin' in body and b'.remotefs-' not in body, body
        assert call('GET','/moved/file.bin')[1]==data[::-1]
        assert call('DELETE','/moved/file.bin')[0]==204 and call('DELETE','/moved')[0]==204
    finally:
        bridge.stop()
    bridge=Bridge({'host':'127.0.0.1','export':'/files','version':4,'path':'/'})
    try:
        assert call('DELETE','/'+folder)[0]==204
    finally:
        bridge.stop()
    print('nfs mount bridge write/replace/range/folder-move/list/delete passed', flush=True)

if __name__=='__main__':
    asyncio.run(run())
    bridge_exercise()

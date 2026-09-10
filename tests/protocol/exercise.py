import asyncio
import secrets
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
            await session.write(prefix+'/file', chunks(b'edited'), overwrite=True)
            await session.copy(prefix, prefix+'-copy')
            await session.rename(prefix+'-copy', prefix+'-moved')
            assert b''.join([c async for c in session.stream(prefix+'-moved/file')])==b'edited'
            await session.remove(prefix+'-moved',recursive=True)
            await session.remove(prefix,recursive=True)
            print(descriptor['type'], 'real-server write/read/conflict/replace/copy/folder-move/delete passed', flush=True)

if __name__=='__main__':
    asyncio.run(run())

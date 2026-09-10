import asyncio
import io
import os
import zipfile
import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Browser, Policy
from remote_fs_browser.jobs import ArchiveJobs, SplitWriter
from remote_fs_browser.http import create_app
from remote_fs_browser.store import SavedLocations

TOKEN='download-test-token-'*3

async def allow(*args):
    pass

@pytest.mark.asyncio
async def test_archive_split_roundtrip_pause_restart_and_purge(tmp_path):
    root=tmp_path/'files';root.mkdir()
    (root/'folder').mkdir();(root/'folder/empty').mkdir()
    payload=os.urandom(2400000)
    (root/'folder/file.bin').write_bytes(payload)
    jobs=ArchiveJobs({'test':tmp_path/'stage'})
    async with Browser(Policy(local_roots=[str(root)])) as browser:
        session=await browser.connect({'type':'local','root':str(root)})
        job=await jobs.create('alice',session,['/folder'],'test',1048576,allow)
        jobs.control('alice',job['id'],'pause')
        await asyncio.sleep(.03)
        assert jobs.get('alice',job['id'])['packed']==0
        jobs.control('alice',job['id'],'resume')
        await jobs.tasks[job['id']]
        actual=jobs.get('alice',job['id'])
        assert actual['stage']=='ready', actual
        assert len(actual['parts'])==3
        packed=b''.join((jobs.directory(actual)/p['name']).read_bytes() for p in actual['parts'])
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            assert archive.read('folder/file.bin')==payload
            assert 'folder/empty/' in archive.namelist()
        with pytest.raises(FileNotFoundError):jobs.get('bob',job['id'])
        restored=ArchiveJobs({'test':tmp_path/'stage'})
        assert restored.get('alice',job['id'])['stage']=='ready'
        result=await restored.purge('alice',job['id'])
        assert result['freed']==len(packed)
        assert list(restored.directory(actual).iterdir())==[restored.directory(actual)/'job.json']

@pytest.mark.asyncio
async def test_archive_authorization_bounds_and_failure(tmp_path):
    root=tmp_path/'files';root.mkdir();(root/'secret').mkdir();(root/'secret/keep').write_text('private')
    jobs=ArchiveJobs({'test':tmp_path/'stage'})
    async with Browser(Policy(local_roots=[str(root)])) as browser:
        session=await browser.connect({'type':'local','root':str(root)})
        async def deny(operation, descriptor):
            if operation=='list':raise PermissionError('denied')
        with pytest.raises(PermissionError):await jobs.create('alice',session,['/secret'],'test',0,deny)
        with pytest.raises(ValueError):await jobs.create('alice',session,['/secret','/secret/keep'],'test',0,allow)
        with pytest.raises(ValueError):await jobs.create('alice',session,['/secret'],'test',12,allow)
        assert not jobs.list('alice')
        job=await jobs.create('alice',session,['/secret'],'test',0,allow)
        await jobs.purge('alice',job['id'])
        assert jobs.get('alice',job['id'])['purged']


def test_http_parts_range_and_ownership(tmp_path):
    root=tmp_path/'files';root.mkdir();(root/'data').write_bytes(b'content'*100)
    app=create_app(Policy(local_roots=[str(root)],requests_per_minute=1000),authenticate=lambda r:r.headers.get('x-user'),staging_stores={'test':tmp_path/'stage'})
    with TestClient(app,raise_server_exceptions=False) as client:
        client.headers['x-user']='alice'
        session=client.post('/api/sessions',json={'descriptor':{'type':'local','root':str(root)}}).json()['id']
        estimate=client.post('/api/downloads/estimate',json={'session':session,'paths':['/data']})
        assert estimate.status_code==200,estimate.text
        response=client.post('/api/downloads',json={'session':session,'paths':['/data'],'store':'test'})
        assert response.status_code==200,response.text
        id=response.json()['id']
        import time
        for _ in range(100):
            job=client.get('/api/downloads').json()['jobs'][0]
            if job['stage']!='packing':break
            time.sleep(.01)
        assert job['stage']=='ready',job
        url=f'/api/downloads/{id}/parts/0'
        full=client.get(url); assert full.status_code==200
        part=client.get(url,headers={'Range':'bytes=4-13'})
        assert part.status_code==206 and part.content==full.content[4:14]
        assert client.get(url,headers={'Range':'bytes=999999-'}).status_code==416
        client.headers['x-user']='bob'
        assert client.get(url).status_code==404
        assert client.delete(f'/api/downloads/{id}').status_code==404
        client.headers['x-user']='alice'
        assert client.delete(f'/api/downloads/{id}').status_code==200
        assert client.get(url).status_code==409


def test_host_credentials_are_owned_bound_and_encrypted(tmp_path):
    store=SavedLocations(tmp_path/'saved.json','storage-key')
    id=store.add_host('alice','NAS.EXAMPLE',{'username':'user','password':'super-secret','domain':'WORKGROUP'})
    assert store.hosts('alice')[0]['host']=='nas.example'
    assert 'super-secret' not in str(store.hosts('alice'))
    assert 'super-secret' not in store.path.read_text()
    assert store.list('alice')==[]
    assert store.resolve_host('alice',id,'nas.example')['password']=='super-secret'
    with pytest.raises(PermissionError):store.resolve_host('bob',id,'nas.example')
    with pytest.raises(PermissionError):store.resolve_host('alice',id,'evil.example')
    restored=SavedLocations(store.path,'storage-key')
    assert restored.resolve_host('alice',id,'nas.example')['username']=='user'

@pytest.mark.asyncio
async def test_capacity_reservation_and_source_growth(tmp_path, monkeypatch):
    from collections import namedtuple
    from remote_fs_browser import jobs as module
    root=tmp_path/'files';root.mkdir();(root/'data').write_bytes(b'x'*3000)
    stage=tmp_path/'stage'
    jobs=ArchiveJobs({'test':stage})
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr(module.shutil,'disk_usage',lambda path:usage(10000,4000,6000))
    async with Browser(Policy(local_roots=[str(root)])) as browser:
        session=await browser.connect({'type':'local','root':str(root)})
        job=await jobs.create('alice',session,['/data'],'test',0,allow)
        jobs.control('alice',job['id'],'pause')
        with pytest.raises(ValueError,match='space'):
            await jobs.create('alice',session,['/data'],'test',0,allow)
        (root/'data').write_bytes(b'y'*4000)
        jobs.control('alice',job['id'],'resume')
        await jobs.tasks[job['id']]
        assert jobs.get('alice',job['id'])['stage']=='failed'
        assert not jobs.reserved
        await jobs.purge('alice',job['id'])
        jobs.forget('alice',job['id'])
        assert not jobs.list('alice')


def test_api_host_reference_cannot_authenticate_to_another_host(tmp_path):
    store=SavedLocations(tmp_path/'saved.json','key')
    id=store.add_host('alice','127.0.0.1',{'username':'user','password':'secret'})
    app=create_app(Policy(network_ranges=['127.0.0.0/8']),authenticate=lambda r:'alice',saved_locations=store)
    with TestClient(app,raise_server_exceptions=False) as client:
        response=client.post('/api/discover',json={'host':'127.0.0.2','type':'smb','credential_id':id})
        assert response.status_code==403
        response=client.post('/api/sessions',json={'descriptor':{'type':'smb','host':'127.0.0.2','share':'files','credential_id':id}})
        assert response.status_code==403
        assert 'secret' not in client.get('/api/credentials').text

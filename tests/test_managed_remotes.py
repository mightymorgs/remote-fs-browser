import json
import hashlib
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Policy
from remote_fs_browser.auth import make_account
from remote_fs_browser.http import create_app
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS
from remote_fs_browser.remotes import RemoteStore


def cloud_data(**changes):
    return dict(provider='s3', label='My archive', root='/bucket', read_only=False,
                options={'access_key_id': 'test-key', 'secret_access_key': 'test-secret'}, **changes)


def test_private_store_preserves_secrets_and_owner(tmp_path):
    store = RemoteStore(tmp_path)
    row = store.save('alice', cloud_data())
    reference = row['id']
    assert 'test-secret' not in json.dumps(store.get('alice', reference))
    assert store.get('alice', reference)['saved_secrets'] == ['secret_access_key']
    assert store.list('bob') == []
    for action in (store.get, store.endpoint, store.remove):
        with pytest.raises(PermissionError):
            action('bob', reference)
    update = cloud_data()
    update['options']['secret_access_key'] = ''
    update['label'] = 'Renamed'
    store.save('alice', update, reference)
    assert 'test-secret' in store.config_path(reference).read_text()
    assert RemoteStore(tmp_path).get('alice', reference)['label'] == 'Renamed'
    if os.name != 'nt':
        assert store.config_path(reference).stat().st_mode & 0o777 == 0o600
    store.remove('alice', reference)
    assert store.list('alice') == []
    assert not (tmp_path / (reference + '.conf')).exists()


@pytest.mark.parametrize('changes', [
    {'provider': 'local'}, {'provider': 'alias'}, {'provider': 'sftp'},
    {'options': {'ssh': 'bad-command'}}, {'root': '/../private'},
    {'read_only': 'false'}, {'options': {'access_key_id': 'key\n[evil]', 'secret_access_key': 'secret'}},
    {'options': {'access_key_id': 'key', 'secret_access_key': ''}},
])
def test_rejects_unsafe_or_incomplete_configuration(tmp_path, changes):
    store = RemoteStore(tmp_path)
    data = cloud_data()
    data.update(changes)
    with pytest.raises(ValueError):
        store.save('owner', data)
    assert store.list('owner') == []


def test_cloud_api_login_csrf_and_owner_isolation(tmp_path):
    store = RemoteStore(tmp_path)
    account = make_account('tester', 'temporary-cloud-password')
    app = create_app(Policy(operations=READ_OPERATIONS + WRITE_OPERATIONS), account=account, token='optional-automation-token-with-32-characters', remote_store=store)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post('/api/remotes', json=cloud_data()).status_code == 401
        assert client.post('/api/login', json={'username':'tester','password':'temporary-cloud-password'}).status_code == 200
        assert client.post('/api/remotes', json=cloud_data()).status_code == 403
        client.headers['Origin'] = 'http://testserver'
        response = client.post('/api/remotes', json=cloud_data())
        assert response.status_code == 200, response.text
        reference = response.json()['id']
        assert 'test-secret' not in client.get('/api/remotes/'+reference).text
        foreign = store.save('another-user', cloud_data())['id']
        for method in ('get', 'delete'):
            assert getattr(client, method)('/api/remotes/'+foreign).status_code == 403
        assert client.post('/api/sessions', json={'descriptor':{'type':'rclone','endpoint':foreign}}).status_code == 403
        client.cookies.clear()
        client.headers['Authorization'] = 'Bearer optional-automation-token-with-32-characters'
        assert client.get('/api/remotes/'+reference).status_code == 200
        assert client.delete('/api/remotes/'+reference).status_code == 200


def test_readonly_service_disables_management(tmp_path):
    app=create_app(Policy(), token='test-token-with-at-least-32-characters', remote_store=RemoteStore(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers['Authorization']='Bearer test-token-with-at-least-32-characters'
        assert not client.get('/api/remotes').json()['manageable']
        assert client.post('/api/remotes',json=cloud_data()).status_code==403


@pytest.fixture
def s3_server():
    """Small disposable S3 fixture. Real rclone signs HTTP requests against it."""
    files = {'bucket/source.txt': b'cloud contents\n', 'bucket/folder/nested.txt': b'nested bytes\n'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, status, data=b'', content_type='application/xml'):
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', content_type)
            self.send_header('ETag', '"'+hashlib.md5(files.get(self.key(), data)).hexdigest()+'"')
            self.send_header('Last-Modified', 'Tue, 29 Sep 2026 00:00:00 GMT')
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(data)
        def key(self): return unquote(urlsplit(self.path).path).strip('/')
        def do_HEAD(self):
            key=self.key()
            self.reply(200 if key in files or key=='bucket' else 404, files.get(key,b''))
        def do_GET(self):
            key=self.key()
            if key in files:
                data=files[key]
                header=self.headers.get('Range')
                if header:
                    start,end=header.removeprefix('bytes=').split('-')
                    data=data[int(start):int(end)+1 if end else None]
                return self.reply(206 if header else 200,data,'application/octet-stream')
            if not key:
                return self.reply(200,b'<ListAllMyBucketsResult><Buckets><Bucket><Name>bucket</Name><CreationDate>2026-09-29T00:00:00Z</CreationDate></Bucket></Buckets></ListAllMyBucketsResult>')
            query=parse_qs(urlsplit(self.path).query)
            prefix=query.get('prefix',[''])[0]; delimiter=query.get('delimiter',[''])[0]
            xml=['<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>']
            folders=set()
            for name,data in list(files.items()):
                if not name.startswith(key+'/'): continue
                name=name[len(key)+1:]
                if not name.startswith(prefix): continue
                tail=name[len(prefix):]
                if delimiter and delimiter in tail:
                    folders.add(prefix+tail.split(delimiter)[0]+delimiter);continue
                xml.append(f'<Contents><Key>{escape(name)}</Key><Size>{len(data)}</Size><LastModified>2026-09-29T00:00:00Z</LastModified><ETag>"{hashlib.md5(data).hexdigest()}"</ETag></Contents>')
            xml += [f'<CommonPrefixes><Prefix>{escape(name)}</Prefix></CommonPrefixes>' for name in sorted(folders)]
            self.reply(200,(''.join(xml)+'</ListBucketResult>').encode())
        def do_PUT(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            if '/' in self.key(): files[self.key()]=body
            self.reply(200)
        def do_DELETE(self):
            files.pop(self.key(),None);self.reply(204)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', files
    finally: server.shutdown();server.server_close();thread.join()


@pytest.mark.skipif(not shutil.which('rclone'), reason='rclone is optional')
def test_real_s3_connection_copy_both_directions_and_restart(tmp_path, s3_server):
    endpoint,files=s3_server
    root=tmp_path/'local';root.mkdir();(root/'upload.txt').write_bytes(b'from local\n')
    store=RemoteStore(tmp_path/'remotes')
    policy=Policy(local_roots=[str(root)],operations=READ_OPERATIONS+WRITE_OPERATIONS,operation_timeout=30)
    app=create_app(policy, token='test-token-with-at-least-32-characters',remote_store=store)
    with TestClient(app,raise_server_exceptions=False) as client:
        client.headers['Authorization']='Bearer test-token-with-at-least-32-characters'
        data=cloud_data();data['options'].update(provider='Other',endpoint=endpoint)
        response=client.post('/api/remotes',json=data);assert response.status_code==200,response.text
        reference=response.json()['id']
        cloud=client.post('/api/sessions',json={'descriptor':{'type':'rclone','endpoint':reference}})
        assert cloud.status_code==200,cloud.text
        cloud=cloud.json()['id']
        local=client.post('/api/sessions',json={'descriptor':{'type':'local','root':str(root)}}).json()['id']
        def copy(src,path,dst,dest):
            response=client.post(f'/api/sessions/{src}/copy',json={'source':path,'destination':dest,'target_session':dst})
            assert response.status_code==200,response.text
        copy(cloud,'/folder',local,'/copied-folder')
        assert (root/'copied-folder/nested.txt').read_bytes()==b'nested bytes\n'
        copy(local,'/upload.txt',cloud,'/uploaded.txt')
        assert files['bucket/uploaded.txt']==b'from local\n'
        copy(cloud,'/source.txt',cloud,'/duplicate.txt')
        assert files['bucket/duplicate.txt']==files['bucket/source.txt']
        # A second managed cloud connection supports cloud-to-cloud clipboard copies.
        data['label']='Second connection'
        second=client.post('/api/remotes',json=data).json()['id']
        target=client.post('/api/sessions',json={'descriptor':{'type':'rclone','endpoint':second}}).json()['id']
        copy(cloud,'/source.txt',target,'/cross-cloud.txt')
        assert files['bucket/cross-cloud.txt']==b'cloud contents\n'
        # Root-level S3 browsing exposes buckets, then their folder structures.
        bucket_data={**data, 'root':'/', 'label':'All buckets'}
        buckets=client.post('/api/remotes',json=bucket_data).json()['id']
        buckets=client.post('/api/sessions',json={'descriptor':{'type':'rclone','endpoint':buckets}}).json()['id']
        listing=client.get(f'/api/sessions/{buckets}/list').json()
        assert [row['name'] for row in listing['entries']]==['bucket']
        listing=client.get(f'/api/sessions/{buckets}/list',params={'path':'/bucket/folder'}).json()
        assert listing['entries'][0]['name']=='nested.txt'
        data['read_only']=True
        response=client.put('/api/remotes/'+reference,json=data);assert response.status_code==200,response.text
        assert client.get(f'/api/sessions/{cloud}/list').status_code==404
        assert client.delete('/api/remotes/'+second).status_code==200
        assert files['bucket/cross-cloud.txt']==b'cloud contents\n'
    assert RemoteStore(tmp_path/'remotes').get('token-user',reference)['read_only']

from fastapi.testclient import TestClient
import pytest
from remote_fs_browser import Policy
from remote_fs_browser.http import create_app, byte_range

TOKEN = 'test-token-' * 5


@pytest.mark.parametrize('value,expected', [(None,(0,10,200)), ('bytes=2-5',(2,4,206)), ('bytes=-3',(7,3,206)), ('bytes=8-',(8,2,206))])
def test_ranges(value, expected):
    assert byte_range(value,10) == expected


@pytest.mark.parametrize('value', ['bytes=20-', 'bytes=5-2', 'bytes=-0', 'bytes=0-1,4-5', 'invalid', 'bytes=a-b'])
def test_invalid_ranges(value):
    with pytest.raises(ValueError): byte_range(value, 10)


def test_http_streaming_and_auth(tmp_path):
    (tmp_path / 'data').write_bytes(b'0123456789')
    app = create_app(Policy(local_roots=[str(tmp_path)]), token=TOKEN)
    with TestClient(app) as client:
        assert client.get('/discover').status_code == 401
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        created = client.post('/sessions', json={'descriptor': {'type': 'local','root': str(tmp_path)}})
        assert created.status_code == 200, created.text
        sid = created.json()['id']
        assert client.get(f'/sessions/{sid}/list', params={'ndjson':True}).headers['content-type'].startswith('application/x-ndjson')
        response = client.get(f'/sessions/{sid}/file', params={'path':'/data'}, headers={'Range':'bytes=2-5'})
        assert response.status_code == 206 and response.content == b'2345'
        assert response.headers['content-range'] == 'bytes 2-5/10'
        assert client.get(f'/sessions/{sid}/file', params={'path':'/data'}, headers={'Range':'bytes=90-'}).status_code == 416
        assert client.delete(f'/sessions/{sid}').status_code == 200
        assert not app.state.browser.sessions
        assert client.post('/sessions', content=b'x'*20000).status_code == 413


def test_discover_groups(tmp_path):
    root = str(tmp_path.resolve())
    app = create_app(Policy(local_roots=[root], network_ranges=['192.0.2.0/24']), token=TOKEN, root_kinds={root: 'home'})
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        data = client.get('/api/discover').json()
        assert data['roots'] == [{'type': 'local', 'root': root, 'kind': 'home'}] and data['hosts'] == [] and data['notes']
        assert [group['id'] for group in data['groups']] == ['local', 'smb', 'nfs']
        assert data['groups'][0]['items'] == [{'type': 'local', 'root': root, 'kind': 'home', 'label': 'Home'}]
        assert '192.0.2.0/24' in data['groups'][1]['hint'] and data['groups'][2]['items'] == []


def test_saved_locations_api(tmp_path, monkeypatch):
    from remote_fs_browser.store import SavedLocations
    seen = []
    def fake_smb(self, config):
        seen.append(dict(config))
        raise OSError('no server in tests')
    monkeypatch.setattr('remote_fs_browser.backends.SMBFilesystem.__init__', fake_smb)
    store = SavedLocations(tmp_path / 'saved.json', TOKEN)
    app = create_app(Policy(network_ranges=['192.0.2.0/24']), authenticate=lambda request: request.headers.get('x-user'), saved_locations=store)
    with TestClient(app, raise_server_exceptions=False) as client:
        alice = {'x-user': 'alice'}
        descriptor = {'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/Campaigns'}
        created = client.post('/api/saved', headers=alice, json={'descriptor': descriptor, 'credentials': {'username': 'media', 'password': 'hunter2'}})
        assert created.status_code == 200, created.text
        reference = created.json()['id']
        listed = client.get('/api/saved', headers=alice).json()
        assert listed['available'] and listed['locations'][0]['descriptor'] == descriptor and listed['locations'][0]['has_credentials']
        assert 'hunter2' not in client.get('/api/saved', headers=alice).text
        assert client.get('/api/saved', headers={'x-user': 'bob'}).json()['locations'] == []
        assert client.post('/api/saved', headers=alice, json={'descriptor': {'type': 'local', 'root': str(tmp_path)}}).status_code == 422
        assert client.delete(f'/api/saved/{reference}', headers={'x-user': 'bob'}).status_code == 404
        assert client.post('/api/sessions', headers={'x-user': 'bob'}, json={'descriptor': {**descriptor, 'credential_id': reference}}).status_code == 403
        assert not seen
        monkeypatch.setattr('socket.getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('192.0.2.5', 0))])
        response = client.post('/api/sessions', headers=alice, json={'descriptor': {**descriptor, 'credential_id': reference}})
        assert response.status_code == 422 and 'hunter2' not in response.text
        assert client.delete(f'/api/saved/{reference}', headers=alice).status_code == 200
        assert client.get('/api/saved', headers=alice).json()['locations'] == []


def test_principal_isolation(tmp_path):
    app = create_app(Policy(local_roots=[str(tmp_path)]), authenticate=lambda request: request.headers.get('x-user'))
    with TestClient(app) as client:
        sid = client.post('/sessions', headers={'x-user':'alice'}, json={'descriptor':{'type':'local','root':str(tmp_path)}}).json()['id']
        assert client.get(f'/sessions/{sid}/list', headers={'x-user':'bob'}).status_code == 404


def test_rate_limit():
    with TestClient(create_app(Policy(requests_per_minute=1), token=TOKEN)) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        assert client.get('/openapi.json').status_code == 200
        assert client.get('/openapi.json').status_code == 429


def test_same_origin_browser_login_and_download(tmp_path):
    (tmp_path / 'download.txt').write_bytes(b'0123456789')
    app = create_app(Policy(local_roots=[str(tmp_path)]), token='x' * 32)
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/discover').status_code == 401
        response = client.post('/api/login', headers={'Authorization': 'Bearer ' + 'x' * 32})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie']
        assert client.get('/api/discover').status_code == 200
        body = {'descriptor': {'type':'local', 'root':str(tmp_path)}}
        assert client.post('/api/sessions', json=body, headers={'Origin':'http://evil.test'}).status_code == 403
        opened = client.post('/api/sessions', json=body, headers={'Origin':'http://testserver'})
        assert opened.status_code == 200
        url = '/api/sessions/' + opened.json()['id'] + '/file?path=/download.txt'
        response = client.get(url, headers={'Range':'bytes=2-5'})
        assert response.status_code == 206 and response.content == b'2345'
        assert client.delete('/api/login', headers={'Origin':'http://testserver'}).status_code == 200
        assert client.get(url).status_code == 401

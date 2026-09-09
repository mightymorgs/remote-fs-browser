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

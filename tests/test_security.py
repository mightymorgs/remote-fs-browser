import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Browser, Policy
from remote_fs_browser.http import create_app


def test_server_allowlist(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.12',0))])
    policy = Policy(network_ranges=['192.0.2.0/24'], servers=['nas.example'])
    assert policy.host('nas.example') == '192.0.2.12'
    with pytest.raises(PermissionError): policy.host('another.example')
    policy.network_ranges = ['198.51.100.0/24']
    with pytest.raises(PermissionError): policy.host('nas.example')


def test_credential_resolver_receives_principal(tmp_path):
    calls = []
    def resolver(principal, ref):
        calls.append((principal,ref)); return {'password':'must-not-appear'}
    app = create_app(Policy(local_roots=[str(tmp_path)]), authenticate=lambda request: 'alice', credential_resolver=resolver)
    with TestClient(app) as client:
        response = client.post('/sessions', json={'descriptor': {'type':'local','root':str(tmp_path),'credential_id':'allowed-ref'}})
        assert response.status_code == 200
        assert calls == [('alice','allowed-ref')]
        assert 'must-not-appear' not in response.text


def test_hook_denies_reads(tmp_path):
    (tmp_path/'file').write_text('private')
    app = create_app(Policy(local_roots=[str(tmp_path)]), token='x'*40, authorize=lambda principal, operation, descriptor: operation != 'read')
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers['Authorization'] = 'Bearer ' + 'x'*40
        sid = client.post('/sessions', json={'descriptor':{'type':'local','root':str(tmp_path)}}).json()['id']
        response = client.get(f'/sessions/{sid}/file', params={'path':'/file'})
        assert response.status_code == 403 and 'private' not in response.text


async def test_session_limit_and_release(tmp_path):
    async with Browser(Policy(local_roots=[str(tmp_path)],max_sessions=1)) as browser:
        first = await browser.connect({'type':'local','root':str(tmp_path)})
        with pytest.raises(ValueError): await browser.connect({'type':'local','root':str(tmp_path)})
        await first.close()
        second = await browser.connect({'type':'local','root':str(tmp_path)})
        assert second.id != first.id


def test_packaged_frontend_matches_source():
    from pathlib import Path
    root = Path(__file__).parents[1]
    assert (root/'frontend/browser.js').read_bytes() == (root/'src/remote_fs_browser/web/browser.js').read_bytes()

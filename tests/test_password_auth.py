import json
import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Policy
from remote_fs_browser.auth import make_account, verify_account
from remote_fs_browser.http import create_app
from remote_fs_browser.store import SavedLocations

PASSWORD = 'a-test-password-with-length'

@pytest.fixture(scope='module')
def account():
    return make_account('tester', PASSWORD)


def test_salted_hash_and_wrong_password(account):
    assert verify_account(account, 'tester', PASSWORD)
    assert not verify_account(account, 'other', PASSWORD)
    assert not verify_account(account, 'tester', 'wrong')
    assert PASSWORD not in json.dumps(account)
    assert make_account('tester', PASSWORD)['hash'] != account['hash']
    with pytest.raises(ValueError):
        make_account('tester', 'short')


def test_password_login_cookie_csrf_logout_and_throttle(tmp_path, account):
    app = create_app(Policy(local_roots=[str(tmp_path)]), account=account)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get('/api/discover').status_code == 401
        assert client.post('/api/login', json={'username':'tester','password':'wrong'}).status_code == 401
        response = client.post('/api/login', json={'username':'tester','password':PASSWORD})
        assert response.status_code == 200, response.text
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert response.headers['cache-control'] == 'no-store'
        assert client.get('/api/discover').status_code == 200
        descriptor = {'type':'local','root':str(tmp_path)}
        assert client.post('/api/sessions', json={'descriptor':descriptor}).status_code == 403
        client.headers['Origin'] = 'http://testserver'
        sid = client.post('/api/sessions', json={'descriptor':descriptor}).json()['id']
        assert client.delete('/api/login').status_code == 200
        assert not app.state.browser.sessions
        assert client.get(f'/api/sessions/{sid}/list').status_code == 401
        for _ in range(8):
            client.post('/api/login', json={'username':'tester','password':'wrong'})
        assert client.post('/api/login', json={'username':'tester','password':PASSWORD}).status_code == 429


def test_legacy_key_and_saved_credentials_survive_account_migration(tmp_path, monkeypatch):
    from remote_fs_browser.cli import main
    token = 'old-service-key-' * 4
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'token':token,'policy':{}}))
    saved = SavedLocations(tmp_path / 'saved.json', token)
    saved.add('token-user', {'type':'smb','host':'nas','share':'files','path':'/'}, {'username':'nas-user','password':'nas-password'})
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('getpass.getpass', lambda _: PASSWORD)
    main(['account','--config',str(config),'--username','tester'])
    settings = json.loads(config.read_text())
    assert 'token' not in settings and settings['storage_key'] == token
    assert settings['account']['principal'] == 'token-user'
    reopened = SavedLocations(tmp_path / 'saved.json', settings['storage_key'])
    assert len(reopened.list(settings['account']['principal'])) == 1
    key = settings['storage_key']
    main(['account','--config',str(config),'--username','renamed'])
    assert json.loads(config.read_text())['storage_key'] == key

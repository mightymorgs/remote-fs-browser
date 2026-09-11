import json
from fastapi.testclient import TestClient
from remote_fs_browser import Policy
from remote_fs_browser.http import create_app
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS

TOKEN = 'staging-picker-test-' * 3


def test_choose_create_and_persist_zip_folder(tmp_path):
    root = tmp_path/'files'; root.mkdir()
    settings = tmp_path/'settings.json'
    app = create_app(Policy(local_roots=[str(root)], operations=READ_OPERATIONS+WRITE_OPERATIONS), TOKEN,
                     staging_stores={'Downloads': tmp_path/'stage'},
                     staging_store_writer=lambda values: settings.write_text(json.dumps(values)))
    with TestClient(app, raise_server_exceptions=False, headers={'Authorization': 'Bearer '+TOKEN}) as client:
        assert client.get('/api/downloads').json()['manage_stores']
        session = client.post('/api/sessions', json={'descriptor': {'type': 'local', 'root': str(root)}}).json()['id']
        assert client.post(f'/api/sessions/{session}/mkdir', json={'path':'/My ZIPs'}).status_code == 200
        response = client.post('/api/downloads/stores', json={'session':session, 'path':'/My ZIPs'})
        assert response.status_code == 200, response.text
        key = response.json()['id']
        assert json.loads(settings.read_text())[key] == str(root/'My ZIPs')
        assert client.post('/api/downloads/stores', json={'session':session, 'path':'/My ZIPs'}).json()['id'] == key
        assert len(client.get('/api/downloads').json()['stores']) == 2
        assert client.get('/api/downloads').json()['stores'][0]['id'] == key
        from remote_fs_browser.jobs import ArchiveJobs
        assert ArchiveJobs(json.loads(settings.read_text())).capacity()[0]['id'] == key
        assert client.post('/api/downloads/stores', json={'session':session, 'path':'/../stage'}).status_code == 422


def test_read_only_or_unmanaged_service_cannot_change_zip_folders(tmp_path):
    for writer, operations in [(None, READ_OPERATIONS+WRITE_OPERATIONS), (lambda _: None, READ_OPERATIONS)]:
        app = create_app(Policy(local_roots=[str(tmp_path)], operations=operations), TOKEN, staging_store_writer=writer)
        with TestClient(app, raise_server_exceptions=False, headers={'Authorization':'Bearer '+TOKEN}) as client:
            assert not client.get('/api/downloads').json()['manage_stores']
            session = client.post('/api/sessions', json={'descriptor':{'type':'local','root':str(tmp_path)}}).json()['id']
            assert client.post('/api/downloads/stores', json={'session':session,'path':'/'}).status_code == 403


def test_failed_persistence_does_not_change_active_stores(tmp_path):
    def fail(_):
        raise PermissionError('Cannot save settings')
    app = create_app(Policy(local_roots=[str(tmp_path)], operations=READ_OPERATIONS+WRITE_OPERATIONS), TOKEN, staging_store_writer=fail)
    with TestClient(app, raise_server_exceptions=False, headers={'Authorization':'Bearer '+TOKEN}) as client:
        session=client.post('/api/sessions', json={'descriptor':{'type':'local','root':str(tmp_path)}}).json()['id']
        assert client.post('/api/downloads/stores', json={'session':session,'path':'/'}).status_code == 403
        assert client.get('/api/downloads').json()['stores'] == []

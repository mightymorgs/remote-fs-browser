import os
import pytest
from fastapi.testclient import TestClient
from remote_fs_browser import Policy
from remote_fs_browser.http import create_app
from remote_fs_browser.backends import LocalFilesystem, SMBFilesystem


def test_create_folder_is_opt_in_and_confined(tmp_path):
    root = str(tmp_path.resolve())
    for enabled in (False, True):
        policy = Policy(local_roots=[root])
        if enabled: policy.operations.append('mkdir')
        with TestClient(create_app(policy, token='x'*40), raise_server_exceptions=False) as client:
            client.headers['Authorization'] = 'Bearer ' + 'x'*40
            sid = client.post('/api/sessions', json={'descriptor':{'type':'local','root':root}}).json()['id']
            endpoint = f'/api/sessions/{sid}/mkdir'
            result = client.post(endpoint, json={'path':'/created'})
            assert result.status_code == (200 if enabled else 403), result.text
            if enabled:
                assert (tmp_path/'created').is_dir()
                assert client.post(endpoint,json={'path':'/../escape'}).status_code == 422
                assert client.post(endpoint,json={'path':'/created'}).status_code >= 400
                rows=client.get(f'/api/sessions/{sid}/list').json()['entries']
                assert rows[0]['name']=='created'
                client.headers.pop('Authorization')
                assert client.post(endpoint,json={'path':'/denied'}).status_code == 401


def test_local_create_does_not_follow_symlink(tmp_path):
    (tmp_path/'root').mkdir()
    (tmp_path/'outside').mkdir()
    (tmp_path/'root'/'link').symlink_to(tmp_path/'outside',target_is_directory=True)
    fs=LocalFilesystem({'root':str(tmp_path/'root')})
    try:
        with pytest.raises(OSError): fs.mkdir('/link/escape')
        assert not (tmp_path/'outside'/'escape').exists()
    finally: fs.close()


def test_smb_create_uses_validated_parent():
    from unittest.mock import Mock
    fs=SMBFilesystem.__new__(SMBFilesystem)
    fs.client=Mock(); fs.cache={}; fs._path=Mock(return_value='\\\\nas\\share')
    assert fs.mkdir('/new') == {'path':'/new'}
    fs._path.assert_called_once_with('/')
    fs.client.mkdir.assert_called_once_with('\\\\nas\\share\\new',connection_cache={})
    with pytest.raises(ValueError): fs.mkdir('/../escape')

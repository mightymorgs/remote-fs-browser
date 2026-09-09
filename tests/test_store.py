import json
import os
import pytest
from remote_fs_browser.store import SavedLocations, StoreLocked

TOKEN = 'store-token-' * 4
SMB = {'type': 'smb', 'host': '192.0.2.5', 'share': 'Projects', 'path': '/Campaigns'}


def test_round_trip_is_sealed_and_private(tmp_path):
    path = tmp_path / 'saved.json'
    store = SavedLocations(path, TOKEN)
    reference = store.add('alice', SMB, {'username': 'media', 'password': 'hunter2', 'domain': ''}, label='NAS projects')
    assert store.list('alice') == [{'id': reference, 'label': 'NAS projects', 'descriptor': SMB, 'created': store.records[0]['created'], 'has_credentials': True}]
    raw = path.read_text()
    assert 'hunter2' not in raw and 'Projects' not in raw and json.loads(raw)['format'] == 1
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600
    again = SavedLocations(path, TOKEN)
    assert again.resolve('alice', reference) == {'username': 'media', 'password': 'hunter2'}
    with pytest.raises(PermissionError):
        again.resolve('bob', reference)
    assert again.list('bob') == []


def test_other_token_cannot_open_store(tmp_path):
    path = tmp_path / 'saved.json'
    SavedLocations(path, TOKEN).add('alice', SMB, {'username': 'u', 'password': 'p'})
    with pytest.raises(StoreLocked):
        SavedLocations(path, 'another-token-' * 4)


def test_same_location_updates_in_place_and_keeps_credentials(tmp_path):
    store = SavedLocations(tmp_path / 'saved.json', TOKEN)
    first = store.add('alice', SMB, {'username': 'u', 'password': 'p'})
    second = store.add('alice', {**SMB, 'path': '/Other'}, {}, label='Renamed')
    assert first == second and len(store.records) == 1
    assert store.list('alice')[0]['descriptor']['path'] == '/Other' and store.list('alice')[0]['label'] == 'Renamed'
    assert store.resolve('alice', first)['password'] == 'p'
    nfs = store.add('alice', {'type': 'nfs', 'host': '192.0.2.5', 'export': '/exports/media', 'version': 4, 'path': '/'})
    assert store.list('alice')[1]['label'] == '192.0.2.5/exports/media' and store.resolve('alice', nfs) == {}
    assert store.remove('bob', first) is False and store.remove('alice', first) is True
    assert [row['id'] for row in store.list('alice')] == [nfs]


def test_limit(tmp_path):
    store = SavedLocations(tmp_path / 'saved.json', TOKEN, limit=1)
    store.add('alice', SMB)
    with pytest.raises(ValueError):
        store.add('alice', {**SMB, 'share': 'Other'})

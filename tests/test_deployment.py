"""Configuration migrations used by every unattended installer."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from remote_fs_browser.auth import verify_account
from remote_fs_browser.store import SavedLocations, write_private

HELPER = Path(__file__).resolve().parents[1] / 'scripts/deployment.py'
spec = importlib.util.spec_from_file_location('deployment', HELPER)
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


@pytest.fixture
def inputs(tmp_path):
    source, target, password = [tmp_path / name for name in ('input.json', 'config.json', 'password')]
    source.write_text(json.dumps({'policy': {'local_roots': [str(tmp_path)]}}))
    password.write_text('deployment-test-password\n')
    return source, target, password


def test_first_install_and_repeat_preserve_hash(inputs):
    source, target, password = inputs
    config, changed = deployment.prepare(source, target, 'admin', password)
    assert changed and verify_account(config['account'], 'admin', 'deployment-test-password')
    assert 'deployment-test-password' not in json.dumps(config)
    write_private(target, json.dumps(config))
    again, changed = deployment.prepare(source, target, 'admin', password)
    assert not changed and again == config


def test_rotation_preserves_vault_and_owner(inputs):
    source, target, password = inputs
    config, _ = deployment.prepare(source, target, 'admin', password)
    config['account']['principal'] = 'original-owner'
    write_private(target, json.dumps(config))
    vault = SavedLocations(target.with_name('saved.json'), config['storage_key'])
    reference = vault.add('original-owner', {'type': 'smb', 'host': '192.0.2.1', 'share': 'test'}, {'password': 'fixture-secret'})
    source.write_text(json.dumps({'storage_key': 'accidental-replacement', 'port': 9000}))
    password.write_text('rotated-test-password')
    updated, changed = deployment.prepare(source, target, 'new-admin', password)
    assert changed and updated['port'] == 9000
    assert updated['storage_key'] == config['storage_key']
    assert updated['account']['principal'] == 'original-owner'
    assert verify_account(updated['account'], 'new-admin', 'rotated-test-password')
    assert SavedLocations(target.with_name('saved.json'), updated['storage_key']).resolve('original-owner', reference)['password'] == 'fixture-secret'


def test_legacy_token_migration_keeps_credentials(inputs):
    source, target, password = inputs
    write_private(target, json.dumps({'token': 'old-fixture-token'}))
    config, _ = deployment.prepare(source, target, 'admin', password)
    assert 'token' not in config
    assert config['storage_key'] == 'old-fixture-token'
    assert config['account']['principal'] == 'token-user'


def run_helper(source, target, password, *extra):
    return subprocess.run([sys.executable, str(HELPER), '--config', str(source), '--destination', str(target), '--username', 'admin', '--password-file', str(password), *extra], capture_output=True, text=True)


def test_check_is_read_only_and_install_creates_staging(inputs):
    source, target, password = inputs
    assert run_helper(source, target, password, '--check').returncode == 2
    assert not target.exists() and not target.with_name('staging').exists()
    assert run_helper(source, target, password).returncode == 0
    assert target.with_name('staging').is_dir()
    assert run_helper(source, target, password, '--check').returncode == 0


@pytest.mark.parametrize('bad', [{'port': 0}, {'policy': {'operations': ['typo']}}, {'unexpected': True}, {'staging_stores': {'Downloads': 'relative'}}])
def test_invalid_update_leaves_live_config_untouched(inputs, bad):
    source, target, password = inputs
    assert run_helper(source, target, password).returncode == 0
    before = target.read_bytes()
    source.write_text(json.dumps(bad))
    result = run_helper(source, target, password)
    assert result.returncode == 1 and target.read_bytes() == before
    assert password.read_text().strip() not in result.stderr


def test_first_install_requires_account(inputs):
    source, target, _ = inputs
    with pytest.raises(ValueError, match='first deployment'):
        deployment.prepare(source, target)
    assert not target.exists()

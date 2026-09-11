import json
import pytest
from remote_fs_browser.cli import main


def test_interactive_setup_detects_network_and_saves_without_launch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('remote_fs_browser.defaults.local_subnets', lambda: ['192.168.50.0/24'])
    monkeypatch.setattr('remote_fs_browser.cli.addresses', lambda *a: [('Network', 'http://192.168.50.12:8080')])
    answers = iter(['2', 'wrong', '9000', '', 'alex'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr('getpass.getpass', lambda _: 'fixture-setup-password')
    monkeypatch.setattr('uvicorn.run', lambda *a, **k: pytest.fail('setup should not start the service'))
    main(['setup'])
    config = json.loads((tmp_path/'remotefs/config.json').read_text())
    assert config['bind'] == '0.0.0.0' and config['port'] == 9000
    assert 'network_ranges' not in config['policy']  # Auto-detect on each start.
    assert config['account']['username'] == 'alex'
    assert '192.168.50.12' in capsys.readouterr().out


def test_setup_custom_subnet_validation_and_existing_account(tmp_path, monkeypatch):
    from remote_fs_browser.auth import make_account
    target = tmp_path/'private.json'
    account = make_account('existing', 'fixture-setup-password', 'owner')
    target.write_text(json.dumps({'account': account, 'storage_key': 'keep-this-key'}))
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    answers = iter(['', '', 'bad-cidr', '192.168.122.12/24'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    main(['setup', '--config', str(target)])
    config = json.loads(target.read_text())
    assert config['policy']['network_ranges'] == ['192.168.122.0/24']
    assert config['account'] == account and config['storage_key'] == 'keep-this-key'

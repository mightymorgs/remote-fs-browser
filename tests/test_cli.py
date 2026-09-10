import json
import os
import subprocess
import sys
import pytest
from remote_fs_browser.cli import main, addresses, build_policy, load_or_create


@pytest.fixture(autouse=True)
def account_prompt(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _: 'tester')
    monkeypatch.setattr('getpass.getpass', lambda _: 'test-password-for-account')


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated per-user config directory on every platform."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'xdg'))
    return tmp_path / 'xdg' / 'remotefs'


@pytest.fixture
def launches(monkeypatch):
    calls = []
    monkeypatch.setattr('uvicorn.run', lambda app, **options: calls.append((app, options)))
    return calls


@pytest.fixture
def detected(monkeypatch, tmp_path):
    volume = tmp_path / 'volume'
    volume.mkdir()
    monkeypatch.setattr('remote_fs_browser.defaults.home_root', lambda: str(tmp_path))
    monkeypatch.setattr('remote_fs_browser.defaults.mounted_volumes', lambda: [str(volume), str(tmp_path / 'missing')])
    monkeypatch.setattr('remote_fs_browser.defaults.local_subnets', lambda: ['192.0.2.0/24'])
    return {'home': str(tmp_path.resolve()), 'volume': str(volume.resolve())}


def test_zero_config_creates_account_and_detects_defaults(home, launches, detected, capsys):
    main(['serve'])
    app, options = launches[-1]
    assert options['host'] == '127.0.0.1' and options['port'] == 8080
    policy = app.state.browser.policy
    assert policy.local_roots == [detected['home'], detected['volume']]
    assert policy.network_ranges == ['192.0.2.0/24']
    assert app.state.root_kinds == {detected['home']: 'home', detected['volume']: 'volume'}
    config = home / 'config.json'
    settings = json.loads(config.read_text())
    key = settings['storage_key']
    assert 'token' not in settings and settings['account']['username'] == 'tester'
    out = capsys.readouterr().out
    assert key not in out and 'tester' in out and '(created)' in out and 'WARNING' not in out and '(home)' in out
    if os.name != 'nt':
        assert config.stat().st_mode & 0o777 == 0o600
    main(['serve'])
    assert json.loads(config.read_text())['storage_key'] == key


def test_flags_override_defaults_and_warn_on_remote_bind(home, launches, detected, tmp_path, capsys):
    main(['serve', '--bind', '0.0.0.0', '--port', '8081', '--root', str(tmp_path), '--allow-network', '198.51.100.0/24'])
    app, options = launches[-1]
    assert options['host'] == '0.0.0.0' and options['port'] == 8081
    assert app.state.browser.policy.local_roots == [str(tmp_path.resolve())]
    assert app.state.browser.policy.network_ranges == ['198.51.100.0/24']
    assert app.state.root_kinds == {}
    assert 'WARNING: reachable from the network' in capsys.readouterr().out


def test_no_defaults_exposes_nothing(home, launches, detected):
    main(['serve', '--no-defaults'])
    policy = launches[-1][0].state.browser.policy
    assert policy.local_roots == [] and policy.network_ranges == []


def test_config_file_beats_defaults_and_flags_beat_config(home, launches, detected, tmp_path):
    config = tmp_path / 'private.json'
    config.write_text(json.dumps({'token': 'x' * 40, 'port': 8765, 'policy': {'local_roots': [], 'network_ranges': []}}))
    main(['serve', '--config', str(config)])
    app, options = launches[-1]
    assert options['port'] == 8765
    assert app.state.browser.policy.local_roots == [] and app.state.browser.policy.network_ranges == []
    main(['serve', '--config', str(config), '--port', '9000', '--allow-network', '192.0.2.0/24'])
    app, options = launches[-1]
    assert options['port'] == 9000 and app.state.browser.policy.network_ranges == ['192.0.2.0/24']


def test_explicit_missing_config_is_an_error(home, launches, tmp_path):
    with pytest.raises(SystemExit):
        main(['serve', '--config', str(tmp_path / 'nope.json')])
    assert not (tmp_path / 'nope.json').exists()


def test_legacy_config_launch(tmp_path, launches, capsys):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'port': 8765, 'policy': {'local_roots': []}}))
    main(['--config', str(config)])
    assert launches[0][1]['port'] == 8765
    assert 'tester' in capsys.readouterr().out
    assert addresses('100.82.14.7', 8080) == [('Tailscale/CGNAT', 'http://100.82.14.7:8080')]


def test_account_setup_does_not_launch_service(home, launches, capsys):
    main(['account', '--username', 'new-user'])
    settings = load_or_create(home / 'config.json', explicit=True)[0]
    assert settings['account']['username'] == 'new-user' and not launches
    assert settings['storage_key'] not in capsys.readouterr().out


def test_headless_service_requires_account(home, monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(SystemExit, match='Set up a username/password'):
        main(['serve'])


def test_read_only_flag_disables_writes(home, launches, detected):
    main(['serve', '--read-only'])
    assert 'write' not in launches[-1][0].state.browser.policy.operations


def test_module_entry_point_help():
    result = subprocess.run([sys.executable, '-m', 'remote_fs_browser', 'serve', '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and '--no-defaults' in result.stdout

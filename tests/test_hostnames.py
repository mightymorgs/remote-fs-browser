import json
import socket
import struct
import subprocess
from types import SimpleNamespace
from remote_fs_browser import hostnames
from remote_fs_browser.discovery import grouped
from remote_fs_browser import Policy


def test_dns_name_and_fallback(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps('nas.office.')))
    assert hostnames.resolve_host('192.168.1.2') == 'nas.office'
    def timeout(*a, **kw):
        assert kw['timeout'] == 1.25
        raise subprocess.TimeoutExpired('lookup', 1.25)
    monkeypatch.setattr(subprocess, 'run', timeout)
    monkeypatch.setattr(hostnames, 'netbios_name', lambda host: 'HOME-PC')
    assert hostnames.resolve_host('192.168.1.2') == 'HOME-PC'


def test_netbios_ignores_group_names(monkeypatch):
    payload = b'\x02' + struct.pack('!15sBH', b'WORKGROUP', 0, 0x8000) + struct.pack('!15sBH', b'OFFICE-PC', 0, 0)
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): assert timeout == 0.5
        def connect(self, address): assert address == ('192.168.1.2',137)
        def send(self, query): self.ident = query[:2]
        def recv(self, size):
            return self.ident + struct.pack('!5H',0x8400,0,1,0,0) + b'\xc0\x0c' + struct.pack('!HHIH',0x21,1,0,len(payload)) + payload
    monkeypatch.setattr(socket, 'socket', lambda *a: Socket())
    assert hostnames.netbios_name('192.168.1.2') == 'OFFICE-PC'


def test_groups_keep_address_and_use_name():
    groups = grouped(Policy(), [], [{'host':'192.168.1.2','name':'NAS','protocols':['smb']}], True)
    assert groups[1]['items'][0] == {'type':'smb','host':'192.168.1.2','label':'NAS'}


def test_frozen_dns_uses_executable_helper(monkeypatch):
    monkeypatch.setattr(hostnames.sys, 'frozen', True, raising=False)
    def lookup(command, **kwargs):
        assert command == [hostnames.sys.executable, '--resolve-host', '192.168.1.2']
        assert kwargs['timeout'] == 1.25
        return SimpleNamespace(stdout=json.dumps('nas.office'))
    monkeypatch.setattr(subprocess, 'run', lookup)
    assert hostnames.resolve_host('192.168.1.2') == 'nas.office'


def test_dns_helper_does_not_start_service(monkeypatch, capsys):
    from remote_fs_browser import cli
    monkeypatch.setattr(socket, 'gethostbyaddr', lambda host: ('nas.office', [], [host]))
    monkeypatch.setattr(cli, 'load_or_create', lambda *args: (_ for _ in ()).throw(AssertionError('must not create config')))
    cli.main(['--resolve-host', '192.168.1.2'])
    assert json.loads(capsys.readouterr().out) == 'nas.office'


def test_missing_dns_and_netbios_leave_address(monkeypatch):
    def missing(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'lookup')
    monkeypatch.setattr(subprocess, 'run', missing)
    monkeypatch.setattr(hostnames, 'netbios_name', lambda host: None)
    assert hostnames.resolve_host('192.168.1.2') is None


def test_scan_resolves_only_live_devices(monkeypatch):
    from remote_fs_browser import discovery
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def connect(address, **kwargs):
        if address == ('192.0.2.1', 445):
            return Connection()
        raise OSError('closed')
    resolved = []
    monkeypatch.setattr(socket, 'create_connection', connect)
    monkeypatch.setattr(discovery, 'resolve_host', lambda host: resolved.append(host) or 'nas.office')
    result = discovery.discover(Policy(network_ranges=['192.0.2.0/30']), scan=True)
    assert resolved == ['192.0.2.1']
    assert result['hosts'] == [{'host': '192.0.2.1', 'protocols': ['smb'], 'name': 'nas.office'}]
    assert result['groups'][1]['items'][0]['label'] == 'nas.office'

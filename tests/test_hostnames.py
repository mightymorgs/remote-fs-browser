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

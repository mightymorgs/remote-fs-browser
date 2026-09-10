"""Authorization policy is explicit and independent of the transport network."""
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import ipaddress
import socket


def normalize(path: str) -> str:
    if not isinstance(path, str) or len(path) > 4096 or '\x00' in path or '\\' in path:
        raise ValueError('Invalid path')
    if any(p in ('.', '..') or ':' in p for p in path.split('/')):
        raise ValueError('Traversal and alternate data streams are not allowed')
    return str(PurePosixPath('/' + path.lstrip('/')))


READ_OPERATIONS = ['discover', 'list', 'stat', 'read']
WRITE_OPERATIONS = ['write', 'mkdir', 'rename', 'delete', 'copy']


@dataclass
class Policy:
    local_roots: list[str] = field(default_factory=list)
    network_ranges: list[str] = field(default_factory=list)
    discovery_ranges: list[str] | None = None
    servers: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=lambda: list(READ_OPERATIONS))
    max_write_bytes: int = 10 * 1024**3
    max_sessions: int = 16
    idle_seconds: float = 300
    operation_timeout: float = 10
    max_entries: int = 10000
    requests_per_minute: int = 120

    def __post_init__(self):
        self.local_roots = [str(Path(p).resolve(strict=True)) for p in self.local_roots]
        for network in self.network_ranges:
            ipaddress.ip_network(network)
        if min(self.max_write_bytes, self.max_sessions, self.idle_seconds, self.operation_timeout, self.max_entries, self.requests_per_minute) <= 0:
            raise ValueError('Policy limits must be positive')
        if self.max_entries > 100000:
            raise ValueError('max_entries must be at most 100000')

    def require(self, operation):
        if operation not in self.operations:
            raise PermissionError('Operation is not permitted')

    def local_root(self, root):
        root = Path(root).resolve(strict=True)
        if not any(root == Path(base) or root.is_relative_to(base) for base in self.local_roots):
            raise PermissionError('Local root is not permitted')
        return str(root)

    def host(self, host):
        if not host or any(c in host for c in '/\\@\x00 \r\n'):
            raise ValueError('Invalid hostname')
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
        allowed = [ipaddress.ip_network(n) for n in self.network_ranges]
        if self.servers and host not in self.servers and not any(ip in self.servers for ip in addresses):
            raise PermissionError('Server is not permitted')
        if not addresses or not all(any(ipaddress.ip_address(ip) in n for n in allowed) for ip in addresses):
            raise PermissionError('Address is outside permitted networks')
        # Pin the address for this operation/session to avoid DNS rebinding.
        return next((ip for ip in addresses if ':' not in ip), addresses[0])

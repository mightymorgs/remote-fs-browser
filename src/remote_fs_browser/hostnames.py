"""Best-effort device labels; connection addresses remain unchanged."""
import json
import secrets
import socket
import struct
import subprocess
import sys


def netbios_name(host):
    """Ask the target directly for its unique NetBIOS workstation/server name."""
    transaction = secrets.randbits(16)
    query = struct.pack('!6H', transaction, 0, 1, 0, 0, 0)
    query += b'\x20CK' + b'A' * 30 + b'\x00\x00\x21\x00\x01'
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect((host, 137))
            sock.send(query)
            data = sock.recv(4096)
        ident, flags, questions, answers, _, _ = struct.unpack_from('!6H', data)
        if ident != transaction or not flags & 0x8000 or flags & 15 or not answers:
            return None
        def skip_name(offset):
            while data[offset]:
                if data[offset] & 0xc0 == 0xc0:
                    return offset + 2
                offset += 1 + data[offset]
            return offset + 1
        offset = 12
        for _ in range(questions):
            offset = skip_name(offset) + 4
        offset = skip_name(offset)
        kind, _, _, length = struct.unpack_from('!HHIH', data, offset)
        payload = data[offset + 10:offset + 10 + length]
        if kind != 0x21 or len(payload) != length:
            return None
        for index in range(payload[0]):
            name, suffix, attributes = struct.unpack_from('!15sBH', payload, 1 + index * 18)
            if suffix in (0, 0x20) and not attributes & 0x8000:
                label = name.decode('ascii').strip(' \x00')
                if label and all(ch.isprintable() for ch in label):
                    return label
    except (OSError, ValueError, IndexError, struct.error, UnicodeError):
        pass
    return None


def resolve_host(host):
    # libc resolver timeouts are not controlled by socket.settimeout. A short-lived
    # subprocess gives DNS a hard deadline without leaving blocked resolver threads.
    try:
        result = subprocess.run(
            [sys.executable, '-c', 'import socket,json,sys; print(json.dumps(socket.gethostbyaddr(sys.argv[1])[0]))', host],
            capture_output=True, text=True, timeout=1.25, check=True,
        )
        label = json.loads(result.stdout).rstrip('.')
        if label and label != host:
            return label
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return netbios_name(host)

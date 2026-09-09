"""Standalone same-port browser and API launcher."""
import argparse
import ipaddress
import json
from pathlib import Path
import secrets


def addresses(bind, port):
    import psutil
    import socket
    hosts = [bind] if bind not in ('0.0.0.0', '::') else sorted({
        item.address.split('%')[0]
        for group in psutil.net_if_addrs().values() for item in group
        if item.family in (socket.AF_INET, socket.AF_INET6)
        and not ipaddress.ip_address(item.address.split('%')[0]).is_link_local
    })
    rows = []
    for host in hosts:
        try:
            address = ipaddress.ip_address(host)
            label = 'Local' if address.is_loopback else 'Tailscale/CGNAT' if address.version == 4 and address in ipaddress.ip_network('100.64.0.0/10') else 'Network'
        except ValueError:
            label = 'Network'
        rows.append((label, f'http://[{host}]:{port}' if ':' in host else f'http://{host}:{port}'))
    return rows


def main(argv=None):
    from .http import create_app
    from .policy import Policy
    import uvicorn
    parser = argparse.ArgumentParser(description='Serve a read-only filesystem browser and API on one port.')
    parser.add_argument('command', nargs='?', choices=['serve'], default='serve')
    parser.add_argument('--config', help='Private JSON configuration (optional for interactive use)')
    parser.add_argument('--bind', help='Listen address; defaults to 127.0.0.1')
    parser.add_argument('--port', type=int, help='Listen port; defaults to 8080')
    parser.add_argument('--root', action='append', help='Allowed local root; repeat for multiple roots (default: current directory)')
    parser.add_argument('--allow-network', action='append', help='Allowed SMB/NFS CIDR; repeat as needed')
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text()) if args.config else {}
    values = config.get('policy', {})
    if not args.config:
        values['local_roots'] = [str(Path.cwd())]
    if args.root:
        values['local_roots'] = [str(Path(root).resolve(strict=True)) for root in args.root]
    if args.allow_network:
        values['network_ranges'] = args.allow_network
    token = config.get('token')
    generated = not token
    if generated:
        token = secrets.token_urlsafe(32)
    app = create_app(Policy(**values), token=token)
    bind = args.bind or config.get('bind', '127.0.0.1')
    port = args.port if args.port is not None else config.get('port', 8080)
    if not 1 <= port <= 65535:
        parser.error('Port must be between 1 and 65535')
    print('\nRemote FS Browser — read-only\n', flush=True)
    for label, url in addresses(bind, port):
        print(f'{label:16} {url}/', flush=True)
    if generated:
        print(f'\nBrowser login token: {token}', flush=True)
    else:
        print('\nUse the service token from your private configuration to sign in.', flush=True)
    print('HTTP is unencrypted. Use a trusted network or an encrypted tunnel.\n', flush=True)
    uvicorn.run(app, host=bind, port=port, access_log=False)

"""Standalone same-port browser and API launcher."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys


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


def config_home():
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / 'remotefs'


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)


def load_or_create(path, explicit):
    """Read the configuration; create the default one with a fresh token on first run."""
    path = Path(path)
    if path.exists():
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            print(f'Warning: {path} is readable by other users; restrict it with chmod 600.', file=sys.stderr)
        return json.loads(path.read_text()), False
    if explicit:
        raise SystemExit(f'Configuration file not found: {path}')
    config = {'token': secrets.token_urlsafe(48), 'policy': {}}
    write_private(path, json.dumps(config, indent=2) + '\n')
    return config, True


def build_policy(args, config):
    """Flags beat the config file, which beats auto-detected defaults; lists replace, never merge."""
    from . import defaults
    from .policy import Policy
    values = dict(config.get('policy', {}))
    kinds = {}
    if args.root:
        values['local_roots'] = [str(Path(root).resolve(strict=True)) for root in args.root]
    elif 'local_roots' not in values and not args.no_defaults:
        home = defaults.readable_dirs([defaults.home_root()])
        values['local_roots'] = defaults.readable_dirs([*home, *defaults.mounted_volumes()])
        kinds = {root: 'home' if root in home else 'volume' for root in values['local_roots']}
    if args.allow_network:
        values['network_ranges'] = list(args.allow_network)
    elif 'network_ranges' not in values and not args.no_defaults:
        values['network_ranges'] = defaults.local_subnets()
    return Policy(**values), kinds


def bundled_library():
    """Frozen Windows builds ship libnfs.dll beside the executable."""
    if not getattr(sys, 'frozen', False):
        return None
    for folder in (Path(sys.executable).parent, Path(getattr(sys, '_MEIPASS', ''))):
        candidate = folder / 'libnfs.dll'
        if candidate.is_file():
            return str(candidate)
    return None


def main(argv=None):
    from . import __version__
    parser = argparse.ArgumentParser(prog='remotefs', description='Serve a read-only filesystem browser and API on one port.')
    parser.add_argument('command', nargs='?', choices=['serve'], default='serve')
    parser.add_argument('--version', action='version', version=f'remotefs {__version__}')
    parser.add_argument('--config', help='Private JSON configuration; defaults to the per-user config, created on first run')
    parser.add_argument('--bind', help='Listen address; defaults to 127.0.0.1. Any other address is reachable from the network')
    parser.add_argument('--port', type=int, help='Listen port; defaults to 8080')
    parser.add_argument('--root', action='append', help='Allowed local root; repeat for multiple roots (default: home and mounted volumes)')
    parser.add_argument('--allow-network', action='append', help='Allowed SMB/NFS CIDR; repeat as needed (default: this host\'s private subnets)')
    parser.add_argument('--no-defaults', action='store_true', help='Do not auto-detect roots or networks; expose only what config and flags name')
    parser.add_argument('--print-token', action='store_true', help='Print the service token and exit')
    args = parser.parse_args(argv)

    library = bundled_library()
    if library:
        os.environ.setdefault('LIBNFS_LIBRARY', library)
    path = Path(args.config) if args.config else config_home() / 'config.json'
    config, created = load_or_create(path, explicit=bool(args.config))
    token = config.get('token')
    ephemeral = not token
    if ephemeral:
        token = secrets.token_urlsafe(32)
    if args.print_token:
        print(token)
        return

    from .http import create_app
    import uvicorn
    policy, kinds = build_policy(args, config)
    app = create_app(policy, token=token)
    app.state.root_kinds = kinds
    bind = args.bind or config.get('bind', '127.0.0.1')
    port = args.port if args.port is not None else config.get('port', 8080)
    if not 1 <= port <= 65535:
        parser.error('Port must be between 1 and 65535')
    try:
        remote = not ipaddress.ip_address(bind).is_loopback
    except ValueError:
        remote = bind not in ('localhost',)

    show_token = created or ephemeral or sys.stdout.isatty()
    lines = [f'remotefs {__version__} — read-only', '']
    lines += [f'{label:16} {url}/' for label, url in addresses(bind, port)]
    lines += ['', f'{"Config":16} {path}{" (created)" if created else ""}']
    if ephemeral:
        lines.append(f'{"Token":16} {token}   (temporary; add a token to the config to keep it)')
    elif show_token:
        lines.append(f'{"Token":16} {token}')
    else:
        lines.append(f'{"Token":16} stored in the config; run remotefs --print-token to show it')
    roots = [f'{root} ({kinds[root]})' if root in kinds else root for root in policy.local_roots]
    lines.append(f'{"Roots":16} {", ".join(roots) or "none"}')
    lines.append(f'{"Networks":16} {", ".join(policy.network_ranges) or "none (SMB/NFS disabled)"}')
    lines.append(f'{"Access":16} read-only: {", ".join(policy.operations)}')
    lines.append('')
    if remote:
        lines.append('WARNING: reachable from the network; anyone with the token can read every root above.')
    lines.append('HTTP is unencrypted. Use a trusted network or an encrypted tunnel.')
    print('\n'.join(lines) + '\n', flush=True)
    uvicorn.run(app, host=bind, port=port, access_log=False)

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


def load_or_create(path, explicit):
    """Read the configuration; create the default one with a private storage key on first run."""
    from .store import write_private
    path = Path(path)
    if path.exists():
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            print(f'Warning: {path} is readable by other users; restrict it with chmod 600.', file=sys.stderr)
        return json.loads(path.read_text()), False
    if explicit:
        raise SystemExit(f'Configuration file not found: {path}')
    config = {'storage_key': secrets.token_urlsafe(48), 'policy': {}}
    write_private(path, json.dumps(config, indent=2) + '\n')
    return config, True


def build_policy(args, config):
    """Flags beat the config file, which beats auto-detected defaults; lists replace, never merge."""
    from . import defaults
    from .policy import Policy, READ_OPERATIONS, WRITE_OPERATIONS
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
    if getattr(args, 'read_only', False):
        values['operations'] = list(READ_OPERATIONS)
    elif getattr(args, 'read_write', False):
        values['operations'] = READ_OPERATIONS + WRITE_OPERATIONS
    else:
        values.setdefault('operations', READ_OPERATIONS + WRITE_OPERATIONS)
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
    # Console-script directories can contain Impacket's smbclient.py, which
    # shadows smbprotocol's smbclient package in this process and its workers.
    if not getattr(sys, 'frozen', False) and sys.path and sys.path[0] and Path(sys.argv[0]).name in ('remotefs', 'remotefs.exe', 'remote-fs-browser', 'remote-fs-browser.exe'):
        if Path(sys.path[0]).resolve() == Path(sys.argv[0]).resolve().parent:
            sys.path.pop(0)
    from . import __version__
    parser = argparse.ArgumentParser(prog='remotefs', description='Serve a remote filesystem manager and API on one port.')
    parser.add_argument('command', nargs='?', choices=['serve', 'account'], default='serve')
    parser.add_argument('--version', action='version', version=f'remotefs {__version__}')
    parser.add_argument('--config', help='Private JSON configuration; defaults to the per-user config, created on first run')
    parser.add_argument('--bind', help='Listen address; defaults to 127.0.0.1. Any other address is reachable from the network')
    parser.add_argument('--port', type=int, help='Listen port; defaults to 8080')
    parser.add_argument('--root', action='append', help='Allowed local root; repeat for multiple roots (default: home and mounted volumes)')
    parser.add_argument('--allow-network', action='append', help='Allowed SMB/NFS CIDR; repeat as needed (default: this host\'s private subnets)')
    parser.add_argument('--no-defaults', action='store_true', help='Do not auto-detect roots or networks; expose only what config and flags name')
    access = parser.add_mutually_exclusive_group()
    access.add_argument('--read-only', action='store_true', help='Disable all filesystem changes')
    access.add_argument('--read-write', action='store_true', help='Enable filesystem changes (overrides configured operations)')
    parser.add_argument('--username', help='Username for account setup or password reset')
    parser.add_argument('--password-stdin', action='store_true', help='Read the new password from standard input for account setup')
    parser.add_argument('--resolve-host', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.resolve_host:
        import socket
        print(json.dumps(socket.gethostbyaddr(args.resolve_host)[0]))
        return

    library = bundled_library()
    if library:
        os.environ.setdefault('LIBNFS_LIBRARY', library)
    path = Path(args.config) if args.config else config_home() / 'config.json'
    config, created = load_or_create(path, explicit=bool(args.config) and args.command != 'account')
    if args.command == 'account' or not config.get('account'):
        import getpass
        from .auth import make_account
        from .store import write_private
        if not sys.stdin.isatty() and not args.password_stdin:
            raise SystemExit('Set up a username/password first: remotefs account --username YOUR_NAME (or use --password-stdin).')
        username = args.username or input('Username: ').strip()
        if args.password_stdin:
            if not args.username:
                parser.error('--password-stdin requires --username')
            password = sys.stdin.readline().rstrip('\r\n')
        else:
            password = getpass.getpass('New password (at least 12 characters): ')
            if password != getpass.getpass('Confirm password: '):
                raise SystemExit('Passwords do not match')
        principal = config.get('account', {}).get('principal', 'token-user' if config.get('token') else 'owner')
        config['account'] = make_account(username, password, principal)
        password = None
        # Preserve the existing vault key so saved NAS credentials remain readable.
        config.setdefault('storage_key', config.get('token') or secrets.token_urlsafe(48))
        config.pop('token', None)
        write_private(path, json.dumps(config, indent=2) + '\n')
        if args.command == 'account':
            print('Account saved. Restart the service to apply the change and end existing logins.')
            return

    from .http import create_app
    from .store import SavedLocations, StoreLocked
    import uvicorn
    policy, kinds = build_policy(args, config)
    saved, saved_note = None, ''
    try:
        saved = SavedLocations(path.with_name('saved.json'), config['storage_key'])
    except StoreLocked:
        saved_note = 'saved locations use a different storage key; restore the matching config to unlock them'
    app = create_app(policy, account=config['account'], root_kinds=kinds, saved_locations=saved,
                     staging_stores=config.get('staging_stores', {'Downloads': str(path.parent / 'staging')}))
    bind = args.bind or config.get('bind', '127.0.0.1')
    port = args.port if args.port is not None else config.get('port', 8080)
    if not 1 <= port <= 65535:
        parser.error('Port must be between 1 and 65535')
    try:
        remote = not ipaddress.ip_address(bind).is_loopback
    except ValueError:
        remote = bind not in ('localhost',)

    writable = any(op in policy.operations for op in ('write', 'mkdir', 'rename', 'delete'))
    access_mode = 'read/write' if writable else 'read-only'
    lines = [f'remotefs {__version__} — {access_mode}', '']
    lines += [f'{label:16} {url}/' for label, url in addresses(bind, port)]
    lines += ['', f'{"Config":16} {path}{" (created)" if created else ""}']
    lines.append(f'{"Account":16} {config["account"]["username"]}')
    roots = [f'{root} ({kinds[root]})' if root in kinds else root for root in policy.local_roots]
    lines.append(f'{"Roots":16} {", ".join(roots) or "none"}')
    lines.append(f'{"Networks":16} {", ".join(policy.network_ranges) or "none (SMB/NFS disabled)"}')
    lines.append(f'{"Access":16} {access_mode}: {", ".join(policy.operations)}')
    lines.append(f'{"Remembered":16} {saved_note or f"{len(saved.records)} saved location(s) in {saved.path}"}')
    from .discovery import share_enumeration_available
    if not share_enumeration_available():
        lines.append(f'{"SMB shares":16} enumeration unavailable (impacket not installed); shares can still be entered by name')
    lines.append('')
    if remote:
        lines.append(f'WARNING: reachable from the network; signed-in users have {access_mode} access to the roots above.')
    lines.append('HTTP is unencrypted. Use a trusted network or an encrypted tunnel.')
    print('\n'.join(lines) + '\n', flush=True)
    uvicorn.run(app, host=bind, port=port, access_log=False)

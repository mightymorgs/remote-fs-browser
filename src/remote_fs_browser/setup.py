"""Interactive first-run choices; configuration files remain an implementation detail."""
import ipaddress
from pathlib import Path


def ask(label, default, validate):
    while True:
        answer = input(f'{label} [{default}]: ').strip() or str(default)
        try:
            return validate(answer)
        except (ValueError, OSError) as error:
            print(f'Please try again: {error}')


def configure(args, config):
    from .cli import addresses, build_policy
    from .defaults import local_subnets
    policy, _ = build_policy(args, config)
    detected = local_subnets()
    print('\nSet up remotefs — press Enter to keep each default.')
    print('Detected network addresses:')
    for label, url in addresses('0.0.0.0', args.port or config.get('port', 8080)):
        print(f'  {label}: {url}')
    print('Detected scan ranges: ' + (', '.join(detected) or 'none'))
    print('Local folders: ' + (', '.join(policy.local_roots) or 'none'))
    print('1: This computer only   2: Allow browsers on other devices')

    def access(value):
        if value not in ('1', '2'):
            raise ValueError('choose 1 or 2')
        return '127.0.0.1' if value == '1' else '0.0.0.0'

    current_bind = args.bind or config.get('bind', '127.0.0.1')
    config['bind'] = ask('Browser access', '1' if current_bind in ('127.0.0.1', '::1', 'localhost') else '2', access)

    def port(value):
        result = int(value)
        if not 1 <= result <= 65535:
            raise ValueError('use a port from 1 to 65535')
        return result

    config['port'] = ask('Port', args.port or config.get('port', 8080), port)

    def networks(value):
        if value.lower() == 'auto':
            return None
        if value.lower() == 'none':
            return []
        rows = [str(ipaddress.ip_network(item.strip(), strict=False)) for item in value.split(',')]
        if any(ipaddress.ip_network(row).version != 4 for row in rows):
            raise ValueError('network discovery uses IPv4 ranges')
        return rows

    current = config.get('policy', {}).get('network_ranges', [] if args.no_defaults else None)
    selected = ask('Scan ranges (auto, none, or comma-separated CIDRs)', ', '.join(current) if current else 'none' if current == [] else 'auto', networks)
    values = config.setdefault('policy', {})
    if selected is None:
        values.pop('network_ranges', None)
    else:
        values['network_ranges'] = selected
    if args.allow_network:
        values['network_ranges'] = args.allow_network
    if args.no_defaults:
        values.setdefault('local_roots', [])
    if args.root:
        values['local_roots'] = [str(Path(root).resolve(strict=True)) for root in args.root]
    if args.read_only or args.read_write:
        values['operations'] = policy.operations
    if args.bind:
        config['bind'] = args.bind
    if args.port is not None:
        config['port'] = args.port
    print('ZIP preparation uses a default folder. You can choose a folder in the browser.')
    return config

#!/usr/bin/env python3
"""Prepare private service configuration without prompts or plaintext password storage."""
import argparse
import base64
import ipaddress
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.request


def prepare(source, destination, username=None, password_file=None):
    from remote_fs_browser.auth import make_account, verify_account
    from remote_fs_browser.policy import Policy, READ_OPERATIONS, WRITE_OPERATIONS
    from remote_fs_browser.store import SavedLocations

    incoming = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    target = Path(destination)
    previous = json.loads(target.read_text(encoding='utf-8-sig')) if target.exists() else {}
    if not isinstance(incoming, dict) or set(incoming) - {'bind', 'port', 'policy', 'account', 'storage_key', 'token', 'staging_stores'}:
        raise ValueError('Unknown configuration fields')
    config = {**previous, **incoming}
    # A redeployment must not orphan the existing encrypted vault or its owner.
    key = previous.get('storage_key') or previous.get('token') or incoming.get('storage_key') or incoming.get('token')
    config['storage_key'] = key or secrets.token_urlsafe(48)
    account = previous.get('account') or incoming.get('account')
    principal = previous.get('account', {}).get('principal') or ('token-user' if previous.get('token') else (account or {}).get('principal', 'token-user' if incoming.get('token') else 'owner'))
    if account:
        account = {**account, 'principal': principal}
    if bool(username) != bool(password_file):
        raise ValueError('Supply both --username and --password-file')
    if password_file:
        password = Path(password_file).read_text(encoding='utf-8-sig').rstrip('\r\n')
        if not account or not verify_account(account, username, password):
            account = make_account(username, password, principal)
    if not account:
        raise ValueError('A first deployment needs an account in the config, or --username and --password-file')
    if (account.get('algorithm') != 'scrypt-131072-8-1' or not account.get('username')
            or not account.get('principal') or len(base64.b64decode(account.get('salt', ''), validate=True)) != 16
            or len(base64.b64decode(account.get('hash', ''), validate=True)) != 32):
        raise ValueError('Invalid password account configuration')
    config['account'] = account
    config.pop('token', None)
    if not isinstance(config['storage_key'], str) or not config['storage_key']:
        raise ValueError('Invalid storage key')
    if target.with_name('saved.json').exists():
        SavedLocations(target.with_name('saved.json'), config['storage_key'])
    policy = config.setdefault('policy', {})
    policy.setdefault('local_roots', [])
    policy.setdefault('network_ranges', [])
    policy.setdefault('operations', READ_OPERATIONS + WRITE_OPERATIONS)
    Policy(**policy)
    if any(op not in READ_OPERATIONS + WRITE_OPERATIONS for op in policy['operations']):
        raise ValueError('Unknown filesystem operation')
    for root in policy['local_roots']:
        if not Path(root).is_absolute() or not Path(root).is_dir():
            raise ValueError('Local roots must be existing absolute directories')
    config.setdefault('bind', '127.0.0.1')
    ipaddress.ip_address(config['bind'])
    config.setdefault('port', 8080)
    if type(config['port']) is not int or not 1 <= config['port'] <= 65535:
        raise ValueError('Port must be an integer between 1 and 65535')
    stores = config.setdefault('staging_stores', {'Downloads': str(target.parent / 'staging')})
    if not isinstance(stores, dict) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in stores.values()):
        raise ValueError('Staging stores must map labels to absolute directory paths')
    return config, config != previous


def health(config_path):
    config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    host = config['bind']
    host = '127.0.0.1' if host == '0.0.0.0' else '::1' if host == '::' else host
    host = f'[{host}]' if ':' in host else host
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        try:
            with opener.open(f'http://{host}:{config["port"]}/', timeout=2) as response:
                if response.status == 200:
                    print('Service ready')
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('Service did not become ready; inspect the service logs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--destination')
    parser.add_argument('--username')
    parser.add_argument('--password-file')
    parser.add_argument('--check', action='store_true', help='Exit 2 if configuration would change; write nothing')
    parser.add_argument('--health-check', action='store_true')
    parser.add_argument('--systemd-write-paths', action='store_true')
    args = parser.parse_args()
    if args.systemd_write_paths:
        config = json.loads(Path(args.config).read_text())
        paths = [str(Path(args.config).parent), *config['policy']['local_roots'], *config['staging_stores'].values()]
        print('ReadWritePaths=' + ' '.join(json.dumps(str(Path(p).resolve()), ensure_ascii=False).replace('%', '%%') for p in dict.fromkeys(paths)))
        return
    if args.health_check:
        health(args.config)
        return
    if not args.destination:
        parser.error('--destination is required')
    config, changed = prepare(args.config, args.destination, args.username, args.password_file)
    if args.check:
        print('Configuration needs updating' if changed else 'Configuration unchanged')
        return 2 if changed else 0
    for folder in config['staging_stores'].values():
        Path(folder).mkdir(parents=True, exist_ok=True, mode=0o700)
    if changed:
        from remote_fs_browser.store import write_private
        write_private(args.destination, json.dumps(config, indent=2) + '\n')
    print('Configuration updated' if changed else 'Configuration unchanged')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        # Do not include configuration values or password material in automation logs.
        print(f'Deployment configuration failed ({type(error).__name__}); check account, policy and private file paths.', file=sys.stderr)
        sys.exit(1)

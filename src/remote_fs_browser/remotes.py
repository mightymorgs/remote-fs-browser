"""Private, user-managed cloud connections. Only provider data, never rclone flags."""
import configparser
import io
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
from .policy import normalize
from .store import write_private


def field(name, label, secret=False, required=False, default=''):
    return dict(name=name, label=label, secret=secret, required=required, default=default)


# Deliberately expose provider fields, not arbitrary rclone options (some execute programs).
PROVIDERS = {
    's3': dict(label='Amazon S3 / S3 compatible', fields=[field('provider', 'S3 provider (AWS, Minio, Other…)', default='AWS'), field('access_key_id', 'Access key ID', required=True), field('secret_access_key', 'Secret access key', True, True), field('region', 'Region', default='us-east-1'), field('endpoint', 'Endpoint URL (optional for AWS)'), field('session_token', 'Session token (optional)', True)]),
    'b2': dict(label='Backblaze B2', fields=[field('account', 'Application key ID', required=True), field('key', 'Application key', True, True)]),
    'dropbox': dict(label='Dropbox', oauth=True, fields=[field('token', 'Authorization JSON', True, True)]),
    'drive': dict(label='Google Drive', oauth=True, fields=[field('token', 'Authorization JSON', True, True), field('team_drive', 'Shared drive ID (optional)')]),
    'onedrive': dict(label='OneDrive', oauth=True, fields=[field('token', 'Authorization JSON', True, True), field('drive_id', 'Drive ID', required=True), field('drive_type', 'Drive type (personal, business, documentLibrary)', default='personal')]),
    'webdav': dict(label='WebDAV / Nextcloud', fields=[field('url', 'WebDAV URL', required=True), field('vendor', 'Vendor (other, nextcloud, owncloud)', default='other'), field('user', 'Username', required=True), field('pass', 'Password / app password', True, True)]),
    'azureblob': dict(label='Azure Blob Storage', fields=[field('account', 'Storage account', required=True), field('key', 'Account key', True, True)]),
}


class RemoteStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.path = self.directory / 'connections.json'
        self.records = json.loads(self.path.read_text()) if self.path.exists() else {}

    @staticmethod
    def providers():
        return {'available': shutil.which('rclone') is not None,
                'providers': [dict(id=name, **value) for name, value in PROVIDERS.items()]}

    def record(self, principal, reference):
        row = self.records.get(reference)
        if not row or row['principal'] != principal:
            raise PermissionError('Cloud connection not found')
        return row

    def config_path(self, reference):
        # References always originate in this store, never from user-provided paths.
        if reference not in self.records:
            raise PermissionError('Cloud connection not found')
        return self.directory / (reference + '.conf')

    def public(self, reference, row, details=False):
        result = {k: row[k] for k in ('label', 'provider', 'root', 'read_only')}
        result.update(id=reference, type='rclone', endpoint=reference, managed=True)
        if details:
            config = configparser.RawConfigParser()
            config.read(self.config_path(reference))
            fields = PROVIDERS[row['provider']]['fields']
            result['options'] = {f['name']: config.get('remote', f['name'], fallback='') for f in fields if not f['secret']}
            result['saved_secrets'] = [f['name'] for f in fields if f['secret'] and config.get('remote', f['name'], fallback='')]
        return result

    def list(self, principal):
        with self.lock:
            return [self.public(key, row) for key, row in self.records.items() if row['principal'] == principal]

    def get(self, principal, reference):
        with self.lock:
            return self.public(reference, self.record(principal, reference), True)

    def endpoint(self, principal, reference):
        with self.lock:
            row = self.record(principal, reference)
            return dict(type='rclone', remote='remote', config=str(self.config_path(reference)), root=row['root'], read_only=row['read_only'])

    def save(self, principal, data, reference=None):
        with self.lock:
            old = self.record(principal, reference) if reference else None
            provider = data.get('provider')
            if provider not in PROVIDERS:
                raise ValueError('Choose a supported cloud provider')
            if old and provider != old['provider']:
                raise ValueError('Create a new connection to change provider')
            label = data.get('label', '')
            if not isinstance(label, str) or not label.strip() or len(label) > 120:
                raise ValueError('Enter a connection name (up to 120 characters)')
            read_only = data.get('read_only', False)
            if not isinstance(read_only, bool):
                raise ValueError('read_only must be a boolean')
            root = normalize(data.get('root') or '/')
            options = data.get('options', {})
            fields = PROVIDERS[provider]['fields']
            if not isinstance(options, dict) or set(options) - {f['name'] for f in fields}:
                raise ValueError('Unsupported provider option')
            config = configparser.RawConfigParser()
            if old:
                config.read(self.config_path(reference))
            else:
                if len(self.list(principal)) >= 100:
                    raise ValueError('Connection limit reached')
                config['remote'] = {'type': provider}
            for f in fields:
                name = f['name']
                value = options.get(name, config.get('remote', name, fallback=f['default']))
                if not isinstance(value, str) or len(value) > 12000 or ('\x00' in value or (name != 'token' and any(c in value for c in '\r\n'))):
                    raise ValueError('Provider fields must be single-line text')
                if f['secret'] and not value and old:
                    value = config.get('remote', name, fallback='')
                if f['required'] and not value:
                    raise ValueError(f['label'] + ' is required')
                if name == 'token' and value:
                    try:
                        token = json.loads(value)
                        if not isinstance(token, dict) or not token.get('access_token'):
                            raise ValueError()
                    except ValueError:
                        raise ValueError('Paste the complete authorization JSON from rclone authorize') from None
                    value = json.dumps(token, separators=(',', ':'))
                if name == 'pass' and value and value != config.get('remote', name, fallback=''):
                    try:
                        process = subprocess.run(['rclone', 'obscure', '-'], input=value.encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
                    except FileNotFoundError:
                        raise ValueError('Install rclone on the service host first') from None
                    if process.returncode:
                        raise ValueError('Could not store provider password')
                    value = process.stdout.decode().strip()
                config['remote'][name] = value
            reference = reference or 'cloud-' + secrets.token_hex(12)
            output = io.StringIO()
            config.write(output)
            write_private(self.directory / (reference + '.conf'), output.getvalue())
            self.records[reference] = dict(principal=principal, provider=provider, label=label.strip(), root=root, read_only=read_only)
            write_private(self.path, json.dumps(self.records) + '\n')
            return self.public(reference, self.records[reference])

    def remove(self, principal, reference):
        with self.lock:
            self.record(principal, reference)
            config = self.config_path(reference)
            del self.records[reference]
            write_private(self.path, json.dumps(self.records) + '\n')
            config.unlink(missing_ok=True)

"""Remembered SMB/NFS locations for the standalone service, sealed under the service token."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

FORMAT = 1
CREDENTIAL_KEYS = ('username', 'password', 'domain')


class StoreLocked(Exception):
    """The file exists but was sealed under a different service token."""


def write_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)


def derive(token, salt):
    return hashlib.scrypt(token.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


class SavedLocations:
    def __init__(self, path, token, limit=200):
        self.path, self.limit = Path(path), limit
        self.records = []
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.salt = base64.b64decode(data['salt'])
            self.key = derive(token, self.salt)
            self.records = self._open(data)
        else:
            self.salt = secrets.token_bytes(16)
            self.key = derive(token, self.salt)

    def _open(self, data):
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        try:
            plain = AESGCM(self.key).decrypt(base64.b64decode(data['nonce']), base64.b64decode(data['sealed']), None)
        except InvalidTag:
            raise StoreLocked(f'{self.path} was saved under a different service token') from None
        return json.loads(plain)

    def save(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        sealed = AESGCM(self.key).encrypt(nonce, json.dumps(self.records).encode(), None)
        write_private(self.path, json.dumps({'format': FORMAT, 'salt': base64.b64encode(self.salt).decode(),
                                             'nonce': base64.b64encode(nonce).decode(),
                                             'sealed': base64.b64encode(sealed).decode()}) + '\n')

    @staticmethod
    def public(record):
        return {'id': record['id'], 'label': record['label'], 'descriptor': record['descriptor'],
                'created': record['created'], 'has_credentials': bool(record.get('credential'))}

    def list(self, principal):
        return [self.public(row) for row in self.records if row['principal'] == principal]

    def add(self, principal, descriptor, credentials=None, label=None):
        """Remember a folder. Folders on one share share credentials; the same folder is updated in place."""
        path = descriptor.get('path', '/')
        identity = {k: v for k, v in descriptor.items() if k not in ('path', 'credential_id')}
        credential = {k: v for k, v in (credentials or {}).items() if k in CREDENTIAL_KEYS and v}
        siblings = [row for row in self.records if row['principal'] == principal
                    and {k: v for k, v in row['descriptor'].items() if k != 'path'} == identity]
        if credential:
            for row in siblings:
                row['credential'] = dict(credential)
        else:
            credential = next((dict(row['credential']) for row in siblings if row.get('credential')), {})
        for row in siblings:
            if row['descriptor'].get('path', '/') == path:
                row['label'] = label or row['label']
                self.save()
                return row['id']
        if len(self.list(principal)) >= self.limit:
            raise ValueError('Too many saved locations; forget one first')
        row = {'id': secrets.token_urlsafe(12), 'principal': principal, 'label': label or self.default_label(identity),
               'descriptor': {**identity, 'path': path}, 'created': time.time(), 'credential': credential}
        self.records.append(row)
        self.save()
        return row['id']

    @staticmethod
    def default_label(descriptor):
        if descriptor.get('type') == 'local':
            return str(descriptor.get('root', ''))
        location = str(descriptor.get('share') or descriptor.get('export') or '').lstrip('/')
        return f"{descriptor.get('host', '')}/{location}".strip('/')

    def remove(self, principal, reference):
        before = len(self.records)
        self.records = [row for row in self.records if not (row['principal'] == principal and row['id'] == reference)]
        if len(self.records) != before:
            self.save()
        return len(self.records) != before

    def get(self, principal, reference):
        for row in self.records:
            if row['principal'] == principal and row['id'] == reference:
                return row
        raise PermissionError('Saved location not found')

    def resolve(self, principal, reference):
        """Credential resolver for create_app: the principal must own the saved location."""
        return dict(self.get(principal, reference).get('credential') or {})

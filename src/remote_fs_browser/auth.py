"""Single-account password authentication for the standalone service."""
import base64
import hashlib
import hmac
import secrets


def password_hash(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**17, r=8, p=1,
                          dklen=32, maxmem=256 * 1024**2)


def make_account(username, password, principal='owner'):
    username = username.strip()
    if not username or len(username) > 64 or any(c.isspace() or ord(c) < 32 for c in username):
        raise ValueError('Use a username of 1–64 characters without spaces')
    if not 12 <= len(password) <= 1024:
        raise ValueError('Use a password of 12–1024 characters')
    salt = secrets.token_bytes(16)
    return {'username': username, 'principal': principal, 'algorithm': 'scrypt-131072-8-1',
            'salt': base64.b64encode(salt).decode(),
            'hash': base64.b64encode(password_hash(password, salt)).decode()}


def verify_account(account, username, password):
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
        return False
    if account.get('algorithm') != 'scrypt-131072-8-1':
        return False
    actual = password_hash(password, base64.b64decode(account['salt']))
    valid = hmac.compare_digest(actual, base64.b64decode(account['hash']))
    return valid and hmac.compare_digest(username.encode(), account['username'].encode())

"""Mount storage as a folder or drive on the computer running the service, using rclone.

Windows mounts a drive letter through WinFsp (`rclone mount --network-mode`), Linux uses FUSE
(`rclone mount`) and macOS uses rclone's built-in NFS server with the system NFS client
(`rclone nfsmount`), so macOS needs no kernel extension. Each mount runs its own rclone process
with a private config, a persistent VFS cache and a loopback remote-control endpoint protected by
a random password. The service asks rclone to finish pending uploads and quit, rather than killing
it, so unmounting does not lose writes.
"""
import base64
import configparser
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import string
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from .policy import normalize
from .store import write_private

MIN_NFSMOUNT = (1, 65)
# The official, unmodified WinFsp installer. WinFsp's FLOSS exception permits distributing it with
# open-source software that credits "WinFsp - Windows File System Proxy, Copyright (C) Bill Zissimopoulos".
WINFSP = {'version': '2.1.25156', 'url': 'https://github.com/winfsp/winfsp/releases/download/v2.1/winfsp-2.1.25156.msi',
          'sha256': '073a70e00f77423e34bed98b86e600def93393ba5822204fac57a29324db9f7a'}
WINFSP_NOTICE = {'text': 'WinFsp - Windows File System Proxy, Copyright (C) Bill Zissimopoulos',
                 'url': 'https://github.com/winfsp/winfsp'}


class MountError(ValueError):
    """A mount request that cannot be carried out; the message is safe to show."""


def platform_method(system=None):
    system = system or sys.platform
    return 'winfsp' if system.startswith('win') else 'nfs' if system == 'darwin' else 'fuse'


def rclone_binary():
    """Explicit override, then an rclone shipped beside a frozen build, then PATH."""
    if os.environ.get('REMOTEFS_RCLONE'):
        return os.environ['REMOTEFS_RCLONE']
    if getattr(sys, 'frozen', False):
        for folder in (Path(sys.executable).parent, Path(getattr(sys, '_MEIPASS', ''))):
            for name in ('rclone.exe', 'rclone'):
                if (folder / name).is_file():
                    return str(folder / name)
    return shutil.which('rclone')


def rclone_version(binary):
    try:
        output = subprocess.run([binary, 'version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, timeout=15).stdout.decode(errors='replace')
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'rclone v(\d+)\.(\d+)', output)
    return (int(match[1]), int(match[2])) if match else None


def winfsp_installed():
    roots = [os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), r'C:\Program Files (x86)']
    if any(root and (Path(root) / 'WinFsp' / 'bin' / 'winfsp-x64.dll').is_file() for root in roots):
        return True
    try:
        import winreg
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WinFsp', 0, winreg.KEY_READ | view) as key:
                    return bool(winreg.QueryValueEx(key, 'InstallDir')[0])
            except OSError:
                continue
    except ImportError:
        pass
    return False


def install_winfsp(directory, opener=urllib.request.urlopen, run=subprocess.run):
    """Download the pinned WinFsp installer, check its hash and install it (Windows asks to elevate)."""
    import hashlib
    target = Path(directory) / f"winfsp-{WINFSP['version']}.msi"
    digest = hashlib.sha256()
    with opener(WINFSP['url'], timeout=120) as response, open(target, 'wb') as output:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != WINFSP['sha256']:
        target.unlink(missing_ok=True)
        raise MountError('The downloaded WinFsp installer did not match the expected checksum')
    # Start-Process -Verb RunAs shows the UAC prompt when the service is not already elevated.
    quoted = str(target).replace("'", "''")  # PowerShell single-quoted string escaping
    script = (f"$p = Start-Process msiexec.exe -ArgumentList '/i', '\"{quoted}\"', '/qb', '/norestart' "
              "-Verb RunAs -Wait -PassThru; exit $p.ExitCode")
    result = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    target.unlink(missing_ok=True)
    if result.returncode not in (0, 3010):
        raise MountError('WinFsp was not installed (the installer was cancelled or failed)')
    return {'installed': True, 'version': WINFSP['version'], 'restart_needed': result.returncode == 3010}


def windows_system_account():
    return os.environ.get('USERNAME', '').upper() in ('SYSTEM', f"{os.environ.get('COMPUTERNAME', '').upper()}$")


def prerequisites(binary=None, system=None):
    """What this host needs before it can mount, with install guidance for anything missing."""
    method = platform_method(system)
    binary = binary if binary is not None else rclone_binary()
    missing = []
    version = rclone_version(binary) if binary else None
    if not binary or not version:
        missing.append({'name': 'rclone', 'detail': 'rclone runs each mount.',
                        'install': 'Install rclone from https://rclone.org/install/ and restart remotefs.'})
    elif method == 'nfs' and version < MIN_NFSMOUNT:
        missing.append({'name': 'rclone 1.65+', 'detail': f'rclone {version[0]}.{version[1]} is too old for macOS mounts.',
                        'install': 'Upgrade rclone (brew upgrade rclone) and restart remotefs.'})
    if method == 'winfsp' and not winfsp_installed():
        missing.append({'name': 'WinFsp', 'detail': 'WinFsp lets Windows show a mount as a drive letter.',
                        'install': 'Run the remotefs installer again, or install WinFsp from https://winfsp.dev/rel/ '
                                   '(winget install WinFsp.WinFsp).'})
    if method == 'fuse' and not (Path('/dev/fuse').exists() and (shutil.which('fusermount3') or shutil.which('fusermount'))):
        missing.append({'name': 'FUSE', 'detail': 'FUSE lets Linux show a mount as a folder.',
                        'install': 'Install fuse3 (for example: sudo apt install fuse3).'})
    return {'method': method, 'available': not missing, 'missing': missing,
            'rclone': f'{version[0]}.{version[1]}' if version else None}


def obscure(binary, secret):
    """rclone stores passwords in its own reversible obscured form, never plain text."""
    process = subprocess.run([binary, 'obscure', '-'], input=secret.encode(), stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=15)
    if process.returncode:
        raise MountError('Could not prepare the login for rclone')
    return process.stdout.decode().strip()


def remote_for(descriptor, credentials, endpoint_config, binary):
    """The rclone [remote] section and the path inside it for a session descriptor."""
    kind = descriptor.get('type')
    path = normalize(descriptor.get('path', '/')).strip('/')
    if kind == 'smb':
        if not credentials or not credentials.get('username') or not credentials.get('password'):
            raise MountError('Sign in to this server with a username and password before mounting it')
        section = {'type': 'smb', 'host': descriptor['host'], 'user': credentials['username'],
                   'pass': obscure(binary, credentials['password'])}
        if credentials.get('domain'):
            section['domain'] = credentials['domain']
        return section, '/'.join(part for part in (descriptor['share'], path) if part)
    if kind == 'rclone':
        if not endpoint_config:
            raise MountError('This cloud connection is not available')
        config = configparser.RawConfigParser()
        config.read(endpoint_config['config'])
        name = endpoint_config.get('remote', 'remote')
        if not config.has_section(name):
            raise MountError('This cloud connection is not available')
        root = normalize(endpoint_config.get('root', '/')).strip('/')
        return dict(config.items(name)), '/'.join(part for part in (root, path) if part)
    if kind == 'local':
        raise MountError('Local folders are already on this computer')
    if kind == 'nfs':
        raise MountError('Mount NFS exports with this computer’s NFS client; remotefs mounts SMB shares and cloud storage')
    raise MountError('This location cannot be mounted')


def safe_label(label):
    allowed = set(string.ascii_letters + string.digits + ' -_.()')
    cleaned = ''.join(c if c in allowed else '-' for c in (label or 'remotefs')).strip(' .-') or 'remotefs'
    return cleaned[:60]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class MountManager:
    """Owns the rclone mount processes started by this service."""

    def __init__(self, directory, base=None, binary=None, system=None, popen=subprocess.Popen):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.system = system or sys.platform
        self.method = platform_method(self.system)
        self.base = Path(base) if base else Path.home() / 'remotefs'
        self.binary = binary
        self.popen = popen
        self.lock = threading.RLock()
        self.state_path = self.directory / 'mounts.json'
        self.processes = {}
        self.records = {}
        self.cleanup_stale()

    # ------------------------------------------------------------------ bookkeeping
    def save(self):
        write_private(self.state_path, json.dumps(self.records, indent=1) + '\n')

    def public(self, key, row):
        result = {k: row[k] for k in ('label', 'target', 'read_only', 'method', 'started', 'descriptor')}
        result['id'] = key
        result['status'] = self.status(key)
        return result

    def list(self, principal):
        with self.lock:
            return [self.public(k, r) for k, r in self.records.items() if r['principal'] == principal]

    def record(self, principal, key):
        row = self.records.get(key)
        if not row or row['principal'] != principal:
            raise PermissionError('Mount not found')
        return row

    def mounted(self, target):
        if self.method == 'winfsp':
            return os.path.exists(target + '\\')
        return os.path.ismount(target)

    def status(self, key):
        row = self.records[key]
        process = self.processes.get(key)
        if process is None or process.poll() is not None:
            return {'state': 'stopped'}
        stats = self.rc(row, 'vfs/stats', timeout=2)  # one VFS per process, so no fs parameter
        cache = (stats or {}).get('diskCache', {})
        pending = int(cache.get('uploadsInProgress', 0)) + int(cache.get('uploadsQueued', 0))
        return {'state': 'mounted' if self.mounted(row['target']) else 'starting', 'pending_uploads': pending}

    def rc(self, row, command, timeout=5, **params):
        request = urllib.request.Request(f"http://127.0.0.1:{row['rc_port']}/{command}", data=json.dumps(params).encode(),
                                         headers={'Content-Type': 'application/json'})
        token = base64.b64encode(f"remotefs:{row['rc_pass']}".encode()).decode()
        request.add_header('Authorization', 'Basic ' + token)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read() or b'{}')
        except (OSError, urllib.error.URLError, ValueError):
            return None

    # ------------------------------------------------------------------ targets
    def choose_target(self, label, requested=None):
        taken = {row['target'] for row in self.records.values()}
        if self.method == 'winfsp':
            letters = [requested.rstrip(':\\').upper()] if requested else list('ZYXWVUTSRQPONMLKJIHGFED')
            for letter in letters:
                if len(letter) != 1 or letter not in string.ascii_uppercase or letter in 'ABC':
                    raise MountError('Choose a drive letter from D to Z')
                target = letter + ':'
                if target not in taken and not os.path.exists(target + '\\'):
                    return target
            raise MountError('That drive letter is in use' if requested else 'No free drive letter')
        name = safe_label(requested or label)
        self.base.mkdir(parents=True, exist_ok=True)
        candidate, n = self.base / name, 2
        while str(candidate) in taken or (candidate.exists() and (os.path.ismount(candidate) or any(candidate.iterdir()))):
            candidate, n = self.base / f'{name} {n}', n + 1
        candidate.mkdir(exist_ok=True)
        return str(candidate)

    # ------------------------------------------------------------------ lifecycle
    def command(self, row, remote_path, conf, log):
        verb = 'nfsmount' if self.method == 'nfs' else 'mount'
        argv = [self.binary, verb, f'remote:{remote_path}', row['target'], '--config', str(conf),
                '--vfs-cache-mode', 'full', '--cache-dir', str(self.directory / 'cache'),
                '--dir-cache-time', '30s', '--volname', row['label'],
                '--log-file', str(log), '--log-level', 'NOTICE',
                '--rc', '--rc-addr', f"127.0.0.1:{row['rc_port']}"]
        if self.method == 'winfsp':
            argv.append('--network-mode')
            if windows_system_account():
                # A drive mounted by the SYSTEM service is visible to every user; give signed-in users
                # the access the mount allows, including "write extended attributes", which WinFsp omits by default.
                access = 'FR' if row['read_only'] else 'FA'
                argv += ['-o', f'FileSecurity=D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;{access};;;AU)']
        if self.method == 'nfs':
            # Keep file handles valid if rclone restarts, so Finder windows don't go stale.
            argv += ['--nfs-cache-type', 'disk']
        if row['read_only']:
            argv.append('--read-only')
        return argv

    def mount(self, principal, descriptor, credentials, endpoint_config, label, read_only, target=None, timeout=30):
        with self.lock:
            self.binary = self.binary or rclone_binary()
            check = prerequisites(self.binary, self.system)
            if not check['available']:
                raise MountError('; '.join(f"{m['name']} is needed: {m['install']}" for m in check['missing']))
            section, remote_path = remote_for(descriptor, credentials, endpoint_config, self.binary)
            key = 'mount-' + secrets.token_hex(8)
            clean = {k: v for k, v in descriptor.items() if k != 'credential_id'}
            row = dict(principal=principal, label=safe_label(label), read_only=bool(read_only), method=self.method,
                       started=time.time(), descriptor=clean, rc_port=free_port(), rc_pass=secrets.token_urlsafe(24))
            row['target'] = self.choose_target(row['label'], target)
            row['remote_path'] = remote_path
            conf = self.directory / f'{key}.conf'
            config = configparser.RawConfigParser()
            config['remote'] = section
            output = io.StringIO()
            config.write(output)
            write_private(conf, output.getvalue())
            log = self.directory / f'{key}.log'
            # The rc login goes through the environment, which other local users cannot read, not argv.
            env = {k: v for k, v in os.environ.items() if not k.startswith('RCLONE_')}
            env.update(RCLONE_RC_USER='remotefs', RCLONE_RC_PASS=row['rc_pass'])
            options = ({'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)} if self.method == 'winfsp'
                       else {'start_new_session': True})
            try:
                process = self.popen(self.command(row, remote_path, conf, log), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **options)
            except OSError:
                conf.unlink(missing_ok=True)
                self.release(row['target'])
                raise MountError('Could not start rclone') from None
            row['pid'] = process.pid
            self.records[key], self.processes[key] = row, process
            self.save()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.release(row['target'])
                    self.forget(key)
                    raise MountError(f'The mount did not start; see {log}')
                if self.mounted(row['target']):
                    return self.public(key, row)
                time.sleep(0.25)
            self.stop(key, wait_uploads=0, keep_if_busy=False)
            raise MountError(f'The mount did not appear within {timeout} seconds; see {log}')

    def unmount(self, principal, key, force=False, wait=60):
        with self.lock:
            self.record(principal, key)
            pending = self.stop(key, wait_uploads=0 if force else wait, keep_if_busy=not force)
            if pending:
                raise MountError(f'{pending} file(s) are still uploading; try again shortly or unmount with force '
                                 '(uploads resume the next time this location is mounted)')
            return {'unmounted': True}

    def stop(self, key, wait_uploads=60, keep_if_busy=False):
        """Give pending uploads time to finish, then ask rclone to quit.

        With keep_if_busy the mount stays up and the number of uploads still pending is returned.
        Otherwise rclone quits anyway; its disk cache uploads the rest the next time this location is mounted.
        """
        row = self.records[key]
        process = self.processes.get(key)
        if process is not None and process.poll() is None:
            deadline = time.monotonic() + wait_uploads
            while True:
                pending = self.status(key).get('pending_uploads', 0)
                if not pending or time.monotonic() >= deadline:
                    break
                time.sleep(0.5)
            if pending and keep_if_busy:
                return pending
            if self.rc(row, 'core/quit') is None:
                self.signal(process)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.release(row['target'])
        self.forget(key)
        return 0

    def signal(self, process):
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT if self.method == 'winfsp' else signal.SIGTERM)
        except (OSError, AttributeError, ValueError):
            process.terminate()

    def release(self, target):
        """Clear a mount left behind by a process that is gone, and tidy the empty folder."""
        if self.method == 'winfsp':
            return
        if os.path.ismount(target):
            tool = (['umount', target] if self.method == 'nfs' else
                    [shutil.which('fusermount3') or shutil.which('fusermount') or 'fusermount', '-u', '-z', target])
            subprocess.run(tool, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        try:
            if Path(target).parent == self.base and not os.path.ismount(target):
                Path(target).rmdir()
        except OSError:
            pass

    def forget(self, key):
        self.records.pop(key, None)
        self.processes.pop(key, None)
        (self.directory / f'{key}.conf').unlink(missing_ok=True)
        self.save()

    def cleanup_stale(self):
        """Mounts recorded by a previous run of the service: ask their rclone to quit, then clear them."""
        try:
            stale = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            stale = {}
        for key, row in stale.items():
            if self.rc(row, 'core/quit', timeout=2) is not None:
                for _ in range(40):
                    if not self.mounted(row.get('target', '')):
                        break
                    time.sleep(0.25)
            if row.get('target'):
                self.release(row['target'])
            (self.directory / f'{key}.conf').unlink(missing_ok=True)
        self.records = {}
        if stale:
            self.save()

    def shutdown(self, wait_uploads=60):
        with self.lock:
            for key in list(self.records):
                self.stop(key, wait_uploads, keep_if_busy=False)

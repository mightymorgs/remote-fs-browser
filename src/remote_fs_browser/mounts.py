"""Mount storage as a folder or drive on the computer running the service, using rclone.

Windows mounts a drive letter through WinFsp (`rclone mount --network-mode`), Linux uses FUSE
(`rclone mount`) and macOS uses rclone's built-in NFS server with the system NFS client
(`rclone nfsmount`), so macOS needs no kernel extension. rclone has no NFS client, so NFS shares
reach rclone through a loopback WebDAV bridge backed by remotefs's own libnfs access (davbridge.py).
Each mount runs its own rclone process
with a private config, a persistent VFS cache and a loopback remote-control endpoint protected by
a random password. The service asks rclone to finish pending uploads and quit, rather than killing
it, so unmounting does not lose writes.

Mounts reconnect by default: the service remembers each one until it is ejected and mounts it again
after a restart, after rclone exits and, on Windows, when the mount owner signs in again.
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


FINDER_LITTER = {'.DS_Store', '.localized'}


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


def remote_for(descriptor, credentials, endpoint_config, binary, bridge=None):
    """The rclone [remote] section and the path inside it for a session descriptor."""
    kind = descriptor.get('type')
    path = normalize(descriptor.get('path', '/')).strip('/')
    if kind == 'smb':
        if not credentials or not credentials.get('username') or not credentials.get('password'):
            raise MountError('Sign in to this server with a username and password before mounting it')
        user, domain = credentials['username'], credentials.get('domain')
        if '\\' in user and not domain:
            # rclone takes the domain separately; "DOMAIN\\user" as one name signs in as nobody.
            domain, user = user.split('\\', 1)
        section = {'type': 'smb', 'host': descriptor['host'], 'user': user, 'pass': obscure(binary, credentials['password'])}
        if domain:
            section['domain'] = domain
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
    if kind == 'kubernetes' and len(path.split('/')) < 3:
        raise MountError('Open a container or a volume to mount it; namespaces and pods are not folders')
    if kind in ('nfs', 'kubernetes'):
        if bridge is None:
            raise MountError('This location is not available')
        # The bridge already serves the chosen folder as its root.
        return {'type': 'webdav', 'url': bridge.url, 'vendor': 'other', 'user': 'remotefs',
                'pass': obscure(binary, bridge.password)}, ''
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
    """Owns the rclone mount processes started by this service, and brings back the ones that reconnect."""

    def __init__(self, directory, base=None, binary=None, system=None, popen=subprocess.Popen, bridge=None,
                 owner=None, sessions=None, resolver=None, interval=15):
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
        self.bridges = {}
        self.bridge = bridge
        # The Windows account whose own session gets mounts when the service runs as SYSTEM.
        self.owner = owner
        self.sessions = sessions
        self.files = {}
        self.records = {}
        # Mounts to bring back until they are ejected. resolver(principal, descriptor) returns the login,
        # cloud endpoint and whether writes are still allowed, as the service's policy stands now.
        self.saved_path = self.directory / 'saved-mounts.json'
        self.saved = self.load_saved()
        self.resolver = resolver
        self.interval = interval
        self.retries = {}  # key -> (monotonic time of the next attempt, delay, reason shown in the list)
        self.stopping = threading.Event()
        self.watcher = None
        self.cleanup_stale()

    # ------------------------------------------------------------------ bookkeeping
    def save(self):
        write_private(self.state_path, json.dumps(self.records, indent=1) + '\n')

    def load_saved(self):
        try:
            saved = json.loads(self.saved_path.read_text())
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    def save_saved(self):
        write_private(self.saved_path, json.dumps(self.saved, indent=1) + '\n')

    def public(self, key, row):
        result = {k: row[k] for k in ('label', 'target', 'read_only', 'method', 'started', 'descriptor')}
        result['id'] = key
        result['auto'] = key in self.saved
        result['status'] = self.status(key)
        return result

    def waiting(self, key):
        """A remembered mount that is not running yet: why, as far as the service knows."""
        definition = self.saved[key]
        _, _, reason = self.retries.get(key, (0, 0, None))
        return {'id': key, 'label': definition['label'], 'target': definition['target'], 'read_only': definition['read_only'],
                'method': self.method, 'started': None, 'auto': True,
                'descriptor': {k: v for k, v in definition['descriptor'].items() if k != 'credential_id'},
                'status': {'state': 'waiting', 'reason': reason or 'Reconnecting…', 'pending_uploads': 0}}

    def list(self, principal):
        with self.lock:
            rows = [self.public(k, r) for k, r in self.records.items() if r['principal'] == principal]
            return rows + [self.waiting(k) for k, d in self.saved.items() if d['principal'] == principal and k not in self.records]

    def record(self, principal, key):
        row = self.records.get(key)
        if not row or row['principal'] != principal:
            raise PermissionError('Mount not found')
        return row

    def visible(self, row, stats=None):
        if row.get('as_user'):
            # The drive exists only in the owner's session, which this service cannot see into.
            return (stats if stats is not None else self.rc(row, 'vfs/stats', timeout=2)) is not None
        return self.mounted(row['target'])

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
        return {'state': 'mounted' if self.visible(row, stats) else 'starting', 'pending_uploads': pending}

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
                '--vfs-cache-mode', 'full', '--cache-dir', str(Path(row.get('files', self.directory)) / 'cache'),
                '--dir-cache-time', '30s', '--volname', row['label'],
                '--log-file', str(log), '--log-level', 'NOTICE',
                '--rc', '--rc-addr', f"127.0.0.1:{row['rc_port']}"]
        if self.method == 'winfsp':
            argv.append('--network-mode')
            # Only the mount's owner may use the drive, including through its \\server\share path. Read-only
            # rights make Windows refuse changes itself: WinFsp's FUSE layer cannot mark a volume read-only,
            # and rclone reports a delete on a read-only VFS as done without doing it.
            access = 'FRFX' if row['read_only'] else 'FA'
            argv += ['-o', f"FileSecurity=D:P(A;;{access};;;{row.get('owner_sid') or 'WD'})"]
        if self.method == 'nfs':
            # Keep file handles valid if rclone restarts, so Finder windows don't go stale.
            argv += ['--nfs-cache-type', 'disk']
            # rclone's NFS server has no lock manager; keep locks on this Mac so apps that lock on save
            # (TextEdit, Office) don't wait on lock requests nobody answers.
            argv += ['-o', 'locallocks']
        if row['read_only']:
            argv.append('--read-only')
        return argv

    def mount(self, principal, descriptor, credentials, endpoint_config, label, read_only, target=None, timeout=30,
              auto=False, key=None):
        """Start one mount. With auto it is remembered, including its credential_id, and reconnects until ejected."""
        with self.lock:
            self.binary = self.binary or rclone_binary()
            check = prerequisites(self.binary, self.system)
            if not check['available']:
                raise MountError('; '.join(f"{m['name']} is needed: {m['install']}" for m in check['missing']))
            key = key or 'mount-' + secrets.token_hex(8)
            user = self.user_session() if self.method == 'winfsp' else None
            row = None
            try:
                files = Path(user.profile()) / 'AppData' / 'Local' / 'remotefs' / 'mounts' if user else self.directory
                files.mkdir(parents=True, exist_ok=True)
                self.files[key] = files
                if descriptor.get('type') in ('nfs', 'kubernetes'):
                    self.bridges[key] = self.start_bridge(descriptor, endpoint_config)
                section, remote_path = remote_for(descriptor, credentials, endpoint_config, self.binary, self.bridges.get(key))
                clean = {k: v for k, v in descriptor.items() if k != 'credential_id'}
                row = dict(principal=principal, label=safe_label(label), read_only=bool(read_only), method=self.method,
                           started=time.time(), descriptor=clean, rc_port=free_port(), rc_pass=secrets.token_urlsafe(24))
                row['target'] = self.choose_target(row['label'], target)
                row['remote_path'] = remote_path
                row['files'] = str(files)
                if self.method == 'winfsp':
                    row['as_user'] = user is not None
                    row['owner_sid'] = user.sid() if user else self.session_api().current_sid()
                conf = files / f'{key}.conf'
                config = configparser.RawConfigParser()
                config['remote'] = section
                output = io.StringIO()
                config.write(output)
                write_private(conf, output.getvalue())
                log = files / f'{key}.log'
                # The rc login goes through the environment, which other local users cannot read, not argv.
                env = {k: v for k, v in (user.environment() if user else os.environ).items() if not k.startswith('RCLONE_')}
                env.update(RCLONE_RC_USER='remotefs', RCLONE_RC_PASS=row['rc_pass'])
                argv = self.command(row, remote_path, conf, log)
                options = ({'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)} if self.method == 'winfsp'
                           else {'start_new_session': True})
                try:
                    if user:
                        process = user.start(argv, env, str(files))
                    else:
                        process = self.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, env=env, **options)
                except OSError:
                    raise MountError('Could not start rclone') from None
            except BaseException:
                if row and row.get('target'):
                    self.release(row['target'])
                self.forget(key)
                raise
            finally:
                if user:
                    user.close()
            row['pid'] = process.pid
            self.records[key], self.processes[key] = row, process
            self.save()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.release(row['target'])
                    self.forget(key)
                    raise MountError(f'The mount did not start; see {log}')
                if self.visible(row):
                    if auto:
                        self.saved[key] = dict(principal=principal, descriptor=dict(descriptor), label=row['label'],
                                               read_only=row['read_only'], target=row['target'])
                        self.save_saved()
                    return self.public(key, row)
                time.sleep(0.25)
            self.stop(key, wait_uploads=0, keep_if_busy=False)
            raise MountError(f'The mount did not appear within {timeout} seconds; see {log}')

    def unmount(self, principal, key, force=False, wait=60):
        """Eject: stop the mount if it is running and stop reconnecting it."""
        with self.lock:
            definition = self.saved.get(key)
            if key in self.records:
                self.record(principal, key)
                pending = self.stop(key, wait_uploads=0 if force else wait, keep_if_busy=not force)
                if pending:
                    raise MountError(f'{pending} file(s) are still uploading; try again shortly or unmount with force '
                                     '(uploads resume the next time this location is mounted)')
            elif not definition or definition['principal'] != principal:
                raise PermissionError('Mount not found')
            if self.saved.pop(key, None) is not None:
                self.save_saved()
            self.retries.pop(key, None)
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
        # macOS finishes an NFS unmount a moment after the command returns.
        for _ in range(20):
            if not os.path.ismount(target):
                break
            time.sleep(0.25)
        folder = Path(target)
        if folder.parent != self.base or os.path.ismount(target):
            return
        try:
            # Finder writes .DS_Store (and ._ files on some volumes) into the folder once it is unmounted.
            for item in folder.iterdir():
                if item.name in FINDER_LITTER or item.name.startswith('._'):
                    item.unlink()
            folder.rmdir()
        except OSError:
            pass

    def session_api(self):
        if self.sessions is None:
            from . import winsession
            self.sessions = winsession
        return self.sessions

    def user_session(self):
        """The mount owner's Windows session when this service runs as SYSTEM; None otherwise."""
        if not windows_system_account():
            return None
        if not self.owner:
            raise MountError('The remotefs service needs a mount owner before it can mount: set "mount_owner" in '
                             'config.json to the Windows account that may use mounts, then restart remotefs')
        api = self.session_api()
        session = api.session_of(self.owner)
        if session is None:
            raise MountError(f'Sign in to Windows as {self.owner} first; mounts appear only in that account’s own session')
        return api.UserSession(session)

    def start_bridge(self, descriptor, endpoint_config=None):
        from .davbridge import Bridge
        what = 'the NFS share' if descriptor.get('type') == 'nfs' else 'this location'
        try:
            if descriptor.get('type') == 'nfs':
                return (self.bridge or Bridge)(descriptor)
            return (self.bridge or Bridge)(descriptor, endpoint_config)
        except (OSError, RuntimeError, ValueError) as error:
            raise MountError(f'Could not reach {what}: {error}') from None

    def forget(self, key):
        self.records.pop(key, None)
        self.processes.pop(key, None)
        bridge = self.bridges.pop(key, None)
        if bridge:
            bridge.stop()
        (Path(self.files.pop(key, self.directory)) / f'{key}.conf').unlink(missing_ok=True)
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
            (Path(row.get('files', self.directory)) / f'{key}.conf').unlink(missing_ok=True)
        self.records = {}
        if stale:
            self.save()

    def shutdown(self, wait_uploads=60):
        """Stop every mount; remembered mounts come back the next time the service starts."""
        self.stopping.set()
        if self.watcher is not None:
            self.watcher.join(timeout=60)
            self.watcher = None
        with self.lock:
            for key in list(self.records):
                self.stop(key, wait_uploads, keep_if_busy=False)

    # ------------------------------------------------------------------ reconnecting
    def start(self):
        """Begin bringing back remembered mounts; the service calls this once it is serving."""
        if self.watcher is None:
            self.stopping.clear()
            self.watcher = threading.Thread(target=self.watch, name='remotefs-mounts', daemon=True)
            self.watcher.start()

    def watch(self):
        while not self.stopping.is_set():
            try:
                self.reconnect()
            except Exception:  # never let one bad pass end reconnecting for good
                pass
            self.stopping.wait(self.interval)

    def reconnect(self, now=None):
        """Mount each remembered mount that is not running: after a restart, a crash or the owner's sign-out."""
        with self.lock:
            now = time.monotonic() if now is None else now
            for key in [k for k in self.saved if k in self.processes and self.processes[k].poll() is not None]:
                # rclone exited (on Windows, the owner signed out and their session ended). Clear it, then remount.
                self.release(self.records[key]['target'])
                self.forget(key)
            for key in [k for k in self.saved if k not in self.records]:
                if self.stopping.is_set():
                    return
                if self.retries.get(key, (0,))[0] <= now:
                    self.remount(key, now)

    def remount(self, key, now):
        definition = self.saved[key]
        if self.method == 'winfsp' and windows_system_account() and self.owner \
                and self.session_api().session_of(self.owner) is None:
            # Not a failure: check again soon, without backing off, so the drive is back right after sign-in.
            self.retries[key] = (now + self.interval, self.interval, f'Waiting for {self.owner} to sign in to Windows')
            return
        try:
            if self.resolver is None:
                raise MountError('This service cannot reconnect mounts')
            credentials, endpoint_config, writable = self.resolver(definition['principal'], definition['descriptor'])
            target = definition['target'] if self.method == 'winfsp' else Path(definition['target']).name
            self.mount(definition['principal'], definition['descriptor'], credentials, endpoint_config, definition['label'],
                       definition['read_only'] or not writable, target, auto=True, key=key)
            self.retries.pop(key, None)
        except Exception as error:
            delay = min(max(self.retries.get(key, (0, 0))[1] * 2, self.interval), 300)
            reason = str(error) if isinstance(error, (MountError, PermissionError)) and str(error) else 'Could not reconnect'
            self.retries[key] = (now + delay, delay, f'{reason}; trying again in {int(delay)} seconds')

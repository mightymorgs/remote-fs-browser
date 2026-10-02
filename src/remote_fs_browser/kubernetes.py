"""Browse the files inside running pods through `kubectl exec`.

Paths are /<namespace>/<pod>/<container>/<path inside the container>. The first
three levels are read-only inventory; below them every operation is a short POSIX
shell script run in the container, so any image with `sh` and coreutils or
BusyBox works. Nothing is installed in the pod and no shell runs on the host.

/<namespace>/Volumes/<claim>/... reaches a PersistentVolumeClaim that no running
pod mounts, through a small helper pod this session starts and deletes.
"""
import hashlib
import io
import json
import os
import queue
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
import stat as modes
import subprocess
import tempfile
import time
from .policy import normalize
from .backends import child_path, listing

LONGHORN = 'driver.longhorn.io'
PROVISIONER = ('volume.kubernetes.io/storage-provisioner', 'volume.beta.kubernetes.io/storage-provisioner')
ROW = '"%s %Y %f %n"'
# Pod names are lowercase, so this entry can never collide with one.
VOLUMES = 'Volumes'
HELPER_IMAGE = 'busybox:1.37.0'
# A helper outlives a crashed service by at most this long, then releases the volume.
HELPER_SECONDS = 3600
# Wait briefly per request and answer "not ready" rather than hold a request
# open; a slow API server would otherwise push it past the session timeout.
ATTACH_WAIT = 5
# Opening one folder needs the pod and its claims; reuse those answers briefly
# so each folder costs one exec instead of several API round trips.
CACHE_SECONDS = 30
# Each `kubectl exec` costs a full API handshake (seconds over a relayed link),
# so a session keeps one shell open per container it is browsing.
MAX_SHELLS = 4
MANAGED = {'app.kubernetes.io/managed-by': 'remotefs'}
UNITS = {'Ki': 2**10, 'Mi': 2**20, 'Gi': 2**30, 'Ti': 2**40, 'Pi': 2**50,
         'k': 10**3, 'M': 10**6, 'G': 10**9, 'T': 10**12, 'P': 10**15}

# Exit statuses the scripts below use; kubectl passes the container's status through.
STATUS = {2: FileNotFoundError, 13: PermissionError, 17: FileExistsError,
          20: NotADirectoryError, 21: IsADirectoryError}
MESSAGES = {FileNotFoundError: 'File or folder not found', PermissionError: 'Permission denied',
            FileExistsError: 'Destination already exists', NotADirectoryError: 'Parent is not a folder',
            IsADirectoryError: 'Destination is a folder'}

# Links are followed to show what they point at (/bin on Debian is one), so each
# row says whether it is a link; `stat` of the link itself is used for planning
# deletes and copies, which therefore never walk through a link.
LIST = ('[ -e "$1" ] || exit 2; [ -d "$1" ] || exit 20; cd -- "$1" 2>/dev/null || exit 13; '
        'for f in * .[!.]* ..?*; do if [ -L "$f" ]; then printf "L "; '
        'stat -L -c ' + ROW + ' -- "$f" 2>/dev/null || stat -c ' + ROW + ' -- "$f"; '
        'elif [ -e "$f" ]; then printf "F "; stat -c ' + ROW + ' -- "$f"; fi; done')
STAT = ('{ [ -e "$1" ] || [ -L "$1" ]; } || exit 2; if [ -L "$1" ]; then printf "L "; else printf "F "; fi; '
        'stat -c ' + ROW + ' -- "$1"')
FOLLOW = '[ -e "$1" ] || exit 2; stat -L -c ' + ROW + ' -- "$1"'
READ = '[ -r "$1" ] || exit 13; tail -c +"$2" -- "$1" | head -c "$3"'
MKDIR = '{ [ -e "$1" ] || [ -L "$1" ]; } && exit 17; mkdir -- "$1"'
RENAME = '[ -e "$1" ] || [ -L "$1" ] || exit 2; { [ -e "$2" ] || [ -L "$2" ]; } && exit 17; mv -- "$1" "$2"'
REMOVE = 'if [ -d "$1" ] && [ ! -L "$1" ]; then rmdir -- "$1"; else rm -f -- "$1"; fi'
# Stream to a sibling temporary file, keep an existing file's mode and owner, then
# rename into place so a half-written config never lands.
WRITE = ('t="$(dirname -- "$1")/.remotefs-upload-$$"; cat > "$t" || { rm -f -- "$t"; exit 5; }; '
         'if [ -d "$1" ] && [ ! -L "$1" ]; then rm -f -- "$t"; exit 21; fi; '
         'if [ -e "$1" ] || [ -L "$1" ]; then if [ "$2" = new ]; then rm -f -- "$t"; exit 17; fi; '
         'chmod "$(stat -c %a -- "$1")" "$t"; chown "$(stat -c %u:%g -- "$1")" "$t" 2>/dev/null; fi; '
         'mv -f -- "$t" "$1"')


class KubernetesError(ValueError):
    """Messages about the cluster itself, safe and useful to show."""
    shown = True


class NotReady(KubernetesError):
    """The storage is getting ready, such as a volume attaching; asking again will succeed."""
    retry = True


class KubernetesFilesystem:
    def __init__(self, config):
        self.config = config
        self.namespaces = config['namespaces']
        self.timeout = config['_timeout']
        self.claims = {}
        self.helpers = set()
        self.cache = {}
        self.shells = {}
        self.oneshot = set()
        # Fail while connecting, not on first use, when the cluster or RBAC is wrong.
        self.get('pods', '-n', self.namespaces[0])

    # --- kubectl ---------------------------------------------------------

    def kubectl(self):
        argv = [self.config.get('kubectl', 'kubectl'), f'--request-timeout={max(1, int(self.timeout))}s']
        if self.config.get('kubeconfig'):
            argv.append('--kubeconfig=' + self.config['kubeconfig'])
        if self.config.get('context'):
            argv.append('--context=' + self.config['context'])
        return argv

    def exec_argv(self, namespace, pod, container, stdin):
        return [*self.kubectl(), 'exec', *(['-i'] if stdin else []), '-n', namespace, pod, '-c', container, '--']

    def environment(self):
        return {k: v for k, v in os.environ.items() if k != 'KUBECONFIG' or not self.config.get('kubeconfig')}

    def run(self, argv, stdin=None, max_bytes=16 * 1024 * 1024):
        env = self.environment()
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            try:
                result = subprocess.run(argv, stdin=stdin or subprocess.DEVNULL, stdout=output, stderr=errors,
                                        timeout=self.timeout, env=env)
            except FileNotFoundError:
                raise KubernetesError('Install kubectl on the service host and put it on PATH') from None
            except subprocess.TimeoutExpired:
                raise TimeoutError('Kubernetes operation timed out') from None
            output.seek(0)
            data = output.read(max_bytes + 1)
            if result.returncode:
                errors.seek(0)
                raise self.failure(result.returncode, errors.read(4096).decode('utf-8', 'replace'))
            if len(data) > max_bytes:
                raise ValueError('Response is too large; select a smaller folder')
            return data

    @staticmethod
    def failure(code, detail):
        # Raw kubectl and container errors can name internal hosts or paths; map them.
        if code in STATUS:
            kind = STATUS[code]
            return kind(MESSAGES[kind])
        if 'executable file not found' in detail or 'no such file or directory: unknown' in detail or code in (126, 127):
            return KubernetesError('This container has no shell (sh), so its files cannot be browsed')
        if 'Forbidden' in detail or 'forbidden' in detail:
            return KubernetesError("Kubernetes refused access; check the service host's kubeconfig and RBAC")
        if 'NotFound' in detail or 'not found' in detail:
            return FileNotFoundError('Pod or container not found')
        if 'Unable to connect' in detail or 'connection refused' in detail:
            return KubernetesError('Cannot reach the Kubernetes API from the service host')
        return OSError('Kubernetes operation failed; check the pod and permissions')

    def get(self, *args):
        now = time.monotonic()
        hit = self.cache.get(args)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
        value = json.loads(self.run([*self.kubectl(), 'get', *args, '-o', 'json']))
        self.cache[args] = (now, value)
        return value

    def get_or_none(self, *args):
        try:
            return self.get(*args)
        except FileNotFoundError:
            return None

    def shell(self, target, script, *args, stdin=None, max_bytes=16 * 1024 * 1024):
        target = tuple(target)
        if stdin is None and target not in self.oneshot:
            try:
                return self.persistent(target).command(script, args, self.timeout, max_bytes)
            except ShellBroken as broken:
                self.drop(target)
                if not broken.started:
                    # The shell never answered (no sh, or the pod is gone): use a
                    # one-off exec, which reports the reason, from now on.
                    self.oneshot.add(target)
        namespace, pod, container = target
        return self.run([*self.exec_argv(namespace, pod, container, stdin is not None), 'sh', '-c', script, 'sh', *args],
                        stdin=stdin, max_bytes=max_bytes)

    def persistent(self, target):
        shell = self.shells.pop(target, None)
        if shell is None or not shell.alive():
            if shell:
                shell.close()
            if len(self.shells) >= MAX_SHELLS:
                oldest = next(iter(self.shells))
                self.shells.pop(oldest).close()
            namespace, pod, container = target
            try:
                shell = Shell([*self.exec_argv(namespace, pod, container, True), 'sh'], self.environment())
            except FileNotFoundError:
                raise KubernetesError('Install kubectl on the service host and put it on PATH') from None
        self.shells[target] = shell  # most recently used last
        return shell

    def drop(self, target):
        shell = self.shells.pop(target, None)
        if shell:
            shell.close()

    # --- paths -----------------------------------------------------------

    def split(self, path):
        path = normalize(path)
        parts = path.strip('/').split('/') if path != '/' else []
        if parts and parts[0] not in self.namespaces:
            raise PermissionError('Namespace is not permitted')
        inner = '/' + '/'.join(parts[3:])
        return parts[:3], inner

    def enter(self, head, inner):
        """Where a browsable path runs: (exec target, path in that container, pod)."""
        if head[1] == VOLUMES:
            pod = self.helper(head[0], head[2])
            return (head[0], pod['metadata']['name'], 'files'), normalize('/volume' + inner), pod
        return tuple(head), inner, self.container(*head)

    # --- volumes no running pod mounts ------------------------------------

    @staticmethod
    def helper_name(claim):
        digest = hashlib.sha256(claim.encode()).hexdigest()[:8]
        return f"remotefs-{claim[:40].rstrip('-.')}-{digest}"

    @staticmethod
    def is_helper(pod):
        labels = pod.get('metadata', {}).get('labels', {})
        return all(labels.get(k) == v for k, v in MANAGED.items())

    def users(self, pods, claim):
        """Pods other than our helpers that hold this claim."""
        return [p['metadata']['name'] for p in pods
                if not self.is_helper(p) and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
                and any(v.get('persistentVolumeClaim', {}).get('claimName') == claim for v in p['spec'].get('volumes', []))]

    def helper(self, namespace, claim):
        if not self.get_or_none('pvc', claim, '-n', namespace):
            raise FileNotFoundError('Volume claim not found')
        name = self.helper_name(claim)
        pod = self.get_or_none('pod', name, '-n', namespace)
        if pod and pod.get('status', {}).get('phase') in ('Succeeded', 'Failed'):
            self.run([*self.kubectl(), 'delete', 'pod', name, '-n', namespace, '--wait=true'])
            self.cache.clear()
            pod = None
        if pod is None:
            users = self.users(self.get('pods', '-n', namespace)['items'], claim)
            if users:
                raise KubernetesError(f'Pod {users[0]} is using this volume; browse it under that pod')
            with tempfile.TemporaryFile() as manifest:
                manifest.write(json.dumps(self.helper_manifest(namespace, claim, name)).encode())
                manifest.seek(0)
                self.run([*self.kubectl(), 'create', '-f', '-'], stdin=manifest)
            self.cache.clear()
        self.helpers.add((namespace, name))
        if pod is None or not self.ready(pod):
            try:
                self.run([*self.kubectl(), 'wait', '--for=condition=Ready', f'pod/{name}', '-n', namespace,
                          f'--timeout={ATTACH_WAIT}s'])
            except (OSError, ValueError):
                raise NotReady('Attaching the volume; this can take up to a minute') from None
            self.cache.clear()
            pod = self.get('pod', name, '-n', namespace)
        return pod

    @staticmethod
    def ready(pod):
        return any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in pod.get('status', {}).get('conditions', []))

    def helper_manifest(self, namespace, claim, name):
        return {'apiVersion': 'v1', 'kind': 'Pod',
                'metadata': {'name': name, 'namespace': namespace, 'labels': dict(MANAGED),
                             'annotations': {'remotefs/claim': claim}},
                'spec': {'restartPolicy': 'Never', 'terminationGracePeriodSeconds': 1,
                         'activeDeadlineSeconds': HELPER_SECONDS,
                         'containers': [{'name': 'files', 'image': self.config.get('helper_image', HELPER_IMAGE),
                                         'command': ['sleep', str(HELPER_SECONDS)],
                                         'volumeMounts': [{'name': 'volume', 'mountPath': '/volume'}],
                                         'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'},
                                                       'limits': {'memory': '64Mi'}}}],
                         'volumes': [{'name': 'volume', 'persistentVolumeClaim': {'claimName': claim}}]}}

    @staticmethod
    def quantity(value):
        try:
            for unit, scale in UNITS.items():
                if value.endswith(unit):
                    return int(float(value[:-len(unit)]) * scale)
            return int(value)
        except (AttributeError, ValueError):
            return None

    def claim_row(self, claim, pods, path):
        notes = claim.get('metadata', {}).get('annotations', {})
        users = self.users(pods, claim['metadata']['name'])
        longhorn = any(notes.get(name) == LONGHORN for name in PROVISIONER)
        state = f'in use by {users[0]}' if users else 'not mounted'
        return {'name': claim['metadata']['name'], 'path': path, 'type': 'directory', 'size': None, 'modified': None,
                'fixed': True, 'claim': claim['metadata']['name'], 'longhorn': longhorn,
                'kind': f"{'Longhorn volume' if longhorn else 'Volume'} · {state}",
                'capacity': self.quantity(claim.get('status', {}).get('capacity', {}).get('storage')),
                'in_use_by': users, 'state': state}

    def pod(self, namespace, name):
        pod = self.get('pod', name, '-n', namespace)
        if pod.get('status', {}).get('phase') != 'Running':
            raise KubernetesError('Only running pods can be browsed')
        return pod

    def container(self, namespace, name, container):
        pod = self.pod(namespace, name)
        if container not in [c['name'] for c in pod['spec'].get('containers', [])]:
            raise FileNotFoundError('Container not found')
        running = {s['name'] for s in pod['status'].get('containerStatuses', []) if 'running' in s.get('state', {})}
        if container not in running:
            raise KubernetesError('Only running containers can be browsed')
        return pod

    def volumes(self, pod, container):
        """Mount points of a container, marking PersistentVolumeClaims and Longhorn."""
        namespace = pod['metadata']['namespace']
        sources = {v['name']: v for v in pod['spec'].get('volumes', [])}
        spec = next(c for c in pod['spec']['containers'] if c['name'] == container)
        found = {}
        for mount in spec.get('volumeMounts', []):
            path = normalize(mount['mountPath'])
            source = sources.get(mount['name'], {})
            value = {'name': mount['name'], 'read_only': bool(mount.get('readOnly'))}
            claim = source.get('persistentVolumeClaim', {}).get('claimName')
            if claim:
                value.update(claim=claim, longhorn=self.longhorn(namespace, claim))
            found[path] = value
        return found

    def longhorn(self, namespace, claim):
        key = (namespace, claim)
        if key not in self.claims:
            try:
                value = self.get('pvc', claim, '-n', namespace)
                notes = value.get('metadata', {}).get('annotations', {})
                self.claims[key] = any(notes.get(name) == LONGHORN for name in PROVISIONER)
            except (OSError, ValueError):
                self.claims[key] = None
        return self.claims[key]

    # --- rows ------------------------------------------------------------

    @staticmethod
    def parse(line, path, link=False):
        if line[:2] in ('L ', 'F '):
            link, line = line[0] == 'L', line[2:]
        size, modified, mode, _ = line.split(' ', 3)
        mode = int(mode, 16)
        kind = 'directory' if modes.S_ISDIR(mode) else 'file' if modes.S_ISREG(mode) else 'other'
        row = {'name': path.rsplit('/', 1)[-1], 'path': path, 'type': kind,
               'size': int(size) if kind == 'file' else None,
               'modified': datetime.fromtimestamp(int(modified), timezone.utc).isoformat()}
        if link:
            row['link'] = True
        return row

    def inventory(self, parts, path):
        row = {'name': parts[-1] if parts else '', 'path': path, 'type': 'directory', 'size': None, 'modified': None,
               'fixed': True}
        if parts[1:2] == [VOLUMES]:
            if len(parts) == 3:
                claim = self.get_or_none('pvc', parts[2], '-n', parts[0])
                if not claim:
                    raise FileNotFoundError('Volume claim not found')
                return self.claim_row(claim, self.get('pods', '-n', parts[0])['items'], path)
        elif len(parts) == 2:
            pod = self.get('pod', parts[1], '-n', parts[0])
            row['state'] = pod.get('status', {}).get('phase')
        elif len(parts) == 3:
            pod = self.container(*parts)
            row['volumes'] = [{'path': k, **v} for k, v in sorted(self.volumes(pod, parts[2]).items())]
        return row

    def stat(self, path):
        path = normalize(path)
        parts, inner = self.split(path)
        if len(parts) < 3 or inner == '/':
            return self.inventory(parts, path)
        target, inner, _ = self.enter(parts, inner)
        row = self.parse(self.shell(target, STAT, inner).decode('utf-8', 'replace').rstrip('\n'), path)
        if row.get('link'):
            # Planning a delete or copy sees the link itself, as a file, so a
            # recursive delete removes the link and never walks into its target.
            row['type'] = 'file'
        return row

    def list(self, path, limit):
        path = normalize(path)
        parts, inner = self.split(path)
        if not parts:
            names = [(n, {'kind': 'Namespace'}) for n in self.namespaces]
        elif len(parts) == 1:
            pods = self.get('pods', '-n', parts[0])['items']
            names = [(p['metadata']['name'], {'state': p.get('status', {}).get('phase'),
                                              'kind': f"Pod · {p.get('status', {}).get('phase', 'Unknown')}"}) for p in pods]
            names.append((VOLUMES, {'state': 'volume claims', 'kind': 'Volume claims'}))
        elif parts[1] == VOLUMES and len(parts) == 2:
            claims = self.get('pvc', '-n', parts[0])['items']
            pods = self.get('pods', '-n', parts[0])['items']
            rows = [self.claim_row(c, pods, child_path(path, c['metadata']['name'])) for c in claims]
            return listing(rows[:limit + 1], 0)
        elif len(parts) == 2:
            pod = self.get('pod', parts[1], '-n', parts[0])
            running = {s['name'] for s in pod.get('status', {}).get('containerStatuses', []) if 'running' in s.get('state', {})}
            names = [(c['name'], {'state': 'running' if c['name'] in running else 'not running',
                                  'kind': 'Container · ' + ('running' if c['name'] in running else 'not running')})
                     for c in pod['spec'].get('containers', [])]
        else:
            return self.files(parts, inner, path, limit)
        rows, skipped = [], 0
        for name, extra in names:
            child = child_path(path, name)
            if child is None:
                skipped += 1
                continue
            rows.append({'name': name, 'path': child, 'type': 'directory', 'size': None, 'modified': None, 'fixed': True,
                         **(extra or {})})
            if len(rows) > limit:
                break
        return listing(rows, skipped)

    def files(self, parts, inner, path, limit):
        mounts = {} if parts[1] == VOLUMES else None
        target, inner, pod = self.enter(parts, inner)
        if mounts is None:
            mounts = self.volumes(pod, parts[2])
        rows, skipped = [], 0
        for raw in self.shell(target, LIST, inner).split(b'\n'):
            if not raw:
                continue
            try:
                flag, line = raw.decode('utf-8').split(' ', 1)
                name = line.split(' ', 3)[3]
                child = child_path(path, name)
                if child is None or '/' in name:
                    raise ValueError
                row = self.parse(line, child, link=flag == 'L')
            except (UnicodeDecodeError, ValueError, IndexError):
                # Names with newlines or invalid UTF-8 cannot be addressed safely.
                skipped += 1
                continue
            mount = mounts.get(normalize(inner.rstrip('/') + '/' + name))
            if mount:
                row['volume'] = mount
            rows.append(row)
            if len(rows) > limit:
                break
        return listing(rows, skipped)

    # --- files -----------------------------------------------------------

    def open(self, path):
        parts, inner = self.split(path)
        if len(parts) < 3 or inner == '/':
            raise PermissionError('Only files may be read')
        target, inner, _ = self.enter(parts, inner)
        info = self.parse(self.shell(target, FOLLOW, inner).decode('utf-8', 'replace').rstrip('\n'), normalize(path))
        if info['type'] != 'file':
            raise PermissionError('Only files may be read')
        return KubernetesReader(self, target, inner, info['size'])

    def writable(self, path):
        if self.config.get('read_only', False):
            raise PermissionError('Endpoint is read-only')
        parts, inner = self.split(path)
        if len(parts) < 3 or inner == '/':
            raise PermissionError('Namespaces, pods, containers and volumes cannot be changed here')
        target, inner, _ = self.enter(parts, inner)
        return target, inner

    def mkdir(self, path):
        parts, inner = self.writable(path)
        self.shell(parts, MKDIR, inner)
        return {'path': normalize(path)}

    def rename(self, source, destination):
        parts, inner = self.writable(source)
        target, other = self.writable(destination)
        if parts != target:
            raise PermissionError('Rename stays within one container; use Copy and Paste between containers')
        self.shell(parts, RENAME, inner, other)
        return {'path': normalize(destination)}

    def remove(self, path):
        parts, inner = self.writable(path)
        self.shell(parts, REMOVE, inner)
        return {'removed': normalize(path)}

    def begin_write(self, path, overwrite=False):
        parts, inner = self.writable(path)
        if not overwrite:
            try:
                self.shell(parts, STAT, inner)
                raise FileExistsError('Destination already exists')
            except FileNotFoundError:
                pass
        return KubernetesUpload(self, parts, inner, overwrite)

    def close(self):
        for target in list(self.shells):
            self.drop(target)
        # Release volumes promptly so their workloads can start again; the
        # helper's deadline covers a service that stops without closing.
        for namespace, name in self.helpers:
            try:
                self.run([*self.kubectl(), 'delete', 'pod', name, '-n', namespace, '--wait=false', '--ignore-not-found'])
            except (OSError, ValueError):
                pass


class ShellBroken(Exception):
    def __init__(self, started):
        super().__init__('Shell ended')
        self.started = started


class Shell:
    """One `kubectl exec -i ... sh` that runs a session's commands in a container.

    Each command runs in a subshell, so a script's `exit` ends only that command,
    with its stdin from /dev/null so it cannot read the next command. Its output
    is followed by a newline and a random marker carrying the exit status, which
    frames binary file data without any length bookkeeping.
    """
    def __init__(self, argv, env):
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
        self.chunks = queue.Queue()
        self.buffer = b''
        self.started = False
        threading.Thread(target=self.pump, daemon=True).start()

    def pump(self):
        try:
            while data := self.process.stdout.read1(1024 * 1024):
                self.chunks.put(data)
        except (OSError, ValueError):
            pass
        self.chunks.put(None)

    def alive(self):
        return self.process.poll() is None

    @staticmethod
    def quote(value):
        return "'" + value.replace("'", "'\\''") + "'"

    def command(self, script, args, timeout, max_bytes):
        nonce = secrets.token_hex(16)
        line = (f"( set -- {' '.join(self.quote(a) for a in args)}; {script}\n) </dev/null 2>/dev/null; "
                f"printf '\\n{nonce} %d\\n' $?\n")
        try:
            self.process.stdin.write(line.encode())
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise ShellBroken(self.started) from None
        marker = b'\n' + nonce.encode() + b' '
        deadline = time.monotonic() + timeout
        while True:
            found = self.buffer.find(marker)
            if found >= 0:
                end = self.buffer.find(b'\n', found + len(marker))
                if end >= 0:
                    data, status = self.buffer[:found], int(self.buffer[found + len(marker):end])
                    self.buffer = self.buffer[end + 1:]
                    self.started = True
                    if status:
                        raise KubernetesFilesystem.failure(status, '')
                    if len(data) > max_bytes:
                        raise ValueError('Response is too large; select a smaller folder')
                    return data
            if len(self.buffer) > max_bytes + 4096:
                # Stop reading rather than buffer an oversized answer; the shell is
                # replaced on the next command.
                self.close()
                raise ValueError('Response is too large; select a smaller folder')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise TimeoutError('Kubernetes operation timed out')
            try:
                data = self.chunks.get(timeout=remaining)
            except queue.Empty:
                continue
            if data is None:
                raise ShellBroken(self.started)
            self.buffer += data

    def close(self):
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()


class KubernetesReader:
    """Bounded range reads; each chunk is one short exec, so no stream outlives a read."""
    def __init__(self, fs, parts, inner, size):
        self.fs, self.parts, self.inner, self.size, self.position = fs, parts, inner, size, 0
        self.buffer = io.BytesIO()

    def seek(self, offset):
        self.position = offset
        self.buffer = io.BytesIO()

    def read(self, size):
        data = self.buffer.read(size)
        if not data and self.position < self.size:
            count = min(4 * 1024 * 1024, self.size - self.position)
            self.buffer = io.BytesIO(self.fs.shell(self.parts, READ, self.inner, str(self.position + 1), str(count),
                                                   max_bytes=count))
            data = self.buffer.read(size)
            if not data:
                raise OSError('File changed or download was incomplete')
        self.position += len(data)
        return data

    def close(self):
        self.buffer.close()


class KubernetesUpload:
    def __init__(self, fs, parts, inner, overwrite):
        self.fs, self.parts, self.inner, self.overwrite = fs, parts, inner, overwrite
        self.file = tempfile.NamedTemporaryFile(dir=fs.config['_scratch'], delete=False)

    def write(self, data):
        return self.file.write(data)

    def commit(self):
        self.file.close()
        try:
            with open(self.file.name, 'rb') as source:
                self.fs.shell(self.parts, WRITE, self.inner, 'replace' if self.overwrite else 'new', stdin=source)
        finally:
            Path(self.file.name).unlink(missing_ok=True)

    def abort(self):
        self.file.close()
        Path(self.file.name).unlink(missing_ok=True)

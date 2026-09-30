"""Browse the files inside running pods through `kubectl exec`.

Paths are /<namespace>/<pod>/<container>/<path inside the container>. The first
three levels are read-only inventory; below them every operation is a short POSIX
shell script run in the container, so any image with `sh` and coreutils or
BusyBox works. Nothing is installed in the pod and no shell runs on the host.
"""
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import stat as modes
import subprocess
import tempfile
from .policy import normalize
from .backends import child_path, listing

LONGHORN = 'driver.longhorn.io'
PROVISIONER = ('volume.kubernetes.io/storage-provisioner', 'volume.beta.kubernetes.io/storage-provisioner')
ROW = '"%s %Y %f %n"'

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


class KubernetesFilesystem:
    def __init__(self, config):
        self.config = config
        self.namespaces = config['namespaces']
        self.timeout = config['_timeout']
        self.claims = {}
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

    def run(self, argv, stdin=None, max_bytes=16 * 1024 * 1024):
        env = {k: v for k, v in os.environ.items() if k != 'KUBECONFIG' or not self.config.get('kubeconfig')}
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
        return json.loads(self.run([*self.kubectl(), 'get', *args, '-o', 'json']))

    def shell(self, target, script, *args, stdin=None, max_bytes=16 * 1024 * 1024):
        namespace, pod, container = target
        return self.run([*self.exec_argv(namespace, pod, container, stdin is not None), 'sh', '-c', script, 'sh', *args],
                        stdin=stdin, max_bytes=max_bytes)

    # --- paths -----------------------------------------------------------

    def split(self, path):
        path = normalize(path)
        parts = path.strip('/').split('/') if path != '/' else []
        if parts and parts[0] not in self.namespaces:
            raise PermissionError('Namespace is not permitted')
        inner = '/' + '/'.join(parts[3:])
        return parts[:3], inner

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
        if len(parts) == 2:
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
        self.container(*parts)
        row = self.parse(self.shell(parts, STAT, inner).decode('utf-8', 'replace').rstrip('\n'), path)
        if row.get('link'):
            # Planning a delete or copy sees the link itself, as a file, so a
            # recursive delete removes the link and never walks into its target.
            row['type'] = 'file'
        return row

    def list(self, path, limit):
        path = normalize(path)
        parts, inner = self.split(path)
        if not parts:
            names = [(n, None) for n in self.namespaces]
        elif len(parts) == 1:
            pods = self.get('pods', '-n', parts[0])['items']
            names = [(p['metadata']['name'], {'state': p.get('status', {}).get('phase')}) for p in pods]
        elif len(parts) == 2:
            pod = self.get('pod', parts[1], '-n', parts[0])
            running = {s['name'] for s in pod.get('status', {}).get('containerStatuses', []) if 'running' in s.get('state', {})}
            names = [(c['name'], {'state': 'running' if c['name'] in running else 'not running'})
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
        pod = self.container(*parts)
        mounts = self.volumes(pod, parts[2])
        rows, skipped = [], 0
        for raw in self.shell(parts, LIST, inner).split(b'\n'):
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
        self.container(*parts)
        info = self.parse(self.shell(parts, FOLLOW, inner).decode('utf-8', 'replace').rstrip('\n'), normalize(path))
        if info['type'] != 'file':
            raise PermissionError('Only files may be read')
        return KubernetesReader(self, parts, inner, info['size'])

    def writable(self, path):
        if self.config.get('read_only', False):
            raise PermissionError('Endpoint is read-only')
        parts, inner = self.split(path)
        if len(parts) < 3 or inner == '/':
            raise PermissionError('Namespaces, pods and containers cannot be changed here')
        self.container(*parts)
        return parts, inner

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
        pass


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

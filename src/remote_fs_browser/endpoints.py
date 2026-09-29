"""Optional host-configured storage adapters. Descriptors carry aliases only."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from .policy import normalize
from .backends import child_path, listing


class RcloneFilesystem:
    def __init__(self, config):
        self.config = config
        self.base = config['remote'] + ':' + normalize(config.get('root', '/')).strip('/')
        self.timeout = config['_timeout']
        # Verify the configured root and fail during connection, not on first use.
        self.stat('/')

    def target(self, path):
        suffix = normalize(path).lstrip('/')
        return self.base.rstrip('/') + ('/' if self.base.split(':', 1)[1] and suffix else '') + suffix

    def run(self, command, *args, max_bytes=16 * 1024 * 1024):
        # Never invoke a shell or expose provider error text (which can contain secrets).
        env = {k: v for k, v in os.environ.items() if not k.startswith('RCLONE_')}
        if os.environ.get('RCLONE_CONFIG_PASS'):
            env['RCLONE_CONFIG_PASS'] = os.environ['RCLONE_CONFIG_PASS']
        argv = ['rclone', command, '--config', self.config['config'], '--ask-password=false',
                '--retries', '1', '--low-level-retries', '1', '--contimeout', f'{self.timeout}s',
                '--timeout', f'{self.timeout}s', *args]
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=output,
                                        stderr=subprocess.DEVNULL, timeout=self.timeout, env=env)
            except FileNotFoundError:
                raise ValueError('Install rclone on the service host and put it on PATH') from None
            except subprocess.TimeoutExpired:
                raise TimeoutError('rclone operation timed out') from None
            if result.returncode in (3, 4):
                raise FileNotFoundError('Remote path not found')
            if result.returncode:
                raise OSError('rclone operation failed; check the host configuration and provider permissions')
            output.seek(0)
            data = output.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError('Remote response is too large; select a smaller folder')
            return data

    @staticmethod
    def row(value, path):
        return {'name': path.rsplit('/', 1)[-1], 'path': path,
                'type': 'directory' if value['IsDir'] else 'file',
                'size': None if value['IsDir'] else value.get('Size'),
                'modified': value.get('ModTime') or None}

    def stat(self, path):
        path = normalize(path)
        value = json.loads(self.run('lsjson', '--stat', self.target(path)))
        return self.row(value, path)

    def list(self, path, limit):
        path = normalize(path)
        values = json.loads(self.run('lsjson', self.target(path)))
        rows, skipped = [], 0
        for value in values:
            name = value.get('Name', '')
            child = child_path(path, name)
            if not name or '/' in name or child is None:
                skipped += 1
                continue
            rows.append(self.row(value, child))
            if len(rows) > limit:
                break
        return listing(rows, skipped)

    def open(self, path):
        info = self.stat(path)
        if info['type'] != 'file':
            raise PermissionError('Only files may be read')
        if not isinstance(info['size'], int) or info['size'] < 0:
            raise ValueError('This provider did not report a downloadable file size')
        return RcloneReader(self, normalize(path), info['size'])

    def writable(self):
        if self.config.get('read_only', True):
            raise PermissionError('Endpoint is read-only')

    def existing(self, path):
        # Listing the parent distinguishes a missing object from S3's synthetic directories.
        parent, name = normalize(path).rsplit('/', 1)
        values = json.loads(self.run('lsjson', self.target(parent or '/')))
        return next((value for value in values if value['Name'] == name), None)

    def absent(self, path):
        if self.existing(path) is not None:
            raise FileExistsError('Destination already exists')

    def begin_write(self, path, overwrite=False):
        self.writable()
        path = normalize(path)
        if path == '/':
            raise PermissionError('Cannot replace the selected root')
        if not overwrite:
            self.absent(path)
        else:
            existing = self.existing(path)
            if existing is not None and existing['IsDir']:
                raise IsADirectoryError('Cannot replace a folder with a file')
        return RcloneUpload(self, path, overwrite)

    def mkdir(self, path):
        self.writable()
        path = normalize(path)
        if path == '/':
            raise FileExistsError('Root already exists')
        self.absent(path)
        self.run('mkdir', self.target(path))
        return {'path': path}

    def remove(self, path):
        self.writable()
        if normalize(path) == '/':
            raise PermissionError('Cannot remove the selected root')
        command = 'rmdir' if self.stat(path)['type'] == 'directory' else 'deletefile'
        self.run(command, self.target(path))
        return {'removed': normalize(path)}

    def close(self):
        pass


class RcloneReader:
    """Bounded range reads; no subprocess survives an individual read operation."""
    def __init__(self, fs, path, size):
        self.fs, self.path, self.size, self.position = fs, path, size, 0
        self.buffer = io.BytesIO()

    def seek(self, offset):
        self.position = offset
        self.buffer = io.BytesIO()

    def read(self, size):
        data = self.buffer.read(size)
        if not data and self.position < self.size:
            count = min(4 * 1024 * 1024, self.size - self.position)
            self.buffer = io.BytesIO(self.fs.run('cat', self.fs.target(self.path), '--offset',
                                               str(self.position), '--count', str(count), max_bytes=count))
            data = self.buffer.read(size)
            if not data:
                raise OSError('Remote file changed or download was incomplete')
        self.position += len(data)
        return data

    def close(self):
        self.buffer.close()


class RcloneUpload:
    def __init__(self, fs, path, overwrite):
        self.fs, self.path, self.overwrite = fs, path, overwrite
        self.file = tempfile.NamedTemporaryFile(dir=fs.config['_scratch'], delete=False)

    def write(self, data):
        return self.file.write(data)

    def commit(self):
        self.file.close()
        if not self.overwrite:
            self.fs.absent(self.path)
        self.fs.run('copyto', self.file.name, self.fs.target(self.path),
                    '--ignore-times' if self.overwrite else '--immutable')
        Path(self.file.name).unlink(missing_ok=True)

    def abort(self):
        self.file.close()
        Path(self.file.name).unlink(missing_ok=True)


class LibvirtFilesystem:
    """Read-only pool/volume inventory, deliberately not a guest disk filesystem."""
    def __init__(self, config):
        try:
            import libvirt
        except ImportError:
            raise ValueError('Install libvirt and the remote-fs-browser[libvirt] extra on the service host') from None
        self.connection = libvirt.openReadOnly(config['uri'])
        self.pools = config['pools']

    def pool(self, name):
        if name not in self.pools:
            raise PermissionError('Pool is not permitted')
        return self.connection.storagePoolLookupByName(name)

    def stat(self, path):
        path = normalize(path)
        parts = path.strip('/').split('/') if path != '/' else []
        row = {'name': parts[-1] if parts else '', 'path': path, 'type': 'directory', 'size': None, 'modified': None}
        if not parts:
            return row
        pool = self.pool(parts[0])
        if len(parts) == 1:
            state, capacity, allocation, available = pool.info()
            return {**row, 'state': state, 'capacity': capacity, 'allocation': allocation, 'available': available}
        if len(parts) != 2:
            raise FileNotFoundError('Volumes have no browsable guest directories')
        volume = pool.storageVolLookupByName(parts[1])
        kind, capacity, allocation = volume.info()
        return {**row, 'type': 'other', 'size': capacity, 'capacity': capacity, 'allocation': allocation, 'volume_type': kind}

    def list(self, path, limit):
        path = normalize(path)
        if path == '/':
            # Only active permitted pools can enumerate volumes. Inactive pools still have metadata.
            names = self.pools
        elif len(path.strip('/').split('/')) == 1:
            names = self.pool(path.strip('/')).listVolumes()
        else:
            raise NotADirectoryError('A volume is not a guest filesystem')
        rows, skipped = [], 0
        for name in names:
            child = child_path(path, name)
            if child is None or '/' in name:
                skipped += 1
                continue
            rows.append(self.stat(child))
            if len(rows) > limit:
                break
        return listing(rows, skipped)

    def close(self):
        self.connection.close()

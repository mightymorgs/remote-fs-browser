"""Backend-neutral read-only operations; network connections belong to one worker."""
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from .policy import normalize


def entry(name, path, mode, size, modified):
    kind = 'directory' if stat.S_ISDIR(mode) else 'file' if stat.S_ISREG(mode) else 'other'
    return {'name': name, 'path': path, 'type': kind,
            'size': size if kind == 'file' else None,
            'modified': datetime.fromtimestamp(modified, timezone.utc).isoformat() if modified else None}


def child_path(path, name):
    """Session path of a directory entry, or None when the name cannot be addressed safely."""
    try:
        return normalize(path + '/' + name)
    except ValueError:
        return None


def listing(rows, skipped):
    return {'entries': rows, 'skipped': skipped}


class LocalFilesystem:
    def __init__(self, config):
        self.root = Path(config['root']).resolve(strict=True)
        self.root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY) if os.name != 'nt' else None

    def _open(self, path, directory=False):
        parts = normalize(path).strip('/').split('/') if normalize(path) != '/' else []
        if os.name != 'nt':
            fd = os.dup(self.root_fd)
            try:
                for i, part in enumerate(parts):
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    if directory or i < len(parts) - 1:
                        flags |= os.O_DIRECTORY
                    next_fd = os.open(part, flags, dir_fd=fd)
                    os.close(fd)
                    fd = next_fd
                return fd
            except Exception:
                os.close(fd)
                raise
        target = self.root.joinpath(*parts)
        for parent in [target, *target.parents]:
            if parent == self.root:
                break
            if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
                raise PermissionError('Links are not browsable')
        if not target.resolve(strict=True).is_relative_to(self.root):
            raise PermissionError('Path leaves the selected root')
        if directory:
            return str(target)
        fd = os.open(target, os.O_RDONLY | os.O_BINARY)
        try:
            # Validate the actual opened Windows handle, not just its earlier pathname.
            import ctypes as c
            import msvcrt
            from ctypes import wintypes
            fn = c.windll.kernel32.GetFinalPathNameByHandleW
            fn.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            fn.restype = wintypes.DWORD
            buffer = c.create_unicode_buffer(32768)
            count = fn(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
            if not count or count >= len(buffer):
                raise PermissionError('Cannot validate file handle')
            final = buffer.value.removeprefix('\\\\?\\')
            if final.startswith('UNC\\'):
                final = '\\\\' + final[4:]
            if not Path(final).is_relative_to(self.root):
                raise PermissionError('File leaves the selected root')
            return fd
        except Exception:
            os.close(fd)
            raise

    def list(self, path, limit):
        path = normalize(path)
        handle = self._open(path, directory=True)
        rows, skipped = [], 0
        try:
            with os.scandir(handle) as entries:
                for item in entries:
                    if item.is_symlink() or (os.name == 'nt' and getattr(item.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
                        continue
                    child = child_path(path, item.name)
                    if child is None:
                        skipped += 1
                        continue
                    info = item.stat(follow_symlinks=False)
                    rows.append(entry(item.name, child, info.st_mode, info.st_size, info.st_mtime))
                    if len(rows) > limit:
                        break
        finally:
            if isinstance(handle, int):
                os.close(handle)
        return listing(rows, skipped)

    def stat(self, path):
        if os.name == 'nt':
            target = self._open(path, directory=True)
            info = os.stat(target, follow_symlinks=False)
            return entry(Path(path).name, normalize(path), info.st_mode, info.st_size, info.st_mtime)
        handle = self._open(path, directory=False)
        try:
            info = os.fstat(handle)
            return entry(Path(path).name, normalize(path), info.st_mode, info.st_size, info.st_mtime)
        finally:
            os.close(handle)

    def open(self, path):
        fd = self._open(path)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise PermissionError('Only regular files may be read')
        return os.fdopen(fd, 'rb')

    def close(self):
        if self.root_fd is not None:
            os.close(self.root_fd)
            self.root_fd = None


class SMBFilesystem:
    def __init__(self, config):
        import smbclient
        self.client, self.cache = smbclient, {}
        host = config['host']
        if ':' in host:
            raise ValueError('SMB IPv6 literals are not supported; use an IPv4 address')
        self.root = '\\\\' + host + '\\' + config['share']
        username = config.get('username')
        if config.get('domain') and username and '\\' not in username:
            username = config['domain'] + '\\' + username
        try:
            smbclient.register_session(host, username=username, password=config.get('password'),
                                       connection_timeout=8, connection_cache=self.cache, auth_protocol='ntlm')
        except Exception:
            self.close()
            raise

    def _path(self, path):
        path = normalize(path)
        current = self.root
        for part in path.strip('/').split('/') if path != '/' else []:
            current += '\\' + part
            info = self.client.stat(current, follow_symlinks=False, connection_cache=self.cache)
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise PermissionError('Links and reparse points are not browsable')
        return current

    def list(self, path, limit):
        rows, skipped = [], 0
        for item in self.client.scandir(self._path(path), connection_cache=self.cache):
            info = item.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                continue
            child = child_path(path, item.name)
            if child is None:
                skipped += 1
                continue
            rows.append(entry(item.name, child, info.st_mode, info.st_size, info.st_mtime))
            if len(rows) > limit:
                break
        return listing(rows, skipped)

    def stat(self, path):
        info = self.client.stat(self._path(path), follow_symlinks=False, connection_cache=self.cache)
        return entry(path.rsplit('/', 1)[-1], normalize(path), info.st_mode, info.st_size, info.st_mtime)

    def open(self, path):
        if self.stat(path)['type'] != 'file':
            raise PermissionError('Only regular files may be read')
        return self.client.open_file(self._path(path), mode='rb', connection_cache=self.cache)

    def close(self):
        self.client.reset_connection_cache(connection_cache=self.cache)

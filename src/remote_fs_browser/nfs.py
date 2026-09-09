"""ctypes binding for libnfs 6+ (API V2). Only read operations are exposed."""
import ctypes as c
import ctypes.util
import os
import stat
from pathlib import Path
from .backends import child_path, entry, listing
from .policy import normalize


class Stat(c.Structure):
    _fields_ = [(key, c.c_uint64) for key in ('dev', 'ino', 'mode', 'nlink', 'uid', 'gid', 'rdev', 'size', 'blksize', 'blocks', 'atime', 'mtime', 'ctime', 'atime_nsec', 'mtime_nsec', 'ctime_nsec', 'used')]


class Timeval(c.Structure):
    _fields_ = [('seconds', c.c_long), ('microseconds', c.c_long)]


class DirEntry(c.Structure):
    _fields_ = [('next', c.c_void_p), ('name', c.c_char_p), ('inode', c.c_uint64), ('type', c.c_uint32), ('mode', c.c_uint32), ('size', c.c_uint64), ('atime', Timeval), ('mtime', Timeval)]


def candidates():
    """Where package managers put libnfs when the dynamic linker does not search there itself."""
    import glob
    prefixes = [os.environ.get('HOMEBREW_PREFIX'), '/opt/homebrew', '/usr/local', '/opt/local']
    rows = [f'{prefix}/lib/libnfs.dylib' for prefix in prefixes if prefix]
    rows += sorted(glob.glob('/usr/lib/*/libnfs.so*')) + sorted(glob.glob('/usr/local/lib/libnfs.so*'))
    return [row for row in rows if os.path.isfile(row)]


def library():
    path = os.environ.get('LIBNFS_LIBRARY') or ctypes.util.find_library('nfs') or next(iter(candidates()), None)
    if not path:
        raise RuntimeError('Install libnfs 6+ (for example: brew install libnfs) or set LIBNFS_LIBRARY')
    lib = c.CDLL(path)
    if not hasattr(lib, 'nfs_preadv'):
        raise RuntimeError('libnfs API V2 (6+) is required; run the platform installer')
    P = c.c_void_p
    for name, args, result in [
        ('nfs_init_context', [], P), ('nfs_destroy_context', [P], None),
        ('nfs_set_version', [P, c.c_int], c.c_int), ('nfs_set_timeout', [P, c.c_int], None),
        ('nfs_set_dircache', [P, c.c_int], None), ('nfs_mount', [P, c.c_char_p, c.c_char_p], c.c_int),
        ('nfs_lstat64', [P, c.c_char_p, c.POINTER(Stat)], c.c_int),
        ('nfs_opendir', [P, c.c_char_p, c.POINTER(P)], c.c_int),
        ('nfs_readdir', [P, P], c.POINTER(DirEntry)), ('nfs_closedir', [P, P], None),
        ('nfs_open', [P, c.c_char_p, c.c_int, c.POINTER(P)], c.c_int),
        ('nfs_pread', [P, P, P, c.c_size_t, c.c_uint64], c.c_int),
        ('nfs_close', [P, P], c.c_int),
    ]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    return lib


class NFSFilesystem:
    def __init__(self, config):
        self.lib = library()
        self.ctx = self.lib.nfs_init_context()
        if not self.ctx:
            raise RuntimeError('Could not allocate NFS context')
        try:
            if self.lib.nfs_set_version(self.ctx, int(config.get('version', 4))) != 0:
                raise ValueError('Unsupported NFS version')
            self.lib.nfs_set_timeout(self.ctx, 5000)
            self.lib.nfs_set_dircache(self.ctx, 0)
            if self.lib.nfs_mount(self.ctx, config['host'].encode(), config['export'].encode()) != 0:
                raise OSError('NFS connection failed')
        except Exception:
            self.close()
            raise

    def _stat(self, path):
        info = Stat()
        if self.lib.nfs_lstat64(self.ctx, path.encode(), c.byref(info)) != 0:
            raise OSError('NFS path unavailable')
        return info

    def _path(self, path):
        path = normalize(path)
        current = ''
        for part in path.strip('/').split('/') if path != '/' else []:
            current += '/' + part
            if stat.S_ISLNK(self._stat(current).mode):
                raise PermissionError('Links are not browsable')
        return path

    def stat(self, path):
        info = self._stat(self._path(path))
        return entry(path.rsplit('/', 1)[-1], normalize(path), info.mode, info.size, info.mtime)

    def list(self, path, limit):
        path = self._path(path)
        directory = c.c_void_p()
        if self.lib.nfs_opendir(self.ctx, path.encode(), c.byref(directory)) != 0:
            raise OSError('NFS folder unavailable')
        rows, skipped = [], 0
        try:
            while True:
                item = self.lib.nfs_readdir(self.ctx, directory)
                if not item:
                    break
                name = os.fsdecode(item.contents.name)
                if name not in ('.', '..') and item.contents.type != 5:
                    child = child_path(path, name)
                    if child is None:
                        skipped += 1
                        continue
                    metadata = item.contents
                    mode = metadata.mode | ({1: stat.S_IFREG, 2: stat.S_IFDIR}.get(metadata.type, 0))
                    rows.append(entry(name, child, mode, metadata.size, metadata.mtime.seconds))
                    if len(rows) > limit:
                        break
        finally:
            self.lib.nfs_closedir(self.ctx, directory)
        return listing(rows, skipped)

    def open(self, path):
        path = self._path(path)
        if not stat.S_ISREG(self._stat(path).mode):
            raise PermissionError('Only regular files may be read')
        handle = c.c_void_p()
        if self.lib.nfs_open(self.ctx, path.encode(), os.O_RDONLY, c.byref(handle)) != 0:
            raise OSError('NFS file unavailable')
        return NFSFile(self, handle)

    def close(self):
        if self.ctx:
            self.lib.nfs_destroy_context(self.ctx)
            self.ctx = None


class NFSFile:
    def __init__(self, fs, handle):
        self.fs, self.handle, self.offset = fs, handle, 0

    def seek(self, offset):
        self.offset = offset

    def read(self, count):
        buffer = c.create_string_buffer(count)
        size = self.fs.lib.nfs_pread(self.fs.ctx, self.handle, buffer, count, self.offset)
        if size < 0:
            raise OSError('NFS read failed')
        self.offset += size
        return buffer.raw[:size]

    def close(self):
        if self.handle:
            self.fs.lib.nfs_close(self.fs.ctx, self.handle)
            self.handle = None

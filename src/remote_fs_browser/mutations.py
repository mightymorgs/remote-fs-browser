"""Staged file writes and backend mutation primitives. No operation follows links."""
import ctypes
import errno
import os
import secrets
import stat
import sys
from contextlib import contextmanager, suppress
from .policy import normalize


def split(path):
    path = normalize(path)
    parent, name = path.rsplit('/', 1)
    if not name:
        raise PermissionError('The selected root cannot be changed')
    return parent or '/', name


def rename_exclusive(source, destination, source_fd=None, destination_fd=None):
    """Use the platform's atomic no-replace rename, including for directories."""
    if os.name == 'nt':
        return os.rename(source, destination)
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        fn, flag = libc.renameatx_np, 4  # RENAME_EXCL
    else:
        fn, flag = libc.renameat2, 1  # RENAME_NOREPLACE
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(source_fd, os.fsencode(source), destination_fd, os.fsencode(destination), flag):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


@contextmanager
def local_parent(fs, path):
    parent, name = split(path)
    handle = fs._open(parent, directory=True)
    lock = None
    try:
        if isinstance(handle, int):
            yield name, {'dir_fd': handle}
        else:
            # Hold a Windows directory handle without FILE_SHARE_DELETE so a
            # concurrent rename/junction replacement cannot redirect the mutation.
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            lock = create(handle, 0x80, 3, None, 3, 0x02000000, None)
            if lock == wintypes.HANDLE(-1).value:
                lock = None
                raise ctypes.WinError(ctypes.get_last_error())
            final = kernel.GetFinalPathNameByHandleW
            final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            final.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            length = final(lock, buffer, len(buffer), 0)
            from pathlib import Path
            resolved = buffer.value.removeprefix('\\\\?\\')
            if resolved.startswith('UNC\\'):
                resolved = '\\\\' + resolved[4:]
            if not length or length >= len(buffer) or not Path(resolved).is_relative_to(fs.root):
                raise PermissionError('Path leaves the selected root')
            yield os.path.join(handle, name), {}
    finally:
        if isinstance(handle, int):
            os.close(handle)
        if lock is not None:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(lock)


class LocalMutations:
    def begin_write(self, path, overwrite=False):
        return LocalWrite(self, path, overwrite)

    def rename(self, source, destination):
        split(source); split(destination)
        # Validate the source type and refuse links/special files.
        if self.stat(source)['type'] not in ('file', 'directory'):
            raise PermissionError('Only files and folders can be moved')
        with local_parent(self, source) as (src, sk), local_parent(self, destination) as (dst, dk):
            rename_exclusive(src, dst, sk.get('dir_fd'), dk.get('dir_fd'))
        return {'path': normalize(destination)}

    def remove(self, path):
        kind = self.stat(path)['type']
        if kind not in ('file', 'directory'):
            raise PermissionError('Only files and folders can be deleted')
        with local_parent(self, path) as (name, kwargs):
            (os.rmdir if kind == 'directory' else os.unlink)(name, **kwargs)
        return {'removed': normalize(path)}


class LocalWrite:
    def __init__(self, fs, path, overwrite):
        self.parent = local_parent(fs, path)
        self.destination, self.kwargs = self.parent.__enter__()
        self.temp = os.path.join(os.path.dirname(self.destination), '.remotefs-' + secrets.token_hex(16) + '.part')
        self.file, self.done = None, False
        self.overwrite = overwrite
        try:
            try:
                old = os.stat(self.destination, follow_symlinks=False, **self.kwargs)
            except FileNotFoundError:
                old = None
            if old and (not overwrite or not stat.S_ISREG(old.st_mode) or getattr(old, 'st_file_attributes', 0) & 0x400):
                raise FileExistsError('Destination already exists or is not a regular file')
            fd = os.open(self.temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600, **self.kwargs)
            self.file = os.fdopen(fd, 'wb')
            if old and os.name != 'nt':
                os.fchmod(fd, stat.S_IMODE(old.st_mode))
        except BaseException:
            self.abort()
            raise

    def write(self, data):
        return self.file.write(data)

    def commit(self):
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        if self.overwrite:
            fd = self.kwargs.get('dir_fd')
            os.replace(self.temp, self.destination, src_dir_fd=fd, dst_dir_fd=fd)
        else:
            rename_exclusive(self.temp, self.destination, self.kwargs.get('dir_fd'), self.kwargs.get('dir_fd'))
        self.done = True
        self.parent.__exit__(None, None, None)

    def abort(self):
        if self.done:
            return
        if self.file:
            self.file.close()
        with suppress(OSError):
            os.unlink(self.temp, **self.kwargs)
        self.done = True
        self.parent.__exit__(None, None, None)


class SMBMutations:
    def destination(self, path):
        parent, name = split(path)
        return self._path(parent) + '\\' + name

    def begin_write(self, path, overwrite=False):
        return RemoteWrite(self, path, overwrite)

    def raw_write(self, path):
        return self.client.open_file(self.destination(path), mode='xb', connection_cache=self.cache)

    def commit_write(self, source, destination, overwrite):
        source, destination = self._path(source), self.destination(destination)
        # Adapted from smbprotocol's MIT-licensed _rename_information
        # (copyright Jordan Borean; see licenses/smbprotocol/LICENSE).
        # smbclient.rename/replace open the destination with FILE_EXECUTE to resolve
        # DFS, which Samba can reject for ordinary non-executable data files.
        # Resolve it with metadata access, retaining the same atomic rename.
        from smbclient._io import SMBRawIO, SMBFileTransaction, set_info
        from smbprotocol.file_info import FileRenameInformation
        from smbprotocol.open import CreateOptions, FilePipePrinterAccessMask as Access
        import ntpath
        options = dict(mode='r', share_access='rwd', connection_cache=self.cache,
                       create_options=CreateOptions.FILE_OPEN_REPARSE_POINT)
        target = SMBRawIO(destination, desired_access=Access.FILE_READ_ATTRIBUTES, **options)
        try:
            SMBFileTransaction(target).commit()
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise
        with SMBRawIO(source, desired_access=Access.DELETE, **options) as handle:
            source_tree, target_tree = handle.fd.tree_connect, target.fd.tree_connect
            if (handle.fd.connection.server_guid != target.fd.connection.server_guid
                    or ntpath.normpath(source_tree.share_name).casefold() != ntpath.normpath(target_tree.share_name).casefold()):
                raise ValueError('Replacement must stay on the same share')
            path = target.fd.file_name
            if target_tree.is_dfs_share and path.startswith(target_tree.share_name[2:]):
                path = path[len(target_tree.share_name) - 1:]
            info = FileRenameInformation()
            info['replace_if_exists'], info['file_name'] = overwrite, path
            with SMBFileTransaction(handle) as transaction:
                set_info(transaction, info)

    def rename(self, source, destination):
        split(source)
        self.commit_write(source, destination, False)
        return {'path': normalize(destination)}

    def remove(self, path):
        split(path)
        kind = self.stat(path)['type']
        if kind not in ('file', 'directory'):
            raise PermissionError('Only files and folders can be deleted')
        fn = self.client.rmdir if kind == 'directory' else self.client.remove
        fn(self._path(path), connection_cache=self.cache)
        return {'removed': normalize(path)}


class RemoteWrite:
    def __init__(self, fs, path, overwrite):
        parent, _ = split(path)
        self.fs, self.path, self.overwrite = fs, normalize(path), overwrite
        self.temp = parent.rstrip('/') + '/.remotefs-' + secrets.token_hex(16) + '.part'
        self.file = fs.raw_write(self.temp)
        self.done = False

    def write(self, data):
        return self.file.write(data)

    def commit(self):
        self.file.flush()
        self.file.close()
        self.fs.commit_write(self.temp, self.path, self.overwrite)
        self.done = True

    def abort(self):
        if not self.done:
            self.file.close()
            with suppress(OSError):
                self.fs.remove(self.temp)
            self.done = True

"""One process/context per browsing session; bounded reads and deterministic cleanup."""
import asyncio
import multiprocessing
import secrets
import threading
import time
from dataclasses import asdict
from .policy import Policy, normalize

CHUNK = 256 * 1024


def worker(pipe, config, policy_values):
    from .backends import LocalFilesystem, SMBFilesystem
    from .nfs import NFSFilesystem
    from .discovery import discover, smb_shares, nfs_exports
    fs, files = None, {}
    try:
        policy = Policy(**policy_values)
        kind = config['type']
        if kind == 'discover':
            pipe.send({'ok': discover(policy, config.get('scan', False), config.get('root_kinds'))})
            return
        if kind in ('shares', 'exports'):
            host = policy.host(config['host'])
            value = smb_shares(host, config) if kind == 'shares' else nfs_exports(host)
            pipe.send({'ok': value})
            return
        if kind == 'local':
            config['root'] = policy.local_root(config['root'])
        else:
            config['host'] = policy.host(config['host'])
        if kind == 'smb':
            # Block Python-level DFS redirects outside the pinned server. This
            # hook exists only in this disposable session worker.
            import sys
            pinned = config['host']
            def socket_policy(event, args):
                if event == 'socket.connect' and isinstance(args[1], tuple) and args[1][0] != pinned:
                    raise PermissionError('SMB redirect leaves the permitted server')
            sys.addaudithook(socket_policy)
        fs = {'local': LocalFilesystem, 'smb': SMBFilesystem, 'nfs': NFSFilesystem}[kind](config)
        config.clear()
        pipe.send({'ok': True})
        while pipe.poll(policy.idle_seconds):
            operation, args = pipe.recv()
            if operation == 'close':
                break
            try:
                if operation == 'list':
                    value = fs.list(args[0], policy.max_entries)
                elif operation == 'mkdir':
                    value = fs.mkdir(args[0])
                elif operation == 'stat':
                    value = fs.stat(args[0])
                elif operation == 'open':
                    if len(files) >= 4:
                        raise ValueError('Too many active file streams')
                    handle = secrets.token_urlsafe(12)
                    files[handle] = fs.open(args[0])
                    files[handle].seek(args[1])
                    value = handle
                elif operation == 'read':
                    value = files[args[0]].read(min(args[1], CHUNK))
                elif operation == 'release':
                    handle = files.pop(args[0], None)
                    if handle:
                        handle.close()
                    value = True
                else:
                    raise ValueError('Unknown operation')
                pipe.send({'ok': value})
            except Exception:
                pipe.send({'error': 'Filesystem operation failed; check path and permissions'})
    except Exception:
        try:
            pipe.send({'error': 'Connection failed; check policy, credentials and native dependencies'})
        except (OSError, EOFError):
            pass
    finally:
        for handle in files.values():
            handle.close()
        if fs:
            fs.close()
        pipe.close()


class Worker:
    def __init__(self, config, policy):
        context = multiprocessing.get_context('spawn')
        self.pipe, child = context.Pipe()
        self.process = context.Process(target=worker, args=(child, config, asdict(policy)), daemon=True)
        self.lock = threading.RLock()
        self.timeout = policy.operation_timeout
        self.process.start()
        child.close()
        try:
            self.initial = self.receive()
        except Exception:
            self.close()
            raise

    def receive(self):
        if not self.pipe.poll(self.timeout):
            self.close()
            raise TimeoutError('Filesystem operation timed out')
        try:
            value = self.pipe.recv()
        except (OSError, EOFError):
            raise KeyError('Session expired') from None
        if 'error' in value:
            raise OSError(value['error'])
        return value['ok']

    def call(self, operation, *args):
        with self.lock:
            if not self.process.is_alive():
                raise KeyError('Session expired')
            self.pipe.send((operation, args))
            return self.receive()

    def close(self):
        with self.lock:
            if self.process.is_alive():
                try:
                    self.pipe.send(('close', ()))
                except OSError:
                    pass
                self.process.join(0.1)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(1)
            self.pipe.close()


class FilesystemSession:
    def __init__(self, worker, descriptor, policy):
        self.worker, self._descriptor, self.policy = worker, descriptor, policy
        self.id = secrets.token_urlsafe(32)
        self.last_activity = time.monotonic()
        self.closed = False
        self.active = 0

    async def _call(self, operation, *args):
        if self.closed:
            raise KeyError('Session expired')
        self.active += 1
        self.last_activity = time.monotonic()
        try:
            return await asyncio.to_thread(self.worker.call, operation, *args)
        finally:
            self.active -= 1
            self.last_activity = time.monotonic()

    async def list(self, path='/'):
        self.policy.require('list')
        result = await self._call('list', normalize(path))
        rows = result['entries']
        return {'entries': rows[:self.policy.max_entries], 'truncated': len(rows) > self.policy.max_entries,
                'skipped': result['skipped']}

    async def mkdir(self, path):
        self.policy.require('mkdir')
        return await self._call('mkdir', normalize(path))

    async def stat(self, path):
        self.policy.require('stat')
        return await self._call('stat', normalize(path))

    async def stream(self, path, offset=0, length=None):
        self.policy.require('read')
        if offset < 0 or (length is not None and length < 0):
            raise ValueError('Invalid byte range')
        handle = await self._call('open', normalize(path), offset)
        try:
            while length is None or length:
                chunk = await self._call('read', handle, min(length, CHUNK) if length is not None else CHUNK)
                if not chunk:
                    break
                if length is not None:
                    length -= len(chunk)
                yield chunk
        finally:
            if not self.closed:
                try:
                    await asyncio.shield(self._call('release', handle))
                except (KeyError, OSError):
                    pass

    def descriptor(self, path='/'):
        return {**self._descriptor, 'path': normalize(path)}

    async def close(self):
        if not self.closed:
            self.closed = True
            await asyncio.to_thread(self.worker.close)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def clean_descriptor(descriptor):
    """Only the fields that identify a location; never credentials or unknown keys."""
    kind = descriptor.get('type')
    fields = {'local': ('root',), 'smb': ('host', 'share'), 'nfs': ('host', 'export', 'version')}
    if kind not in fields:
        raise ValueError('Choose local, smb or nfs')
    clean = {'type': kind, **{k: descriptor[k] for k in fields[kind] if k in descriptor}}
    if kind == 'smb' and (not clean.get('share') or any(c in clean['share'] for c in '/\\\x00')):
        raise ValueError('Use a share name without subfolders')
    if kind == 'nfs' and (not clean.get('export', '').startswith('/') or int(clean.get('version', 4)) not in (3, 4)):
        raise ValueError('Use an absolute NFS export and version 3 or 4')
    if kind != 'local' and not clean.get('host'):
        raise ValueError('A server hostname or address is required')
    return clean


class Browser:
    def __init__(self, policy: Policy, credential_resolver=None, root_kinds=None):
        self.policy, self.credential_resolver = policy, credential_resolver
        # Labels for the picker only ("home", "volume"); authorization stays with the policy.
        self.root_kinds = dict(root_kinds or {})
        self.sessions = {}
        self.pending = 0
        self.closed = False
        self.starting = set()

    async def _worker(self, config):
        if self.closed:
            raise RuntimeError('Browser is closed')
        task = asyncio.create_task(asyncio.to_thread(Worker, config, self.policy))
        self.starting.add(task)
        try:
            value = await asyncio.shield(task)
            if self.closed:
                await asyncio.to_thread(value.close)
                raise RuntimeError('Browser is closed')
            return value
        except asyncio.CancelledError:
            try:
                value = await task
                await asyncio.to_thread(value.close)
            except Exception:
                pass
            raise
        finally:
            self.starting.discard(task)

    async def connect(self, descriptor, credentials=None):
        await self.expire()
        if len(self.sessions) + self.pending >= self.policy.max_sessions:
            raise ValueError('Session limit reached')
        clean = clean_descriptor(descriptor)
        config = dict(clean)
        ref = descriptor.get('credential_id')
        if ref:
            if not self.credential_resolver:
                raise PermissionError('No credential resolver configured')
            credentials = self.credential_resolver(ref)
            clean['credential_id'] = ref
        config.update({k: v for k, v in (credentials or {}).items() if k in ('username', 'password', 'domain')})
        self.pending += 1
        try:
            worker = await self._worker(config)
            session = FilesystemSession(worker, clean, self.policy)
            self.sessions[session.id] = session
            return session
        finally:
            self.pending -= 1

    async def discover(self, scan=False, host=None, protocol=None, credentials=None):
        self.policy.require('discover')
        config = {'type': 'discover', 'scan': scan, 'root_kinds': self.root_kinds}
        if host:
            if protocol not in ('smb', 'nfs'):
                raise ValueError('Choose smb or nfs discovery')
            config = {'type': 'shares' if protocol == 'smb' else 'exports', 'host': host,
                      **{k: v for k, v in (credentials or {}).items() if k in ('username', 'password', 'domain')}}
        if self.pending >= self.policy.max_sessions:
            raise ValueError('Discovery limit reached')
        self.pending += 1
        worker = None
        try:
            worker = await self._worker(config)
            return worker.initial
        finally:
            self.pending -= 1
            if worker:
                await asyncio.to_thread(worker.close)

    async def expire(self):
        for key, session in list(self.sessions.items()):
            if session.closed or not session.worker.process.is_alive() or (not session.active and time.monotonic() - session.last_activity > self.policy.idle_seconds):
                await session.close()
                self.sessions.pop(key, None)

    async def close(self):
        self.closed = True
        starts = await asyncio.gather(*list(self.starting), return_exceptions=True)
        for value in starts:
            if isinstance(value, Worker):
                await asyncio.to_thread(value.close)
        await asyncio.gather(*(session.close() for session in self.sessions.values()))
        self.sessions.clear()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

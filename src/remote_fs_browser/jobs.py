"""Owned, disk-backed ZIP jobs. Split parts concatenate to a standard ZIP64 archive."""
import asyncio
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import time
import zipfile
from .policy import normalize
from .store import write_private


class SplitWriter(io.RawIOBase):
    def __init__(self, directory, name, limit, budget):
        self.directory, self.name, self.limit, self.budget = directory, name, limit, budget
        self.position, self.handle, self.parts = 0, None, []

    def writable(self):
        return True

    def tell(self):
        return self.position

    def write(self, data):
        size = len(data)
        if self.position + size > self.budget:
            raise ValueError('Archive exceeded reserved space; source files may have changed')
        data = memoryview(data)
        while data:
            if self.handle is None or (self.limit and self.parts[-1]['size'] == self.limit):
                if self.handle:
                    self.handle.close()
                if len(self.parts) >= 999:
                    raise ValueError('Archive exceeds 999 parts')
                name = self.name + (f'.{len(self.parts) + 1:03}' if self.limit else '')
                self.handle = open(self.directory / name, 'xb', buffering=0)
                os.chmod(self.directory / name, 0o600)
                self.parts.append({'name': name, 'size': 0, 'downloaded': False, 'ready': False})
            count = min(len(data), self.limit - self.parts[-1]['size']) if self.limit else len(data)
            # Raw writes can be short (especially when a filesystem fills up).
            written = self.handle.write(data[:count])
            if not written:
                raise OSError('Unable to write staged archive')
            self.parts[-1]['size'] += written
            if self.limit and self.parts[-1]['size'] == self.limit:
                self.parts[-1]['ready'] = True
            self.position += written
            data = data[written:]
        return size

    def close(self):
        if self.handle:
            self.handle.close()
        super().close()


class ArchiveJobs:
    def __init__(self, stores=None):
        self.stores = {str(key): Path(value).expanduser().resolve() for key, value in (stores or {}).items()}
        self.jobs, self.tasks, self.gates, self.reserved = {}, {}, {}, {}
        for key, path in self.stores.items():
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            for manifest in path.glob('*/job.json'):
                if manifest.parent.is_symlink() or manifest.is_symlink():
                    continue
                try:
                    job = json.loads(manifest.read_text())
                    if job['id'] != manifest.parent.name or job['store_id'] != key:
                        continue
                    if job['stage'] == 'packing':
                        job.update(stage='failed', status='failed', error='Service restarted during packing; purge and pack again')
                    self.jobs[job['id']] = job
                except (ValueError, KeyError, OSError):
                    continue

    def directory(self, job):
        return self.stores[job['store_id']] / job['id']

    def save(self, job):
        write_private(self.directory(job) / 'job.json', json.dumps(job))

    def public(self, job):
        return {k: v for k, v in job.items() if k not in ('owner', 'sources')}

    def list(self, owner):
        return [self.public(job) for job in reversed(list(self.jobs.values())) if job['owner'] == owner]

    def get(self, owner, id):
        job = self.jobs.get(id)
        if not job or job['owner'] != owner:
            raise FileNotFoundError('Download job not found')
        return job

    def capacity(self):
        result = []
        for key, path in self.stores.items():
            disk = shutil.disk_usage(path)
            # Stores on one filesystem share reservations.
            device = path.stat().st_dev
            reserved = sum(amount for id, amount in self.reserved.items()
                           if self.stores[self.jobs[id]['store_id']].stat().st_dev == device)
            result.append({'id': key, 'label': key, 'path': str(path), 'total': disk.total,
                           'free': max(0, disk.free - reserved)})
        return result

    async def plan(self, session, paths, check):
        if not isinstance(paths, list) or not paths or len(paths) > session.policy.max_entries:
            raise ValueError('Choose files or folders to pack')
        rows, seen, names = [], set(), set()
        for path in paths:
            path = normalize(path)
            name = PurePosixPath(path).name or 'root'
            if name in names:
                raise ValueError('Selections must have distinct archive names')
            names.add(name)
            # Authorize traversal before asking the worker to list each directory.
            async def walk(current, archive, depth):
                if depth > 64 or len(rows) >= session.policy.max_entries:
                    raise ValueError('Archive exceeds the entry or depth limit')
                if current in seen:
                    raise ValueError('Selections overlap')
                seen.add(current)
                await check('stat', session.descriptor(current))
                info = await session.stat(current)
                if info['type'] not in ('file', 'directory'):
                    raise ValueError('Archives contain regular files and directories only')
                await check('list' if info['type'] == 'directory' else 'read', session.descriptor(current))
                rows.append({**info, 'archive': archive})
                if info['type'] == 'directory':
                    listing = await session.list(current)
                    if listing['truncated'] or listing['skipped']:
                        raise ValueError('Folder contains skipped or too many entries')
                    for item in listing['entries']:
                        await walk(item['path'], archive + '/' + item['name'], depth + 1)
            await walk(path, name, 0)
        total = sum(row['size'] or 0 for row in rows if row['type'] == 'file')
        # ZIP_STORED plus ZIP64 headers, UTF-8 filenames and data descriptors.
        needed = total + max((total + 49) // 50, sum(256 + 2 * len(row['archive'].encode()) for row in rows) + 1024)
        return rows, total, needed

    async def create(self, owner, session, paths, store, limit, check):
        if store not in self.stores:
            raise ValueError('Choose a configured staging store')
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0 or 0 < limit < 1048576:
            raise ValueError('Part size must be zero or at least 1 MB')
        if sum(job['owner'] == owner and not job['purged'] for job in self.jobs.values()) >= 32:
            raise ValueError('Purge existing jobs before adding more (limit 32)')
        session.active += 1
        try:
            rows, total, needed = await self.plan(session, paths, check)
            if limit and (needed + limit - 1) // limit > 999:
                raise ValueError('Choose a larger part size (maximum 999 parts)')
            if needed > next(row['free'] for row in self.capacity() if row['id'] == store):
                raise ValueError('Not enough free staging space')
            id = secrets.token_hex(16)
            name = (PurePosixPath(paths[0]).name if len(paths) == 1 else 'selection') or 'download'
            job = dict(id=id, owner=owner, kind='zip', name=name + '.zip', total=total, packed=0,
                       staged=0, stage='packing', status='running', parts=[], store=store, store_id=store,
                       limit=limit, purged=False, created=time.time(), open=True,
                       sources=[session.descriptor(row['path']) for row in rows if row['type'] == 'file'])
            self.directory(job).mkdir(mode=0o700)
            self.jobs[id] = job
            self.reserved[id] = needed
            self.save(job)
            self.gates[id] = asyncio.Event()
            self.gates[id].set()
            self.tasks[id] = asyncio.create_task(self.pack(job, session, rows, needed, check))
            return self.public(job)
        finally:
            session.active -= 1

    async def pack(self, job, session, rows, needed, check):
        session.active += 1
        writer = SplitWriter(self.directory(job), job['name'], job['limit'], needed)
        started = time.monotonic()
        try:
            with zipfile.ZipFile(writer, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for row in rows:
                    await self.gates[job['id']].wait()
                    await check('list' if row['type'] == 'directory' else 'read', session.descriptor(row['path']))
                    if row['type'] == 'directory':
                        archive.writestr(row['archive'] + '/', b'')
                        continue
                    info = zipfile.ZipInfo(row['archive'])
                    info.external_attr = 0o100600 << 16
                    with archive.open(info, 'w', force_zip64=True) as target:
                        count = 0
                        async for chunk in session.stream(row['path']):
                            await self.gates[job['id']].wait()
                            count += len(chunk)
                            if count > row['size']:
                                raise ValueError('Source file changed while packing; pack again')
                            pending = asyncio.create_task(asyncio.to_thread(target.write, chunk))
                            try:
                                await asyncio.shield(pending)
                            except asyncio.CancelledError:
                                await pending
                                raise
                            job['parts'] = writer.parts
                            job['packed'] += len(chunk)
                            job['speed'] = job['packed'] / max(0.001, time.monotonic() - started)
                            job['staged'] = writer.position
                            self.reserved[job['id']] = max(0, needed - writer.position)
                        if count != row['size']:
                            raise ValueError('Source file changed while packing; pack again')
            for part in writer.parts:
                part['ready'] = True
            job.update(stage='ready', status='ready')
        except asyncio.CancelledError:
            job.update(stage='failed', status='failed', error='Packing cancelled; purge and pack again')
            raise
        except Exception as error:
            job.update(stage='failed', status='failed', error=str(error))
        finally:
            writer.close()
            job.update(parts=writer.parts, staged=writer.position)
            self.reserved.pop(job['id'], None)
            self.save(job)
            session.active -= 1
            session.last_activity = time.monotonic()

    def control(self, owner, id, action):
        job = self.get(owner, id)
        if job['stage'] != 'packing' or action not in ('pause', 'resume'):
            raise ValueError('Only packing jobs can be paused or resumed')
        self.gates[id].clear() if action == 'pause' else self.gates[id].set()
        job['status'] = 'paused' if action == 'pause' else 'running'
        self.save(job)
        return self.public(job)

    def forget(self, owner, id):
        job = self.get(owner, id)
        if not job['purged']:
            raise ValueError('Purge the staged parts before removing this job')
        (self.directory(job) / 'job.json').unlink(missing_ok=True)
        self.directory(job).rmdir()
        self.jobs.pop(id)
        self.tasks.pop(id, None)
        self.gates.pop(id, None)
        return {'removed': True}

    async def purge(self, owner, id):
        job = self.get(owner, id)
        task = self.tasks.get(id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        freed = job['staged']
        for path in self.directory(job).iterdir():
            if path.name != 'job.json':
                path.unlink()
        job.update(staged=0, stage='purged', status='done', purged=True)
        self.save(job)
        return {'freed': freed}

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

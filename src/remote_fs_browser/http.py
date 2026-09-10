"""Small authenticated reference service. Replace authentication/authorization when embedding."""
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hmac
import inspect
import json
import secrets
import socket
from pathlib import Path
import time
from typing import Callable
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from . import Browser, Policy
from .policy import normalize
from .sessions import clean_descriptor


def byte_range(header, size):
    if not header:
        return 0, size, 200
    if not header.startswith('bytes=') or ',' in header:
        raise ValueError('Only one bytes range is supported')
    first, separator, last = header[6:].partition('-')
    if not separator or (not first and not last) or (first and not first.isdecimal()) or (last and not last.isdecimal()):
        raise ValueError('Invalid range')
    if not size:
        raise ValueError('Empty file')
    if not first:
        length = int(last)
        if length <= 0:
            raise ValueError('Invalid suffix')
        start, end = max(0, size - length), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError('Unsatisfiable range')
    return start, end - start + 1, 206


class BodyLimit:
    def __init__(self, app, limit=16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        # Buffer only the small control request, never file response contents.
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.limit:
                response = JSONResponse({'detail': 'Request too large'}, status_code=413)
                return await response(scope, receive, send)
            if not message.get('more_body'):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)


def create_app(policy: Policy, token=None, authenticate: Callable | None = None,
               authorize: Callable | None = None, credential_resolver=None, root_kinds=None, saved_locations=None):
    if not authenticate and (not token or len(token) < 32):
        raise ValueError('Configure an authentication hook or a token of at least 32 characters')
    if saved_locations is not None and credential_resolver is None:
        credential_resolver = saved_locations.resolve
    browser = Browser(policy, root_kinds=root_kinds)
    owners, rates = {}, defaultdict(deque)
    logins = {}

    @asynccontextmanager
    async def lifespan(app):
        async def reap():
            while True:
                await asyncio.sleep(min(1, policy.idle_seconds))
                await browser.expire()
                for key in list(owners):
                    if key not in browser.sessions:
                        owners.pop(key, None)
        task = asyncio.create_task(reap())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await browser.close()
    app = FastAPI(title='Remote filesystem browser', version='0.1.0', lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.browser = browser
    app.state.root_kinds = browser.root_kinds

    @app.middleware('http')
    async def access(request, call_next):
        if request.url.path in ('/', '/browser.js', '/demo.js'):
            return await call_next(request)
        principal = None
        cookie = request.cookies.get('remote_fs_session')
        grant = logins.get(cookie)
        if grant and grant[1] > time.monotonic():
            if request.method not in ('GET', 'HEAD') and request.headers.get('origin') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': 'Same-origin request required'}, status_code=403)
            principal = grant[0]
        if not principal and authenticate:
            principal = authenticate(request)
            if inspect.isawaitable(principal):
                principal = await principal
        elif not principal and token and hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer ' + token).encode()):
            principal = 'token-user'
        if not principal or not isinstance(principal, str):
            return JSONResponse({'detail': 'Authentication required'}, status_code=401)
        now = time.monotonic()
        if len(rates) > 4096:
            for name in list(rates):
                if not rates[name] or rates[name][-1] < now - 60:
                    rates.pop(name, None)
            if principal not in rates and len(rates) > 4096:
                return JSONResponse({'detail': 'Rate limit capacity reached'}, status_code=429)
        queue = rates[principal]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= policy.requests_per_minute:
            return JSONResponse({'detail': 'Request limit reached'}, status_code=429, headers={'Retry-After': '60'})
        queue.append(now)
        request.state.principal = principal
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/api/login')
    async def login_status(request: Request):
        return {'hostname': socket.gethostname()}

    @app.post('/api/login')
    async def login(request: Request):
        # Exchange the service token for a short-lived HttpOnly browser cookie.
        now = time.monotonic()
        for key in list(logins):
            if logins[key][1] <= now:
                logins.pop(key, None)
        if len(logins) >= 1024:
            raise HTTPException(429, 'Too many browser logins')
        key = secrets.token_urlsafe(32)
        logins[key] = (request.state.principal, now + 28800)
        response = JSONResponse({'hostname': socket.gethostname()})
        response.set_cookie('remote_fs_session', key, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=28800, path='/api')
        return response

    @app.delete('/api/login')
    async def logout(request: Request):
        logins.pop(request.cookies.get('remote_fs_session'), None)
        response = JSONResponse({'closed': True})
        response.delete_cookie('remote_fs_session', path='/api')
        return response

    @app.get('/')
    async def demo():
        return FileResponse(Path(__file__).with_name('web') / 'index.html')

    @app.get('/browser.js')
    async def component():
        return FileResponse(Path(__file__).with_name('web') / 'browser.js', media_type='text/javascript')

    @app.get('/demo.js')
    async def demo_script():
        return FileResponse(Path(__file__).with_name('web') / 'demo.js', media_type='text/javascript')

    async def allowed(request, operation, session=None):
        policy.require(operation)
        if authorize:
            ok = authorize(request.state.principal, operation, session)
            if inspect.isawaitable(ok):
                ok = await ok
            if not ok:
                raise PermissionError('Operation is not permitted')

    def get(request, id):
        if owners.get(id) != request.state.principal:
            raise HTTPException(404, 'Session not found')
        session = browser.sessions.get(id)
        if not session or session.closed:
            raise KeyError('Session expired')
        return session

    @app.exception_handler(Exception)
    async def failure(request, error):
        status = 403 if isinstance(error, PermissionError) else 410 if isinstance(error, KeyError) else 504 if isinstance(error, TimeoutError) else 422
        return JSONResponse({'detail': 'Session expired; reconnect' if status == 410 else 'Request failed; check permissions, path, connection and dependencies'}, status_code=status)

    @app.get('/api/saved')
    @app.get('/saved', include_in_schema=False)
    async def saved_list(request: Request):
        await allowed(request, 'discover')
        if saved_locations is None:
            return {'locations': [], 'available': False}
        return {'locations': saved_locations.list(request.state.principal), 'available': True}

    @app.post('/api/saved')
    @app.post('/saved', include_in_schema=False)
    async def saved_add(request: Request):
        await allowed(request, 'discover')
        if saved_locations is None:
            raise HTTPException(404, 'This service does not remember locations')
        data = await request.json()
        descriptor = clean_descriptor(data['descriptor'])
        descriptor['path'] = normalize(data['descriptor'].get('path', '/'))
        reference = saved_locations.add(request.state.principal, descriptor, data.get('credentials'), data.get('label'))
        return {'id': reference}

    @app.delete('/api/saved/{reference}')
    @app.delete('/saved/{reference}', include_in_schema=False)
    async def saved_remove(request: Request, reference: str):
        await allowed(request, 'discover')
        if saved_locations is None or not saved_locations.remove(request.state.principal, reference):
            raise HTTPException(404, 'Saved location not found')
        return {'removed': True}

    @app.get('/api/discover')
    @app.get('/discover', include_in_schema=False)
    async def discover(request: Request, scan: bool = False):
        await allowed(request, 'discover')
        return await browser.discover(scan=scan)

    @app.post('/api/discover')
    @app.post('/discover', include_in_schema=False)
    async def discover_server(request: Request):
        await allowed(request, 'discover')
        data = await request.json()
        if 'ranges' in data:
            return await browser.discover(scan=True, ranges=data['ranges'], offset=data.get('offset', 0))
        return await browser.discover(host=data['host'], protocol=data['type'], credentials=data.get('credentials'))

    @app.post('/api/sessions')
    @app.post('/sessions', include_in_schema=False)
    async def connect(request: Request):
        # A connection alone grants no read permission; operations are checked separately.
        if authorize:
            check = authorize(request.state.principal, 'connect', None)
            if inspect.isawaitable(check):
                check = await check
            if not check:
                raise PermissionError()
        data = await request.json()
        descriptor = dict(data['descriptor'])
        reference = descriptor.pop('credential_id', None)
        credentials = data.get('credentials')
        if reference:
            if not credential_resolver:
                raise PermissionError('No credential resolver configured')
            credentials = credential_resolver(request.state.principal, reference)
            if inspect.isawaitable(credentials):
                credentials = await credentials
        session = await browser.connect(descriptor, credentials)
        if reference:
            session._descriptor['credential_id'] = reference
        owners[session.id] = request.state.principal
        return {'id': session.id, 'descriptor': session.descriptor(), 'idle_seconds': policy.idle_seconds}

    @app.post('/api/sessions/{id}/mkdir')
    async def mkdir(request: Request, id: str):
        data = await request.json()
        path = data.get('path', '')
        session = get(request, id)
        await allowed(request, 'mkdir', session.descriptor(path))
        return await session.mkdir(path)

    @app.get('/api/sessions/{id}/list')
    @app.get('/sessions/{id}/list', include_in_schema=False)
    async def listing(request: Request, id: str, path: str = '/', ndjson: bool = False):
        session = get(request, id)
        await allowed(request, 'list', session.descriptor(path))
        data = await session.list(path)
        if not ndjson:
            return data
        async def lines():
            for item in data['entries']:
                yield json.dumps(item) + '\n'
        return StreamingResponse(lines(), media_type='application/x-ndjson',
                                 headers={'X-Listing-Truncated': str(data['truncated']).lower(), 'X-Listing-Skipped': str(data['skipped'])})

    @app.get('/api/sessions/{id}/stat')
    @app.get('/sessions/{id}/stat', include_in_schema=False)
    async def info(request: Request, id: str, path: str):
        session = get(request, id)
        await allowed(request, 'stat', session.descriptor(path))
        return await session.stat(path)

    @app.get('/api/sessions/{id}/file')
    @app.get('/sessions/{id}/file', include_in_schema=False)
    async def file(request: Request, id: str, path: str):
        session = get(request, id)
        await allowed(request, 'read', session.descriptor(path))
        info = await session.stat(path)
        if info['type'] != 'file':
            raise HTTPException(422, 'Choose a regular file')
        size = info['size']
        try:
            offset, length, status = byte_range(request.headers.get('range'), size)
        except ValueError:
            return JSONResponse({'detail': 'Invalid byte range'}, status_code=416, headers={'Content-Range': f'bytes */{size}'})
        stream = session.stream(path, offset, length)
        first = await anext(stream, b'')
        async def chunks():
            try:
                if first:
                    yield first
                async for chunk in stream:
                    yield chunk
            finally:
                await stream.aclose()
        from urllib.parse import quote
        headers = {'Accept-Ranges': 'bytes', 'Content-Length': str(length), 'Content-Disposition': "attachment; filename*=UTF-8''" + quote(path.rsplit('/', 1)[-1], safe='')}
        if status == 206:
            headers['Content-Range'] = f'bytes {offset}-{offset + length - 1}/{size}'
        return StreamingResponse(chunks(), status_code=status, media_type='application/octet-stream', headers=headers)

    @app.get('/api/sessions/{id}/descriptor')
    @app.get('/sessions/{id}/descriptor', include_in_schema=False)
    async def descriptor(request: Request, id: str, path: str = '/'):
        session = get(request, id)
        await allowed(request, 'stat', session.descriptor(path))
        info = await session.stat(path)
        if info['type'] != 'directory':
            raise HTTPException(422, 'Choose a directory')
        return session.descriptor(path)

    @app.delete('/api/sessions/{id}')
    @app.delete('/sessions/{id}', include_in_schema=False)
    async def close(request: Request, id: str):
        session = get(request, id)
        await session.close()
        browser.sessions.pop(id, None)
        owners.pop(id, None)
        return {'closed': True}
    return app


def main():
    from .cli import main as serve
    serve()


if __name__ == '__main__':
    main()

"""Serve an NFS export to rclone over loopback WebDAV, so NFS shares mount like SMB and cloud storage.

rclone has no NFS client. remotefs already reads and writes NFS through libnfs, so each NFS mount
gets a small WebDAV server in its own process, bound to 127.0.0.1 and protected by a random
password, and rclone mounts it as a `webdav` remote with its usual VFS cache and upload handling.
The server implements what rclone's WebDAV backend uses: PROPFIND, GET/HEAD with ranges, PUT,
DELETE, MKCOL and MOVE. It works over any remotefs filesystem object, which keeps it testable.
"""
import base64
import email.utils
import errno
import hmac
import multiprocessing
import secrets
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

from .policy import normalize

CHUNK = 1 << 20
USER = 'remotefs'


def hidden(name):
    """Staged uploads in progress, which should not show up in the mount."""
    return name.startswith('.remotefs-') and name.endswith('.part')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'remotefs-bridge'

    def log_message(self, *args):
        pass

    # ------------------------------------------------------------------ plumbing
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionError, TimeoutError):
            self.close_connection = True

    def send(self, code, body=b'', content_type='text/plain', headers=()):
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        if body or code not in (204, 304):
            self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body and self.command != 'HEAD':
            self.wfile.write(body)

    def authorized(self):
        header = self.headers.get('Authorization', '')
        expected = 'Basic ' + base64.b64encode(f'{USER}:{self.server.password}'.encode()).decode()
        return hmac.compare_digest(header.encode(), expected.encode())

    def path_of(self, url):
        """Filesystem path for a request URL; the bridge only exposes its root folder."""
        relative = normalize(unquote(urlsplit(url).path))
        root = self.server.root
        return root if relative == '/' else normalize(root.rstrip('/') + relative)

    def href(self, path, directory):
        root = self.server.root.rstrip('/')
        relative = path[len(root):] if root and path.startswith(root) else path
        relative = relative or '/'
        if directory and not relative.endswith('/'):
            relative += '/'
        return quote(relative)

    def discard_body(self):
        for _ in self.body_chunks():
            pass

    def body_chunks(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            while True:
                size = int(self.rfile.readline().split(b';')[0].strip() or b'0', 16)
                if not size:
                    while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                        pass
                    return
                remaining = size
                while remaining:
                    data = self.rfile.read(min(remaining, CHUNK))
                    if not data:
                        raise ConnectionError('Upload ended early')
                    remaining -= len(data)
                    yield data
                self.rfile.readline()
        remaining = int(self.headers.get('Content-Length') or 0)
        while remaining:
            data = self.rfile.read(min(remaining, CHUNK))
            if not data:
                raise ConnectionError('Upload ended early')
            remaining -= len(data)
            yield data

    def fs(self, method, *args):
        with self.server.lock:
            return getattr(self.server.fs, method)(*args)

    def stat(self, path):
        try:
            return self.fs('stat', path)
        except FileNotFoundError:
            return None

    def dispatch(self):
        if not self.authorized():
            self.discard_body()
            return self.send(401, headers=[('WWW-Authenticate', 'Basic realm="remotefs"')])
        try:
            path = self.path_of(self.path)
            getattr(self, 'do_' + self.command.lower() + '_')(path)
            return
        except (ConnectionError, TimeoutError):
            self.close_connection = True
            return
        except FileNotFoundError:
            code = 404
        except FileExistsError:
            code = 412
        except (PermissionError, ValueError):
            code = 403
        except OSError as error:
            code = 409 if error.errno in (errno.ENOTEMPTY, errno.EEXIST, errno.ENOTDIR, errno.EISDIR) else 502
        # A failed request may leave part of its body unread, so do not reuse the connection.
        self.close_connection = True
        self.send(code)

    do_OPTIONS = do_PROPFIND = do_GET = do_HEAD = do_PUT = do_DELETE = do_MKCOL = do_MOVE = dispatch

    # ------------------------------------------------------------------ methods
    def do_options_(self, path):
        self.send(200, headers=[('DAV', '1'), ('Allow', 'OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE, MKCOL, MOVE')])

    def response(self, row):
        directory = row['type'] == 'directory'
        props = [f"<d:displayname>{escape(row['name'] or '')}</d:displayname>",
                 '<d:resourcetype><d:collection/></d:resourcetype>' if directory else '<d:resourcetype/>']
        if not directory:
            props.append(f"<d:getcontentlength>{row['size'] or 0}</d:getcontentlength>")
            props.append('<d:getcontenttype>application/octet-stream</d:getcontenttype>')
        if row['modified']:
            stamp = datetime.fromisoformat(row['modified']).timestamp()
            props.append(f'<d:getlastmodified>{email.utils.formatdate(stamp, usegmt=True)}</d:getlastmodified>')
        return (f"<d:response><d:href>{escape(self.href(row['path'], directory))}</d:href><d:propstat><d:prop>"
                + ''.join(props) + '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')

    def do_propfind_(self, path):
        self.discard_body()
        row = self.stat(path)
        if row is None:
            return self.send(404)
        rows = [row]
        if row['type'] == 'directory' and self.headers.get('Depth', '1') != '0':
            listing = self.fs('list', path, self.server.max_entries)
            rows += [child for child in listing['entries'] if child['type'] in ('file', 'directory') and not hidden(child['name'])]
        body = ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">'
                + ''.join(self.response(r) for r in rows) + '</d:multistatus>').encode()
        self.send(207, body, 'application/xml; charset=utf-8')

    def do_get_(self, path):
        row = self.stat(path)
        if row is None:
            return self.send(404)
        if row['type'] != 'file':
            return self.send(405)
        size, start, end = row['size'] or 0, 0, None
        wanted = self.headers.get('Range', '')
        if wanted.startswith('bytes=') and ',' not in wanted:
            first, _, last = wanted[6:].partition('-')
            if first:
                start, end = int(first), int(last) if last else size - 1
            elif last:
                start, end = max(0, size - int(last)), size - 1
            if start >= size and size:
                return self.send(416, headers=[('Content-Range', f'bytes */{size}')])
            end = min(end, size - 1)
        length = (end - start + 1) if end is not None else size
        handle = self.fs('open', path) if self.command == 'GET' and length > 0 else None
        self.send_response(206 if end is not None else 200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(max(length, 0)))
        self.send_header('Accept-Ranges', 'bytes')
        if end is not None:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if handle is None:
            return
        try:
            handle.seek(start)
            while length > 0:
                with self.server.lock:
                    data = handle.read(min(length, CHUNK))
                if not data:
                    raise OSError('The file shrank while it was being read')
                self.wfile.write(data)
                length -= len(data)
        except OSError:
            # The headers are already sent, so a short response is the only way to report it.
            self.close_connection = True
        finally:
            with self.server.lock:
                handle.close()

    do_head_ = do_get_

    def do_put_(self, path):
        existing = self.stat(path)
        if existing is not None and existing['type'] != 'file':
            self.discard_body()
            return self.send(405)
        with self.server.lock:
            write = self.server.fs.begin_write(path, overwrite=True)
        try:
            for data in self.body_chunks():
                with self.server.lock:
                    write.write(data)
            with self.server.lock:
                write.commit()
        except BaseException:
            with self.server.lock:
                write.abort()
            raise
        self.send(204 if existing else 201)

    def do_delete_(self, path):
        self.discard_body()
        if path == self.server.root:
            return self.send(403)
        self.fs('remove', path)
        self.send(204)

    def do_mkcol_(self, path):
        self.discard_body()
        if self.stat(path) is not None:
            return self.send(405)
        self.fs('mkdir', path)
        self.send(201)

    def do_move_(self, path):
        self.discard_body()
        if path == self.server.root:
            return self.send(403)
        destination = self.path_of(self.headers.get('Destination', ''))
        overwrite = self.headers.get('Overwrite', 'T').upper() != 'F'
        source = self.stat(path)
        if source is None:
            return self.send(404)
        target = self.stat(destination)
        if target is not None and not overwrite:
            return self.send(412)
        if target is not None and (source['type'] == 'directory' or target['type'] != 'file'):
            return self.send(412)
        self.fs('move', path, destination, target is not None)
        self.send(204 if target else 201)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, fs, root, password, max_entries=1_000_000):
        super().__init__(('127.0.0.1', 0), Handler)
        self.fs, self.root, self.password = fs, normalize(root or '/'), password
        self.max_entries = max_entries
        self.lock = threading.Lock()  # one libnfs context, so one operation at a time

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_address[1]}/'


def worker(pipe, config, root, password):
    """Child process: serve one NFS export until the service closes the pipe or exits."""
    try:
        from .nfs import NFSFilesystem
        fs = NFSFilesystem(config)
        server = Server(fs, root, password)
    except Exception as error:  # reported to the service, which shows a safe message
        pipe.send({'error': str(error) or type(error).__name__})
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    pipe.send({'url': server.url})
    try:
        pipe.recv()
    except (EOFError, OSError):
        pass
    server.shutdown()
    fs.close()


class Bridge:
    """A bridge process owned by one mount."""

    def __init__(self, descriptor, timeout=30):
        config = {k: descriptor[k] for k in ('host', 'export', 'version') if k in descriptor}
        self.password = secrets.token_urlsafe(24)
        context = multiprocessing.get_context('spawn')
        self.pipe, child = context.Pipe()
        self.process = context.Process(target=worker, args=(child, config, descriptor.get('path', '/'), self.password),
                                       daemon=True)
        self.process.start()
        child.close()
        if not self.pipe.poll(timeout):
            self.stop()
            raise TimeoutError('The NFS server did not answer')
        try:
            reply = self.pipe.recv()
        except EOFError:
            reply = {'error': 'The NFS bridge stopped unexpectedly'}
        if 'error' in reply:
            self.stop()
            raise OSError(reply['error'])
        self.url = reply['url']

    def stop(self):
        try:
            self.pipe.send('stop')
        except (OSError, ValueError):
            pass
        self.pipe.close()
        self.process.join(10)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(5)

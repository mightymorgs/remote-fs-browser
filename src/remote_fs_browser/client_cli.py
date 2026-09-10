"""Terminal client for the same authenticated API used by the browser UI."""
import argparse
import getpass
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request

COMMANDS = ('login', 'logout', 'discover', 'scan', 'shares', 'connect', 'disconnect',
            'ls', 'stat', 'select', 'mkdir', 'rename', 'copy', 'remove', 'get', 'put',
            'saved', 'credentials', 'downloads')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a login, cookie, upload or credentials to another origin.
        return None


class Client:
    def __init__(self, url, auth_file, timeout):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('--url must be an HTTP(S) origin, without credentials or a path')
        self.url = url.rstrip('/')
        self.auth_file, self.timeout = Path(auth_file), timeout
        self.cookie = None
        if self.auth_file.exists():
            self.cookie = json.loads(self.auth_file.read_text()).get(self.url)
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(NoRedirect(), HTTPCookieProcessor(self.jar))

    def request(self, method, route, data=None, params=None, source=None, output=None):
        headers = {'Origin': self.url}
        if self.cookie:
            headers['Cookie'] = 'remote_fs_session=' + self.cookie
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        if source is not None:
            body = source
            headers['Content-Type'] = 'application/octet-stream'
            headers['Content-Length'] = str(os.fstat(source.fileno()).st_size)
        url = self.url + '/api/' + route
        if params:
            url += '?' + urlencode(params)
        try:
            with self.opener.open(Request(url, data=body, headers=headers, method=method), timeout=self.timeout) as response:
                if output is not None:
                    received = 0
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        received += len(chunk)
                    length = response.headers.get('Content-Length')
                    if length is not None and received != int(length):
                        raise ValueError('Incomplete download; destination was not replaced')
                    return None
                return json.load(response)
        except HTTPError as error:
            # Server response details are sanitized by the API; never echo request bodies.
            try:
                detail = json.load(error).get('detail', error.reason)
            except (ValueError, AttributeError):
                detail = error.reason
            raise ValueError(f'HTTP {error.code}: {detail}') from None
        except URLError as error:
            raise ValueError(f'Cannot reach server: {error.reason}') from None

    def remember(self, cookie):
        from .store import write_private
        state = json.loads(self.auth_file.read_text()) if self.auth_file.exists() else {}
        if cookie:
            state[self.url] = cookie
        else:
            state.pop(self.url, None)
        write_private(self.auth_file, json.dumps(state) + '\n')
        self.cookie = cookie


def password(stdin, prompt):
    if stdin:
        return sys.stdin.readline().rstrip('\r\n')
    if not sys.stdin.isatty():
        raise ValueError('Use --password-stdin for non-interactive credentials')
    return getpass.getpass(prompt)


def credential_flags(parser):
    parser.add_argument('--username', help='SMB username; password is prompted, never a command-line argument')
    parser.add_argument('--domain', default='')
    parser.add_argument('--password-stdin', action='store_true')
    parser.add_argument('--credential-id', help='Use a credential reference already saved on the server')


def credentials(args):
    if args.credential_id and (args.username or args.password_stdin):
        raise ValueError('Choose --credential-id or a username/password')
    if args.password_stdin and not args.username:
        raise ValueError('--password-stdin requires --username')
    if args.username:
        return {'username': args.username, 'domain': args.domain,
                'password': password(args.password_stdin, 'SMB password: ')}
    return None


def location_flags(parser):
    parser.add_argument('--type', choices=('local', 'smb', 'nfs'))
    parser.add_argument('--root', help='Local root on the server, not this client')
    parser.add_argument('--host')
    parser.add_argument('--share')
    parser.add_argument('--export')
    parser.add_argument('--nfs-version', type=int, choices=(3, 4), default=4)
    parser.add_argument('--path', default='/')
    parser.add_argument('--saved-id', help='Reuse a saved location and its credentials')
    credential_flags(parser)


def location(args, client):
    if args.saved_id:
        if any((args.type, args.root, args.host, args.share, args.export, args.username, args.credential_id)):
            raise ValueError('--saved-id cannot be combined with a new location or credentials')
        rows = client.request('GET', 'saved')['locations']
        row = next((row for row in rows if row['id'] == args.saved_id), None)
        if not row:
            raise ValueError('Saved location not found')
        result = dict(row['descriptor'], credential_id=row['id'])
        if args.path != '/':
            result['path'] = args.path
        return result
    from .sessions import clean_descriptor
    result = {'type': args.type, 'path': args.path}
    for key in ('root', 'host', 'share', 'export'):
        if getattr(args, key):
            result[key] = getattr(args, key)
    if args.type == 'local' and not args.root:
        raise ValueError('--type local requires --root')
    if args.type == 'nfs':
        result['version'] = args.nfs_version
    result = dict(clean_descriptor(result), path=args.path)
    if args.credential_id:
        result['credential_id'] = args.credential_id
    return result


def parser():
    from .cli import config_home
    p = argparse.ArgumentParser(prog='remotefs', description='Use the web file manager API from the terminal. Results are JSON; file transfers are streamed.')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--url', default=os.environ.get('REMOTEFS_URL', 'http://127.0.0.1:8080'), help='Server origin (or REMOTEFS_URL)')
    common.add_argument('--auth-file', default=str(config_home() / 'client.json'), help='Private login-cookie file; passwords are not stored here')
    common.add_argument('--timeout', type=float, default=120, help='HTTP timeout in seconds')
    sub = p.add_subparsers(dest='command', required=True)
    def command(name, help):
        return sub.add_parser(name, help=help, parents=[common])
    login = command('login', 'Sign in to an existing server')
    login.add_argument('--username', required=True)
    login.add_argument('--password-stdin', action='store_true')
    command('logout', 'Sign out and close this account’s active browsing sessions')
    command('discover', 'Show roots, mounted volumes and detected networks')
    scan = command('scan', 'Scan default networks or custom IP addresses/CIDRs')
    scan.add_argument('--ranges', action='append', help='Repeat or separate with commas: 192.168.1.0/24,10.10.0.0/24,10.20.0.5')
    scan.add_argument('--offset', type=int, default=0)
    scan.add_argument('--all', action='store_true', help='Emit every scan page as a separate JSON line')
    shares = command('shares', 'Enumerate SMB shares or NFS exports')
    shares.add_argument('host')
    shares.add_argument('--type', choices=('smb', 'nfs'), default='smb')
    credential_flags(shares)
    location_flags(command('connect', 'Open a local, SMB or NFS browsing session; returns its ID'))
    close = command('disconnect', 'Close a browsing session immediately')
    close.add_argument('session')
    for name in ('ls', 'stat', 'select', 'mkdir', 'remove', 'get', 'put', 'rename', 'copy'):
        cmd = command(name, {'select': 'Return a directory descriptor', 'get': 'Download a file', 'put': 'Upload a file'}.get(name, name.capitalize() + ' within a browsing session'))
        cmd.add_argument('session')
        cmd.add_argument('path', nargs='?' if name in ('ls', 'select') else None, default='/')
        if name in ('rename', 'copy'):
            cmd.add_argument('destination')
        if name == 'copy':
            cmd.add_argument('--target-session')
        if name == 'remove':
            cmd.add_argument('--recursive', action='store_true')
        if name in ('get', 'put'):
            cmd.add_argument('file', help='Client-side filename; get accepts - for stdout')
            cmd.add_argument('--overwrite', action='store_true')
    saved = command('saved', 'List, add or remove remembered locations')
    saved.add_argument('action', choices=('list', 'add', 'remove'))
    saved.add_argument('--id')
    saved.add_argument('--label')
    location_flags(saved)
    creds = command('credentials', 'List, save or forget server-side SMB credentials')
    creds.add_argument('action', choices=('list', 'add', 'remove'))
    creds.add_argument('--id')
    creds.add_argument('--host')
    credential_flags(creds)
    jobs = command('downloads', 'Manage staged ZIP jobs, including pause, resume and parts')
    jobs.add_argument('action', choices=('list', 'estimate', 'create', 'pause', 'resume', 'purge', 'forget', 'part'))
    jobs.add_argument('--id')
    jobs.add_argument('--session')
    jobs.add_argument('--paths', nargs='+')
    jobs.add_argument('--store')
    jobs.add_argument('--part-size', type=int, default=0, help='Bytes per archive part; 0 uses the server default')
    jobs.add_argument('--index', type=int)
    jobs.add_argument('--file')
    jobs.add_argument('--overwrite', action='store_true')
    return p


def required(args, *names):
    for name in names:
        if getattr(args, name) is None:
            raise ValueError('--' + name.replace('_', '-') + ' is required')


def download(client, route, filename, overwrite, params=None):
    if filename == '-':
        return client.request('GET', route, params=params, output=sys.stdout.buffer)
    destination = Path(filename)
    if destination.exists() and not overwrite:
        raise FileExistsError(f'File exists: {destination}')
    fd, temporary = tempfile.mkstemp(dir=destination.absolute().parent, prefix='.remotefs-')
    try:
        with os.fdopen(fd, 'wb') as output:
            client.request('GET', route, params=params, output=output)
        if overwrite:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def execute(args, client):
    cmd = args.command
    if cmd == 'login':
        client.cookie = None
        result = client.request('POST', 'login', {'username': args.username, 'password': password(args.password_stdin, 'Server password: ')})
        cookie = next((c.value for c in client.jar if c.name == 'remote_fs_session'), None)
        if not cookie:
            raise ValueError('Server did not return a login cookie')
        client.remember(cookie)
        return result
    if cmd == 'logout':
        result = client.request('DELETE', 'login')
        client.remember(None)
        return result
    if cmd == 'discover':
        return client.request('GET', 'discover')
    if cmd == 'scan':
        ranges = [item.strip() for group in args.ranges or [] for item in group.split(',') if item.strip()]
        if not ranges:
            info = client.request('GET', 'discover')
            ranges = info.get('scan_ranges', info.get('networks', []))
            if not ranges:
                raise ValueError('No default scan ranges returned; specify --ranges')
        import ipaddress
        ranges = [str(ipaddress.ip_network(item, strict=False)) for item in ranges]
        offset = args.offset
        while True:
            result = client.request('POST', 'discover', {'ranges': ranges, 'offset': offset})
            if not args.all:
                return result
            print(json.dumps(result), flush=True)
            next_offset = result.get('next_offset')
            if next_offset is None:
                return None
            if next_offset <= offset:
                raise ValueError('Server returned a non-advancing scan cursor')
            offset = next_offset
    if cmd == 'shares':
        return client.request('POST', 'discover', {'host': args.host, 'type': args.type, 'credentials': credentials(args), 'credential_id': args.credential_id})
    if cmd == 'connect':
        return client.request('POST', 'sessions', {'descriptor': location(args, client), 'credentials': credentials(args)})
    if cmd in ('saved', 'credentials'):
        if args.action == 'list':
            return client.request('GET', cmd)
        if args.action == 'remove':
            required(args, 'id')
            return client.request('DELETE', cmd + '/' + quote(args.id, safe=''))
        if cmd == 'saved':
            return client.request('POST', cmd, {'descriptor': location(args, client), 'credentials': credentials(args), 'label': args.label})
        required(args, 'host', 'username')
        return client.request('POST', cmd, {'host': args.host, 'credentials': credentials(args)})
    if cmd == 'downloads':
        if args.action == 'list':
            return client.request('GET', cmd)
        if args.action in ('estimate', 'create'):
            required(args, 'session', 'paths')
            if args.action == 'create':
                required(args, 'store')
            return client.request('POST', cmd + ('/estimate' if args.action == 'estimate' else ''), {'session': args.session, 'paths': args.paths, 'store': args.store, 'part_size': args.part_size})
        required(args, 'id')
        route = cmd + '/' + quote(args.id, safe='')
        if args.action == 'part':
            required(args, 'index', 'file')
            return download(client, route + '/parts/' + str(args.index), args.file, args.overwrite)
        return client.request('DELETE' if args.action == 'purge' else 'POST', route, None if args.action == 'purge' else {'action': args.action})
    route = 'sessions/' + quote(args.session, safe='')
    if cmd == 'disconnect':
        return client.request('DELETE', route)
    params = {'path': args.path}
    if cmd in ('ls', 'stat', 'select'):
        return client.request('GET', route + '/' + {'ls': 'list', 'stat': 'stat', 'select': 'descriptor'}[cmd], params=params)
    if cmd == 'mkdir':
        return client.request('POST', route + '/mkdir', params)
    if cmd in ('rename', 'copy'):
        data = {'source': args.path, 'destination': args.destination}
        if cmd == 'copy' and args.target_session:
            data['target_session'] = args.target_session
        return client.request('POST', route + '/' + cmd, data)
    if cmd == 'remove':
        return client.request('DELETE', route + '/entry', params=dict(params, recursive=str(args.recursive).lower()))
    if cmd == 'get':
        return download(client, route + '/file', args.file, args.overwrite, params)
    if cmd == 'put':
        with open(args.file, 'rb') as source:
            return client.request('PUT', route + '/file', params=dict(params, overwrite=str(args.overwrite).lower()), source=source)


def main(argv):
    args = parser().parse_args(argv)
    try:
        if args.timeout <= 0:
            raise ValueError('--timeout must be positive')
        result = execute(args, Client(args.url, args.auth_file, args.timeout))
        if result is not None:
            print(json.dumps(result, indent=2))
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from None

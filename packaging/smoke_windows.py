"""Exercise the frozen Windows executable before uploading release artifacts."""
import http.cookiejar
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import tomllib
import urllib.request

version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
exe = str(Path('dist/remotefs/remotefs.exe').resolve())
assert subprocess.check_output([exe, '--version'], text=True).strip() == f'remotefs {version}'
subprocess.run([exe, 'setup', '--help'], check=True, stdout=subprocess.DEVNULL)
subprocess.run([exe, 'downloads', '--help'], check=True, stdout=subprocess.DEVNULL)
with tempfile.TemporaryDirectory(prefix='remotefs-release-') as folder:
    root = Path(folder)
    config = root/'config.json'
    password = secrets.token_urlsafe(24)
    subprocess.run([exe, 'account', '--config', str(config), '--username', 'release-test', '--password-stdin'],
                   input=password+'\n', text=True, check=True, stdout=subprocess.DEVNULL)
    settings = json.loads(config.read_text())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    settings.update(bind='127.0.0.1', port=port, policy={'local_roots':[str(root)], 'network_ranges':[]})
    config.write_text(json.dumps(settings))
    base = f'http://127.0.0.1:{port}'
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        with client.open(urllib.request.Request(base+path, data=body, headers={'Content-Type':'application/json','Origin':base}), timeout=10) as response:
            return json.loads(response.read())
    with (root/'server.log').open('w') as log:
        server = subprocess.Popen([exe, 'serve', '--config', str(config)], stdout=log, stderr=log)
        try:
            for attempt in range(40):
                if server.poll() is not None:
                    raise RuntimeError('Frozen service exited during startup')
                try:
                    request('/api/login');break
                except OSError:
                    time.sleep(.5)
            else:
                raise RuntimeError('Frozen service did not become ready')
            request('/api/login', {'username':'release-test','password':password})
            session = request('/api/sessions', {'descriptor':{'type':'local','root':str(root)}})['id']
            request(f'/api/sessions/{session}/mkdir', {'path':'/Prepared ZIPs'})
            store = request('/api/downloads/stores', {'session':session,'path':'/Prepared ZIPs'})
            assert request('/api/downloads')['stores'][0]['id'] == store['id']
            assert Path(json.loads(config.read_text())['staging_stores'][store['id']]).is_dir()
            with client.open(base+'/manager') as response:
                assert b'Choose folder' in response.read()
            print('Frozen executable version, CLI, login, filesystem worker, ZIP folder selection and persistence passed.')
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill();server.wait(timeout=5)

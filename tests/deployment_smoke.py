"""Destructive service smoke test: run ONLY on disposable CI machines."""
import http.cookiejar
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[1]
PLATFORM = 'windows' if sys.platform == 'win32' else 'macos' if sys.platform == 'darwin' else 'linux'
PREFIX = Path('C:/ProgramData/remote-fs-browser' if PLATFORM == 'windows' else '/opt/remote-fs-browser')
BASE = 'http://127.0.0.1:18765'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('This test installs and removes system services. Use a disposable GitHub Actions runner.')
    workspace = Path(os.environ['RUNNER_TEMP']) / 'deployment smoke'
    workspace.mkdir(exist_ok=True)
    root = workspace / 'local files'
    root.mkdir(exist_ok=True)
    config = workspace / 'config.json'
    password_file = workspace / 'password'
    password = secrets.token_urlsafe(32)
    password_file.write_text(password)
    password_file.chmod(0o600)
    settings = {'bind': '127.0.0.1', 'port': 18765,
                'policy': {'local_roots': [str(root)], 'network_ranges': ['127.0.0.1/32']},
                'staging_stores': {'Downloads': str(workspace / 'staging 100%')}}
    config.write_text(json.dumps(settings))
    if PLATFORM == 'windows':
        install = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', REPO / 'scripts/windows/install.ps1', '-Config', config,
                   '-Username', 'smoke', '-PasswordFile', password_file, '-SkipDependencies', '-WithoutNfs', '-Python', sys.executable]
        uninstall = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', REPO / 'scripts/windows/uninstall.ps1', '-Purge']
    else:
        install = ['sudo', 'env', 'REMOTE_FS_PYTHON=' + sys.executable, 'bash', REPO / f'scripts/{PLATFORM}/install.sh', config,
                   '--username', 'smoke', '--password-file', password_file, '--skip-dependencies', '--without-nfs']
        uninstall = ['sudo', 'bash', REPO / f'scripts/{PLATFORM}/uninstall.sh', '--purge']
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, data=None, method=None, raw=False):
        body = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(BASE + path, data=body, method=method,
                                     headers={'Origin': BASE, 'Content-Type': 'application/octet-stream' if isinstance(data, bytes) else 'application/json'})
        with client.open(req, timeout=30) as response:
            content = response.read()
            return content if raw else json.loads(content)

    def login():
        request('/api/login', {'username': 'smoke', 'password': password})

    try:
        run(install)
        login()
        session = request('/api/sessions', {'descriptor': {'type': 'local', 'root': str(root)}})['id']
        request(f'/api/sessions/{session}/mkdir', {'path': '/created'})
        payload = secrets.token_bytes(100_000)
        request(f'/api/sessions/{session}/file?path=/created/proof.bin', payload, 'PUT')
        assert request(f'/api/sessions/{session}/file?path=/created/proof.bin', raw=True) == payload
        credential = request('/api/credentials', {'host': '127.0.0.1', 'credentials': {'username': 'fixture', 'password': 'saved-fixture-password'}})['id']
        job = request('/api/downloads', {'session': session, 'paths': ['/created/proof.bin'], 'store': 'Downloads', 'part_size': 0})
        for _ in range(60):
            current = next(j for j in request('/api/downloads')['jobs'] if j['id'] == job['id'])
            if current['stage'] == 'ready':
                break
            assert current['stage'] != 'failed', current.get('error')
            time.sleep(.5)
        else:
            raise AssertionError('Archive did not finish')
        archive = request(f'/api/downloads/{job["id"]}/parts/0', raw=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as packed:
            assert len(packed.namelist()) == 1
            assert packed.read(packed.namelist()[0]) == payload
        print('Service login, folder creation, upload and staged ZIP download passed', flush=True)

        if PLATFORM != 'windows':
            variables = {'remote_fs_source': str(workspace / 'source'), 'remote_fs_settings': settings,
                         'remote_fs_username': 'smoke', 'remote_fs_password': password,
                         'remote_fs_skip_dependencies': True, 'remote_fs_without_nfs': True,
                         'remote_fs_python': sys.executable, 'ansible_python_interpreter': sys.executable}
            var_file = workspace / 'ansible-private.json'
            var_file.write_text(json.dumps(variables))
            var_file.chmod(0o600)
            ansible = [shutil.which('ansible-playbook'), REPO / f'playbooks/{PLATFORM}/install.yml', '-i', 'localhost,', '-c', 'local', '-e', '@' + str(var_file), '-e', '{"ansible_become":true}', '--limit', 'all']
            # Use the playbook's actual inventory group.
            inventory = workspace / 'inventory.ini'
            inventory.write_text('[filesystem_hosts]\nlocalhost ansible_connection=local\n')
            ansible[ansible.index('localhost,')] = str(inventory)
            run(ansible)
            repeat = run(ansible, capture_output=True, text=True)
            print(repeat.stdout)
            assert 'changed=0 ' in repeat.stdout, 'Second Ansible deployment was not idempotent'
            var_file.unlink()
        else:
            # Parse both scripts on the platform where they execute.
            run(['powershell.exe', '-NoProfile', '-Command',
                 "$errors=$null; Get-ChildItem scripts/windows/*.ps1 | ForEach-Object { [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$null,[ref]$errors) | Out-Null; if ($errors) { throw $errors } }"])
            run(install)
        login()
        assert any(c['id'] == credential for c in request('/api/credentials')['credentials'])
        password = secrets.token_urlsafe(32)
        password_file.write_text(password)
        run(install)
        login()
        assert any(c['id'] == credential for c in request('/api/credentials')['credentials'])
        session = request('/api/sessions', {'descriptor': {'type': 'local', 'root': str(root)}})['id']
        assert request(f'/api/sessions/{session}/file?path=/created/proof.bin', raw=True) == payload
        print('Redeployment and password rotation preserved files and saved credentials', flush=True)
    finally:
        try:
            run(uninstall)
        finally:
            password_file.unlink(missing_ok=True)
            (workspace / 'ansible-private.json').unlink(missing_ok=True)
    assert not PREFIX.exists(), 'Purge left the installation directory behind'
    print('Service uninstall and purge passed', flush=True)


if __name__ == '__main__':
    main()

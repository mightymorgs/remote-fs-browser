"""The Kubernetes endpoint, run against real containers.

A stand-in `kubectl` answers `get` from canned pod and claim JSON and turns
`exec` into `docker exec`, so the in-container shell scripts run for real on
BusyBox (Alpine-style images) and GNU coreutils (Debian-style images).
"""
import json
import shutil
import subprocess
import sys
import uuid

import pytest
from remote_fs_browser import Browser, Policy
from remote_fs_browser.kubernetes import KubernetesFilesystem
from remote_fs_browser.policy import READ_OPERATIONS, WRITE_OPERATIONS
from remote_fs_browser.sessions import clean_descriptor

IMAGES = ('busybox:1.37.0', 'debian:bookworm-slim')


def docker_ready():
    if not shutil.which('docker'):
        return False
    # Windows runners have Docker in Windows-container mode, which cannot run these images.
    result = subprocess.run(['docker', 'info', '--format', '{{.OSType}}'], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == 'linux'


FAKE = '''#!{python}
import json, os, sys
path = {state!r}
state = json.load(open(path))
def save():
    json.dump(state, open(path, 'w'))
args = [a for a in sys.argv[1:] if a == '--' or not a.startswith('--')]
open(path + '.calls', 'a').write(' '.join(args[:2]) + '\\n')
if args[0] == 'get':
    kind, rest = args[1], args[2:]
    namespace = rest[rest.index('-n') + 1]
    name = rest[0] if rest[0] != '-n' else None
    if kind == 'events':
        about = next((a.split('=', 2)[2] for a in sys.argv if a.startswith('--field-selector=involvedObject.name=')), None)
        print(json.dumps({{'items': [e for e in state.get('events', []) if e['involvedObject']['name'] == about]}})); sys.exit(0)
    table = state['pods'] if kind in ('pod', 'pods') else state['claims']
    table = [i for i in table if i['metadata']['namespace'] == namespace]
    if '-l' in rest:
        wanted = dict(pair.split('=', 1) for pair in rest[rest.index('-l') + 1].split(','))
        table = [i for i in table if all(i['metadata'].get('labels', {{}}).get(k) == v for k, v in wanted.items())]
    if name is None:
        print(json.dumps({{'items': table}})); sys.exit(0)
    for item in table:
        if item['metadata']['name'] == name:
            print(json.dumps(item)); sys.exit(0)
    sys.stderr.write('Error from server (NotFound): not found'); sys.exit(1)
if args[0] == 'create':
    pod = json.load(sys.stdin)
    pod['status'] = {{'phase': 'Running', 'conditions': [{{'type': 'Ready', 'status': 'False'}}],
                     'containerStatuses': [{{'name': 'files', 'state': {{'running': {{}}}}}}]}}
    state['pods'].append(pod); state.setdefault('created', []).append(pod); save(); sys.exit(0)
if args[0] == 'wait':
    if state.get('wait_fails', 0):
        state['wait_fails'] -= 1; save()
        sys.stderr.write('error: timed out waiting for the condition'); sys.exit(1)
    for pod in state['pods']:
        if 'pod/' + pod['metadata']['name'] in args:
            pod['status']['conditions'] = [{{'type': 'Ready', 'status': 'True'}}]
    save(); sys.exit(0)
if args[0] == 'delete':
    state['pods'] = [p for p in state['pods'] if p['metadata']['name'] != args[2]]
    state.setdefault('deleted', []).append(args[2]); save(); sys.exit(0)
if args[0] == 'exec':
    if state.get('noshell'):
        sys.stderr.write('OCI runtime exec failed: exec: "sh": executable file not found in $PATH'); sys.exit(126)
    command = args[args.index('--') + 1:]
    interactive = '-i' in args
    os.execvp('docker', ['docker', 'exec', *(['-i'] if interactive else []), state['container'], *command])
sys.exit(3)
'''


def pod(name, container='app', phase='Running', claim='data', app=None):
    return {'metadata': {'name': name, 'namespace': 'apps', 'labels': {'app': app or name}},
            'spec': {'containers': [{'name': container, 'volumeMounts': [{'name': 'data', 'mountPath': '/srv/data'},
                                                                       {'name': 'cfg', 'mountPath': '/etc/app', 'readOnly': True}]}],
                     'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}},
                                 {'name': 'cfg', 'configMap': {'name': 'cfg'}}]},
            'status': {'phase': phase, 'containerStatuses': [{'name': container, 'state': {'running': {}} if phase == 'Running' else {'waiting': {}}}]}}


def claim(name, size='1Gi'):
    return {'metadata': {'name': name, 'namespace': 'apps', 'annotations': {
        'volume.kubernetes.io/storage-provisioner': 'driver.longhorn.io'}}, 'status': {'capacity': {'storage': size}}}


@pytest.fixture(params=IMAGES)
def cluster(request, tmp_path):
    if not docker_ready():
        pytest.skip('needs a running Docker daemon')
    name = 'remotefs-k8s-' + uuid.uuid4().hex[:8]
    subprocess.run(['docker', 'run', '-d', '--rm', '--name', name, request.param, 'sleep', '600'],
                   check=True, capture_output=True)
    setup = ('mkdir -p /srv/data/sub /etc/app && printf hello-pod > /srv/data/hello.txt && '
             'printf "a=1\\n" > /srv/data/sub/config.ini && chmod 640 /srv/data/sub/config.ini && '
             'ln -s /srv/data/sub /srv/data/link && ln -s /missing /srv/data/broken && '
             'mkdir -p /volume/old && printf archived > /volume/old/report.txt')
    subprocess.run(['docker', 'exec', name, 'sh', '-c', setup], check=True)
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'container': name,
                                 'pods': [pod('web'), pod('stopped', phase='Pending')],
                                 'claims': [claim('data'), claim('archive', '2Gi')]}))
    kubectl = tmp_path / 'kubectl'
    kubectl.write_text(FAKE.format(python=sys.executable, state=str(state)))
    kubectl.chmod(0o755)
    yield {'type': 'kubernetes', 'kubectl': str(kubectl), 'namespaces': ['apps']}
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True)


def policy_for(endpoint, read_only=None):
    config = endpoint if read_only is None else {**endpoint, 'read_only': read_only}
    return Policy(endpoints={'pods': config},
                  operations=READ_OPERATIONS + WRITE_OPERATIONS, operation_timeout=30)


def test_descriptors_carry_only_the_endpoint_name():
    assert clean_descriptor({'type': 'kubernetes', 'endpoint': 'pods', 'kubeconfig': '/root/.kube/config',
                             'namespaces': ['kube-system']}) == {'type': 'kubernetes', 'endpoint': 'pods'}


@pytest.mark.parametrize('config', [
    {'type': 'kubernetes', 'namespaces': []},
    {'type': 'kubernetes', 'namespaces': ['Bad_Name']},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'kubeconfig': 'relative/config'},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'kubectl': 'kubectl'},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'context': '--insecure-skip-tls-verify'},
])
def test_invalid_kubernetes_policy(config):
    with pytest.raises(ValueError):
        Policy(endpoints={'pods': config})


def test_kubectl_errors_are_mapped_not_echoed():
    assert isinstance(KubernetesFilesystem.failure(1, 'Error from server (Forbidden): pods "x" is forbidden: User'), ValueError)
    assert 'RBAC' in str(KubernetesFilesystem.failure(1, 'pods is forbidden'))
    assert 'no shell' in str(KubernetesFilesystem.failure(1, 'exec: "sh": executable file not found in $PATH'))
    assert isinstance(KubernetesFilesystem.failure(17, ''), FileExistsError)
    error = KubernetesFilesystem.failure(1, 'dial tcp 10.0.0.5:6443: secret-host')
    assert 'secret-host' not in str(error)


@pytest.mark.asyncio
async def test_inventory_levels_list_namespaces_pods_containers_and_longhorn_volumes(cluster):
    async with Browser(policy_for(cluster)) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        assert [r['name'] for r in (await session.list('/'))['entries']] == ['apps']
        pods = {r['name']: r for r in (await session.list('/apps'))['entries']}
        assert pods['web']['state'] == 'Running' and pods['stopped']['state'] == 'Pending'
        assert [r['name'] for r in (await session.list('/apps/web'))['entries']] == ['app']
        info = await session.stat('/apps/web/app')
        volumes = {v['path']: v for v in info['volumes']}
        assert volumes['/srv/data']['claim'] == 'data' and volumes['/srv/data']['longhorn'] is True
        assert volumes['/etc/app']['read_only'] is True and 'claim' not in volumes['/etc/app']
        srv = {r['name']: r for r in (await session.list('/apps/web/app/srv'))['entries']}
        assert srv['data']['volume']['longhorn'] is True
        with pytest.raises(ValueError, match='running pods'):
            await session.list('/apps/stopped/app')
        with pytest.raises(PermissionError):
            await session.list('/kube-system')


@pytest.mark.asyncio
async def test_files_inside_a_container_read_ranges_and_links(cluster):
    async with Browser(policy_for(cluster, read_only=True)) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        rows = {r['name']: r for r in (await session.list('/apps/web/app/srv/data'))['entries']}
        assert rows['hello.txt']['type'] == 'file' and rows['hello.txt']['size'] == 9
        assert rows['sub']['type'] == 'directory'
        assert rows['link']['type'] == 'directory' and rows['link']['link'] is True
        assert rows['broken']['type'] == 'other'
        assert [r['name'] for r in (await session.list('/apps/web/app/srv/data/link'))['entries']] == ['config.ini']
        assert b''.join([c async for c in session.stream('/apps/web/app/srv/data/hello.txt', 2, 4)]) == b'llo-'
        async def chunks():
            yield b'x'
        with pytest.raises(PermissionError):
            await session.write('/apps/web/app/srv/data/new.txt', chunks())
        with pytest.raises(FileNotFoundError):
            await session.list('/apps/web/app/srv/missing')
        with pytest.raises(OSError, match='not a folder'):
            await session.list('/apps/web/app/srv/data/hello.txt')


@pytest.mark.asyncio
async def test_writes_are_atomic_keep_modes_and_never_walk_links(cluster, tmp_path):
    policy = policy_for(cluster)
    policy.local_roots = [str(tmp_path)]
    async with Browser(policy) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        base = '/apps/web/app/srv/data'
        async def chunks(data):
            yield data
        await session.write(base + '/sub/config.ini', chunks(b'a=2\n'), overwrite=True)
        assert b''.join([c async for c in session.stream(base + '/sub/config.ini')]) == b'a=2\n'
        mode = subprocess.run(['docker', 'exec', json.loads((tmp_path / 'state.json').read_text())['container'],
                               'stat', '-c', '%a', '/srv/data/sub/config.ini'], capture_output=True, text=True).stdout.strip()
        assert mode == '640'
        with pytest.raises(FileExistsError):
            await session.write(base + '/hello.txt', chunks(b'nope'))
        await session.mkdir(base + '/made')
        with pytest.raises(FileExistsError):
            await session.mkdir(base + '/made')
        await session.rename(base + '/hello.txt', base + '/made/moved.txt')
        with pytest.raises(FileExistsError):
            await session.rename(base + '/sub/config.ini', base + '/made/moved.txt')
        # Copy out of the pod to local storage.
        local = await browser.connect({'type': 'local', 'root': str(tmp_path)})
        await session.copy(base + '/made/moved.txt', '/moved.txt', target=local)
        assert (tmp_path / 'moved.txt').read_bytes() == b'hello-pod'
        # Deleting a folder that holds a link removes the link, never its target.
        container = json.loads((tmp_path / 'state.json').read_text())['container']
        subprocess.run(['docker', 'exec', container, 'ln', '-s', '/srv/data/sub', '/srv/data/made/outlink'], check=True)
        assert (await session.stat(base + '/made/outlink'))['link'] is True
        await session.remove(base + '/made', recursive=True)
        with pytest.raises(FileNotFoundError):
            await session.stat(base + '/made')
        await session.remove(base + '/link')
        assert (await session.stat(base + '/sub/config.ini'))['type'] == 'file'
        # Namespaces, pods and containers are inventory, not folders.
        for path in ('/apps', '/apps/web', '/apps/web/app'):
            with pytest.raises(PermissionError):
                await session.remove(path, recursive=True)
        with pytest.raises(PermissionError):
            await session.mkdir('/apps/web/new')
        assert (await session.stat(base + '/sub/config.ini'))['type'] == 'file'


@pytest.mark.asyncio
async def test_unmounted_volumes_open_through_a_helper_pod_that_is_deleted_on_close(cluster, tmp_path):
    state = tmp_path / 'state.json'
    async with Browser(policy_for(cluster)) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        assert 'Volumes' in [r['name'] for r in (await session.list('/apps'))['entries']]
        claims = {r['name']: r for r in (await session.list('/apps/Volumes'))['entries']}
        assert claims['data']['in_use_by'] == ['web', 'stopped'] and claims['data']['state'] == 'in use by web'
        assert claims['archive']['state'] == 'not mounted' and claims['archive']['longhorn'] is True
        assert claims['archive']['capacity'] == 2 * 2**30
        with pytest.raises(ValueError, match='web is using this volume'):
            await session.list('/apps/Volumes/data')
        assert 'created' not in json.loads(state.read_text())
        assert [r['name'] for r in (await session.list('/apps/Volumes/archive'))['entries']] == ['old']
        helper = json.loads(state.read_text())['created'][0]
        assert helper['metadata']['labels'] == {'app.kubernetes.io/managed-by': 'remotefs'}
        assert helper['spec']['volumes'][0]['persistentVolumeClaim'] == {'claimName': 'archive'}
        assert helper['spec']['activeDeadlineSeconds'] > 0
        base = '/apps/Volumes/archive/old'
        assert b''.join([c async for c in session.stream(base + '/report.txt')]) == b'archived'
        async def chunks():
            yield b'restored'
        await session.write(base + '/restored.txt', chunks())
        # The helper does not count as the volume's user, and is reused.
        claims = {r['name']: r for r in (await session.list('/apps/Volumes'))['entries']}
        assert claims['archive']['state'] == 'not mounted'
        await session.list(base)
        assert len(json.loads(state.read_text())['created']) == 1
        for path in ('/apps/Volumes', '/apps/Volumes/archive'):
            with pytest.raises(PermissionError):
                await session.remove(path, recursive=True)
        await session.remove(base + '/restored.txt')
    assert json.loads(state.read_text())['deleted'] == [helper['metadata']['name']]


def test_a_volume_still_attaching_answers_503_until_it_opens(cluster, tmp_path):
    from fastapi.testclient import TestClient
    from remote_fs_browser.http import create_app
    state = tmp_path / 'state.json'
    value = json.loads(state.read_text())
    value['wait_fails'] = 2
    state.write_text(json.dumps(value))
    token = 'kubernetes-test-token-at-least-32-chars'
    with TestClient(create_app(policy_for(cluster), token=token), raise_server_exceptions=False) as client:
        client.headers['Authorization'] = f'Bearer {token}'
        session = client.post('/api/sessions', json={'descriptor': {'type': 'kubernetes', 'endpoint': 'pods'}}).json()
        url = f"/api/sessions/{session['id']}/list?path=/apps/Volumes/archive"
        for _ in range(2):
            response = client.get(url)
            assert response.status_code == 503 and response.headers['Retry-After'] == '3'
            assert response.json()['detail'] == 'Attaching the volume; this can take up to a minute'
        response = client.get(url)
        assert response.status_code == 200
        assert [r['name'] for r in response.json()['entries']] == ['old']
        rows = {r['name']: r for r in client.get(f"/api/sessions/{session['id']}/list?path=/apps/Volumes").json()['entries']}
        assert rows['archive']['kind'] == 'Longhorn volume · not mounted'
        assert rows['data']['kind'] == 'Longhorn volume · in use by web'


@pytest.mark.asyncio
async def test_opening_folders_reuses_pod_and_claim_lookups(cluster, tmp_path):
    calls = tmp_path / 'state.json.calls'
    async with Browser(policy_for(cluster)) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        await session.stat('/apps/web/app/srv/data')
        await session.list('/apps/web/app/srv/data')
        assert [c for c in calls.read_text().split('\n') if c.startswith('exec')] == ['exec -i']
        calls.write_text('')
        # Browsing on within the same container reuses the lookups and the open
        # shell: no further kubectl calls at all.
        await session.stat('/apps/web/app/srv/data/sub')
        await session.list('/apps/web/app/srv/data/sub')
        await session.list('/apps/web/app/srv')
        assert b''.join([c async for c in session.stream('/apps/web/app/srv/data/hello.txt')]) == b'hello-pod'
        assert calls.read_text() == ''


def test_a_persistent_shell_frames_binary_output_and_survives_failing_commands():
    import os
    from remote_fs_browser.kubernetes import Shell
    shell = Shell(['sh'], dict(os.environ))
    try:
        # Arguments arrive intact, quotes and newlines included.
        assert shell.command('printf %s "$1"', ["it's a\nname $HOME"], 10, 1024) == b"it's a\nname $HOME"
        # Binary output, including a trailing newline and NUL bytes, comes back exactly.
        assert shell.command('printf "a\\000b\\n\\n"', [], 10, 1024) == b'a\x00b\n\n'
        # A script's exit status maps to the usual errors, and the shell carries on.
        with pytest.raises(FileNotFoundError):
            shell.command('exit 2', [], 10, 1024)
        with pytest.raises(FileExistsError):
            shell.command('exit 17', [], 10, 1024)
        # Commands cannot read the shell's own input.
        assert shell.command('cat', [], 10, 1024) == b''
        assert shell.command('echo still here', [], 10, 1024) == b'still here\n'
        with pytest.raises(ValueError, match='too large'):
            shell.command('head -c 100000 /dev/zero', [], 10, 1024)
        with pytest.raises(TimeoutError):
            Shell(['sh'], dict(os.environ)).command('sleep 5', [], 0.5, 1024)
    finally:
        shell.close()


def test_a_shell_that_never_starts_is_reported_as_not_started():
    import os
    from remote_fs_browser.kubernetes import Shell, ShellBroken
    with pytest.raises(ShellBroken) as broken:
        Shell(['false'], dict(os.environ)).command('true', [], 5, 1024)
    assert broken.value.started is False


@pytest.mark.asyncio
async def test_a_container_without_a_shell_says_so(cluster, tmp_path):
    state = tmp_path / 'state.json'
    value = json.loads(state.read_text())
    value['noshell'] = True
    state.write_text(json.dumps(value))
    async with Browser(policy_for(cluster)) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        for _ in range(2):
            with pytest.raises(ValueError, match='no shell'):
                await session.list('/apps/web/app/srv')


def edit_state(tmp_path, change):
    state = tmp_path / 'state.json'
    value = json.loads(state.read_text())
    change(value)
    state.write_text(json.dumps(value))
    return value


@pytest.mark.parametrize('config', [
    {'type': 'kubernetes', 'namespaces': ['apps'], 'selector': '-l app=web'},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'selector': 'app=web; rm -rf /'},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'selector': ' '},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'selector': ['app=web']},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'label': 'two\nlines'},
    {'type': 'kubernetes', 'namespaces': ['apps'], 'label': ''},
])
def test_invalid_selectors_and_labels(config):
    with pytest.raises(ValueError):
        Policy(endpoints={'pods': config})


def test_selectors_and_labels_are_accepted_and_labels_are_shown():
    from remote_fs_browser.discovery import discover
    policy = Policy(endpoints={
        'wordpress': {'type': 'kubernetes', 'namespaces': ['apps'], 'label': 'WordPress files',
                      'selector': 'app.kubernetes.io/instance=wordpress,tier!=cache,env in (prod, staging)'},
        'plain': {'type': 'kubernetes', 'namespaces': ['apps']}})
    rows = {r['endpoint']: r for r in discover(policy)['endpoints']}
    assert rows['wordpress']['label'] == 'WordPress files' and rows['plain']['label'] == 'plain'


@pytest.mark.asyncio
async def test_a_selector_scopes_the_endpoint_to_one_apps_pods_and_volumes(cluster, tmp_path):
    def add_other_app(state):
        state['pods'].append(pod('blog', claim='blog-data', app='blog'))
        state['claims'] += [claim('blog-data'), claim('spare')]
    edit_state(tmp_path, add_other_app)
    async with Browser(policy_for({**cluster, 'selector': 'app=web'})) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        assert [r['name'] for r in (await session.list('/apps'))['entries']] == ['web', 'Volumes']
        # Its own claim and the claims nobody mounts, not another app's.
        assert sorted(r['name'] for r in (await session.list('/apps/Volumes'))['entries']) == ['archive', 'data', 'spare']
        assert [r['name'] for r in (await session.list('/apps/web/app/srv/data'))['entries']]
        for path in ('/apps/blog', '/apps/blog/app', '/apps/blog/app/srv', '/apps/Volumes/blog-data'):
            with pytest.raises(FileNotFoundError):
                await session.list(path)
        with pytest.raises(FileNotFoundError):
            await session.stat('/apps/Volumes/blog-data')
        assert (await session.stat('/apps/Volumes/spare'))['state'] == 'not mounted'
    created = json.loads((tmp_path / 'state.json').read_text()).get('created', [])
    assert not [p for p in created if p['spec']['volumes'][0]['persistentVolumeClaim']['claimName'] == 'blog-data']


@pytest.mark.asyncio
async def test_configmap_and_secret_mounts_are_marked_managed_and_refuse_writes_with_the_reason(cluster, tmp_path):
    def add_secret(state):
        web = state['pods'][0]
        web['spec']['containers'][0]['volumeMounts'].append({'name': 'tls', 'mountPath': '/etc/tls', 'readOnly': True})
        web['spec']['volumes'].append({'name': 'tls', 'secret': {'secretName': 'web-tls'}})
    value = edit_state(tmp_path, add_secret)
    subprocess.run(['docker', 'exec', value['container'], 'sh', '-c',
                    'mkdir -p /etc/tls && printf "listen=80\n" > /etc/app/app.conf && printf key > /etc/tls/tls.key'], check=True)
    async with Browser(policy_for(cluster)) as browser:
        session = await browser.connect({'type': 'kubernetes', 'endpoint': 'pods'})
        volumes = {v['path']: v for v in (await session.stat('/apps/web/app'))['volumes']}
        assert volumes['/etc/app']['managed'] == {'kind': 'ConfigMap', 'name': 'cfg'}
        assert volumes['/etc/tls']['managed'] == {'kind': 'Secret', 'name': 'web-tls'}
        assert 'managed' not in volumes['/srv/data']
        etc = {r['name']: r for r in (await session.list('/apps/web/app/etc'))['entries']}
        assert etc['app']['managed'] == {'kind': 'ConfigMap', 'name': 'cfg'} and etc['app']['volume']['read_only'] is True
        assert 'managed' not in etc.get('hostname', {})
        inside = await session.list('/apps/web/app/etc/app')
        assert inside['managed'] == {'kind': 'ConfigMap', 'name': 'cfg'}
        assert [r['managed']['name'] for r in inside['entries'] if r['name'] == 'app.conf'] == ['cfg']
        assert (await session.stat('/apps/web/app/etc/tls/tls.key'))['managed']['kind'] == 'Secret'
        assert 'managed' not in await session.list('/apps/web/app/srv/data')
        async def chunks():
            yield b'listen=8080\n'
        with pytest.raises(PermissionError, match='ConfigMap `cfg`; the cluster rewrites it from its source'):
            await session.write('/apps/web/app/etc/app/app.conf', chunks(), overwrite=True)
        with pytest.raises(PermissionError, match='Secret `web-tls`'):
            await session.mkdir('/apps/web/app/etc/tls/new')
        with pytest.raises(PermissionError, match='edit the source instead'):
            await session.rename('/apps/web/app/srv/data/hello.txt', '/apps/web/app/etc/app/hello.txt')
        with pytest.raises(PermissionError, match='ConfigMap'):
            await session.remove('/apps/web/app/etc/app/app.conf')
    assert subprocess.run(['docker', 'exec', value['container'], 'cat', '/etc/app/app.conf'],
                          capture_output=True, text=True).stdout == 'listen=80\n'


def test_projected_and_downward_api_sources_are_named():
    assert KubernetesFilesystem.source_name({'sources': [{'configMap': {'name': 'a'}}, {'serviceAccountToken': {}},
                                                         {'secret': {'name': 'b'}}]}) == 'a, b'
    assert KubernetesFilesystem.source_name({'items': []}) is None
    assert KubernetesFilesystem.managed_at({'/etc/app': {'managed': {'kind': 'ConfigMap', 'name': 'cfg'}}}, '/etc/application') is None
    assert KubernetesFilesystem.managed_at({'/': {'managed': {'kind': 'Projected', 'name': 'x'}}}, '/a')['name'] == 'x'


def test_a_volume_that_never_attaches_says_what_kubernetes_reports(cluster, tmp_path):
    from fastapi.testclient import TestClient
    from remote_fs_browser.http import create_app
    helper = KubernetesFilesystem.helper_name('archive')
    def failing(state):
        state['wait_fails'] = 1
        state['events'] = [
            {'involvedObject': {'name': helper}, 'reason': 'Scheduled', 'message': 'Successfully assigned',
             'lastTimestamp': '2026-10-03T00:00:00Z'},
            {'involvedObject': {'name': helper}, 'reason': 'FailedAttachVolume', 'lastTimestamp': '2026-10-03T00:00:05Z',
             'message': 'AttachVolume.Attach failed for volume "pvc-1" : volume is not ready for workloads:\n'
                        'replica scheduling failed, disks are unavailable'},
            {'involvedObject': {'name': 'someone-else'}, 'reason': 'FailedScheduling', 'message': 'not ours'}]
    edit_state(tmp_path, failing)
    token = 'kubernetes-test-token-at-least-32-chars'
    with TestClient(create_app(policy_for(cluster), token=token), raise_server_exceptions=False) as client:
        client.headers['Authorization'] = f'Bearer {token}'
        session = client.post('/api/sessions', json={'descriptor': {'type': 'kubernetes', 'endpoint': 'pods'}}).json()
        response = client.get(f"/api/sessions/{session['id']}/list?path=/apps/Volumes/archive")
        assert response.status_code == 503
        assert response.json()['detail'] == (
            'Attaching the volume; this can take up to a minute (AttachVolume.Attach failed for volume "pvc-1" : '
            'volume is not ready for workloads: replica scheduling failed, disks are unavailable)')

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
state = json.load(open({state!r}))
args = [a for a in sys.argv[1:] if a == '--' or not a.startswith('--')]
if args[0] == 'get':
    kind, rest = args[1], args[2:]
    namespace = rest[rest.index('-n') + 1]
    name = rest[0] if rest[0] != '-n' else None
    if kind == 'pods':
        pods = [p for p in state['pods'] if p['metadata']['namespace'] == namespace]
        print(json.dumps({{'items': pods}})); sys.exit(0)
    table = state['pods'] if kind == 'pod' else state['claims']
    for item in table:
        if item['metadata']['name'] == name and item['metadata']['namespace'] == namespace:
            print(json.dumps(item)); sys.exit(0)
    sys.stderr.write('Error from server (NotFound): not found'); sys.exit(1)
if args[0] == 'exec':
    command = args[args.index('--') + 1:]
    interactive = '-i' in args
    os.execvp('docker', ['docker', 'exec', *(['-i'] if interactive else []), state['container'], *command])
sys.exit(3)
'''


def pod(name, container='app', phase='Running', claim='data'):
    return {'metadata': {'name': name, 'namespace': 'apps'},
            'spec': {'containers': [{'name': container, 'volumeMounts': [{'name': 'data', 'mountPath': '/srv/data'},
                                                                       {'name': 'cfg', 'mountPath': '/etc/app', 'readOnly': True}]}],
                     'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}},
                                 {'name': 'cfg', 'configMap': {'name': 'cfg'}}]},
            'status': {'phase': phase, 'containerStatuses': [{'name': container, 'state': {'running': {}} if phase == 'Running' else {'waiting': {}}}]}}


@pytest.fixture(params=IMAGES)
def cluster(request, tmp_path):
    if not docker_ready():
        pytest.skip('needs a running Docker daemon')
    name = 'remotefs-k8s-' + uuid.uuid4().hex[:8]
    subprocess.run(['docker', 'run', '-d', '--rm', '--name', name, request.param, 'sleep', '600'],
                   check=True, capture_output=True)
    setup = ('mkdir -p /srv/data/sub /etc/app && printf hello-pod > /srv/data/hello.txt && '
             'printf "a=1\\n" > /srv/data/sub/config.ini && chmod 640 /srv/data/sub/config.ini && '
             'ln -s /srv/data/sub /srv/data/link && ln -s /missing /srv/data/broken')
    subprocess.run(['docker', 'exec', name, 'sh', '-c', setup], check=True)
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'container': name,
                                 'pods': [pod('web'), pod('stopped', phase='Pending')],
                                 'claims': [{'metadata': {'name': 'data', 'namespace': 'apps', 'annotations': {
                                     'volume.kubernetes.io/storage-provisioner': 'driver.longhorn.io'}}}]}))
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

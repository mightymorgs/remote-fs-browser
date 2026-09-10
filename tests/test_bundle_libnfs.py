import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'packaging' / 'bundle_libnfs.py'
spec = importlib.util.spec_from_file_location('bundle_libnfs', SCRIPT)
bundler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundler)


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args])


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    git(source, 'init', '--quiet')
    git(source, 'config', 'user.name', 'Packaging test')
    git(source, 'config', 'user.email', 'test@example.invalid')
    for name in bundler.LICENSE_FILES:
        (source / name).write_text(f'Full upstream text for {name}\n')
    (source / 'cmake').mkdir()
    (source / 'cmake' / 'ConfigureChecks.cmake').write_text('add_definitions(-Wall)\n')
    git(source, 'add', '.')
    git(source, 'commit', '--quiet', '-m', 'Fixture upstream source')
    commit = git(source, 'rev-parse', 'HEAD').decode().strip()
    monkeypatch.setattr(bundler, 'PINNED_COMMIT', commit)
    bundle = tmp_path / 'remotefs'
    bundle.mkdir()
    (bundle / 'libnfs.dll').write_bytes(b'fixture DLL')
    recipe = tmp_path / 'action.yml'
    recipe.write_text('name: Actual build recipe\n')
    return source, bundle, recipe


def test_packages_modified_source_and_full_notices(checkout):
    source, bundle, recipe = checkout
    modified = '# Modified on 2026-09-10 for Windows resources\nadd_compile_options("$<$<COMPILE_LANGUAGE:C>:-Wall>")\n'
    (source / 'cmake' / 'ConfigureChecks.cmake').write_text(modified)
    (source / 'untracked-secret.txt').write_text('must not ship')
    (source / 'build').mkdir()
    (source / 'build' / 'generated.obj').write_bytes(b'do not ship')

    archive = bundler.bundle_libnfs(*checkout)
    prefix = f'libnfs-{bundler.PINNED_COMMIT}/'
    with tarfile.open(archive) as contents:
        names = contents.getnames()
        assert set(names) == {prefix + name for name in (*bundler.LICENSE_FILES, 'cmake/ConfigureChecks.cmake')}
        assert contents.extractfile(prefix + 'cmake/ConfigureChecks.cmake').read() == (source / 'cmake' / 'ConfigureChecks.cmake').read_bytes()
    notices = bundle / 'licenses' / 'libnfs'
    for name in bundler.LICENSE_FILES:
        assert (notices / name).read_bytes() == (source / name).read_bytes()
    assert (notices / 'build-libnfs-action.yml').read_bytes() == recipe.read_bytes()
    patch = (notices / 'local-changes.patch').read_text()
    assert '+# Modified on 2026-09-10' in patch
    assert '-add_definitions(-Wall)' in patch
    provenance = json.loads((notices / 'PROVENANCE.json').read_text())
    assert provenance['commit'] == bundler.PINNED_COMMIT
    assert provenance['source_archive_sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert provenance['dll_sha256'] == hashlib.sha256((bundle / 'libnfs.dll').read_bytes()).hexdigest()
    assert provenance['build_recipe_sha256'] == hashlib.sha256(recipe.read_bytes()).hexdigest()
    assert provenance['modified_tracked_files'] == ['cmake/ConfigureChecks.cmake']
    assert provenance['packaged_at_utc']
    instructions = (notices / 'BUILDING.md').read_text()
    assert archive.name in instructions
    assert '-DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc' in instructions
    assert 'Stop remotefs' in instructions
    assert 'do not apply the patch again' in instructions


@pytest.mark.parametrize('name', bundler.LICENSE_FILES)
def test_rejects_missing_licence_before_creating_archive(checkout, name):
    source, bundle, _ = checkout
    (source / name).unlink()
    with pytest.raises(ValueError, match='Missing'):
        bundler.bundle_libnfs(*checkout)
    assert not (bundle / 'sources').exists()


def test_rejects_wrong_source_commit(checkout, monkeypatch):
    monkeypatch.setattr(bundler, 'PINNED_COMMIT', '0' * 40)
    with pytest.raises(ValueError, match='Expected libnfs commit'):
        bundler.bundle_libnfs(*checkout)


@pytest.mark.parametrize('missing', ['dll', 'recipe'])
def test_requires_dll_and_build_recipe(checkout, missing):
    _, bundle, recipe = checkout
    (bundle / 'libnfs.dll' if missing == 'dll' else recipe).unlink()
    with pytest.raises(ValueError, match='DLL|dll'):
        bundler.bundle_libnfs(*checkout)

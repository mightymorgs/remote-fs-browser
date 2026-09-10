import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'packaging' / 'bundle_toolchain.py'
spec = importlib.util.spec_from_file_location('bundle_toolchain', SCRIPT)
bundler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundler)


@pytest.fixture
def toolchain(tmp_path):
    root = tmp_path / 'toolchain'
    # Representative text fixtures exercise missing/truncated coverage gates;
    # release integration additionally uses the actual installed notice bytes.
    samples = {
        'licenses/mingw-w64/COPYING.MinGW-w64-runtime.txt':
            'MinGW-w64 runtime licensing\nCopyright\nRedistribution and use\nDisclaimer\n' + 'terms\n' * 150,
        'licenses/gcc/COPYING.RUNTIME':
            'GCC RUNTIME LIBRARY EXCEPTION\nVersion 3.1\nGrant of Additional Permission\n' + 'terms\n' * 300,
        'licenses/gcc/COPYING3':
            'GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\nTERMS AND CONDITIONS\n' + 'terms\n' * 2600,
        'licenses/mingw-w64/DISCLAIMER.PD': 'Public domain disclaimer\n',
    }
    for name, text in samples.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def test_preserves_notice_paths_bytes_and_hashes(toolchain, tmp_path, monkeypatch):
    compiler = toolchain / 'bin' / 'gcc.exe'
    compiler.parent.mkdir()
    compiler.write_bytes(b'compiler fixture')
    responses = {'--version': 'gcc 14.2.0\n', '-dumpmachine': 'x86_64-w64-mingw32\n'}
    monkeypatch.setattr(bundler.subprocess, 'check_output', lambda args, **kw: responses[args[1]])
    output = tmp_path / 'release' / 'licenses' / 'mingw'
    manifest = json.loads(bundler.bundle_toolchain(toolchain, output, compiler).read_text())
    assert manifest['compiler']['version'] == 'gcc 14.2.0'
    assert manifest['compiler']['target'] == 'x86_64-w64-mingw32'
    assert len(manifest['files']) == 4
    assert not (output / 'bin').exists()
    for name, digest in manifest['files'].items():
        assert (output / name).read_bytes() == (toolchain / name).read_bytes()
        assert digest == hashlib.sha256((toolchain / name).read_bytes()).hexdigest()


@pytest.mark.parametrize('name,expected', [
    ('licenses/gcc/COPYING.RUNTIME', 'Exception 3.1'),
    ('licenses/gcc/COPYING3', 'GPL version 3'),
    ('licenses/mingw-w64/COPYING.MinGW-w64-runtime.txt', 'MinGW runtime'),
])
def test_rejects_missing_runtime_terms(toolchain, tmp_path, name, expected):
    (toolchain / name).unlink()
    output = tmp_path / 'output'
    with pytest.raises(bundler.LicenseError, match=expected):
        bundler.bundle_toolchain(toolchain, output)
    assert not output.exists()


def test_rejects_identifier_instead_of_exception_text(toolchain):
    (toolchain / 'licenses/gcc/COPYING.RUNTIME').write_text('GPL-3.0-with-GCC-exception')
    with pytest.raises(bundler.LicenseError, match='Exception 3.1'):
        bundler.collect_notices(toolchain)


def test_rejects_notice_symlinks(toolchain, tmp_path):
    outside = tmp_path / 'private.txt'
    outside.write_text('outside')
    (toolchain / 'licenses' / 'NOTICE').symlink_to(outside)
    with pytest.raises(bundler.LicenseError, match='Symlink'):
        bundler.collect_notices(toolchain)


def test_rejects_other_installed_compiler(toolchain, tmp_path):
    compiler = tmp_path / 'gcc.exe'
    compiler.write_bytes(b'other compiler')
    with pytest.raises(bundler.LicenseError, match='inside'):
        bundler.bundle_toolchain(toolchain, tmp_path / 'output', compiler)


def test_rejects_output_inside_toolchain_and_stale_notices(toolchain, tmp_path):
    with pytest.raises(bundler.LicenseError, match='outside'):
        bundler.bundle_toolchain(toolchain, toolchain / 'out')
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'old-notice').write_text('stale')
    with pytest.raises(bundler.LicenseError, match='empty'):
        bundler.bundle_toolchain(toolchain, output)

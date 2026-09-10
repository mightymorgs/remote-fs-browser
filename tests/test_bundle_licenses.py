"""Release notices must cover runtime dependencies and fail closed on missing text."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest

_SPEC = spec_from_file_location("bundle_licenses", Path(__file__).parents[1] / "packaging" / "bundle_licenses.py")
licenses = module_from_spec(_SPEC)
_SPEC.loader.exec_module(licenses)


class Distribution:
    def __init__(self, base, name, *, requires=(), files=None, license_value="MIT"):
        self.base = base
        self.metadata = {"Name": name, "License": license_value, "License-Expression": "MIT"}
        self.version = "1.2.3"
        self.requires = requires
        self.files = list(files) if files is not None else []
        for path, content in (files or {}).items():
            target = base / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    def locate_file(self, relative):
        return self.base / str(relative)


def installed(monkeypatch, distributions):
    lookup = {licenses.canonicalize_name(d.metadata["Name"]): d for d in distributions}

    def distribution(name):
        try:
            return lookup[licenses.canonicalize_name(name)]
        except KeyError:
            raise licenses.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(licenses.metadata, "distribution", distribution)


def test_closure_includes_smbprotocol_transitive_extras_and_markers(tmp_path, monkeypatch):
    root = Distribution(tmp_path, "remote-fs-browser", requires=[
        "smbprotocol[security]", 'absent; python_version < "2"', 'test-only; extra == "test"',
    ])
    smb = Distribution(tmp_path, "smbprotocol", requires=['crypto; extra == "security"', 'remote-fs-browser'])
    crypto = Distribution(tmp_path, "crypto")
    installed(monkeypatch, [root, smb, crypto])
    assert [d.metadata["Name"] for d in licenses.runtime_distributions("remote-fs-browser")] == [
        "crypto", "remote-fs-browser", "smbprotocol",
    ]


def test_missing_runtime_dependency_fails(tmp_path, monkeypatch):
    installed(monkeypatch, [Distribution(tmp_path, "root", requires=["missing"])])
    with pytest.raises(licenses.LicenseError, match="not installed: missing"):
        licenses.runtime_distributions("root")


def test_collects_nested_vendored_and_non_dist_info_notices(tmp_path):
    files = {
        "demo.dist-info/licenses/LICENSE": "primary licence",
        "demo/_vendor/NOTICE.txt": "vendor notice",
        "demo/_vendor/licenses/another-project": "another vendor licence",
        "PyInstaller/COPYING.txt": "bootloader terms",
        "demo/__init__.py": "not a notice",
    }
    dist = Distribution(tmp_path, "demo", files=files)
    assert set(licenses.distribution_notices(dist)) == set(files) - {"demo/__init__.py"}


@pytest.mark.parametrize("path", ["../LICENSE", "/LICENSE", "C:/LICENSE", "..\\LICENSE"])
def test_rejects_unsafe_record_paths(tmp_path, path):
    dist = Distribution(tmp_path, "demo")
    dist.files = [path]
    with pytest.raises(licenses.LicenseError, match="Unsafe notice path"):
        licenses.distribution_notices(dist)


def test_rejects_symlink_outside_distribution(tmp_path):
    base = tmp_path / "site-packages"
    base.mkdir()
    outside = tmp_path / "private"
    outside.write_text("do not redistribute")
    (base / "LICENSE").symlink_to(outside)
    dist = Distribution(base, "demo")
    dist.files = ["LICENSE"]
    with pytest.raises(licenses.LicenseError, match="unsafe notice file"):
        licenses.distribution_notices(dist)


@pytest.mark.parametrize("value", ["MIT", "BSD-3-Clause", "Apache Software License", ""])
def test_identifier_is_not_full_license_text(tmp_path, value):
    with pytest.raises(licenses.LicenseError, match="No licence text"):
        licenses.distribution_notices(Distribution(tmp_path, "demo", license_value=value))


def test_full_metadata_license_fallback(tmp_path):
    value = (Path(__file__).parents[1] / "LICENSE").read_text()
    notices = licenses.distribution_notices(Distribution(tmp_path, "demo", license_value=value))
    assert notices == {"LICENSE.metadata.txt": value.encode()}


@pytest.mark.parametrize("content", [None, ""])
def test_missing_or_empty_record_fails(tmp_path, content):
    dist = Distribution(tmp_path, "demo")
    dist.files = ["LICENSE"]
    if content is not None:
        (tmp_path / "LICENSE").write_text(content)
    with pytest.raises(licenses.LicenseError):
        licenses.distribution_notices(dist)


def prepare_bundle(tmp_path, monkeypatch, pyinstaller_license="GNU General Public License\nBootloader Exception"):
    root = Distribution(tmp_path, "remote-fs-browser", requires=["smbprotocol"], files={"root/LICENSE": "root terms"})
    smb = Distribution(tmp_path, "smbprotocol", files={"smbprotocol.dist-info/licenses/LICENSE": "SMB terms"})
    bootloader = Distribution(tmp_path, "pyinstaller", files={"pyinstaller.dist-info/COPYING.txt": pyinstaller_license})
    installed(monkeypatch, [root, smb, bootloader])
    python = tmp_path / "python-license.txt"
    python.write_text("CPython licence")
    return python


def test_bundle_contains_runtime_bootloader_python_and_index(tmp_path, monkeypatch):
    python = prepare_bundle(tmp_path, monkeypatch)
    output = tmp_path / "release/licenses"
    licenses.bundle(output, python_license=python)
    index = json.loads((output / "INDEX.json").read_text())
    assert {d["name"] for d in index} == {"remote-fs-browser", "smbprotocol", "pyinstaller", "CPython"}
    smb = next(d for d in index if d["name"] == "smbprotocol")
    assert smb["version"] == "1.2.3"
    assert smb["license_expression"] == "MIT"
    assert (output / smb["files"][0]).read_text() == "SMB terms"
    assert (output / "python/LICENSE.txt").read_text() == "CPython licence"


def test_missing_bootloader_exception_prevents_output(tmp_path, monkeypatch):
    python = prepare_bundle(tmp_path, monkeypatch, "GNU General Public License")
    output = tmp_path / "release/licenses"
    with pytest.raises(licenses.LicenseError, match="bootloader exception"):
        licenses.bundle(output, python_license=python)
    assert not output.exists()


def test_missing_python_license_prevents_output(tmp_path, monkeypatch):
    prepare_bundle(tmp_path, monkeypatch)
    output = tmp_path / "release/licenses"
    with pytest.raises(licenses.LicenseError, match="CPython licence not found"):
        licenses.bundle(output, python_license=tmp_path / "missing")
    assert not output.exists()


def test_python_license_auto_discovery_uses_base_interpreter(tmp_path, monkeypatch):
    (tmp_path / "LICENSE.txt").write_text("CPython full licence")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(tmp_path))
    assert licenses.python_license_path(None) == tmp_path / "LICENSE.txt"


def test_additional_optional_runtime_closure(tmp_path, monkeypatch):
    root = Distribution(tmp_path, "root")
    optional = Distribution(tmp_path, "impacket", requires=["dependency"])
    dependency = Distribution(tmp_path, "dependency")
    installed(monkeypatch, [root, optional, dependency])
    assert {d.metadata["Name"] for d in licenses.runtime_distributions("root", ("impacket",))} == {
        "root", "impacket", "dependency",
    }


def test_wheel_notice_outside_site_packages_stays_within_prefix(tmp_path, monkeypatch):
    base = tmp_path / "lib/python3.12/site-packages"
    base.mkdir(parents=True)
    dist = Distribution(base, "impacket", files={"../../../share/doc/impacket/LICENSE": "full licence"})
    monkeypatch.setattr(licenses.sys, "prefix", str(tmp_path))
    assert licenses.distribution_notices(dist) == {
        "_environment/share/doc/impacket/LICENSE": b"full licence",
    }

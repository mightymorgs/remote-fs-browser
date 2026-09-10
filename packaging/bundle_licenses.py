"""Bundle installed runtime notices into a portable release (fail on missing text)."""
from __future__ import annotations

import argparse
from collections import deque
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


class LicenseError(RuntimeError):
    """A release is missing licence material or contains an unsafe file path."""


def runtime_distributions(root: str, include: tuple[str, ...] = ()) -> list:
    """Resolve installed runtime requirements, including activated dependency extras."""
    pending = deque((name, "") for name in (root, *include))
    seen = set()
    distributions = {}
    while pending:
        name, extra = pending.popleft()
        name = canonicalize_name(name)
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as exc:
            raise LicenseError(f"Required runtime distribution is not installed: {name}") from exc
        distributions[name] = dist
        for value in dist.requires or []:
            req = Requirement(value)
            if req.marker and not req.marker.evaluate({"extra": extra}):
                continue
            pending.append((req.name, ""))
            pending.extend((req.name, item) for item in req.extras)
    return [distributions[name] for name in sorted(distributions)]


def is_notice(path: PurePosixPath) -> bool:
    # Files under licence directories can be named after the vendored project.
    return bool(re.match(r"^(licen[cs]e|copying|copyright|notice)([._-].*|s)?$", path.name, re.I)) or any(
        part.lower() in {"licenses", "licences", "license", "licence", "notices"}
        for part in path.parts[:-1]
    )


def full_license_text(value: str) -> bool:
    # SPDX identifiers and classifier-like descriptions are not redistribution text.
    lower = value.lower()
    return len(value) >= 300 and any(
        phrase in lower for phrase in (
            "permission is hereby granted", "redistribution and use", "apache license",
            "gnu general public license", "permission to use, copy",
        )
    ) and any(word in lower for word in ("warranty", "disclaimer", "liability"))


def distribution_notices(dist) -> dict[str, bytes]:
    notices = {}
    base = Path(dist.locate_file("")).resolve()
    for record in dist.files or []:
        path = PurePosixPath(str(record).replace("\\", "/"))
        if not is_notice(path):
            continue
        if path.is_absolute() or any(":" in part for part in path.parts):
            raise LicenseError(f"Unsafe notice path for {dist.metadata['Name']}: {record}")
        source = Path(dist.locate_file(record)).resolve()
        if ".." in path.parts:
            # Wheel data files can live in <prefix>/share/doc, outside site-packages.
            prefix = Path(sys.prefix).resolve()
            if not base.is_relative_to(prefix) or not source.is_relative_to(prefix):
                raise LicenseError(f"Unsafe notice path for {dist.metadata['Name']}: {record}")
            path = PurePosixPath("_environment") / source.relative_to(prefix).as_posix()
        elif not source.is_relative_to(base):
            raise LicenseError(f"Missing or unsafe notice file for {dist.metadata['Name']}: {record}")
        if not source.is_file():
            raise LicenseError(f"Missing or unsafe notice file for {dist.metadata['Name']}: {record}")
        data = source.read_bytes()
        if not data.strip():
            raise LicenseError(f"Empty notice file for {dist.metadata['Name']}: {record}")
        notices[str(path)] = data
    if not notices:
        value = dist.metadata.get("License", "")
        if full_license_text(value):
            notices["LICENSE.metadata.txt"] = value.encode("utf-8")
        else:
            raise LicenseError(f"No licence text found for {dist.metadata['Name']} {dist.version}")
    return notices


def python_license_path(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit else [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt",
    ]
    for path in candidates:
        if path is not None and path.is_file() and path.read_bytes().strip():
            return path
    raise LicenseError("CPython licence not found; provide --python-license PATH to the interpreter's full licence")


def bundle(output: Path, root: str = "remote-fs-browser", python_license: Path | None = None,
           include: tuple[str, ...] = ()) -> None:
    distributions = runtime_distributions(root, include)
    try:
        pyinstaller = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError as exc:
        raise LicenseError("PyInstaller must be installed to bundle its bootloader licence") from exc
    distributions = [d for d in distributions if canonicalize_name(d.metadata["Name"]) != "pyinstaller"]
    distributions.append(pyinstaller)
    files = {}
    index = []
    for dist in distributions:
        name = canonicalize_name(dist.metadata["Name"])
        if not re.fullmatch(r"[a-z0-9]+(?:[-][a-z0-9]+)*", name):
            raise LicenseError(f"Unsafe distribution name: {name}")
        notices = distribution_notices(dist)
        if name == "pyinstaller":
            text = b"\n".join(notices.values()).decode("utf-8", errors="replace").lower()
            if "bootloader exception" not in text or "gnu general public license" not in text:
                raise LicenseError("PyInstaller licence is missing the GPL text or bootloader exception")
        paths = []
        for relative, data in sorted(notices.items()):
            target = f"{name}/{relative}"
            files[target] = data
            paths.append(target)
        index.append({
            "name": dist.metadata["Name"], "version": dist.version,
            "license_expression": dist.metadata.get("License-Expression"),
            "license": dist.metadata.get("License"), "files": paths,
        })
    source = python_license_path(python_license)
    files["python/LICENSE.txt"] = source.read_bytes()
    index.append({"name": "CPython", "version": sys.version.split()[0], "files": ["python/LICENSE.txt"]})
    # Resolve all required notices before writing, so missing material fails the build.
    for relative, data in files.items():
        target = output / relative
        if not target.resolve().is_relative_to(output.resolve()):
            raise LicenseError(f"Unsafe output path: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    output.mkdir(parents=True, exist_ok=True)
    (output / "INDEX.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled {len(files)} notice files for {len(index)} components into {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Release licence directory, e.g. dist/remotefs/licenses")
    parser.add_argument("--root", default="remote-fs-browser", help="Installed runtime root distribution")
    parser.add_argument("--include", action="append", default=[], help="Additional bundled runtime distribution (repeatable)")
    parser.add_argument("--python-license", type=Path, help="Explicit CPython full licence file")
    args = parser.parse_args()
    try:
        bundle(args.output, args.root, args.python_license, tuple(args.include))
    except LicenseError as exc:
        parser.exit(1, f"Cannot bundle release licences: {exc}\n")


if __name__ == "__main__":
    main()

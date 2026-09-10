"""Preserve installed MinGW toolchain notices, failing if runtime terms are absent."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


class LicenseError(RuntimeError):
    """The selected compiler's runtime notices cannot be bundled safely."""


def is_notice(path: Path) -> bool:
    return bool(re.match(r"^(copying|licen[cs]e|notice|copyright|disclaimer)([._-].*|\d.*|s)?$", path.name, re.I)) or any(
        part.lower() in {"licenses", "licences", "license", "licence", "notices"}
        for part in path.parts[:-1]
    )


def collect_notices(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    if not root.is_dir():
        raise LicenseError(f"Toolchain directory does not exist: {root}")
    notices = {}
    for source in sorted(root.rglob("*")):
        relative = source.relative_to(root)
        if not is_notice(relative):
            continue
        if source.is_symlink():
            raise LicenseError(f"Symlink in toolchain notices: {relative}")
        if not source.is_file():
            continue
        data = source.read_bytes()
        if not data.strip() or b"\0" in data:
            raise LicenseError(f"Empty or binary toolchain notice: {relative}")
        notices[relative.as_posix()] = data

    # These markers must occur in actual terms, not just a package/version list.
    texts = {name: data.decode("utf-8", errors="replace").lower() for name, data in notices.items()}
    mingw = any(
        "mingw-w64 runtime licensing" in text and "copyright" in text and "redistribution and use" in text
        and "disclaimer" in text and len(text) > 700
        for text in texts.values()
    )
    exception = any(
        "gcc runtime library exception" in text and "version 3.1" in text
        and "grant of additional permission" in text and len(text) > 1500
        for text in texts.values()
    )
    gpl = any(
        "gnu general public license" in text and "version 3, 29 june 2007" in text
        and "terms and conditions" in text and len(text) > 15000
        for text in texts.values()
    )
    missing = [name for name, present in (("MinGW runtime copyright/terms", mingw),
               ("GCC Runtime Library Exception 3.1", exception), ("GPL version 3", gpl)) if not present]
    if missing:
        raise LicenseError("Missing toolchain licence coverage: " + ", ".join(missing)
                           + ". Supply the complete selected compiler distribution's notices; "
                           "do not substitute notices from another installed compiler.")
    return notices


def bundle_toolchain(root: Path, output: Path, compiler: Path | None = None) -> Path:
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root):
        raise LicenseError("Notice output must be outside the toolchain directory")
    if output.exists() and any(output.iterdir()):
        raise LicenseError(f"Notice output must be empty: {output}")
    notices = collect_notices(root)
    compiler_info = None
    if compiler is not None:
        compiler = compiler.resolve()
        if not compiler.is_relative_to(root) or not compiler.is_file():
            raise LicenseError("Selected compiler must be a file inside the supplied toolchain root")
        compiler_info = {
            "path": compiler.relative_to(root).as_posix(),
            "version": subprocess.check_output([str(compiler), "--version"], text=True, timeout=30).strip(),
            "target": subprocess.check_output([str(compiler), "-dumpmachine"], text=True, timeout=30).strip(),
        }
    output.mkdir(parents=True, exist_ok=True)
    for name, data in notices.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = output / "toolchain-notices.json"
    manifest.write_text(json.dumps({
        "compiler": compiler_info,
        "description": "Notices copied from the selected compiler distribution; inclusion does not imply every tool is shipped.",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in notices.items()},
    }, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, help="Actual gcc used to compile libnfs; records its version and target")
    args = parser.parse_args()
    try:
        print(bundle_toolchain(args.toolchain, args.output, args.compiler))
    except (LicenseError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Toolchain notice bundling failed: {exc}\n")


if __name__ == "__main__":
    main()

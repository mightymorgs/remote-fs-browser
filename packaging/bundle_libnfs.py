"""Bundle the source and notices corresponding to the portable libnfs DLL."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


PINNED_COMMIT = 'c69a48c8116fd50287875decd50474685937a4af'
UPSTREAM = 'https://github.com/sahlberg/libnfs.git'
LICENSE_FILES = ('COPYING', 'LICENCE-BSD.txt', 'LICENCE-GPL-3.txt', 'LICENCE-LGPL-2.1.txt')


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_libnfs(source, bundle, build_recipe):
    source, bundle, build_recipe = map(Path, (source, bundle, build_recipe))
    commit = git(source, 'rev-parse', 'HEAD').decode().strip()
    if commit != PINNED_COMMIT:
        raise ValueError(f'Expected libnfs commit {PINNED_COMMIT}, found {commit}')
    dll = bundle / 'libnfs.dll'
    if not dll.is_file() or not build_recipe.is_file():
        raise ValueError('The bundled libnfs.dll and actual build recipe must exist')

    # Read working files, not git archive: the Windows build modifies a tracked
    # CMake file before compilation. Preserve the tracked executable bits too.
    tracked = []
    for entry in git(source, 'ls-files', '--stage', '-z').split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, _, stage = metadata.decode().split()
        name = name.decode('utf-8')
        if name.split('/')[0] in ('.git', 'build'):
            continue
        if stage != '0' or mode not in ('100644', '100755'):
            raise ValueError(f'Unsupported tracked source entry: {name}')
        if not (source / name).is_file() or (source / name).is_symlink():
            raise ValueError(f'Missing or non-regular tracked source file: {name}')
        tracked.append((name, int(mode, 8) & 0o777))
    names = {name for name, _ in tracked}
    for name in LICENSE_FILES:
        if name not in names or not (source / name).read_bytes().strip():
            raise ValueError(f'Missing required upstream licence: {name}')

    notices = bundle / 'licenses' / 'libnfs'
    sources = bundle / 'sources'
    notices.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    archive = sources / f'libnfs-{commit}.tar.gz'
    prefix = f'libnfs-{commit}'
    with tarfile.open(archive, 'w:gz') as output:
        for name, mode in tracked:
            path = source / name
            info = output.gettarinfo(str(path), arcname=f'{prefix}/{name}')
            info.mode = mode
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            with path.open('rb') as data:
                output.addfile(info, data)

    for name in LICENSE_FILES:
        shutil.copyfile(source / name, notices / name)
    recipe_copy = notices / 'build-libnfs-action.yml'
    shutil.copyfile(build_recipe, recipe_copy)
    patch = notices / 'local-changes.patch'
    patch.write_bytes(git(source, 'diff', '--binary', '--no-ext-diff', 'HEAD', '--', '.', ':(exclude)build'))
    modified = git(source, 'diff', '--name-only', '-z', 'HEAD', '--', '.', ':(exclude)build')
    provenance = {
        'upstream': UPSTREAM,
        'commit': commit,
        'packaged_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_archive': f'sources/{archive.name}',
        'source_archive_sha256': sha256(archive),
        'dll': 'libnfs.dll',
        'dll_sha256': sha256(dll),
        'build_recipe': recipe_copy.name,
        'build_recipe_sha256': sha256(recipe_copy),
        'local_patch': patch.name,
        'local_patch_sha256': sha256(patch),
        'modified_tracked_files': [name.decode('utf-8') for name in modified.split(b'\0') if name],
        'source_contents': 'Tracked files from the build checkout, including local changes; .git, build and untracked files excluded.',
    }
    (notices / 'PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    (notices / 'BUILDING.md').write_text(f'''# Bundled libnfs

This portable distribution dynamically loads the separate `libnfs.dll` next to
`remotefs.exe`. libnfs is a third-party component. See COPYING for the upstream
licence allocation and the accompanying full LGPL-2.1, BSD and GPL-3 texts.
The GPL-licensed examples and utilities are not built into this DLL.

The accompanying `../../sources/{archive.name}` contains the tracked source
files used to build this DLL, including local modifications. Upstream is
{UPSTREAM} at commit `{commit}`. `PROVENANCE.json` records the archive and DLL
hashes, packaging date, modified file list and build recipe hash.
`local-changes.patch` records the changes against that upstream commit.
For the Windows build, ConfigureChecks.cmake applies `-Wall` only to C
compilation so that it is not passed to windres. The archive already includes
this change; do not apply the patch again.

## Rebuild on Windows

Install CMake and a 64-bit MinGW GCC toolchain (the release uses Chocolatey's
`mingw` package). `build-libnfs-action.yml` is the exact CI build recipe copied
from the release. From the portable distribution directory, run in PowerShell:

```powershell
tar -xzf sources/{archive.name}
$Source = (Resolve-Path {prefix}).Path
$Gcc = (Get-Command gcc).Source
cmake -S "$Source" -B "$Source/build" -G 'MinGW Makefiles' "-DCMAKE_C_COMPILER=$Gcc" -DBUILD_SHARED_LIBS=ON -DENABLE_TLS=OFF -DENABLE_UTILS=OFF -DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc
cmake --build "$Source/build" --parallel 2
Get-ChildItem "$Source/build" -Recurse -Filter '*nfs*.dll'
```

Check each command succeeds before continuing. You may modify the extracted
library sources before building. Keep the DLL compatible with the libnfs API
used by this version of remotefs and build for the same architecture.

## Replace the library

Stop remotefs, keep a backup of the original `libnfs.dll`, and copy the rebuilt
DLL next to `remotefs.exe` using the filename `libnfs.dll`. Restart remotefs;
the program loads this separate library without rebuilding the application.
Restore the backup to undo the replacement. Changes to the library are governed
by its upstream licences; the application's MIT licence does not replace them.
''', encoding='utf-8')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--build-recipe', required=True, type=Path)
    args = parser.parse_args()
    print(bundle_libnfs(args.source, args.bundle, args.build_recipe))


if __name__ == '__main__':
    main()

# Releasing remotefs

Ordered checklist for cutting a release. Steps 1-3 are one-time setup; the
rest repeat per version. Commands assume the repo root as the working
directory and `v0.2.0` as the version being released.

## 0. Required release contents

Windows releases include `THIRD_PARTY_NOTICES.md`, a licence inventory and full
licence texts under `licenses/`, and the matching modified libnfs source under
`sources/`. The build must fail if a required licence or source component is
missing. The libnfs source bundle records the pinned revision, actual local
changes and DLL/source hashes, together with the build recipe and DLL replacement
instructions. The MinGW notices come from the compiler selected for the build.

Before publishing, inspect the ZIP and verify the libnfs DLL/source hashes against
`licenses/libnfs/PROVENANCE.json`, that the source includes the dated CMake
modification notice, and that `licenses/smbprotocol/`, Python runtime licensing
and the MinGW runtime exception are present. Keep published versioned assets
immutable: use a new version for packaging corrections and update registry hashes.

## Previous validation

- `packaging/homebrew/remotefs.rb` carries resource blocks and the GitHub release sdist checksum for 0.2.0.
- The winget manifests pass `winget validate` on Windows 11. When copying them from macOS, use `COPYFILE_DISABLE=1 tar ...` or delete the `._*` AppleDouble files first; winget tries to parse every file in the directory.
- The PyInstaller spec produces a working `remotefs.exe` on Windows 11 (about 39 MB unpacked).

## 1. One-time: PyPI and TestPyPI trusted publishers

`release.yml` publishes with OIDC; it does not require a PyPI API token in GitHub.

1. On https://pypi.org/manage/account/publishing/ add a **pending publisher**:
   - PyPI project name: `remote-fs-browser`
   - Owner: `mightymorgs`
   - Repository name: `remote-fs-browser`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. Repeat the same form on https://test.pypi.org/manage/account/publishing/
   (separate account, same values).

## 2. One-time: GitHub environment

In the repo, Settings > Environments > New environment, named `pypi`.
Optionally add yourself as a required reviewer so a tag push pauses for
approval before anything is uploaded.

## 3. One-time: check the workflows

- `.github/workflows/release.yml` runs on `push` of tags matching `v*`. Tags
  containing `rc` go to TestPyPI and are marked as GitHub pre-releases;
  everything else goes to PyPI.
- `.github/workflows/ci.yml` must be green on `main`, including the
  `brew-libnfs` job, before tagging.

## 4. Bump the version

```sh
sed -i '' 's/^version = ".*"/version = "0.2.0"/' pyproject.toml   # macOS sed
git switch -c release/v0.2.0
git commit -am "Bump version to 0.2.0"
git push -u origin release/v0.2.0
```

Open a PR, wait for CI, merge it. Then:

```sh
git switch main && git pull
```

## 5. Rehearse on TestPyPI with a release candidate

```sh
git tag v0.2.0-rc1
git push --tags
```

Watch the **Release** workflow. When it finishes, verify from a clean machine
or venv (TestPyPI does not host the dependencies, hence the extra index):

```sh
pipx install --index-url https://test.pypi.org/simple/ \
  --pip-args="--extra-index-url https://pypi.org/simple" remote-fs-browser
remotefs --version
remotefs serve --help
pipx uninstall remote-fs-browser
```

Download the `remotefs-0.2.0-rc1-windows-x64.zip` asset from the pre-release
and run `remotefs\remotefs.exe --version` on a Windows box if one is handy.

## 6. Tag the real release

```sh
git tag v0.2.0
git push --tags
```

Confirm https://pypi.org/project/remote-fs-browser/0.2.0/ exists and the
GitHub release lists the sdist, wheel and Windows zip.

## 7. Homebrew tap

The tap is published at `mightymorgs/homebrew-tap` with a `Formula/` directory.

```sh
git clone git@github.com:mightymorgs/homebrew-tap.git
cp packaging/homebrew/remotefs.rb homebrew-tap/Formula/remotefs.rb
cd homebrew-tap
```

Use the sdist attached to the GitHub release as the formula URL and checksum.
This lets Homebrew install the release independently of PyPI publication:

```sh
curl -fL -o /tmp/remote_fs_browser-0.2.0.tar.gz \
  https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.0/remote_fs_browser-0.2.0.tar.gz
shasum -a 256 /tmp/remote_fs_browser-0.2.0.tar.gz
# Update url and sha256 in Formula/remotefs.rb for each release.
```

Generate the dependency resource blocks, then build and test:

```sh
brew tap mightymorgs/tap "$PWD"          # or: brew tap mightymorgs/tap once pushed
brew update-python-resources remotefs    # rewrites Formula/remotefs.rb in place
brew install --build-from-source mightymorgs/tap/remotefs
brew test remotefs
brew audit --strict --online remotefs
git commit -am "remotefs 0.2.0" && git push
```

Optional: run it as a background service (uses `HOMEBREW_PREFIX/lib/libnfs.dylib`
and logs to `$(brew --prefix)/var/log/remotefs.log`):

```sh
brew services start remotefs
```

## 8. winget

Get the checksum of the Windows zip attached to the GitHub release:

```sh
curl -sLo /tmp/remotefs-0.2.0-windows-x64.zip \
  https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.0/remotefs-0.2.0-windows-x64.zip
sha256sum /tmp/remotefs-0.2.0-windows-x64.zip          # Linux/macOS (shasum -a 256 on macOS)
```

```powershell
Get-FileHash -Algorithm SHA256 remotefs-0.2.0-windows-x64.zip   # Windows
```

Paste the hash into `InstallerSha256` in
`packaging/winget/manifests/m/mightymorgs/remotefs/0.2.0/mightymorgs.remotefs.installer.yaml`
and remove the TODO comment. Validate and test-install on Windows:

```powershell
winget validate --manifest packaging/winget/manifests/m/mightymorgs/remotefs/0.2.0
winget install --manifest packaging/winget/manifests/m/mightymorgs/remotefs/0.2.0
remotefs --version
```

Submit, either with wingetcreate (prompts for a GitHub token):

```powershell
wingetcreate submit packaging/winget/manifests/m/mightymorgs/remotefs/0.2.0
```

or by forking https://github.com/microsoft/winget-pkgs and opening a PR that
adds the same three files under `manifests/m/mightymorgs/remotefs/0.2.0/`.

A first-time package goes through manual review and typically takes several
days to land; subsequent version bumps are usually merged within a day.

## 9. After the release

- Bump `packaging/homebrew/remotefs.rb` and the winget manifest directory
  when the next version ships; both carry the version number in their URLs.
- Close the milestone and announce.

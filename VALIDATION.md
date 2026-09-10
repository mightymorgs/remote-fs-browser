# Validation and limitations

CI targets Windows x64, Linux x86_64/ARM64, and macOS Intel/Apple Silicon with the same tests and API. It builds the pinned libnfs source on each platform and checks that the binding can load/create/destroy a native context. This verifies client packaging and local behavior; it does not simulate every NAS or exercise privileged service installation on each host.

Local tests cover normalized paths, traversal/symlink refusal, configured roots and networks, session expiry/cleanup, operation authorization, per-principal ownership, credential references, HTTP size/rate limits, NDJSON and file ranges. File reads use bounded chunks.

During development on macOS Apple Silicon, the standalone SDK was also exercised against a real NAS over a private network: SMB share enumeration, NFS export enumeration, both root listings, metadata, and a 4 KiB read of the same file through both protocols passed. The read hashes matched. No NAS addresses, credentials, file contents, or private test fixtures are included in this repository.

Known limits:

- Host discovery is opt-in TCP probing of explicitly permitted ranges with at most 256 candidates probed per page. It is not a network inventory service.
- SMB share enumeration uses SMB2 SRVS RPC with bounded pagination; traversal uses SMB2/3. Some servers disallow enumeration while allowing a manually named share.
- NFS export discovery uses mountd; NFSv4-only servers may require a manual export path. libnfs AUTH_SYS identity follows the service account. Kerberos setup is outside this release.
- NDJSON is emitted after a bounded native listing completes. Very large/slow directories may hit the configured entry or operation limit; truncation is reported.
- Windows directories are browsed through native pathname APIs. File handles are checked after opening, but directory metadata is not a sandbox against concurrent hostile namespace changes. See SECURITY.md.
- SDK worker processes require the usual Python `if __name__ == '__main__'` guard. File streams, metadata and session operations share the same backend context; no per-click CLI subprocess is used.
- The system installers are provided for review and testing. Public CI checks libraries and API behavior, not complete host service installation/uninstallation. macOS may need Apple's command-line-tools/license setup before unattended Homebrew bootstrap can finish.
- This is an initial open-source release, not a signed binary distribution or a blanket compatibility guarantee for all NAS servers and authentication modes.

## Filesystem manager checks

The read/write and password-login changes shipped in 0.2.1. Local tests cover staged writes, replacement conflicts, cancelled and oversized uploads, traversal/link refusal, recursive authorization, copying between owned sessions, and read-only policy enforcement. Password tests cover salted hashes, wrong credentials, HttpOnly/SameSite cookies, same-origin mutation checks, sign-in throttling, logout cleanup, and migration of existing saved credentials.

On macOS Apple Silicon, an isolated Docker Samba server and NFS-Ganesha v4 server (MEM filesystem with data storage enabled) passed binary upload/readback, no-overwrite conflict, explicit replacement, recursive copy, folder move, and recursive delete. The native libnfs write symbols loaded successfully. These are protocol integration checks, not proof for every NAS implementation or ACL model.

The local browser preview passed username/password login, text editing/save, and folder creation. Cross-platform CI exercises the local mutation primitives and password handling; NFS/SMB integration remains an explicit test-server check.

## Cross-host browser dogfood

The [11 September 2026 report](docs/validation/2026-09-11-dogfood.md) records real Mac, Windows and Ubuntu click-through checks, manual SMB/NFS mapping, native Windows Chromium runs, and two verified 100 MiB network multipart downloads. It also records the bugs found, fixes, environment requirements and cleanup.

## Published 0.2.1 artifacts

The [0.2.1 release](https://github.com/mightymorgs/remote-fs-browser/releases/tag/v0.2.1) includes the source distribution, Python wheel and Windows portable ZIP. Main-branch cross-platform CI and the release workflow passed. A clean install from PyPI reported 0.2.1 with no broken dependencies; PyPI distribution hashes matched the GitHub assets. The Windows portable preflight passed native Chromium login, favourites and file/folder operations. Published ZIP licence, DLL and matching-source hashes were verified.

The [WinGet submission](https://github.com/microsoft/winget-pkgs/pull/432620) was updated to 0.2.1. Local manifest validation and download hash verification passed; the SSH-driven installation exited during Windows attachment handling, so a completed WinGet installation on that VM is not claimed. Microsoft review and installer checks are separate from the portable-executable tests.

The Homebrew tap published 0.2.1 and its [clean macOS installation check](https://github.com/mightymorgs/homebrew-tap/actions/runs/34517082227) passed, including `brew test`, version and CLI help checks. This Mac could not run a source installation or strict audit because its Command Line Tools were outdated; the clean runner supplied the installation evidence.

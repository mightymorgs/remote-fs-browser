# Validation and limitations

CI targets Windows x64, Linux x86_64/ARM64, and macOS Intel/Apple Silicon with the same tests and API. It builds the pinned libnfs source on each platform and checks that the binding can load/create/destroy a native context. This verifies client packaging and local behavior; it does not simulate every NAS or exercise privileged service installation on each host.

Local tests cover normalized paths, traversal/symlink refusal, configured roots and networks, session expiry/cleanup, operation authorization, per-principal ownership, credential references, HTTP size/rate limits, NDJSON and file ranges. File reads use bounded chunks.

During development on macOS Apple Silicon, the standalone SDK was also exercised against a real NAS over a private network: SMB share enumeration, NFS export enumeration, both root listings, metadata, and a 4 KiB read of the same file through both protocols passed. The read hashes matched. No NAS addresses, credentials, file contents, or private test fixtures are included in this repository.

Known limits:

- Host discovery is opt-in TCP probing of explicitly permitted ranges of at most 256 addresses each, with at most 1024 candidates probed per request. It is not a network inventory service.
- SMB share enumeration uses SMB2 SRVS RPC with bounded pagination; traversal uses SMB2/3. Some servers disallow enumeration while allowing a manually named share.
- NFS export discovery uses mountd; NFSv4-only servers may require a manual export path. libnfs AUTH_SYS identity follows the service account. Kerberos setup is outside this release.
- NDJSON is emitted after a bounded native listing completes. Very large/slow directories may hit the configured entry or operation limit; truncation is reported.
- Windows directories are browsed through native pathname APIs. File handles are checked after opening, but directory metadata is not a sandbox against concurrent hostile namespace changes. See SECURITY.md.
- SDK worker processes require the usual Python `if __name__ == '__main__'` guard. File streams, metadata and session operations share the same backend context; no per-click CLI subprocess is used.
- The system installers are provided for review and testing. Public CI checks libraries and API behavior, not complete host service installation/uninstallation. macOS may need Apple's command-line-tools/license setup before unattended Homebrew bootstrap can finish.
- This is an initial open-source release, not a signed binary distribution or a blanket compatibility guarantee for all NAS servers and authentication modes.

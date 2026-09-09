# Remote filesystem browser

Discover and browse local folders, SMB shares and NFS exports **from a remote machine's perspective**, using one Python API on Windows, macOS and Linux.

The client needs access to the browser service. It does **not** need direct access to the NAS. No SSH browsing, pre-mounted shares, fstab edits, or OS network mounts are required.

```text
Control plane / browser
        │ authenticated HTTP (VPN or TLS)
        ▼
Remote host — Windows, macOS or Linux
        ├── Local folders: Python filesystem API
        ├── SMB2/3 shares: smbprotocol
        └── NFSv3/v4 exports: libnfs
```

- One SDK and HTTP API across operating systems.
- Session-scoped connections, idle expiry and explicit cleanup.
- Local roots, bounded host discovery, SMB share and NFS export enumeration.
- File metadata, bounded directory listings, NDJSON responses.
- Chunked file streaming with HTTP byte ranges.
- A reusable, dependency-free frontend storage picker.
- Install/uninstall scripts and Ansible playbooks.
- Configurable roots, networks, operations and authentication hooks.

**Initial release:** this is a reference service and embedding SDK, not a hardened multi-tenant filesystem sandbox. See [security boundaries](SECURITY.md) and [validation](VALIDATION.md) before deployment. No secret manager, orchestration system or VPN is required by the library.

## Serve the browser

Install from a checkout with `pip install .` (Python 3.11+), then:

```sh
remote-fs-browser serve --port 8080
```

Open `http://127.0.0.1:8080/` and enter the temporary token printed in the terminal. The default exposes only the current directory, read-only, on loopback. No config file is needed.

To access it from another computer:

```sh
remote-fs-browser serve --bind 0.0.0.0 --port 8080 --root /srv/media
# Or listen only on a particular interface:
remote-fs-browser serve --bind 100.82.14.7 --port 8080
```

Open the network URL printed at startup. Detected addresses in the shared 100.64.0.0/10 range are labelled Tailscale/CGNAT; this does not require or verify Tailscale. Interface addresses are candidates, not a guarantee that your firewall permits access. Plain HTTP needs a trusted network or encrypted tunnel.

The UI and API share one port and origin, with no separate frontend deployment or CORS setup. Sign-in exchanges the token for an HttpOnly, SameSite browser cookie lasting eight hours. Downloads stream directly through the browser download manager, including HTTP Range support; tokens are never put in download URLs. Sign out revokes the browser cookie.

- `/?mode=browse` (default): navigate folders and download files.
- `/?mode=select`: choose a directory and copy its credential-free descriptor.
- `/api/discover`, `/api/sessions`, `/api/sessions/{id}/list`, `/api/sessions/{id}/file`: API endpoints. The original unprefixed SDK routes remain supported.

Repeat `--root` to expose multiple folders. SMB/NFS connections and host scans require explicit permitted networks:

```sh
remote-fs-browser serve --root /srv/media --allow-network 192.168.1.0/24
```

NFS requires **libnfs 6+ / API V2**; the platform installers handle it. Local and SMB browsing work without loading libnfs. No shares are mounted into the host OS.

For persistent service settings, copy `examples/config.example.json` to a private config, set your roots, permitted networks and a random token of at least 32 characters, then run:

```sh
remote-fs-browser serve --config config.json
```

Explicit CLI options override config values. Existing `remote-fs-browser --config config.json` installations still work. The example uses port 8765. No firewall rule is opened automatically, and authentication is always required.

## Python SDK

```python
import asyncio
from remote_fs_browser import Browser, Policy

async def example():
    policy = Policy(local_roots=['/srv/media'])
    async with Browser(policy) as browser:
        async with await browser.connect({'type': 'local', 'root': '/srv/media'}) as fs:
            print(await fs.list('/'))
            print(await fs.stat('/example.mp4'))
            async for chunk in fs.stream('/example.mp4', offset=1024, length=4096):
                consume(chunk)
            selected = fs.descriptor('/Projects')

# Worker processes require the normal multiprocessing main guard on every OS.
if __name__ == '__main__':
    asyncio.run(example())
```

`list`, `stat`, `stream`, `descriptor` and `close` have identical interfaces for all backends. Paths inside a session always use `/`, including on Windows. A local connection's `root` remains a native host path such as `C:/Media`. Entries contain `name`, normalized `path`, `type`, `size`, and UTC `modified` time.

Connect to SMB with `{'type':'smb','host':'nas.example','share':'Projects'}` and a separate `credentials={'username':..., 'password':...}` argument. NFS uses `{'type':'nfs','host':'nas.example','export':'/exports/media','version':4}`. Set the permitted network ranges first.

The worker is created when connecting to a selected location, not merely when opening the picker. It keeps the protocol connection through subsequent navigation and file reads. `close()` terminates it; abandoned workers exit after the configured idle period (300 seconds by default). Each filesystem operation has a hard deadline (10 seconds by default), so a stuck native call cannot block another session. The reference HTTP service also reaps expired session records.

## HTTP API

All data endpoints require `Authorization: Bearer <token>` by default. The demo assets alone are public.

| Method / route | Purpose |
|---|---|
| `GET /discover?scan=false` | Allowed local roots; `scan=true` also probes permitted narrow ranges |
| `POST /discover` | Enumerate shares/exports: `{type, host, credentials?}` |
| `POST /sessions` | Connect: `{descriptor, credentials?}` |
| `GET /sessions/{id}/list?path=/` | Entries plus `truncated` flag |
| `GET /sessions/{id}/list?path=/&ndjson=true` | NDJSON response, with `X-Listing-Truncated` header |
| `GET /sessions/{id}/stat?path=/file` | Normalized metadata |
| `GET /sessions/{id}/file?path=/file` | Stream bytes; supports a single `Range: bytes=...` header |
| `GET /sessions/{id}/descriptor?path=/folder` | Validated durable directory descriptor |
| `DELETE /sessions/{id}` | Close immediately |

File responses use bounded 256 KiB reads. Range requests support explicit, open-ended and suffix ranges; invalid/multiple ranges return 416. Files are served as attachments with `nosniff`. A client disconnect releases its active file handle; the browsing session remains for the configured idle grace period so it can reconnect after a brief interruption. An explicit DELETE closes it immediately.

Directory listings are bounded by `max_entries`; NDJSON streams the bounded result to the client. The initial implementation does not lazily page a native directory across HTTP requests. It reports truncation rather than silently claiming a full listing. It never recursively indexes a share.

## Credentials and descriptors

Raw credentials are separate from descriptors and are not persisted by this package. A descriptor can hold `credential_id`; the embedding application owns its meaning and storage.

```json
{"type":"smb","host":"nas.example","share":"Projects","path":"/Campaigns","credential_id":"media-reader"}
```

The SDK accepts `Browser(policy, credential_resolver=lambda reference: ...)`. The reference service accepts `create_app(policy, token=..., credential_resolver=lambda principal, reference: ...)`; check ownership of the reference before returning credentials. No resolver is configured by the CLI by default. A local descriptor contains `type`, native `root`, and a session-relative `path`; NFS retains `host`, `export`, `version` and `path`.

To customize authentication, pass `authenticate(request) -> principal` and optionally `authorize(principal, operation, descriptor) -> bool` to `create_app`. Hooks can be async. The default bearer token represents one principal; use per-user hooks for separate users. Sessions cannot be read by a different principal. The service never logs credentials or request bodies; access logging is disabled by its CLI.

## Frontend

Use `frontend/browser.js` directly or the packaged `/browser.js` asset. It defines `<remote-fs-browser>` and exports `RemoteFsClient`. No React, Vue or build system is required.

```javascript
import { RemoteFsClient } from './browser.js'
const picker = document.querySelector('remote-fs-browser')
picker.client = new RemoteFsClient('/storage-api', () => ({ Authorization: `Bearer ${token}` }))
picker.addEventListener('path-selected', event => saveDescriptor(event.detail))
// Optional: the embedding app saves credentials and returns an opaque reference.
// picker.storeCredentials = async credentials => mySecretStore.save(credentials)
```

The picker supports discovery, manual locations, credential entry, nested folders, metadata, loading/errors, expiry reconnect and final directory selection. It closes its session on selection, disconnect or element removal. Keep the service on the same origin or explicitly configure a restrictive CORS policy when embedding across origins. The JS client's `file()` returns a Fetch `Response`; consume its `body` as a stream rather than calling `blob()` for large files.

## Installation and removal

From a checkout on a self-hosted runner or target host:

- Linux: `sudo scripts/linux/install.sh /path/to/private-config.json`
- macOS: `sudo scripts/macos/install.sh /path/to/private-config.json`
- Windows, elevated PowerShell: `scripts/windows/install.ps1 -Config C:\path\private-config.json`

The Unix dispatcher `scripts/install.sh` detects Linux/macOS. Linux installs Python/build dependencies and builds a pinned libnfs. macOS installs Python/libnfs with Homebrew, bootstrapping Homebrew if absent (Apple's command-line tools and their license prerequisites may still need the usual host setup). Windows installs Chocolatey/Python/build tools and builds the same libnfs revision as a DLL. Python code runs in a private environment. Services use systemd, launchd or a Windows startup task.

For Ansible, use `playbooks/<platform>/install.yml` with the `filesystem_hosts` group, `remote_fs_source` (destination checkout directory), and `remote_fs_config` (private config path already supplied to the host by your provisioning system). macOS also needs `remote_fs_brew_user`. Windows requires `ansible.windows`. The playbooks copy only public source files; secrets never come from this repository.

Matching uninstall scripts/playbooks stop and remove the service. Configurations/dependencies are preserved by default; use `--purge` on Unix or `-Purge` on Windows to remove the private installation directory. Never store credentials or actual host configurations in Git.

## Discovery limits

Discovery probes TCP 445/2049 only in explicitly permitted ranges of at most 256 addresses, with a total request cap of 256 candidates. This is portable and requires no SMB1 browser service. Manual hostnames work when discovery cannot cross subnets/VPNs. SMB authentication in this release uses NTLM (including domain-qualified usernames). SMB enumeration uses Impacket's SRVS RPC over SMB2; traversal/streaming uses smbprotocol's SMB2/3 session. NFS export enumeration uses mountd and may return no exports on NFSv4-only servers; enter the export manually in that case. NFS uses AUTH_SYS UID/GID behavior from libnfs/the service account; NFS Kerberos is not configured by this release.

This project is a path picker and read-only browser. It does not provision mounts, manage backups, sync files, or abstract cloud object storage.

## Development

```sh
pip install -e '.[test]'
pytest
python -m build
```

MIT licensed. Protocol implementations are dependencies, not copied sources: [smbprotocol](https://github.com/jborean93/smbprotocol), [Impacket](https://github.com/fortra/impacket), and [libnfs](https://github.com/sahlberg/libnfs). Libnfs has its own LGPL licensing; installers fetch/build it separately. Preserve its license obligations if distributing a bundled native library.

# Remote filesystem browser

**Browse local, SMB and NFS storage over HTTP from another machine.**

Install it on any machine inside a network, then browse the storage that machine can see from anywhere you can reach its HTTP port. A Mac mini, a workstation, a server or a homelab node becomes a small read-only storage window: it shows its own disks and mounted volumes, and the SMB shares and NFS exports it can reach, without mounting anything, syncing anything or giving the viewer direct access to the NAS.

```text
This Computer
├── Home
├── Mounted volumes
└── Attached storage

SMB
├── NAS
├── Windows shares
└── Other SMB servers

NFS
├── NAS exports
└── Server exports
```

"The whole network" means what that host can reach and what its policy and credentials permit. That is the useful bit: the browser works from the network perspective of the machine you installed it on.

![The picker after signing in](docs/picker.png)

## Quick start

Choose an installation method below, then run `remotefs serve`.

### Homebrew (macOS)

The Homebrew package is pending publication: the formula in this repository still needs its release checksum and publication to the tap. Once published, install with [Homebrew](https://brew.sh/):

```sh
brew tap mightymorgs/tap
brew install mightymorgs/tap/remotefs
remotefs serve
```

The formula installs Python and libnfs as dependencies. To run it in the background instead of keeping a terminal open:

```sh
brew services start remotefs
remotefs --print-token
```

Use `brew services stop remotefs` to stop it. To update, run `brew update` followed by `brew upgrade mightymorgs/tap/remotefs`. See the [Homebrew tap documentation](https://docs.brew.sh/Taps) for how third-party packages are installed.

### WinGet (Windows x64)

The WinGet package is pending publication: its manifest still needs the release ZIP checksum and acceptance into the WinGet community repository. Once published, run in PowerShell with [WinGet installed](https://learn.microsoft.com/en-us/windows/package-manager/winget/):

```powershell
winget install --id mightymorgs.remotefs --exact --source winget
remotefs serve
```

The package uses a portable Windows executable, so a separate Python installation is not required. If `remotefs` is not found after installation, open a new terminal. To update:

```powershell
winget upgrade --id mightymorgs.remotefs --exact --source winget
```

See [WinGet install options](https://learn.microsoft.com/en-us/windows/package-manager/winget/install) for the command syntax. Maintainers can find the publication steps for both packages in [Releasing remotefs](packaging/RELEASING.md).

### Python (Windows, macOS or Linux)

Requires Python 3.11+ and pipx. For a published PyPI release:

```sh
pipx install remote-fs-browser
remotefs serve
```

Before the packages are published, install directly from a checkout of this repository:

```sh
pipx install .
remotefs serve
```

### Open the browser

Open `http://127.0.0.1:8080/` and sign in with the token printed in the terminal. The first run creates `~/.config/remotefs/config.json` (`%APPDATA%\remotefs\config.json` on Windows) with a random token, readable only by you, and every later run reuses it. `remotefs --print-token` shows it again.

With no configuration the service exposes, read-only, on loopback only:

- **This Computer**: your home directory and mounted volumes (`/Volumes` on macOS, drive letters on Windows, mounts under `/mnt`, `/media`, `/run/media`, `/srv`, `/data` and `/home` on Linux).
- **SMB and NFS**: servers in the private subnets of the host's physical interfaces (container, VM and tunnel interfaces are ignored), each narrowed to a /24. Press **Scan network** to probe them, or add a server by name.

To reach it from another computer, bind to an interface on purpose:

```sh
remotefs serve --bind 0.0.0.0 --port 8080
# Or one interface only, for example a Tailscale address:
remotefs serve --bind 100.82.14.7
```

The startup banner lists the URLs, warns that the service is reachable from the network, and reminds you that plain HTTP needs a trusted network or an encrypted tunnel. No firewall rule is opened automatically. Authentication is always required.

Narrow or widen what is visible with flags, which replace the defaults rather than adding to them:

```sh
remotefs serve --root /srv/media --root /mnt/backup --allow-network 192.168.1.0/24
remotefs serve --no-defaults --config /etc/remotefs/config.json   # expose only what the config names
```

NFS needs libnfs 6 or newer (included as a Homebrew dependency; for Python installs, use `brew install libnfs` or the platform installers below). Local and SMB browsing work without it. On Windows, listing the shares a server offers needs the optional `remote-fs-browser[smb-enum]` extra, which Windows Defender quarantines during install unless the Python environment is excluded; without it, type the share name and browsing works as usual.

## Shortlist

**Save folder to shortlist** pins the folder you are viewing, on a local root, an SMB share or an NFS export. Signing in later with the same token shows it under **Shortlist**, and one click reopens it; folders on the same SMB share reuse the credentials you gave when you first saved one. The shortlist lives in `saved.json` beside the config, readable only by you and encrypted under the service token; a different token cannot open it. **Forget** removes one entry, deleting the file removes them all. See [security boundaries](SECURITY.md).

## The browser

The UI and API share one port and origin. Sign-in is its own screen: it exchanges the token for an HttpOnly, SameSite browser cookie lasting eight hours, and **Sign out** revokes it. The picker shows the host's roots and mapped network locations in a sidebar, the folder listing beside it, and collapses to a sources sheet on phones. Downloads stream through the browser's download manager with HTTP Range support, and tokens never appear in download URLs.

- `/?mode=browse` (default): navigate folders and download files.
- `/?mode=select`: choose a directory and copy its credential-free descriptor, for use by other automation.

## System service installs

For an always-on service run as root or SYSTEM, from a checkout on the target host:

- Linux: `sudo scripts/linux/install.sh /path/to/private-config.json`
- macOS: `sudo scripts/macos/install.sh /path/to/private-config.json`
- Windows, elevated PowerShell: `scripts/windows/install.ps1 -Config C:\path\private-config.json`

These install into a private prefix, build the pinned libnfs (macOS uses Homebrew's), and register a systemd unit, launchd daemon or Windows startup task running `remotefs serve --no-defaults --config …`, so only the roots and networks in the private config are exposed. Start from `examples/config.example.json`: set `local_roots`, `network_ranges` and a random token of at least 32 characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), and keep the file private. An empty list denies that class of access.

For Ansible, use `playbooks/<platform>/install.yml` with the `filesystem_hosts` group, `remote_fs_source` (destination checkout directory) and `remote_fs_config` (private config path already on the host). macOS also needs `remote_fs_brew_user`; Windows needs `ansible.windows`. The playbooks copy only public source files. Matching uninstall scripts and playbooks stop and remove the service; `--purge` on Unix or `-Purge` on Windows also removes the private installation directory. Never store credentials or real host configurations in Git.

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

`list`, `stat`, `stream`, `descriptor` and `close` have identical interfaces for all backends. Paths inside a session always use `/`, including on Windows. A local connection's `root` remains a native host path such as `C:/Media`. Entries contain `name`, normalized `path`, `type`, `size`, and UTC `modified` time. Listings report `truncated` when the entry limit was hit and `skipped` for names that cannot be addressed safely (for example a colon or backslash in a filename); nothing aborts the listing.

Connect to SMB with `{'type':'smb','host':'nas.example','share':'Projects'}` and a separate `credentials={'username':..., 'password':...}` argument. NFS uses `{'type':'nfs','host':'nas.example','export':'/exports/media','version':4}`. Set the permitted network ranges first.

The worker is created when connecting to a selected location, not merely when opening the picker. It keeps the protocol connection through subsequent navigation and file reads. `close()` terminates it; abandoned workers exit after the configured idle period (300 seconds by default). Each filesystem operation has a hard deadline (10 seconds by default), so a stuck native call cannot block another session. The reference HTTP service also reaps expired session records.

## HTTP API

All data endpoints require `Authorization: Bearer <token>` or the browser cookie. The page assets alone are public. Routes are served under `/api/`; the unprefixed forms remain for existing SDK clients.

| Method / route | Purpose |
|---|---|
| `POST /api/login`, `DELETE /api/login` | Exchange the token for a browser cookie; revoke it |
| `GET /api/discover?scan=false` | Allowed roots and the `groups` tree; `scan=true` also probes permitted ranges |
| `POST /api/discover` | Enumerate shares/exports: `{type, host, credentials?}` |
| `GET /api/saved`, `POST /api/saved`, `DELETE /api/saved/{id}` | Remembered locations for the signed-in principal |
| `POST /api/sessions` | Connect: `{descriptor, credentials?}`; `descriptor.credential_id` reuses saved credentials |
| `GET /api/sessions/{id}/list?path=/` | Entries plus `truncated` and `skipped` |
| `GET /api/sessions/{id}/list?path=/&ndjson=true` | NDJSON response, with `X-Listing-Truncated` and `X-Listing-Skipped` headers |
| `GET /api/sessions/{id}/stat?path=/file` | Normalized metadata |
| `GET /api/sessions/{id}/file?path=/file` | Stream bytes; supports a single `Range: bytes=...` header |
| `GET /api/sessions/{id}/descriptor?path=/folder` | Validated durable directory descriptor |
| `DELETE /api/sessions/{id}` | Close immediately |

File responses use bounded 256 KiB reads. Range requests support explicit, open-ended and suffix ranges; invalid/multiple ranges return 416. Files are served as attachments with `nosniff`. A client disconnect releases its active file handle; the browsing session remains for the configured idle grace period so it can reconnect after a brief interruption. An explicit DELETE closes it immediately.

Directory listings are bounded by `max_entries`; NDJSON streams the bounded result to the client. The service does not lazily page a native directory across HTTP requests. It reports truncation rather than silently claiming a full listing. It never recursively indexes a share.

## Credentials and descriptors

Descriptors never contain credentials. A descriptor can hold `credential_id`; `remotefs serve` resolves it from the remembered locations of the signed-in principal, and an embedding application can supply its own resolver instead.

```json
{"type":"smb","host":"nas.example","share":"Projects","path":"/Campaigns","credential_id":"media-reader"}
```

The SDK accepts `Browser(policy, credential_resolver=lambda reference: ...)`. The reference service accepts `create_app(policy, token=..., credential_resolver=lambda principal, reference: ...)` or `saved_locations=SavedLocations(path, token)`; a resolver must check that the principal owns the reference before returning credentials. The SDK and `create_app` persist nothing on their own. A local descriptor contains `type`, native `root`, and a session-relative `path`; NFS retains `host`, `export`, `version` and `path`.

To customize authentication, pass `authenticate(request) -> principal` and optionally `authorize(principal, operation, descriptor) -> bool` to `create_app`. Hooks can be async. The default bearer token represents one principal; use per-user hooks for separate users. Sessions and saved locations cannot be read by a different principal. The service never logs credentials or request bodies; access logging is disabled by its CLI.

## Frontend

Use `frontend/browser.js` directly or the packaged `/browser.js` asset. It defines `<remote-fs-browser>` and exports `RemoteFsClient`. No React, Vue or build system is required.

```javascript
import { RemoteFsClient } from './browser.js'
const picker = document.querySelector('remote-fs-browser')
picker.client = new RemoteFsClient('/storage-api', () => ({ Authorization: `Bearer ${token}` }))
picker.addEventListener('path-selected', event => saveDescriptor(event.detail))
// Optional: the embedding app saves credentials itself and returns an opaque reference.
// picker.storeCredentials = async credentials => mySecretStore.save(credentials)
```

The element fills the box it is given. It renders the shortlist and the host's roots in a sidebar, network devices from an explicit scan, per-host share and export lists, credential entry, nested folders with formatted sizes and dates, in-place errors with retry, expiry reconnect, downloads in browse mode and a live descriptor preview with a Select button in select mode. The `signout` attribute adds a Sign out button that fires a `sign-out` event for the host page to act on. When the service offers `/api/saved` and no `storeCredentials` hook is set, "Save folder to shortlist" stores the current folder there. It closes its session on selection, disconnect or element removal. Keep the service on the same origin or configure a restrictive CORS policy when embedding across origins. The JS client's `file()` returns a Fetch `Response`; consume its `body` as a stream rather than calling `blob()` for large files.

## Discovery limits

Scan results show the DNS hostname, NetBIOS device name and IP address together whenever the names are available. DNS and NetBIOS are queried independently; devices without either name still show their IP address. Named devices retain a label in the Network sidebar, and connections use the scanned IP address. Both name lookups have deadlines so unavailable name services do not hold up the scan indefinitely.

Discovery probes TCP 445/2049 only in explicitly permitted ranges of at most 256 addresses each, and scans at most 1024 candidates per request, reporting when more were permitted. This is portable and requires no SMB1 browser service. Manual hostnames work when discovery cannot cross subnets or VPNs. SMB authentication uses NTLM (including domain-qualified usernames). SMB enumeration uses Impacket's SRVS RPC over SMB2; traversal and streaming use smbprotocol's SMB2/3 session. NFS export enumeration uses mountd and may return no exports on NFSv4-only servers; enter the export manually in that case. NFS uses AUTH_SYS UID/GID behaviour from libnfs and the service account; NFS Kerberos is not configured.

This project is a path picker and read-only browser. It does not provision mounts, manage backups, sync files, or abstract cloud object storage. It is a reference service and embedding SDK, not a hardened multi-tenant filesystem sandbox: see [security boundaries](SECURITY.md) and [validation](VALIDATION.md) before exposing it beyond a trusted network.

## Development

```sh
pip install -e '.[test]'
pytest
python -m build
```

Releases are built by `.github/workflows/release.yml`; `packaging/RELEASING.md` describes publishing to PyPI, the Homebrew tap and winget.

MIT licensed. Protocol implementations are dependencies, not copied sources: [smbprotocol](https://github.com/jborean93/smbprotocol), [Impacket](https://github.com/fortra/impacket), and [libnfs](https://github.com/sahlberg/libnfs). Libnfs has its own LGPL licensing; installers fetch or build it separately. Preserve its license obligations if distributing a bundled native library.

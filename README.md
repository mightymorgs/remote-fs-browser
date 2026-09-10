# Remote filesystem browser

**Manage local folders, SMB shares and NFS exports through one browser and HTTP API.**

Run remotefs on a workstation, server or homelab node to access the storage that machine can reach. Its home directory, mounted volumes and permitted network servers appear in one interface. The viewing computer needs only access to the service’s HTTP port; SMB and NFS connections run from the service host.

Version 0.2.1 introduces password login, file write operations and staged multipart downloads. The [cross-host dogfood report](docs/validation/2026-09-11-dogfood.md) records the completed browser workflows and network download checks. See [validation](VALIDATION.md) for scope and limitations.

## What is included

- Local, SMB and NFS browsing, metadata, uploads, downloads, new files/folders, text editing, copy, move, rename and recursive deletion, subject to policy and filesystem permissions.
- CIDR scanning with DNS names, NetBIOS names and IP addresses shown together; manual connections, mapped hosts, encrypted saved SMB credentials and folder shortlists.
- A responsive manager with filtering, sorting, breadcrumbs, checkbox/range selection, context menus and keyboard shortcuts.
- Direct file downloads or host-staged ZIP64 archives, optional byte splitting, HTTP Range support, packing pause/resume and explicit purge.
- A Python SDK, authenticated HTTP API and embeddable directory picker with credential-free descriptors.

## Quick start

Follow the [step-by-step quickstart](QUICKSTART.md) for first login, NAS connections, file operations and multipart downloads.

To install from a source checkout, use `pipx install .` (or `pip install -e .` in a virtual environment).

### Homebrew (macOS)

Install from the [Homebrew tap](https://github.com/mightymorgs/homebrew-tap) with [Homebrew](https://brew.sh/):

```sh
brew tap mightymorgs/tap
brew install mightymorgs/tap/remotefs
remotefs serve
```

The formula installs Python and libnfs as dependencies. To run a published release in the background:

```sh
remotefs account --username YOUR_NAME  # set up the account before starting the service
brew services start remotefs
```

Use `brew services stop remotefs` to stop it. To update, run `brew update` followed by `brew upgrade mightymorgs/tap/remotefs`. See the [Homebrew tap documentation](https://docs.brew.sh/Taps) for how third-party packages are installed.

### WinGet (Windows x64)

The WinGet package has been [submitted for review](https://github.com/microsoft/winget-pkgs/pull/432620) and is awaiting acceptance into the community repository. Once accepted, run in PowerShell with [WinGet installed](https://learn.microsoft.com/en-us/windows/package-manager/winget/):

```powershell
winget install --id mightymorgs.remotefs --exact --source winget
remotefs serve
```

Until WinGet accepts the package, download the [Windows x64 ZIP](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.1/remotefs-0.2.1-windows-x64.zip), extract it, and run `remotefs\remotefs.exe serve` from PowerShell. The portable executable includes libnfs and does not require a separate Python installation. If `remotefs` is not found after installation, open a new terminal. To update:

```powershell
winget upgrade --id mightymorgs.remotefs --exact --source winget
```

See [WinGet install options](https://learn.microsoft.com/en-us/windows/package-manager/winget/install) for the command syntax. Maintainers can find the publication steps for both packages in [Releasing remotefs](packaging/RELEASING.md).

### Python (Windows, macOS or Linux)

Requires Python 3.11+ and pipx. Install from [PyPI](https://pypi.org/project/remote-fs-browser/):

```sh
pipx install remote-fs-browser
remotefs serve
```

You can also install directly from a checkout of this repository:

```sh
pipx install .
remotefs serve
```

## Account and service configuration

On first interactive launch, choose a username and password (at least 12 characters), then open `http://127.0.0.1:8080/`. The private config stores a salted scrypt password hash, not your password.

Set up or reset the account separately with `remotefs account --username YOUR_NAME`; restart the service after changing it. For automation, `--password-stdin` reads the password from standard input without putting it in command-line arguments. A non-interactive service refuses to start until an account exists. Set up the account before starting a background service; restart an already-running service after setup. The config is `~/.config/remotefs/config.json` (`%APPDATA%\remotefs\config.json` on Windows).

Existing token-based configs are migrated during account setup. The old token becomes an internal storage key so saved NAS credentials remain readable; it no longer authenticates the standalone service. Password changes preserve that key. Back up the private config and `saved.json` together.

The standalone service defaults to read/write access on loopback only. Use `--read-only` to disable mutations, or set an explicit `policy.operations` list. Its default locations are:

- **This Computer**: your home directory and mounted volumes (`/Volumes` on macOS, drive letters on Windows, mounts under `/mnt`, `/media`, `/run/media`, `/srv`, `/data` and `/home` on Linux).
- **SMB and NFS**: servers in the private subnets of the host's physical interfaces (container, VM and tunnel interfaces are ignored), each covering at most a /24. Press **Scan network** to probe them, or add a server by name.

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

NFS needs libnfs 6 or newer (included as a Homebrew dependency; for Python installs, use `brew install libnfs` or the platform installers below). Local and SMB browsing work without it. On Windows Python installations, listing the shares a server offers needs the optional `remote-fs-browser[smb-enum]` extra. Without it, enter a share name directly. See [validation and limitations](VALIDATION.md) for protocol and platform coverage.

## Using the manager

Open `/` or `/?mode=browse` for the manager. `/?mode=select` uses the embeddable picker to select a directory and copy its descriptor. The UI and API share one port and origin.

The manager has a collapsible sidebar for local roots, mapped hosts and shortlists, plus separate Scan, Add location and Downloads panels. Click a folder row or breadcrumb to navigate; click a file row for a small UTF-8 preview. Filter matches names in the current listing, not recursively across storage. Click the name, size or modified-date heading to sort; folders remain first.

Use the checkboxes to select items. Shift-click a checkbox to add a range, or clear the range when its endpoint is already selected. Ctrl/Cmd-click toggles individual checks. Select all applies to the visible, filtered rows. Right-click an item or use its **…** menu for open/preview, download, ZIP, copy/cut/paste, rename, shortlist, delete or metadata. Right-click empty space for actions on the current folder. Available actions depend on policy.

### File operations

Use **Copy**, navigate to another folder, share, export or local root, then **Paste**. Copies and rename/move destinations do not overwrite existing entries. **Cut** followed by **Paste** moves within a session using rename; across sessions it copies each item successfully before deleting its source. A failure can leave both copies or partial results. Refresh both locations before retrying.

**Upload files here** accepts multiple files and uploads them sequentially, with byte progress and cancellation. Replacing a same-named file requires confirmation. The default limit is 10 GiB per uploaded file (`policy.max_write_bytes`). There is no directory-upload or resumable-upload interface.

**New text file** creates an empty file and opens the editor. Preview reads at most 1 MiB, accepts UTF-8 text and rejects NUL-containing/binary content. Save requires `write`; saving replaces the file explicitly and remains subject to the upload limit. The 1 MiB limit applies to opening the preview, not a separate server-side text-edit limit. There is no editing lock or conflict detection; the last explicit save wins.

**Delete** asks for confirmation and permanently deletes selected files and folder contents; there is no recycle bin or undo. Filesystem permissions and server ACLs still apply to every operation.

### Keyboard shortcuts

These shortcuts apply outside text fields and open editor/dialog controls. Use Cmd on macOS or Ctrl on Windows/Linux.

| Shortcut | Action |
|---|---|
| Cmd/Ctrl + D | Toggle Downloads |
| Cmd/Ctrl + S | Toggle Scan network |
| Cmd/Ctrl + N | Toggle Add location |
| Cmd/Ctrl + Shift + N | New folder |
| Cmd/Ctrl + A | Select visible items |
| Cmd/Ctrl + C / X / V | Copy / cut / paste |
| Cmd/Ctrl + Backspace | Delete selection, with confirmation |
| Cmd/Ctrl + Shift + Q | Open sign-out confirmation |
| Cmd/Ctrl + / | Show shortcuts |
| Escape | Close manager panels or clear selection |

### Scan, map and remember locations

**Scan network** accepts one to sixteen comma- or whitespace-separated CIDRs within the configured policy. It probes TCP 445 and 2049 in pages of at most 256 candidate addresses and continues through the pages. **Stop** stops requesting further pages; an in-flight bounded probe may finish on the server.

Each result shows its DNS hostname, NetBIOS name and IP address together when available. DNS and NetBIOS lookups are independent and have deadlines; unnamed devices still show their IP. A device offering both protocols appears for both. Scanned connections use the IP address, while mapped hosts retain an available name as their label.

**Map** lists a host’s shares or exports in the sidebar. SMB accepts username, password and optional domain; you can reconnect as another user or save host credentials for reuse. NFS offers version 3 or 4 and an explicit export path. **Add location** also accepts a permitted local path, an SMB host/share or an NFS host/export directly. Manual hostnames help when a scan cannot cross subnets or VPNs. If enumeration returns no locations, enter the known share/export manually.

Mapping is an application connection, not an operating-system mount. **Unmount** disconnects mapped sessions and removes the sidebar mapping. Mappings and unsaved credentials are page-local; they do not survive refresh. Saved credentials and shortlists persist separately.

Use a folder’s star or **Shortlist folder** to save it with its connection details. **Forget** removes the shortlist entry. Saved SMB host credentials can be forgotten separately from a mapping; removing a mapping does not delete them. Credential references are bound to the signed-in principal and the normalized hostname/IP originally entered, so a DNS alias and its IP do not automatically share a host credential reference.

Shortlists and saved SMB credentials are encrypted in `saved.json` beside the private config using its separate `storage_key`. Changing the login password preserves that key. Back up both files together; anyone with both can recover the stored credentials. The default store allows 200 folder entries and 200 host credentials per principal. See [security boundaries](SECURITY.md).

## Downloads and staged ZIPs

Select only files and choose **Download** to queue direct links, or use a file’s download arrow. A selection containing folders opens the ZIP dialog. **Download as multi-part zip…** can also pack any file selection, including one large file. Direct links stream from the original storage without making a staging copy.

ZIPs are built on the service host using ZIP64 with stored, uncompressed entries. Before starting, the server walks and authorizes the selection and estimates space for the payload plus ZIP headers and at least about 2% headroom. Reservations account for other jobs on the same staging filesystem. Packing does not take a filesystem snapshot: detected source size changes fail the job, and same-size content changes are not detected.

Choose a single ZIP, 1/2/4 GiB parts, or a custom part size (the UI labels binary sizes as MB/GB). Split parts must be at least 1 MiB; a job may have at most 999 parts. These are byte slices of **one archive**, named `.zip.001`, `.zip.002`, and so on. Concatenate every part in numeric order before opening the ZIP, or use an archiver that joins split files. Individual parts are not independent ZIP archives.

The Downloads panel shows packing progress, speed, staged bytes, storage capacity and ready-part links. Full parts may be fetched while later parts are still packing. **Pause/resume** controls packing in the running service; it does not pause a browser transfer. Ready parts and direct file links support a single HTTP byte range for clients that resume downloads. Open links individually and use the browser’s download manager to track transfer completion. **Handed to browser** records a request, not proof that the file was saved; requesting an already-handed-off part prompts before repeating it.

Packing continues when its panel is closed. Completed archives and their job records survive service restart. Interrupted or paused packing is marked failed after a restart and must be purged and started again. Failed archives are not presented as complete. Direct-file queues live only in the current page and disappear on refresh.

Staged files remain until **Purge**, which cancels active packing, warns about parts not yet requested, removes staged copies and reports freed bytes. Purge can interrupt active transfers. **Clear purged** removes their remaining job records. There is no automatic expiry; each principal can have at most 32 unpurged jobs.

### Configure staging storage

The standalone service defaults to `staging` beside its configuration file. To offer other directories, add `staging_stores` at the top level of the JSON config, then restart:

```json
{
  "staging_stores": {
    "Downloads": "/srv/remotefs-staging",
    "Scratch disk": "/mnt/scratch/remotefs-staging"
  }
}
```

Use dedicated directories writable by the service account. These are administrator-selected host paths, not arbitrary paths submitted by a browser; this feature does not create mounts. An empty map disables packing while direct file downloads remain available. An embedding application opts in with `create_app(..., staging_stores={"Downloads": "/path/to/staging"})`.

## System service installs

For an always-on service run as root or SYSTEM, from a checkout on the target host:

- Linux: `sudo scripts/linux/install.sh /path/to/private-config.json`
- macOS: `sudo scripts/macos/install.sh /path/to/private-config.json`
- Windows, elevated PowerShell: `scripts/windows/install.ps1 -Config C:\path\private-config.json`

These install into a private prefix, build the pinned libnfs (macOS uses Homebrew's), and register a systemd unit, launchd daemon or Windows startup task running `remotefs serve --no-defaults --config …`, so only the roots and networks in the private config are exposed. Start from `examples/config.example.json`: set `local_roots`, `network_ranges` and `operations`, then run `remotefs account --config /path/to/private-config.json --username YOUR_NAME` before installing the service. Keep the file private. An empty list denies that class of access.

For Ansible, use `playbooks/<platform>/install.yml` with the `filesystem_hosts` group, `remote_fs_source` (destination checkout directory) and `remote_fs_config` (private config path already on the host). macOS also needs `remote_fs_brew_user`; Windows needs `ansible.windows`. The playbooks copy only public source files. Matching uninstall scripts and playbooks stop and remove the service; `--purge` on Unix or `-Purge` on Windows also removes the private installation directory. Never store credentials or real host configurations in Git.

## Terminal file manager

Client commands are available from the current source checkout; the published 0.2.1 CLI has only `serve` and `account`. Install the checkout with `pipx install .` to use them before the next release.

The CLI can use the same running service as the web UI. Commands share its roots,
network policy, saved locations, encrypted credentials and download jobs. `serve`
and `account` still work as before; client commands do not start another server.

```bash
export REMOTEFS_URL=http://127.0.0.1:8080
remotefs login --username morgs        # prompts for the server password
remotefs discover                    # roots and server-side network ranges
remotefs scan                        # first page of the server's default ranges
remotefs scan --ranges '192.168.1.0/24,10.10.0.0/24,10.20.0.5' --all
remotefs shares nas.example --type smb --username morgs
remotefs connect --type smb --host nas.example --share Media --username morgs
```

`connect` returns a session `id`. Use it in subsequent commands; paths are relative
to that connection's root. Sessions expire after the server's configured idle
timeout, or immediately with `disconnect`.

```bash
remotefs ls SESSION_ID /
remotefs mkdir SESSION_ID /Movies
remotefs select SESSION_ID /Movies    # directory descriptor for an installer
remotefs stat SESSION_ID /Movies/example.mkv
remotefs get SESSION_ID /Movies/example.mkv ./example.mkv
remotefs put SESSION_ID /Movies/example.mkv ./example.mkv
remotefs rename SESSION_ID /Movies/old.mkv /Movies/new.mkv
remotefs copy SESSION_ID /Movies/new.mkv /Movies/copy.mkv
remotefs remove SESSION_ID /Movies/copy.mkv
remotefs disconnect SESSION_ID
```

`connect --type local --root /path/on/server` browses a permitted server directory.
For NFS, use `--type nfs --host nas.example --export /media --nfs-version 4`.
`copy --target-session OTHER_ID` copies between connections. Directory deletion
requires `--recursive`; replacing uploaded or downloaded files requires
`--overwrite`. Downloads stream to a temporary file before replacing their
output; `get ... -` streams to stdout.

```bash
remotefs saved add --type smb --host nas.example --share Media --username morgs --label Media
remotefs saved list
remotefs connect --saved-id LOCATION_ID
remotefs saved remove --id LOCATION_ID
remotefs credentials add --host nas.example --username morgs
remotefs credentials list
remotefs shares nas.example --credential-id CREDENTIAL_ID
remotefs credentials remove --id CREDENTIAL_ID
```

Saved locations and host credentials are stored by the server, and are immediately
available in its web UI. Passwords are prompted without echo; `--password-stdin`
is available for automation. Do not put passwords in command arguments. Client
login cookies are kept in the per-user `remotefs/client.json` file (mode 0600 on
Unix), keyed by server origin. Use `--auth-file` to isolate clients. `logout`
invalidates that login and closes the account's active browsing sessions, including
sessions opened in the web UI. Authentication expires after the server's login
lifetime; sign in again when it returns HTTP 401. Use HTTPS or an encrypted tunnel
for remote access, as with the web UI.

```bash
remotefs downloads list
remotefs downloads estimate --session SESSION_ID --paths /Movies /Music
remotefs downloads create --session SESSION_ID --paths /Movies --store Downloads
remotefs downloads pause --id JOB_ID
remotefs downloads resume --id JOB_ID
remotefs downloads part --id JOB_ID --index 0 --file ./media.zip
remotefs downloads purge --id JOB_ID
remotefs downloads forget --id JOB_ID
```

All command results are JSON, except streamed file bytes. `scan --all` emits one
JSON line per page; without it, use the returned `next_offset` with `--offset`.
Custom ranges remain subject to the server's allowed networks. Every client
command accepts `--url`, `--auth-file`, and `--timeout`; put options after the
command. Use `remotefs COMMAND --help` for details. GUI layout, sorting and visual
selection are presentation features; the CLI exposes their underlying directory
listings and descriptors for shell tools.

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
                print(len(chunk))
            selected = fs.descriptor('/Projects')

# Worker processes require the normal multiprocessing main guard on every OS.
if __name__ == '__main__':
    asyncio.run(example())
```

`list`, `stat`, `stream`, `descriptor` and `close` have identical interfaces for all backends. Paths inside a session always use `/`, including on Windows. A local connection's `root` remains a native host path such as `C:/Media`. Entries contain `name`, normalized `path`, `type`, `size`, and UTC `modified` time. Listings report `truncated` when the entry limit was hit and `skipped` for names that cannot be addressed safely (for example a colon or backslash in a filename); nothing aborts the listing.

Connect to SMB with `{'type':'smb','host':'nas.example','share':'Projects'}` and a separate `credentials={'username':..., 'password':...}` argument. NFS uses `{'type':'nfs','host':'nas.example','export':'/exports/media','version':4}`. Set the permitted network ranges first.

Each connected location owns a worker process that keeps its protocol connection through subsequent navigation and file reads. Discovery runs in a separate bounded worker. `close()` terminates it; abandoned workers exit after the configured idle period (300 seconds by default). Each filesystem operation has a hard deadline (10 seconds by default), so a stuck native call cannot block another session. The reference HTTP service also reaps expired session records.

For mutations, add the required operations to `Policy.operations`: `write`, `mkdir`, `rename`, `copy` and `delete`. The SDK defaults to read-only even though the standalone CLI defaults to read/write. `FilesystemSession.write(path, async_byte_chunks, overwrite=False)`, `mkdir(path)`, `rename(source, destination)`, `copy(source, destination, target=other_session)` and `remove(path, recursive=False)` use the same session-relative paths. Copy also requires source `read` and destination `write`; copying directories requires destination `mkdir`.

## HTTP API

The standalone service uses one configured username/password account. Sign-in issues an eight-hour HttpOnly, SameSite=Strict cookie scoped to `/api`; it is Secure when served over HTTPS. Mutations using a browser cookie require a matching Origin header. Login attempts and authenticated requests are rate-limited. Sign-out revokes the current login and closes filesystem sessions belonging to that principal; service restart ends all browser logins.

Page assets are public; data endpoints require authentication. An embedded service may supply authentication hooks or a bearer token instead. Routes below use `/api`. The current source checkout also exposes unprefixed compatibility aliases for discovery, sessions, saved locations, mutations, credentials and archives. Login stays under `/api/login`; use the canonical prefix for cookie authentication.

| Method / route | Purpose or body |
|---|---|
| `GET /api/login` | Check authentication and return service hostname |
| `POST /api/login`, `DELETE /api/login` | Sign in with `{username, password}`; sign out |
| `GET /api/discover?scan=false` | Allowed roots, groups and scan ranges; `scan=true` probes one page |
| `POST /api/discover` | Scan `{ranges, offset}` or enumerate `{type, host, credentials?, credential_id?}` |
| `GET/POST /api/saved`, `DELETE /api/saved/{id}` | List/save/forget folder descriptors and optional credentials |
| `GET/POST /api/credentials`, `DELETE /api/credentials/{id}` | List metadata, save `{host, credentials}`, or forget host credentials |
| `POST /api/sessions` | Connect with `{descriptor, credentials?}`; returns session ID, configured operations and upload limit |
| `DELETE /api/sessions/{id}` | Close session immediately |
| `GET /api/sessions/{id}/list?path=/` | Entries, `truncated` and `skipped`; add `ndjson=true` for NDJSON |
| `GET /api/sessions/{id}/stat?path=/file` | Normalized metadata |
| `GET /api/sessions/{id}/descriptor?path=/folder` | Validated durable directory descriptor |
| `GET /api/sessions/{id}/file?path=/file` | Stream file; supports a single `Range: bytes=...` header |
| `PUT /api/sessions/{id}/file?path=/file&overwrite=false` | Raw binary upload |
| `POST /api/sessions/{id}/mkdir` | `{path}` |
| `POST /api/sessions/{id}/rename` | `{source, destination}` |
| `POST /api/sessions/{id}/copy` | `{source, destination, target_session?}` |
| `DELETE /api/sessions/{id}/entry?path=/folder&recursive=true` | Remove file or directory tree |
| `GET /api/downloads` | Owned archive jobs and configured store capacity |
| `POST /api/downloads/estimate` | `{session, paths}`; returns entry/byte estimate and stores |
| `POST /api/downloads` | `{session, paths, store, part_size?}`; zero means a single ZIP |
| `POST /api/downloads/{id}` | `{action: "pause"}`, `"resume"` or `"forget"` (after purge) |
| `GET /api/downloads/{id}/parts/{index}` | Ready staged part, zero-based index; supports Range |
| `DELETE /api/downloads/{id}` | Purge staged files and return freed bytes |

File reads use bounded 256 KiB chunks. Explicit, open-ended and suffix ranges are supported; invalid or multiple ranges return 416. Downloads are attachments with `nosniff`, and credentials never appear in their URLs. A disconnected file transfer releases its active handle; the browsing session remains until expiry or explicit close.

Directory listings are bounded, not lazily paged: NDJSON emits the bounded result with `X-Listing-Truncated` and `X-Listing-Skipped` headers. The default `max_entries` is 10,000, also used to bound recursive operations and archive walks; maximum depth is 64. Truncated or skipped recursive listings are rejected. Control request bodies are limited to 16 KiB; raw uploads are counted separately against `max_write_bytes`. The defaults allow 16 filesystem sessions across the service and 120 authenticated requests per minute per principal.

## Credentials and descriptors

Descriptors never contain credentials. A descriptor can hold `credential_id`; `remotefs serve` resolves it from the remembered locations of the signed-in principal, and an embedding application can supply its own resolver instead.

```json
{"type":"smb","host":"nas.example","share":"Projects","path":"/Campaigns","credential_id":"media-reader"}
```

The SDK accepts `Browser(policy, credential_resolver=lambda reference: ...)`. The reference service accepts `create_app(policy, token=..., credential_resolver=lambda principal, reference: ...)` or `saved_locations=SavedLocations(path, storage_key)`; a resolver must check that the principal owns the reference before returning credentials. The SDK does not persist credentials. `create_app` persists saved locations or archive jobs only when the corresponding store is configured. A local descriptor contains `type`, native `root`, and a session-relative `path`; NFS retains `host`, `export`, `version` and `path`.

To customize authentication, pass `authenticate(request) -> principal` and optionally `authorize(principal, operation, descriptor) -> bool` to `create_app`. Hooks can be async. The default bearer token represents one principal; use per-user hooks for separate users. Sessions and saved locations cannot be read by a different principal. The CLI disables HTTP access logging; keep credentials and request bodies out of any logging added by the embedding application.

## Frontend

Use `frontend/browser.js` directly or the packaged `/browser.js` asset. It defines `<remote-fs-browser>` and exports `RemoteFsClient`. The embeddable component needs no React, Vue or build system. The standalone manager is a separate supplied UI and is not the custom element.

```javascript
import { RemoteFsClient } from './browser.js'
const picker = document.querySelector('remote-fs-browser')
picker.client = new RemoteFsClient('/storage-api/api', () => ({ Authorization: `Bearer ${token}` }))
picker.addEventListener('path-selected', event => saveDescriptor(event.detail))
// Optional: the embedding app saves credentials itself and returns an opaque reference.
// picker.storeCredentials = async credentials => mySecretStore.save(credentials)
```

When mounting the reference API inside another FastAPI application, include its lifespan in the host's lifespan so session expiry and worker/job cleanup run:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from remote_fs_browser.http import create_app

storage = create_app(policy, authenticate=authenticate_user)

@asynccontextmanager
async def lifespan(app):
    async with storage.router.lifespan_context(storage):
        yield

app = FastAPI(lifespan=lifespan)
app.mount('/storage-api', storage)
```

Here `policy` and `authenticate_user` are supplied by the embedding application as described above.

For an API mounted with `app.mount('/storage-api', create_app(...))`, use `/storage-api/api` as the client base. The standalone service uses `/api`. Existing bearer-authenticated integrations using the legacy unprefixed routes continue to work, including file mutations, host credentials and staged downloads. Cookie login uses the canonical `/api` routes and is scoped to the mount path.

The current source checkout adds the client helpers below alongside the terminal client; published 0.2.1 does not yet include all of these helpers.

| Area | JavaScript methods |
| --- | --- |
| Login | `login(username, password)`, `loginStatus()`, `logout()` |
| Discovery | `discover()`, `scan(ranges, offset)`, `shares(type, host, credentials?, credentialId?)` |
| Sessions | `connect(descriptor, credentials?)`, `close(id)` |
| Files | `list`, `stat`, `descriptor`, `file`, `upload`, `mkdir`, `rename`, `copy`, `remove` |
| Saved locations | `saved()`, `save(descriptor, credentials, label)`, `forget(id)` |
| Host credentials | `hostCredentials()`, `saveHostCredentials(host, credentials)`, `forgetHostCredentials(id)` |
| Archives | `downloads()`, `estimateDownload(session, paths)`, `createDownload(session, paths, store, partSize)` |
| Archive controls | `controlDownload(id, 'pause' | 'resume' | 'forget')`, `purgeDownload(id)`, `downloadPart(id, index, range?)` |

```javascript
const client = new RemoteFsClient('/api')
await client.login(username, password) // HttpOnly session cookie; no JS password storage
const { id } = await client.connect({ type: 'local', root: '/srv/files' })
await client.mkdir(id, '/inbox')
const estimate = await client.estimateDownload(id, ['/inbox'])
// Choose an available staging store returned by the service before creating a job.
await client.close(id)
```

`file()` and `downloadPart()` return a Fetch `Response`; check `response.ok` and stream the body for large downloads. Both accept a final `{ signal }` option. `upload()` accepts `{ overwrite, signal, progress }`. `copy(id, source, destination, targetSession?)` supports copying between owned sessions. `controlDownload(..., 'forget')` removes an already-purged job record; `purgeDownload()` removes staged bytes.

Fetch and upload requests use same-origin credentials by default. A third constructor argument `{ credentials: 'include' }` enables credentialed cross-origin requests where the host's CORS/authentication policy permits them; it does not bypass same-origin mutation checks or SameSite cookies. Custom authentication headers remain supported. The embedding app owns its login screen, archive controls and credential-management UI; the custom element keeps its existing picker/browse interface and events.

The element fills the box it is given. It renders the shortlist and the host's roots in a sidebar, network devices from an explicit scan, per-host share and export lists, credential entry, nested folders with formatted sizes and dates, in-place errors with retry, expiry reconnect, downloads in browse mode and a live descriptor preview with a Select button in select mode. The `signout` attribute adds a Sign out button that fires a `sign-out` event for the host page to act on. When the service offers `/api/saved` and no `storeCredentials` hook is set, "Save folder to shortlist" stores the current folder there. It closes its session on selection, disconnect or element removal. Keep the service on the same origin or configure a restrictive CORS policy when embedding across origins. The JS client's `file()` returns a Fetch `Response`; consume its `body` as a stream rather than calling `blob()` for large files.

## Operation and protocol limits

Uploads are staged beside the destination and committed after the full body arrives; ordinary cancellation cleans the temporary file and keeps the original. The default upload limit is 10 GiB (`max_write_bytes`). A killed process or lost server connection can leave a `.remotefs-*.part` file; remove stale files after checking no upload is active. Atomic replacement inherits the staging file's permissions/ACLs (local replacement preserves permission bits), so this is not an ACL-preserving backup tool.

Folder copies, recursive deletes and NFS folder moves run in steps. An error can leave partial results: refresh both locations before retrying. NFS folder moves create destinations exclusively and move files with server-side links before removing empty source folders. They are not atomic. Servers must support hard links for non-overwriting NFS file publication/moves. Symlinks, reparse points and special files are excluded; a recursive operation with hidden or truncated entries is rejected.

Filesystem ownership, POSIX permissions and server ACLs remain authoritative. The app does not expose arbitrary shell commands, ownership changes, ACL editing, symlink creation or mount administration.

SMB authentication uses NTLM (including domain-qualified usernames). The SMB backend does not accept IPv6 literals; use IPv4 or a hostname resolving to an allowed IPv4 address. SMB enumeration uses Impacket's SRVS RPC over SMB2; traversal and streaming use smbprotocol's SMB2/3 session. NFS export enumeration uses mountd and may return no exports on NFSv4-only servers; enter the export manually in that case. NFS uses AUTH_SYS UID/GID behaviour from libnfs and the service account; NFS Kerberos is not configured.

This project is a filesystem manager with an embeddable path picker. It does not provision mounts, manage backups, sync files, or abstract cloud object storage. It is a reference service and embedding SDK, not a hardened multi-tenant filesystem sandbox: see [security boundaries](SECURITY.md) and [validation](VALIDATION.md) before exposing it beyond a trusted network.

## Development and licensing

```sh
pip install -e '.[test]'
pytest
node --test frontend/*.test.js
python -m build
```

See [VALIDATION.md](VALIDATION.md) for completed checks and outstanding limitations. Release mechanics are documented in [packaging/RELEASING.md](packaging/RELEASING.md).

The application is MIT licensed. Dependencies retain their own licences: [smbprotocol](https://github.com/jborean93/smbprotocol), [Impacket](https://github.com/fortra/impacket), [libnfs](https://github.com/sahlberg/libnfs) and the other bundled components. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Windows portable packages include dependency licence texts and matching modified libnfs source, its build recipe and DLL replacement instructions.

# Cloud storage, libvirt and Kubernetes

Version 0.3.0 adds two optional connection types: **rclone** for cloud connections you add in the GUI or CLI and **libvirt** for read-only storage-pool and volume inventory. Upgrade remotefs to 0.3.0 or newer to use them.

## Install or upgrade

```sh
pipx install remote-fs-browser
# Already installed with pipx:
pipx upgrade remote-fs-browser
```

Install [rclone](https://rclone.org/install/) separately on the computer running remotefs. It must be on the service account's PATH.

For libvirt, install the native libvirt development package and pkg-config, then install the Python extra with `pipx install --force 'remote-fs-browser[libvirt]'`. On macOS, native prerequisites are `brew install libvirt pkgconf`; Debian/Ubuntu use `sudo apt install libvirt-dev pkg-config python3-dev build-essential`. These are service-host dependencies; viewing devices need only a browser. Windows users can run the libvirt-enabled service on a Linux host and connect to its browser interface.

## Add cloud storage in the GUI

Sign in with your remotefs **username and password**, then choose **Cloud storage → Add / manage** (or **Add location → Cloud / rclone**). Choose a provider, name the connection, enter its credentials, and select **Save & connect**. No configuration-file edit or service restart is needed.

The built-in forms cover Amazon S3 and compatible services, Backblaze B2, Dropbox, Google Drive, OneDrive, WebDAV/Nextcloud, and Azure Blob Storage. S3 takes an access key, secret, region and optional custom endpoint. Set the bucket/folder prefix to `/my-bucket/projects`, or `/` to browse everything those credentials can access.

Connections allow writes by default when the service and provider permit them. Tick **Read-only** for browse/copy-out access. Saved connections appear in the sidebar. Use **Edit** to change their name, prefix, permissions or credentials; leave secret fields blank to preserve them. **Remove connection** removes the saved configuration and closes its sessions, without deleting cloud files.

Credentials are stored in private rclone configuration files under the service's `remotes` directory next to `config.json`. They are not included in descriptors, browser storage, listings, or API responses. Back up and protect this directory with the rest of the service configuration. Each signed-in principal sees only its own managed connections. A globally read-only service disables connection changes.

### Dropbox, Drive and OneDrive authorization

These providers use OAuth. On a computer with rclone and a browser, run `rclone authorize dropbox`, `rclone authorize drive`, or `rclone authorize onedrive`. Sign in to the provider and paste the returned authorization JSON into the form. OneDrive also needs the drive ID and drive type. The form explains this step; it works with headless remotefs hosts. See [rclone's remote authorization guide](https://rclone.org/remote_setup/).

This is a provider authorization step, separate from the remotefs login. At present it requires the rclone authorization helper; remotefs does not provide an embedded OAuth redirect flow. Refreshed provider tokens are saved by rclone on the service host.

### Copy and paste across storage

1. Open a local folder, SMB/NFS share or cloud connection. Select files or folders and choose **Copy**.
2. Open the destination connection and folder.
3. Select **Paste here** in the clipboard bar, including when the destination folder is empty.

The service transfers the data; your browser does not need to download and re-upload it. Folder copies recurse through their contents. Existing destination files are not silently overwritten. Read-only connections may be copy sources, but the destination needs write permission. Cloud Cut and Rename remain unavailable; use Copy, verify, then Delete when moving cloud data.

## Manage cloud connections from the CLI

```sh
remotefs login --username YOUR_NAME
remotefs remotes providers
# Prompts for provider fields; secret fields are hidden:
remotefs remotes add --provider s3 --label "Studio archive" --root /my-bucket
remotefs remotes list
remotefs remotes edit --id CLOUD_ID --read-only
remotefs connect --type rclone --endpoint CLOUD_ID
remotefs copy SOURCE_SESSION /photos /backup/photos --target-session DESTINATION_SESSION
remotefs remotes remove --id CLOUD_ID
```

For non-interactive setup, pass `--options-stdin` and pipe a JSON object containing the provider's field names. Credentials are never command-line arguments. `remotes show --id CLOUD_ID` returns non-secret fields and the names of saved secret fields, not their values.

Automation may optionally use a separate `automation_token` of at least 32 random characters in the server's private `config.json` (restart to apply), and `REMOTEFS_TOKEN` in the client environment. It acts as the configured account. Normal GUI and CLI use remains username/password with a login cookie; no API token is required.

## Configure rclone once on the service host

This optional advanced route preserves existing host-configured remotes and provides access to other rclone providers. The GUI/CLI flow above does not need it.


Run rclone as the account that runs remotefs, with an explicit config path:

```sh
rclone config --config /srv/remotefs/rclone.conf
rclone listremotes --config /srv/remotefs/rclone.conf
```

Choose **New remote**, give it a name such as `archive` or `team`, and follow the provider-specific setup. For S3, select the S3 provider, region, endpoint (for S3-compatible services) and authentication method. For Dropbox, complete rclone's OAuth authorization. The [S3 setup](https://rclone.org/s3/) and [Dropbox setup](https://rclone.org/dropbox/) describe the current prompts. Provider credentials remain in rclone's host-side config, not browser descriptors or the saved-location store.

Keep the config private and writable by the service account when OAuth token refresh requires it. Encrypted configs can use `RCLONE_CONFIG_PASS` in the service environment; the adapter never prompts. Other `RCLONE_*` environment overrides are excluded, so use the named config for backend settings. Cloud egress is governed by the configured remote and provider credentials, **not** the SMB/NFS `network_ranges` policy. Only expose trusted configurations and grant provider credentials access to the intended bucket or prefix.

Merge an `endpoints` map into the existing **policy** object in `~/.config/remotefs/config.json` (Windows: `%APPDATA%\remotefs\config.json`). Preserve the existing account and storage key. Restart remotefs after editing it.

```json
{
  "policy": {
    "endpoints": {
      "s3-archive": {
        "type": "rclone",
        "config": "/srv/remotefs/rclone.conf",
        "remote": "archive",
        "root": "/my-bucket/projects",
        "read_only": true
      },
      "dropbox-team": {
        "type": "rclone",
        "config": "/srv/remotefs/rclone.conf",
        "remote": "team",
        "root": "/Shared",
        "read_only": false
      },
      "hypervisor": {
        "type": "libvirt",
        "uri": "qemu:///system",
        "pools": ["default", "images"]
      }
    }
  }
}
```

Endpoint names are public aliases. A browser cannot supply a different rclone config, remote, prefix or libvirt URI. `root` is a path within the named remote; for S3 it normally starts with the bucket. To expose a local folder through rclone, configure an rclone **alias** remote pointing at its absolute path, then use `/` as the endpoint root.

## Connect in the browser or terminal

Managed cloud connections appear under **Cloud storage** in the sidebar. Host-configured rclone endpoints also appear there. For libvirt, select **Libvirt pools** in Add location and choose or enter the configured alias. Browse with the normal folder list and breadcrumbs, and shortlist folders for later. The embeddable picker exposes the same endpoints.

```sh
remotefs login --username YOUR_NAME
remotefs discover
remotefs connect --type rclone --endpoint s3-archive
# Use the id returned by connect:
remotefs ls SESSION_ID /
remotefs get SESSION_ID /report.csv ./report.csv
remotefs select SESSION_ID /reports

remotefs connect --type libvirt --endpoint hypervisor
remotefs ls SESSION_ID /
remotefs ls SESSION_ID /default
remotefs stat SESSION_ID /default/disk.qcow2
```

The SDK and HTTP API use the same credential-free descriptor:

```json
{"type": "rclone", "endpoint": "s3-archive", "path": "/reports"}
```

The libvirt equivalent is `{"type":"libvirt","endpoint":"hypervisor","path":"/default"}`. Session responses advertise the permitted operations; clients must honor them.

## What each connection supports

| Capability | Local / SMB / NFS | Rclone | Libvirt |
| --- | --- | --- | --- |
| Browse and metadata | Yes | Yes | Allowed pools and their volumes |
| Download, preview and HTTP byte ranges | Yes | Yes, for files | No disk-content access |
| Copy out to a writable location | Yes | Yes, when `copy` is permitted | No |
| ZIP preparation and split downloads | Yes | Yes, through the service host | No |
| Upload and text save | With write permission | With `read_only: false` and write permission | No |
| Create folders and delete | With permission | With write permission; provider semantics apply | No |
| Rename / cut | With permission | Not exposed; use Copy, verify, then Delete | No |
| Saved folders, CLI, SDK, picker | Yes | Yes | Yes, for inventory paths |

Managed GUI/CLI cloud connections default to writable; the Read-only option disables mutations. Advanced policy endpoints default to read-only. Setting `read_only: false` cannot override the global operations policy or provider permissions. Empty folders may not persist on object stores. Names that the common path format cannot represent are skipped and reported. Large listing responses above 16 MiB are rejected; narrower prefixes help.

Uploads first spool to temporary disk on the service host, then publish through rclone. Allow enough free disk for concurrent uploads. Each provider operation must finish within the configured operation timeout (10 seconds by default); increase `policy.operation_timeout` for large transfers or slow providers. Downloads use bounded 4 MiB ranged requests, so they favor predictable memory use over maximum throughput. Provider APIs can incur request and egress charges.

Non-overwrite uploads check for an existing destination and use rclone's immutable mode. Cloud providers do not share local filesystem atomicity: concurrent writers and interrupted transfers can leave partial or conflicting results. Explicit overwrite is last-writer-wins. After any failed cloud mutation, refresh and inspect the destination before retrying. Cloud rename/cut is intentionally unavailable because a uniform no-replace rename guarantee is not available.

## Libvirt: pools and volumes, not guest files

The adapter opens a **read-only** libvirt connection. Its root lists only the pool names in `pools`; open a pool to list its volumes. **Get info** shows pool capacity, allocation and available space, or volume capacity, allocation and type. Inactive or unavailable pools may reject enumeration; manage their lifecycle with your normal hypervisor tools.

A URI such as `qemu+ssh://USER@HOST/system` can target a remote hypervisor when the service account already has non-interactive SSH authentication and host verification configured. Do not put passwords in the URI. Pool allowlists and the URI are administrator-controlled. The adapter never starts, stops or edits VMs, mounts disks, or reads guest filesystem contents.

Ductstack's storage picker is the related workflow: choose VM storage or a mounted network share and browse directories on a live VM. Standalone remotefs now offers a separate libvirt inventory connection; selecting a volume is not equivalent to browsing files inside a VM.

## Kubernetes: files inside running pods

Merge a `kubernetes` entry into the policy's `endpoints` map as for rclone and restart remotefs. It browses the containers of a cluster the service host can reach. Its root lists the namespaces named in `namespaces`; open one for its pods, a pod for its containers, and a running container for its filesystem. **Get info** on a container lists its mounts, marking PersistentVolumeClaims and the ones Longhorn provisions, and those mount points carry the same marks in listings.

```json
{
  "policy": {
    "endpoints": {
      "cluster": {
        "type": "kubernetes",
        "namespaces": ["apps", "media"],
        "kubeconfig": "/etc/rancher/k3s/k3s.yaml",
        "read_only": true
      }
    }
  }
}
```

- `namespaces` is required and nothing outside it is listed or reachable.
- `kubeconfig` and `context` are optional. Without a `kubeconfig`, kubectl uses its own defaults, which inside a pod means that pod's service account. `kubectl` may name an absolute path to the binary.
- `read_only` defaults to `true`. Set it to `false` to allow uploads, text saves, new folders, rename (within one container) and delete.

The service host needs `kubectl`. Files are read and written with `kubectl exec` running short POSIX shell scripts, so any container with `sh` and coreutils or BusyBox works; distroless containers without a shell are reported as such and cannot be browsed. Nothing is installed in the pod. Saves go to a temporary file beside the target and are renamed into place, keeping an existing file's mode and, where the container allows it, its owner, so a half-written config never lands. Links are followed for browsing, but deleting a folder removes links inside it without touching what they point at. Namespaces, pods and containers are inventory: they cannot be renamed or deleted here.

Grant the kubeconfig's identity only what you intend to expose. A dedicated ServiceAccount with a Role in each listed namespace allowing `get` and `list` on `pods` and `persistentvolumeclaims`, and `create` on `pods/exec`, is enough. `pods/exec` is powerful: it runs commands as the container's user, so treat write access to this endpoint like shell access to those pods.

Only running pods and containers can be browsed. A Longhorn volume that no running pod mounts is not reachable yet.

## Validation scope

The adapter tests exercise real rclone against a disposable S3 HTTP fixture and a local alias remote. Coverage includes managed connection creation, edits, owner isolation, persistence, removal without cloud deletion, local-to-cloud and cloud-to-cloud copies, as well as including ranged and multi-chunk downloads, uploads, overwrite handling, cross-backend copying, deletion and read-only enforcement. Libvirt is exercised against its in-memory `test:///default` driver, with separate pool/volume metadata and allowlist tests. The Kubernetes adapter's shell scripts run in real BusyBox and Debian containers behind a stand-in kubectl that serves canned pod and claim records; those tests cover listing, links, ranged reads, atomic saves that keep file modes, no-replace rename and mkdir, link-safe recursive deletes and copying out to local storage. The manager and endpoint controls are also checked in a browser.

These checks do not authenticate to live S3, Dropbox or other cloud accounts, and they do not modify production hypervisors or clusters. Validate your provider configuration and permissions with a small test folder before using important data.

For the Linux service installer, temporary cloud data uses the private
`/opt/remote-fs-browser/tmp` directory, within the service's existing writable
prefix. Put a refreshable OAuth config at `/opt/remote-fs-browser/rclone.conf`
so token updates are also permitted by its systemd filesystem policy. A custom
service must provide a writable temporary directory (for example with `TMPDIR`)
and allow writes to the rclone config's parent when OAuth refresh requires them.

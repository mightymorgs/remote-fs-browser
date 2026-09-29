# Cloud storage and libvirt

The source version of remotefs adds two optional connection types: **rclone** for configured cloud remotes and **libvirt** for read-only storage-pool and volume inventory. These additions are not in the published 0.2.2 packages. Install from the updated source checkout to use them.

## Install the source version

```sh
git clone https://github.com/mightymorgs/remote-fs-browser.git
cd remote-fs-browser
pipx install .
```

If pipx already manages an older installation, use `pipx install --force .` from this checkout. Install [rclone](https://rclone.org/install/) separately on the computer running remotefs. It must be on the service account's PATH.

For libvirt, install the native libvirt development package and pkg-config, then install the Python extra with `pipx install --force '.[libvirt]'`. On macOS, native prerequisites are `brew install libvirt pkgconf`; Debian/Ubuntu use `sudo apt install libvirt-dev pkg-config python3-dev build-essential`. These are service-host dependencies; viewing devices need only a browser. Windows users can run the libvirt-enabled service on a Linux host and connect to its browser interface.

## Configure rclone once on the service host

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

In **Add location**, select **Cloud / rclone** or **Libvirt pools**, then open one of the configured endpoints. You can also type its alias. Browse with the normal folder list and breadcrumbs, and shortlist folders for later. The embeddable picker exposes the same endpoints.

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
| Create folders and delete | With permission | With endpoint opt-in; provider semantics apply | No |
| Rename / cut | With permission | Not exposed; use Copy, verify, then Delete | No |
| Saved folders, CLI, SDK, picker | Yes | Yes | Yes, for inventory paths |

Rclone endpoints default to read-only. Setting `read_only: false` cannot override the global operations policy or provider permissions. Empty folders may not persist on object stores. Names that the common path format cannot represent are skipped and reported. Large listing responses above 16 MiB are rejected; narrower prefixes help.

Uploads first spool to temporary disk on the service host, then publish through rclone. Allow enough free disk for concurrent uploads. Each provider operation must finish within the configured operation timeout (10 seconds by default); increase `policy.operation_timeout` for large transfers or slow providers. Downloads use bounded 4 MiB ranged requests, so they favor predictable memory use over maximum throughput. Provider APIs can incur request and egress charges.

Non-overwrite uploads check for an existing destination and use rclone's immutable mode. Cloud providers do not share local filesystem atomicity: concurrent writers and interrupted transfers can leave partial or conflicting results. Explicit overwrite is last-writer-wins. After any failed cloud mutation, refresh and inspect the destination before retrying. Cloud rename/cut is intentionally unavailable because a uniform no-replace rename guarantee is not available.

## Libvirt: pools and volumes, not guest files

The adapter opens a **read-only** libvirt connection. Its root lists only the pool names in `pools`; open a pool to list its volumes. **Get info** shows pool capacity, allocation and available space, or volume capacity, allocation and type. Inactive or unavailable pools may reject enumeration; manage their lifecycle with your normal hypervisor tools.

A URI such as `qemu+ssh://USER@HOST/system` can target a remote hypervisor when the service account already has non-interactive SSH authentication and host verification configured. Do not put passwords in the URI. Pool allowlists and the URI are administrator-controlled. The adapter never starts, stops or edits VMs, mounts disks, or reads guest filesystem contents.

Ductstack's storage picker is the related workflow: choose VM storage or a mounted network share and browse directories on a live VM. Standalone remotefs now offers a separate libvirt inventory connection; selecting a volume is not equivalent to browsing files inside a VM.

## Validation scope

The adapter tests exercise real rclone commands against a disposable local alias remote, including ranged and multi-chunk downloads, uploads, overwrite handling, cross-backend copying, deletion and read-only enforcement. Libvirt is exercised against its in-memory `test:///default` driver, with separate pool/volume metadata and allowlist tests. The manager and endpoint controls are also checked in a browser.

These checks do not authenticate to live S3, Dropbox or other cloud accounts, and they do not modify production hypervisors. Validate your provider configuration and permissions with a small test folder before using important data.

For the Linux service installer, temporary cloud data uses the private
`/opt/remote-fs-browser/tmp` directory, within the service's existing writable
prefix. Put a refreshable OAuth config at `/opt/remote-fs-browser/rclone.conf`
so token updates are also permitted by its systemd filesystem policy. A custom
service must provide a writable temporary directory (for example with `TMPDIR`)
and allow writes to the rclone config's parent when OAuth refresh requires them.

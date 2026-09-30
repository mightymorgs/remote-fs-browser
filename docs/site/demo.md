# Your files. Across storage.

The **2:04 remotefs 0.3.0 feature tour** uses actual browser workflows, short command cards and captions that work with sound off. [Watch on the homepage](index.html#watch-it-install-and-run) or [download the 1080p video](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.3.0/remotefs-0.3.0-feature-tour.mp4).

## 0:00 — Copy across storage

Copy a local “Launch kit” folder, switch to SmartNAS S3 and paste. Nested folders, text, an image and a CSV arrive together. Preview and edit the README on S3, then copy the folder back into an empty local destination. All four returned files match the S3 objects byte for byte, including the edited README.

The service moves the bytes between storage endpoints. The browser operates the file manager; it does not need to download and re-upload the folder itself.

## 0:28 — Install and sign in

Install with `pipx install remote-fs-browser`, then run `remotefs` for guided setup. Homebrew and Windows portable packages are also available. Configure reachable networks, permitted operations and your account. Sign in with a username and password; optional tokens support automation.

## 0:36 — SMB and NFS

Scan a permitted network, map an SMB share, save its credentials and open a file. DNS, NetBIOS and IP have separate columns. Saved SMB credentials are encrypted on the service host. Application sessions require no operating-system mount.

The NFS connection form exposes NFSv3 and NFSv4 options. NFS requires libnfs on the service host. This recording shows NFS setup, not an NFS file transfer.

## 0:50 — Everyday file tools

Save frequently used folders to the shortlist. Filter and sort a listing, upload a file, create a folder, rename and move. Preview, metadata, deletion and keyboard shortcuts are available from the same manager. Operations depend on the backend and configured permissions; cloud transfers use Copy / Paste.

## 1:08 — Cloud connections

Add a named S3 connection in the GUI. Provider forms also cover Dropbox, Google Drive, OneDrive, WebDAV / Nextcloud, Backblaze B2 and Azure Blob. OAuth providers use the `rclone authorize` helper described in the form. Connections can also be managed through CLI commands.

These provider forms demonstrate configuration. The live cloud transfer in this cut uses SmartNAS S3; it does not claim live connections to every other provider.

## 1:22 — Downloads and ZIP jobs

Choose a ZIP preparation folder and custom part size. Pause and resume archive packing, then fetch ready parts. Downloads support HTTP ranges, and explicit purge controls release staged space. Rejoin multipart files before opening the ZIP.

The recording uses a 128 MiB source with 40 MiB parts. Its four-part archive was reassembled, checked for ZIP integrity and compared with the original content. The film shows the ready download controls; archive verification was performed separately.

## 1:37.5 — Libvirt inventory

Browse configured storage pools and inspect volumes with capacity metadata. This is read-only inventory, not access to files inside guest disks. The recording uses libvirt’s test driver with two sample volumes; it does not operate on production VMs.

## 1:44 — CLI, API and embedding

The CLI signs in to the same service, connects to a managed rclone endpoint, lists files and returns location descriptors. The command card abbreviates arguments for readability; the SmartNAS listing was verified with the actual CLI.

Embed the folder picker in another application to return a location descriptor without embedding credentials. An authenticated HTTP API and asynchronous Python SDK provide integration options. Explicit roots, endpoints and operations control access. Service setup supports Homebrew services, systemd, launchd and Windows startup.

## 1:59.5 — Get started

Local folders, SMB, NFS, rclone cloud storage and libvirt inventory, through one service. [Install remotefs](install.html), [read the guide](guide.html) or [configure storage endpoints](endpoints.html).

## Recording environment

The local service used isolated demo roots. Actual SmartNAS S3 footage used a dedicated `nas/remotefs-demo-20260930` prefix with disposable files. SMB discovery and reading ran against a disposable SMB server in an isolated network namespace on SmartNAS, accessed through an SSH tunnel. Existing running installations and production shares were not changed for this recording. No real storage credentials appear in the film.

The [original 0.2.1 SMB recording](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.1/remotefs-feature-demo.mp4) remains available, along with its [validation notes](docs/validation/2026-09-11-network-demo.md).

# One service. All the places you work.

Remotefs runs on a computer that can reach your storage. Your browser, terminal client and integrations connect to that service. Files are read or written by the service host using its permitted roots, network connections and configured endpoints.

Version 0.4.0 supports local folders, SMB, NFS, optional rclone cloud connections, read-only libvirt pool/volume inventory and optional mounts, which show any of those shares or cloud connections as a folder or drive on the service host. See the [endpoint guide](endpoints.html) for installation, configuration and the complete capability table.

## Set up the service

[Install remotefs](install.html) on your workstation, server or homelab node. Run `remotefs`, choose the network access and create your account. Open the startup URL and sign in. The default is `http://127.0.0.1:8080/` on the service host.

To connect from another device, deliberately bind the service to a reachable interface. Use a trusted LAN, VPN, SSH tunnel or HTTPS reverse proxy. The viewing device needs a browser and access to the service; SMB/NFS file servers need no remotefs agent. `remotefs setup` revisits first-run choices after the running service is stopped.

[Follow the full quickstart](quickstart.html).

## Find your storage

**This computer** lists the service host's permitted local roots and mounted volumes. **Scan network** checks selected CIDR ranges for SMB and NFS services and shows DNS names, NetBIOS names and IP addresses when available. You can enter a server directly when discovery is unavailable.

Choose **Map**, authenticate to an SMB share or select an NFS export, and open a folder. SMB credentials can be saved encrypted. A **shortlist** remembers the location separately from the current connection. Mapping and unmounting SMB/NFS manage application sessions, not operating-system mounts; to get a real folder or drive, see [Mount it as a folder or drive](#mount-it-as-a-folder-or-drive). NFS requires libnfs 6+.

[Discovery, mapping and saved locations](reference.html#scan-map-and-remember-locations).

## Work with files

Use breadcrumbs to navigate, filter the current folder by name and sort by name, size or modified date. Checkboxes select items; Shift-click selects a range. The context menu and keyboard shortcuts expose the available actions.

- **Preview and edit:** open UTF-8 text up to 1 MiB for preview. Save explicitly replaces it. There is no editing lock or conflict detection.
- **Upload:** choose multiple files, see byte progress and cancel an in-flight upload. Replacing a file needs confirmation. Directory and resumable uploads are not provided.
- **Create:** make a directory or a new text file.
- **Copy:** select files or directories, open another location and paste. Copies can cross supported backends through the service host.
- **Move and rename:** supported on local, SMB and NFS. Cross-session cut/paste copies before deleting; failures can leave partial results. Cloud endpoints expose Copy and Delete separately.
- **Delete:** removes the selected files and folder contents permanently after confirmation. There is no recycle bin.
- **Get info:** inspect file metadata or libvirt capacity and allocation.

Actions are limited by global policy, connection capabilities and underlying filesystem/provider permissions. [Read the detailed operation semantics](reference.html#file-operations).

## Download one file or prepare a collection

Direct downloads stream through the service and support HTTP byte ranges. For a selection of folders or files, choose **Download as multi-part zip**. Estimate the required space, choose a host-side staging store and preparation folder, then select a single ZIP or a split size.

Packing creates a ZIP64 archive on the service host. Pause and resume affect packing, not browser transfers. Request the completed parts through the browser. Download all split parts, concatenate them in order and unzip the rejoined archive; individual parts are not standalone ZIPs.

Completed archives survive a service restart. Interrupted packing does not resume after restart: purge and start again. Staged data has no automatic expiry. **Purge** removes it and frees space; it can interrupt transfers. A browser handoff means the download was requested, not proof that it finished saving.

[Download jobs, staging configuration and limits](reference.html#downloads-and-staged-zips).

## Add cloud storage with rclone

Choose **Cloud storage → Add / manage**, select a provider, enter its credentials and bucket/folder prefix, then **Save & connect**. Connections are saved for your account and appear in the sidebar immediately. The CLI offers the same setup through `remotefs remotes add`.

Browse, preview, download, copy out and prepare ZIPs. Writable endpoints can also upload, save text, create folders and delete, subject to the provider's capabilities. Tick Read-only when you only want to browse and copy out. Native cloud rename/cut is not exposed, and object stores do not necessarily preserve empty folders.

[Set up S3, Dropbox and other rclone remotes](endpoints.html#add-cloud-storage-in-the-gui).

## Mount it as a folder or drive

When another program needs the files, such as a video editor, a disk-image tool or File Explorer, mount the location on the computer running remotefs. Start the service with `remotefs serve --allow-mounts` (or add `"mount"` to `policy.operations`), right-click an SMB share, NFS export, folder or cloud connection and choose **Mount on this computer…**.

Mounts are read-write by default; untick **Allow changes** for a read-only mount. They appear under **Mounted on this computer** in the sidebar, as a folder under `~/remotefs` on macOS and Linux or a drive letter on Windows. There is no file-size limit. **Eject** waits for uploads to finish. The CLI has the same controls: `remotefs mount`, `remotefs mounts` and `remotefs unmount`.

Mounting uses rclone on the service host, plus FUSE on Linux or WinFsp on Windows. NFS mounts go through rclone too, via a private local link, so they behave the same on every system. On Windows the drive belongs only to your own account and sign-in session, and it comes back each time you sign in. Mounting is available from version 0.4.0, and mounts reconnect by themselves after restarts unless you untick **Reconnect automatically**.

[Mount storage on this computer](mounts.html).

## Inspect libvirt storage

Install the optional libvirt adapter, configure a local or remote hypervisor URI and explicitly name its allowed storage pools. Select **Libvirt pools** in Add location. Open a pool, list its volumes and use **Get info** to inspect capacity, allocation and type.

The connection is read-only inventory. It never mounts a virtual disk, reads guest files, or modifies the hypervisor. Ductstack's related VM storage workflow browses the VM's own filesystem and mounted network shares; those are different capabilities.

[Configure the libvirt connection](endpoints.html#libvirt-pools-and-volumes-not-guest-files).

## Use the same service from a terminal

Log in with `remotefs login`, connect to a location and use the returned session ID with `ls`, `stat`, `get`, `put` and other supported commands. Results are JSON except file bytes. Client commands share the browser's service, locations, credentials, permissions and download jobs.

```sh
remotefs login --username YOUR_NAME
remotefs discover
remotefs connect --type smb --host nas.example --share Projects --username YOUR_NAME
remotefs ls SESSION_ID /
remotefs get SESSION_ID /report.csv ./report.csv
remotefs downloads list
```

[Complete terminal command guide](reference.html#terminal-file-manager).

## Embed or automate

The Python SDK provides asynchronous sessions and streaming reads. The authenticated HTTP API exposes connections, discovery, operations and archive jobs. The directory-picker web component returns a credential-free descriptor so another application can remember the selected directory. Rclone and libvirt descriptors reference a configured endpoint alias; they do not include provider secrets.

The standalone service defaults to read/write, while the Python SDK defaults to read-only. Worker processes isolate sessions and apply operation deadlines and idle expiry. Endpoints further restrict the operations advertised by each session.

[Python SDK](reference.html#python-sdk) · [HTTP API](reference.html#http-api) · [Embeddable picker](reference.html#frontend).

## Keep it running

Use the service installers for Linux systemd, macOS launchd or Windows startup tasks, or the Ansible deployment playbooks. Configure accounts, roots, allowed network ranges, endpoints, operations and staging stores explicitly for unattended installations.

[Deployment guide](deployment.html) · [Full reference and limits](reference.html#operation-and-protocol-limits).

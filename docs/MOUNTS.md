# Mount storage on this computer

remotefs can show an SMB share, an NFS export or a cloud connection as a normal folder or drive on **the computer running the remotefs service**. Finder, File Explorer and every other app can then open, save and copy files there directly. This includes large files: there is no per-file size limit, so disk images and video work.

Mounting is available from version 0.4.0. It has been tested on Linux and macOS. Windows mounts are supported, but the per-account drive described below has not yet been checked on a real Windows computer, so treat Windows as a preview for now.

Mounting is off by default. Turn it on when you start the service:

```sh
remotefs serve --allow-mounts
```

For installed services, add `"mount"` to `policy.operations` in `config.json` and restart the service. To place macOS/Linux mounts somewhere other than `~/remotefs`, pass `--mount-folder /path` or set `"mount_folder"` in `config.json`.

## Mount and eject

- **In the browser:** right-click a share in the sidebar, a folder, or the empty space in a folder, then choose **Mount on this computer…**. Pick a name (and a drive letter on Windows), and untick **Allow changes** if you want the mount to be read-only. Mounts allow changes by default. Active mounts appear under **Mounted on this computer** in the sidebar, with an **Eject** button.
- **From the terminal:**

  ```sh
  remotefs connect --type smb --host 192.168.1.20 --share Projects --credential-id CREDENTIAL_ID
  remotefs mount SESSION_ID /Clients --label "Client work"   # add --read-only to block changes, --no-reconnect for this run only
  remotefs mounts                      # active mounts and anything this computer still needs
  remotefs unmount MOUNT_ID
  ```

### Mounts reconnect by themselves

**Reconnect automatically** is ticked by default. remotefs then remembers the mount, with its name, drive letter or folder and read-only setting, and mounts it again:

- when the remotefs service starts, for example after the computer restarts;
- if rclone stops unexpectedly;
- on Windows, each time the mount owner signs in. Signing out of Windows ends the drive; it comes back within about 15 seconds of signing in again.

A mount that is waiting shows why in the sidebar, for example "Waiting for PC\\morgan to sign in to Windows", or the reason the last attempt failed. Failed attempts are retried with increasing gaps, up to every five minutes. **Eject** stops a mount and forgets it. Untick **Reconnect automatically**, or pass `--no-reconnect`, for a mount that lasts only until the service stops.

A reconnecting SMB mount has to sign in to the server without you. If you typed the login rather than choosing a saved one, remotefs stores it with your other saved logins, encrypted with the service's storage key. You can remove it there. If a saved login is removed or no longer works, the mount waits and shows the error until you eject it or fix the login. Cloud connections and NFS exports need no stored login.

Reconnecting follows the service's current policy: a mount comes back read-only if the service no longer allows writes, and does not come back at all while its server is outside the allowed networks.

Eject waits up to a minute for uploads to finish before unmounting. If uploads are still running, the app asks before ejecting anyway (`remotefs unmount --force`). Unfinished uploads are kept in the local cache and resume the next time the same location is mounted. When the service stops, it unmounts everything the same way; reconnecting mounts come back when it starts again.

## What can be mounted

| Location | Mountable | How |
| --- | --- | --- |
| SMB share or folder | Yes | rclone's SMB backend with the login you used or saved for that server |
| Cloud connection (S3, B2, Dropbox, Drive, OneDrive, WebDAV, Azure) | Yes | The saved rclone connection, limited to its bucket/folder prefix |
| Host-configured rclone endpoint | Yes | Its configured remote and root |
| Local folder | No | It is already on this computer |
| NFS export or folder | Yes | remotefs reads the export with its own NFS client and hands it to rclone over a private loopback WebDAV link (rclone has no NFS client) |
| Libvirt pool | No | Read-only inventory, not file content |

A mount is limited to what its session allows: a read-only connection or service always mounts read-only.

**NFS mounts.** Each NFS mount runs a small WebDAV server in its own process, listening only on 127.0.0.1 behind a random password, backed by the same libnfs connection remotefs uses for browsing. It needs nothing beyond what browsing NFS already needs, and it works the same way on Windows, macOS and Linux. The NFS server sees the service host's address, as it does when you browse. Symbolic links on the export are hidden, as they are in the browser.

## How it works on each system

Every mount is a separate rclone process started by the service, with a private configuration file, a local cache (`vfs-cache-mode full`, so ordinary apps can edit files in place) and a remote-control endpoint on 127.0.0.1 protected by a random password that is passed through the environment, not the command line.

| System | Command | Needs |
| --- | --- | --- |
| **Windows** | `rclone mount … Z: --network-mode` | WinFsp. The app offers to install it on first use: it downloads the official installer from the WinFsp GitHub release, checks its SHA-256 checksum and runs it, and Windows asks for permission once. `remotefs` installed with winget brings WinFsp with it. |
| **macOS** | `rclone nfsmount` (rclone serves NFS on 127.0.0.1 and macOS mounts it) | rclone 1.65 or later, which Homebrew installs. No kernel extension or macFUSE. |
| **Linux** | `rclone mount` (FUSE) | `fuse3` (`sudo apt install fuse3`). |

The Windows portable download bundles `rclone.exe`. Homebrew installs rclone as a dependency; on Linux install it from your distribution or https://rclone.org/install/.

**Where mounts appear**
- Windows: the next free drive letter (Z: downwards) or the one you choose. The drive belongs to one Windows account: only that account can open it, and it appears only in that account's own sign-in session.
  - When you run `remotefs serve` yourself, that account is you.
  - The Windows service installer runs remotefs as SYSTEM and records the account that ran the installer as `mount_owner` in `config.json`. The service starts each mount inside that account's session, so the owner has to be signed in to Windows; reconnecting mounts appear shortly after the owner signs in. Other people signed in to the same computer don't see the drive or its `\\rclone\…` path. To give mounts to a different account, change `mount_owner` (for example `"PC\\morgan"`) and restart the service. Without a `mount_owner`, the service refuses to mount rather than mounting for everyone.
- macOS/Linux: a folder under `~/remotefs` of the account running the service, named after the mount.

**Disk space.** Reads cache only the parts of files you open. Writes are staged in the cache before upload, so writing a 30 GB file needs about 30 GB free on the drive holding the service's configuration folder. The cache lives in the `mounts/cache` folder next to `config.json`.

## Limits

- Mounts are created on the computer running the service. To use one from a different computer, run remotefs on that computer, or share the mount with that computer's own tools.
- On Linux and macOS a mount belongs to the account running the service. A service installed as root creates mounts under root's home folder unless `mount_folder` points elsewhere.
- rclone's `nfsmount` is marked experimental by the rclone project.
- NFS mounts pass every file operation through one connection, so they are slower than a native NFS mount for many small files. Large files stream at close to network speed.
- On Windows, a read-only mount refuses changes from ordinary accounts with "Access is denied". An elevated administrator bypasses that check, so deleting a file on a read-only drive appears to succeed, but nothing is deleted.
- Cloud storage has no real rename for large folders; renaming them through a mount copies and deletes, which is slow.

WinFsp - Windows File System Proxy, Copyright (C) Bill Zissimopoulos — https://github.com/winfsp/winfsp. rclone is MIT-licensed, copyright Nick Craig-Wood — https://rclone.org.

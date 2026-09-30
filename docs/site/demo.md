# Feature walkthrough

The **16-minute remotefs walkthrough** is the real app, driven at human pace, with captions that work with sound off. [Watch on the homepage](index.html#watch-it-install-and-run), [download the 1080p walkthrough](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.3.0/remotefs-0.3.0-walkthrough.mp4) or [the 72-second promo](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.3.0/remotefs-0.3.0-promo.mp4).

## 0:00 — Sign in

Open remotefs in your browser and get your bearings.

## 0:36 — Work like Finder

Shift-click ranges, ⌘-click, drag to select, right-click menus and shortcuts.

## 2:19 — Organise files

New folders, copy and paste, rename, and edit text files in place.

## 3:54 — Find network shares

Scan your network, see every file server by name, and map a share. Mapping a share opens it in the app; nothing is mounted until you ask for a mount (chapter 8).

## 5:32 — Servers and saved logins

Server menus, disconnecting, saved logins and several servers at once. **Unmount** here disconnects the app from the server; it is not the same as ejecting a mounted drive.

## 7:20 — Shortlist favourites

Star folders and reopen them with one click, even after a reload.

## 8:24 — Copy across storage

Add an S3 bucket, then copy between your computer, the cloud and the NAS. The service moves the bytes; the browser never downloads and re-uploads them.

## 9:39 — Mount as a drive

Mount a NAS folder or cloud bucket as a folder or drive that every app can use, read-write or read-only. The NAS folder is mounted read-write and the S3 bucket read-only. A terminal copies a 96 MB video onto the NAS mount and edits a text file, and `rm` on the S3 mount is refused with "Read-only file system". Back in the browser, the new file and the edit are read over SMB, then both mounts are ejected. Needs `remotefs serve --allow-mounts`; mounting ships in the next release. Filmed on Linux; macOS is tested; Windows drives belong to your own account and are not yet verified on a real Windows computer. [How mounts work](mounts.html).

## 12:06 — Big downloads

Zip large folders on the server and download them in parts.

## 13:17 — VM storage

Read-only libvirt storage pools and volumes. Read-only inventory: it never opens or changes a VM disk.

## 14:08 — Command line

Scan, connect, copy, cloud and ZIP jobs: the whole app from the terminal and scripts.

## 15:23 — Build it into your app

Mount the API in your FastAPI app and drop in the folder picker, using the repo’s templates.

## Recording environment

Recorded 2026-09-30 in a disposable Linux container against a demo lab built by `scripts/video/demo_lab.sh`: three Samba servers on a private 192.168.50.0/24 network, a local S3-compatible server reached through rclone, a libvirt test-driver pool and a fictional studio's files. Every SMB, S3 and mount operation in the film is real traffic to those servers. NFS is not filmed. Demo passwords are disposable. The [recording notes](docs/validation/2026-09-30-feature-tour.md) list exactly what each chapter exercises, and [docs/video](docs/video/README.md) explains how to re-record it.

Earlier recordings remain available: the [2-minute 0.3.0 feature tour](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.3.0/remotefs-0.3.0-feature-tour.mp4) and the [original 0.2.1 SMB recording](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.1/remotefs-feature-demo.mp4).

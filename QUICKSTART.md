# Run remotefs

Run remotefs on the computer that can reach your files or NAS. Open its web interface from that computer or through an encrypted tunnel from another one. SMB and NFS connections originate from the computer running remotefs.

## 1. Install

Choose one option.

### macOS with Homebrew

```sh
brew install mightymorgs/tap/remotefs
```

Homebrew installs Python and libnfs for you.

### Windows x64

Download the [0.2.1 portable ZIP](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.1/remotefs-0.2.1-windows-x64.zip) and extract it. Open PowerShell inside the extracted `remotefs` folder. Use `.\remotefs.exe` in place of `remotefs` in the commands below. Python and libnfs are bundled.

The [WinGet submission](https://github.com/microsoft/winget-pkgs/pull/432620) is awaiting review. Once accepted, install with:

```powershell
winget install --id mightymorgs.remotefs --exact --source winget
```

Open a new terminal if the `remotefs` command is not found.

### Python on Linux, macOS or Windows

With Python 3.11+ and pipx installed:

```sh
pipx install remote-fs-browser
```

Local files and SMB work without a native library. NFS additionally requires **libnfs 6 or newer**. On macOS, use `brew install libnfs`; the Windows portable download includes it. Linux distribution packages may be older: see the [system installation instructions](README.md#system-service-installs) for the pinned build, or set `LIBNFS_LIBRARY` to your compatible library's absolute path.

## 2. Create your login and start

```sh
remotefs account --username admin
remotefs serve
```

Choose a password of at least 12 characters when prompted. Open **http://127.0.0.1:8080/** and sign in. Keep the terminal open while using the app; press Ctrl+C there to stop it.

The default service listens only on this computer. It exposes your home directory, detected mounted volumes and local private network ranges, with read/write access subject to your operating-system permissions. The startup banner lists the exact roots and networks. To try it without changing files:

```sh
remotefs serve --read-only
```

To use a different port, add `--port 8090` and open http://127.0.0.1:8090/.

## 3. Browse and connect

- **Local files:** choose a root under **This Computer**, then click folders to browse. Click a file for a text preview where supported.
- **SMB:** open **Add location**, choose SMB and enter the server hostname or IP, share name, and that server's username/password. These are separate from your remotefs login. If share enumeration is unavailable, enter the share name directly.
- **NFS:** use **Add location**, choose NFS, enter the server and export path, and select version 3 or 4. The NAS must permit the service host and its NFS identity to access that export.
- **Discovery:** open **Scan network** and scan an allowed CIDR. Results display IP addresses and available DNS/NetBIOS names. A missing name does not prevent connecting by IP.
- **Favourites:** use a folder's menu to add it to the shortlist, then reopen it from the sidebar.

For a NAS outside the automatically detected ranges, restart with an explicit allowed range. For example, replace this address with your NAS address:

```sh
remotefs serve --allow-network 192.168.1.50/32
```

`--allow-network` replaces the detected network list; repeat it for additional ranges. Hostnames must resolve to permitted addresses. VPN/tunnel interfaces are not included in automatic subnet detection.

## 4. Manage files

Use the folder toolbar or **…** menu to create folders/files and upload files. Open a supported text file, edit and save it. Select checkboxes for batch operations; **Copy** or **Cut**, navigate to the destination, then **Paste**. Deletion asks for confirmation and permanently removes the selected files or folder contents.

For a direct download, use a file's **Download** action. For several files or a folder:

1. Select the items and choose ZIP.
2. Choose staging storage and a single ZIP or multipart size; start packing.
3. Open **Downloads**, wait for completion and save every part through the browser.
4. Join split parts in numeric order, then extract the resulting ZIP.

For exactly three downloaded parts, on macOS/Linux:

```sh
cat selection.zip.001 selection.zip.002 selection.zip.003 > selection.zip
unzip -t selection.zip
unzip selection.zip -d extracted
```

On Windows PowerShell, join the same three parts using the Windows binary-copy command, then extract:

```powershell
cmd /c "copy /b selection.zip.001+selection.zip.002+selection.zip.003 selection.zip"
Expand-Archive -LiteralPath .\selection.zip -DestinationPath .\extracted
```

Substitute the actual filenames and include **every** numbered part. Each part is a slice of one ZIP, not a separate archive. Once your downloads are complete, **Purge** removes the staged copies from the service host; it does not delete the original files. Packing pause/resume controls archive creation, not your browser's transfer.

## 5. Reach it from another computer

One option is to leave remotefs listening on loopback and forward it through SSH. On your viewing computer:

```sh
ssh -N -L 8080:127.0.0.1:8080 YOUR_USER@YOUR_SERVER
```

Open http://127.0.0.1:8080/ on the viewing computer. Keep the SSH connection open. If local port 8080 is occupied, use `-L 8090:127.0.0.1:8080` and open port 8090 instead.

For a trusted network or encrypted VPN, you can bind the service to a specific interface with `remotefs serve --bind YOUR_SERVER_IP`. Plain HTTP does not encrypt the login or file contents; use an encrypted tunnel or HTTPS when crossing an untrusted network. No firewall rules are created automatically.

## Background operation and updates

On macOS, create your account first, stop the foreground service, then run:

```sh
brew services start remotefs
# Stop it later:
brew services stop remotefs
```

For Linux systemd, macOS launchd or Windows startup-task installations with explicit policies, follow [system service installs](README.md#system-service-installs).

Update using the method you installed with:

```sh
brew update
brew upgrade mightymorgs/tap/remotefs
# Or, for a pipx installation:
pipx upgrade remote-fs-browser
```

For the Windows portable edition, stop the app and extract the new ZIP into a fresh directory. Your default config lives separately in `%APPDATA%\remotefs`. Restart after upgrading.

**Upgrading from token login:** run `remotefs account --username YOUR_NAME`, then restart. This migrates the existing config while retaining the saved-credential storage key. Back up both `config.json` and `saved.json` from `~/.config/remotefs` (or `%APPDATA%\remotefs` on Windows). Linux also honours `XDG_CONFIG_HOME`.

## If something fails

| Symptom | What to check |
| --- | --- |
| Browser cannot connect | Service terminal is still running; use the port printed in its banner. |
| Service requests an account | Run `remotefs account --username YOUR_NAME` interactively, using the same `--config` if applicable. |
| Forgotten login password | Run the account command again and restart the service. |
| NAS rejected by policy | Add its IP/subnet with `--allow-network`; inspect the startup banner. |
| SMB share list is empty | Enter the known share manually; enumeration is optional in Windows Python/portable installs. Check NAS credentials and permissions. |
| NFS cannot load | Install libnfs 6+ or set `LIBNFS_LIBRARY` to the compatible library. |
| NFS connects but cannot write | Check export permissions and squashed UID/GID. Some exports also require reserved source ports; see the service installation notes. |
| ZIP fails or staging is full | Ensure the configured staging directory is writable and has enough space; purge old staged jobs. |

See the [full README](README.md), [security boundaries](SECURITY.md) and [tested environments](docs/validation/2026-09-11-dogfood.md) for details.

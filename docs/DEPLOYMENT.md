# Automated deployments

The installer scripts and Ansible playbooks install **the source checkout you run them from**. Check out the commit or tag you intend to deploy first. These updated automation options are available on main; they are not part of the older v0.2.1 tag.

The service runs as root on Linux/macOS or SYSTEM on Windows. It uses Python to access local folders, SMB shares and NFS exports; connecting a share does not create an operating-system mount. Clients only need a browser. Set the policy to the directories and network ranges the service should expose.

## Start with defaults — no configuration file needed

For a normal installation, run:

```sh
remotefs
```

The first-run setup shows this computer's addresses and detected scan ranges. Press Enter to accept the defaults, choose whether other devices can connect, and create your username and password. Your home folder and mounted volumes are available automatically. Network discovery starts with detected private LAN subnets, bounded to a /24 per interface; you can choose a different CIDR in setup or in the scanner, within the service's allowed ranges.

To change the setup later, stop the service and run `remotefs setup`, then start it again with `remotefs`. The interactive network choices and ZIP folder picker described here are in the current source checkout and will ship in the next package release. Published 0.2.1 already creates your login interactively and detects local roots and networks.

### Choose where ZIPs are prepared

Select files or folders, choose **Download as ZIP**, then **Choose folder…**. Browse the local folders on the service computer, use **New folder** if needed, and click **Use this folder**. The choice is saved and available immediately, including after a restart. Until you choose another folder, ZIP preparation uses the built-in default.

These are preparation folders on the computer running remotefs. The browser chooses where the downloaded ZIP is saved on the viewing device, using its normal download settings. Downloaded ZIPs are not automatically extracted; open them with your archive application after downloading (join multipart files first).

Folder selection respects the service's allowed local roots, write permissions and any system-service restrictions. Managed deployments can disable archive preparation with an empty staging-store map. Embedding applications opt into persistent folder changes with `staging_store_writer`.

## Advanced: prepare a custom configuration

Use this section for a managed system service or a custom access policy. Ordinary interactive use does not require creating or editing JSON.

Start with `examples/config.example.json`. For example, on Linux:

```json
{
  "bind": "127.0.0.1",
  "port": 8765,
  "policy": {
    "local_roots": ["/srv/shared"],
    "network_ranges": ["192.168.1.0/24", "192.168.122.0/24"],
    "operations": ["discover", "list", "stat", "read", "mkdir", "write", "rename", "delete", "copy"]
  },
  "staging_stores": {"Downloads": "/var/lib/remotefs-downloads"}
}
```

Create the local roots before installing. All local roots and staging paths must be absolute paths on the service host. Use Windows paths such as `C:/Shared` and `C:/ProgramData/remotefs-downloads` on Windows. The installer creates missing staging directories. An empty `staging_stores` map disables archive packing. If omitted on first installation, staging uses a directory inside the private installation prefix.

An empty list of roots or networks denies that class of access. Explicitly list operations to restrict mutations; when operations are omitted, the service enables its read and write operations. Saved locations and host credentials require `discover`.

Loopback binding is accessible only on the service host. For access from another device, bind to a reachable interface or `0.0.0.0` and configure your firewall and HTTPS reverse proxy or private network access. Tailscale is one option: the browser reaches the service host, and that host must have routes and credentials for the target shares. These installers do not open firewall ports or configure TLS.

## Unattended installation

Provide a username and a private UTF-8 file containing a password of at least 12 characters. Trailing line endings are ignored. Obtain the file from your deployment secret manager; do not put passwords in command-line arguments or commit them to Git. On Unix, restrict the input files with `chmod 600`.

From the checkout on the target machine:

```bash
sudo bash scripts/linux/install.sh /private/config.json \
  --username admin --password-file /private/password

sudo bash scripts/macos/install.sh /private/config.json \
  --username admin --password-file /private/password
```

In elevated Windows PowerShell:

```powershell
& ./scripts/windows/install.ps1 -Config C:\private\config.json `
  -Username admin -PasswordFile C:\private\password
```

Alternatively, create a hashed account beforehand with `remotefs account --config /private/config.json --username admin`; then omit the username/password-file options. Existing installations can also omit them to preserve their account. A fresh installation without either form of account fails rather than prompting.

Delete your temporary input password file after deployment. The installer stores a password hash, not that plaintext password. It keeps the existing storage key and account principal during updates so saved network credentials continue to work. To rotate a login, rerun with the new username/password file. Reapplying identical credentials preserves the existing hash. Legacy token configurations are migrated to password login when credentials are supplied.

### Dependencies and options

| Platform | Default dependency setup | Service |
| --- | --- | --- |
| Linux | apt or dnf installs Python/build tools; builds pinned libnfs | systemd `remote-fs-browser` |
| macOS | Uses an existing Homebrew installation, installs Python 3.12 and libnfs | launchd `org.remote-fs-browser` |
| Windows | Installs Chocolatey if missing, then Python/build tools; builds pinned libnfs | Scheduled task `Remote filesystem browser` at startup |

Python 3.11 or newer is required. Install Homebrew as the macOS deployment user before running the installer through sudo.

- `--without-nfs` / `-WithoutNfs`: skip installing/building libnfs. SMB and local files still work. This is a dependency option, not a policy restriction; an already available library may still enable NFS.
- `--skip-dependencies` / `-SkipDependencies`: use dependencies already provisioned on the machine. Package installation still needs access to the configured Python package index. Linux/Windows still build libnfs unless the previous option is also set.
- Unix: set `REMOTE_FS_PYTHON` to an absolute Python executable path. With sudo, use `sudo env REMOTE_FS_PYTHON=/path/to/python3 bash ...`. macOS uses Homebrew Python unless dependencies are skipped.
- Windows: `-Python C:\path\python.exe` selects the Python interpreter.
- macOS with skipped dependencies and NFS enabled: also supply `LIBNFS_LIBRARY` pointing to the installed libnfs dylib.

Direct installer runs rebuild/reinstall the service and briefly interrupt active sessions. Ansible skips that work when source, options and configuration are unchanged. Both paths wait for an HTTP response before reporting success. Linux's service sandbox allows writes in the configured roots, staging stores and private configuration directory.

## Ansible

Run Ansible from a Linux or macOS controller with this checkout. Install collections for Windows targets:

```bash
ansible-galaxy collection install -r playbooks/requirements.yml
```

Use an inventory group named `filesystem_hosts`, containing hosts for the selected platform:

```ini
[filesystem_hosts]
fileserver ansible_host=192.0.2.10 ansible_user=deploy
```

Unix targets need SSH and sudo/become access. Windows targets need an administrator account and a configured Ansible Windows connection such as WinRM. Keep connection credentials in your normal inventory secret store.

Create a vars file, for example `deployment.yml`:

```yaml
remote_fs_source: /opt/remote-fs-browser-source
remote_fs_username: admin
remote_fs_password: '{{ vault_remote_fs_password }}'
remote_fs_settings:
  bind: 127.0.0.1
  port: 8765
  policy:
    local_roots: ['/srv/shared']
    network_ranges: ['192.168.1.0/24', '192.168.122.0/24']
    operations: [discover, list, stat, read, mkdir, write, rename, delete, copy]
  staging_stores:
    Downloads: /var/lib/remotefs-downloads
```

Store `vault_remote_fs_password` in a separate encrypted file using `ansible-vault create secrets.yml`. Then run:

```bash
ansible-playbook -i inventory.ini playbooks/linux/install.yml \
  -e @deployment.yml -e @secrets.yml --ask-vault-pass --ask-become-pass
```

Use `playbooks/macos/install.yml` or `playbooks/windows/install.yml` for those platforms. macOS needs `remote_fs_brew_user` set to the Homebrew owner unless dependency installation is skipped. Windows needs Windows paths in `remote_fs_source`, local roots and staging stores.

| Variable | Purpose |
| --- | --- |
| `remote_fs_source` | Target directory for public source and installer files; keep separate from the private installation prefix |
| `remote_fs_settings` | Configuration mapping staged privately on the target |
| `remote_fs_config` | Alternative: path to a configuration JSON file already on the target |
| `remote_fs_username`, `remote_fs_password` | Optional account bootstrap/rotation; required on a fresh install unless the configuration already contains a hashed account |
| `remote_fs_without_nfs` | Skip native dependency setup; default false |
| `remote_fs_skip_dependencies` | Use preinstalled dependencies; default false |
| `remote_fs_python` | Python executable; defaults to `python3` on Unix or `python` on Windows |
| `remote_fs_brew_user` | Homebrew owner on macOS |
| `remote_fs_libnfs_library` | macOS dylib path when skipping dependencies with NFS enabled |
| `remote_fs_force` | Force reinstall even if inputs are unchanged; default false |
| `remote_fs_purge` | Delete private installation data during uninstall; default false |

The playbooks copy the package and its licence notices, stage secret inputs privately, suppress secret-bearing task output, and remove temporary inputs in cleanup blocks. Use Ansible Vault or another secret manager for passwords. Never pass a plaintext password using `-e` on the command line.

Repeat runs compare configuration, credentials, source and installer options before restarting. Failed updates invalidate the success marker so the next run retries. `--check` previews file-copy changes but does not bootstrap accounts or start services. Policy updates replace the supplied policy mapping; omitted top-level settings preserve their installed values. Existing account and storage-key values are protected; use the credential variables for account rotation.

## Operations and removal

| Platform | Private installation | Status and logs |
| --- | --- | --- |
| Linux | `/opt/remote-fs-browser` | `sudo systemctl status remote-fs-browser`; `sudo journalctl -u remote-fs-browser` |
| macOS | `/opt/remote-fs-browser` | `sudo launchctl print system/org.remote-fs-browser`; `service.log` and `service-error.log` in the prefix |
| Windows | `C:\ProgramData\remote-fs-browser` | `Get-ScheduledTask -TaskName 'Remote filesystem browser'`; `service.log` and `service-error.log` in the prefix |

Back up `config.json` and `saved.json` together: the former contains the key needed to read the encrypted saved credentials in the latter. Protect both files as secrets. Installations are private to root or SYSTEM/Administrators.

Uninstall using `scripts/<platform>/uninstall.sh` (sudo) or `scripts/windows/uninstall.ps1` (elevated PowerShell). By default, this removes the service registration but keeps configuration, credentials and installed files. Add `--purge` on Unix or `-Purge` on Windows to remove the private prefix too. External local roots and external staging directories are preserved, including any staged archives.

The matching `playbooks/<platform>/uninstall.yml` accepts `remote_fs_source` and optional `remote_fs_purge: true`. After a non-purging uninstall, an install playbook run registers the service again.

## Validation

`tests/test_deployment.py` covers account setup, repeat configuration, password rotation, legacy-token migration, vault-key preservation and rejected updates. The Automated deployment checks workflow installs real systemd/launchd/Windows startup services on disposable runners, exercises authenticated file writes and staged ZIP downloads, redeploys, rotates the password, then uninstalls. Unix jobs also run the Ansible playbook twice to check idempotence. Windows runs the playbook’s PowerShell body with typed inputs and verifies repeat behavior; this does not test WinRM transport. These service tests skip native dependency setup; the separate cross-platform workflow checks the libnfs ABI and SMB/NFS protocols.

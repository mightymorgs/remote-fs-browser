# Install remotefs

## Version 0.4.0

Version 0.4.0 can mount an SMB share, NFS export or cloud connection as a folder or drive on the service host, and reconnects those mounts after restarts and Windows sign-in. Mounting uses rclone, plus WinFsp on Windows (the app offers to install it) or fuse3 on Linux; see [mounts](https://github.com/mightymorgs/remote-fs-browser/blob/main/docs/MOUNTS.md). Windows hosts now list SMB shares, and NFS connections try NFSv4, then NFSv3.

Cloud connection management and cross-storage Copy/Paste are included in 0.3.0. Homebrew includes rclone. For other installations, install [rclone](https://rclone.org/install/) on the service host for cloud access. Libvirt inventory needs the native libvirt development packages and `pipx install --force 'remote-fs-browser[libvirt]'`. See the [endpoint guide](endpoints.html).

**Mounting (next release).** To show shares and cloud connections as folders or drives on the service host, you need rclone plus `fuse3` on Linux (`sudo apt install fuse3`) or WinFsp on Windows, which the app offers to install. macOS needs only rclone 1.65+, which Homebrew installs. Start the service with `--allow-mounts`. See [Mount storage on this computer](mounts.html).

Existing pipx installations can update with `pipx upgrade remote-fs-browser`; Homebrew users can run `brew update && brew upgrade mightymorgs/tap/remotefs`. Restart your service after upgrading.

## Install a package

Choose the option for the computer that will run remotefs. Other devices only need a browser and access to that computer.

### macOS — Homebrew

[Homebrew](https://brew.sh/) installs Python, libnfs and rclone for you:

```sh
brew install mightymorgs/tap/remotefs
remotefs
```

Upgrade with `brew update` followed by `brew upgrade mightymorgs/tap/remotefs`. After setup, stop the foreground app and use `brew services start remotefs` for background operation.

### Windows — portable download

[Download remotefs 0.4.0 for Windows x64](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.4.0/remotefs-0.4.0-windows-x64.zip). Extract the ZIP, open PowerShell in the extracted `remotefs` folder, and run:

```powershell
.\remotefs.exe
```

Python and libnfs are bundled; no separate Python installation is needed. To upgrade, stop the app and extract the new release into a fresh directory. Your configuration is stored separately.

### Windows — WinGet (pending acceptance)

The [WinGet submission](https://github.com/microsoft/winget-pkgs/pull/432620) is still awaiting Microsoft review. Use the portable download above now. Once accepted, install with:

```powershell
winget install --id mightymorgs.remotefs --exact --source winget
remotefs
```

Open a new terminal if the command is not found. Once available, upgrade with `winget upgrade --id mightymorgs.remotefs --exact --source winget`.

### Linux, macOS or Windows — Python / pipx

With Python 3.11+ and [pipx](https://pipx.pypa.io/stable/installation/) installed:

```sh
pipx install remote-fs-browser
remotefs
```

Upgrade with `pipx upgrade remote-fs-browser`. Local files and SMB work with the Python package. NFS additionally needs **libnfs 6+**; Homebrew and the Windows portable edition include it. See the [deployment guide](deployment.html) for Linux native dependency installation.

### Python — pip in a virtual environment

If you prefer pip, create and activate a virtual environment first:

```sh
python -m venv .venv
# macOS / Linux (use python3 above if needed):
source .venv/bin/activate
```

On Windows PowerShell, activate it with `.\.venv\Scripts\Activate.ps1` instead. Then:

```sh
python -m pip install remote-fs-browser
remotefs
```

Use `python -m pip install --upgrade remote-fs-browser` inside that environment to upgrade. The same Python and NFS requirements apply as for pipx.

### Install from source

With Git, Python 3.11+ and pipx installed:

```sh
git clone https://github.com/mightymorgs/remote-fs-browser.git
cd remote-fs-browser
git checkout v0.4.0
pipx install .
remotefs
```

This installs the published release source. Developers can use `python -m pip install -e .` in an activated virtual environment for an editable checkout.

### Always-on services and automated deployment

The [deployment guide](deployment.html) covers Linux systemd, macOS launchd and Windows startup-task installers, plus Ansible playbooks, unattended account setup, upgrades and custom access policies. The installers deploy the source checkout you run them from; choose your release tag first.

## First launch

Version 0.2.2 guides you through network access and login on first launch, with no configuration file needed. Open the address printed at startup (default **http://127.0.0.1:8080/**) and sign in. Stop the service and run `remotefs setup` to revisit your choices.

Follow the [quickstart](quickstart.html) to connect SMB/NFS shares, scan networks, save locations, prepare ZIP downloads and reach the service from another device.


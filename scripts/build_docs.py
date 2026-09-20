"""Build GitHub Pages from the canonical Markdown documentation."""
from pathlib import Path
import re
import shutil
import markdown

root = Path(__file__).resolve().parents[1]
out = root / '_site'
out.mkdir(exist_ok=True)
style = '''body{margin:0;background:#10171e;color:#e4eaf0;font:17px/1.7 system-ui,sans-serif}main{max-width:920px;margin:auto;padding:48px 24px}a{color:#69ddd0}nav{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:48px}h1{font-size:clamp(36px,6vw,60px);line-height:1.15}h2{margin-top:48px}pre{padding:20px;background:#1c2934;overflow:auto;border-radius:10px}code{font-size:.9em}table{display:block;overflow:auto;border-collapse:collapse}td,th{border:1px solid #42525f;padding:10px;text-align:left}video{width:100%;border-radius:12px;background:#000}blockquote{border-left:3px solid #69ddd0;padding-left:20px}footer{margin-top:60px;color:#aab8c5}img{max-width:100%}'''
video = 'https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.1/remotefs-feature-demo.mp4'
home = f'''# Your files. In your browser.

Install one Python service on a computer that can reach your shares. Open a browser from another device, from anywhere with a permitted connection to the service. Browse local folders, SMB shares and NFS exports over your LAN, VPN, SSH tunnel or HTTPS setup. No operating-system mounts or remotefs agents on each file server are required.

[Get started →](quickstart.html) · [Full features and API reference](reference.html)

## Watch it install and run

<video controls preload="metadata" poster="demo-poster.jpg" aria-label="remotefs installation and file management demonstration"><source src="{video}" type="video/mp4"><track kind="captions" src="demo.vtt" srclang="en" label="English"></video>

[Download the video]({video}) · [Read the demonstration transcript](demo.html)

A 70-second feature demo using published 0.2.1: a short installation excerpt, real LAN discovery and SMB browsing through a Linux service. It shows subnet selection, saved locations, repo files, right-click actions, Shift-click selection, a verified SMB download and Unmount. This recording uses SSH over Tailscale; that is one connection option, not a requirement. NFS uses libnfs 6+.

## Install

Choose the option for the computer that will run remotefs. Other devices only need a browser and access to that computer.

### macOS — Homebrew

[Homebrew](https://brew.sh/) installs Python and libnfs for you:

```sh
brew install mightymorgs/tap/remotefs
remotefs
```

Upgrade with `brew update` followed by `brew upgrade mightymorgs/tap/remotefs`. After setup, stop the foreground app and use `brew services start remotefs` for background operation.

### Windows — portable download

[Download remotefs 0.2.2 for Windows x64](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.2/remotefs-0.2.2-windows-x64.zip). Extract the ZIP, open PowerShell in the extracted `remotefs` folder, and run:

```powershell
.\\remotefs.exe
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

On Windows PowerShell, activate it with `.\\.venv\\Scripts\\Activate.ps1` instead. Then:

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
git checkout v0.2.2
pipx install .
remotefs
```

This installs the published release source. Developers can use `python -m pip install -e .` in an activated virtual environment for an editable checkout.

### Always-on services and automated deployment

The [deployment guide](deployment.html) covers Linux systemd, macOS launchd and Windows startup-task installers, plus Ansible playbooks, unattended account setup, upgrades and custom access policies. The installers deploy the source checkout you run them from; choose your release tag first.

## First launch

Version 0.2.2 guides you through network access and login on first launch, with no configuration file needed. Open the address printed at startup (default **http://127.0.0.1:8080/**) and sign in. Stop the service and run `remotefs setup` to revisit your choices.

Follow the [quickstart](quickstart.html) to connect SMB/NFS shares, scan networks, save locations, prepare ZIP downloads and reach the service from another device.

'''
for filename, title, source in [('index.html','remotefs',home),('quickstart.html','Quickstart',(root/'QUICKSTART.md').read_text()),('reference.html','Features and API',(root/'README.md').read_text()),('deployment.html','Automated deployments',(root/'docs/DEPLOYMENT.md').read_text()),('demo.html','Demo transcript',(root/'docs/site/demo.md').read_text())]:
    body=markdown.markdown(source,extensions=['fenced_code','tables','toc'])
    body=body.replace('href="README.md','href="reference.html').replace('href="QUICKSTART.md','href="quickstart.html').replace('href="docs/DEPLOYMENT.md','href="deployment.html')
    def link(match):
        url = match.group(1)
        if url.startswith(('https:', 'http:', '#', 'mailto:')) or url.split('#')[0] in {'index.html', 'quickstart.html', 'reference.html', 'demo.html', 'deployment.html'}:
            return match.group(0)
        return 'href="https://github.com/mightymorgs/remote-fs-browser/blob/main/' + url + '"'
    body = re.sub(r'href="([^"]+)"', link, body)
    (out/filename).write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="remotefs: browser file management for local folders, SMB and NFS. Installation, quickstart and API documentation."><title>{title} — remotefs</title><style>{style}</style></head><body><main><nav><a href="index.html">remotefs</a><a href="quickstart.html">Quickstart</a><a href="reference.html">Reference</a><a href="deployment.html">Deploy</a><a href="https://github.com/mightymorgs/remote-fs-browser">GitHub</a></nav>{body}<footer>MIT licensed · Built from the repository documentation.</footer></main></body></html>')
(out/'.nojekyll').touch()

for asset in ("demo-poster.jpg", "demo.vtt"):
    shutil.copyfile(root / "docs/site" / asset, out / asset)

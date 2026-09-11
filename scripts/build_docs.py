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

```sh
pipx install remote-fs-browser
remotefs account --username admin
remotefs serve
```

Open **http://127.0.0.1:8080/** and sign in. Homebrew and Windows installation instructions are in the [quickstart](quickstart.html).
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

"""Build the static GitHub Pages guide and canonical Markdown references."""
from pathlib import Path
from html import escape
import re
import shutil
import markdown

root = Path(__file__).resolve().parents[1]
source = root / 'docs/site'
out = root / '_site'
out.mkdir(exist_ok=True)
pages = [
    ('index.html', 'One control plane for all your storage', source / 'home.html'),
    ('guide.html', 'How it works', source / 'guide.md'),
    ('install.html', 'Install', source / 'install.md'),
    ('quickstart.html', 'Quickstart', root / 'QUICKSTART.md'),
    ('reference.html', 'Features and API', root / 'README.md'),
    ('deployment.html', 'Automated deployments', root / 'docs/DEPLOYMENT.md'),
    ('endpoints.html', 'Cloud storage and libvirt', root / 'docs/ENDPOINTS.md'),
    ('mounts.html', 'Mount storage on this computer', root / 'docs/MOUNTS.md'),
    ('demo.html', 'Feature walkthrough', source / 'demo.md'),
]
links = {'README.md': 'reference.html', 'QUICKSTART.md': 'quickstart.html',
         'docs/DEPLOYMENT.md': 'deployment.html', 'docs/ENDPOINTS.md': 'endpoints.html',
         'docs/MOUNTS.md': 'mounts.html', 'MOUNTS.md': 'mounts.html'}
local_pages = {name for name, _, _ in pages}


def link(match):
    url = match.group(1)
    path, separator, fragment = url.partition('#')
    if path in links:
        return 'href="' + links[path] + separator + fragment + '"'
    if url.startswith(('https:', 'http:', '#', 'mailto:')) or path in local_pages:
        return match.group(0)
    return 'href="https://github.com/mightymorgs/remote-fs-browser/blob/main/' + url + '"'


for filename, title, path in pages:
    home = filename == 'index.html'
    body = path.read_text()
    if path.suffix == '.md':
        body = markdown.markdown(body, extensions=['fenced_code', 'tables', 'toc'])
    body = re.sub(r'href="([^"]+)"', link, body)
    script = '<script src="tour.js" defer></script>' if home else ''
    (out / filename).write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="remotefs is a self-hosted control plane for your storage: find, browse, copy and mount local disks, SMB, NFS and cloud storage from a browser, CLI, HTTP API or Python SDK.">
<title>{escape(title)} — remotefs</title><link rel="stylesheet" href="site.css">{script}</head>
<body><a class="skip" href="#main">Skip to content</a><header class="site-header"><a class="brand" href="index.html">remotefs</a><nav aria-label="Main navigation"><a href="guide.html">How it works</a><a href="endpoints.html">Storage endpoints</a><a href="install.html">Install</a><a href="reference.html">Reference</a><a href="https://github.com/mightymorgs/remote-fs-browser">GitHub</a></nav></header>
<main id="main" class="{'home' if home else 'document'}">{body}</main><footer class="site-footer"><span>remotefs / One control plane for all your storage.</span><span>MIT licensed · <a href="deployment.html">Deployment guide</a> · <a href="https://github.com/mightymorgs/remote-fs-browser">Source on GitHub</a></span></footer></body></html>''')
(out / '.nojekyll').touch()
for asset in ('demo-poster.jpg', 'walkthrough-poster.jpg', 'walkthrough.vtt', 'promo.vtt', 'site.css', 'tour.js'):
    shutil.copyfile(source / asset, out / asset)

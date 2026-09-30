"""Embed remotefs in an existing app: a job tracker that stores a delivery folder per job.

Follows the README templates: the reference API is mounted inside the host FastAPI app (with its
lifespan), the host's own login gates it through an ``authenticate`` hook, and the page uses the
``<remote-fs-browser mode="select">`` picker to return a credential-free descriptor.

  pip install remote-fs-browser uvicorn
  python examples/embed/app.py --root ~/Projects --allow-network 192.168.1.0/24
  open http://127.0.0.1:8090/
"""
import argparse
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from remote_fs_browser import Policy
from remote_fs_browser.http import create_app

HERE = Path(__file__).resolve().parent
SESSION = secrets.token_urlsafe(32)  # stands in for the host app's real login session


def build(roots, networks):
    policy = Policy(local_roots=roots, network_ranges=networks, operations=['discover', 'list', 'stat', 'read'])

    def authenticate_user(request: Request):
        # The host app already knows who is signed in; the storage API trusts that, nothing else.
        return 'tracker-user' if request.cookies.get('tracker_session') == SESSION else None

    storage = create_app(policy, authenticate=authenticate_user)

    @asynccontextmanager
    async def lifespan(app):
        async with storage.router.lifespan_context(storage):
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get('/', response_class=HTMLResponse)
    def index():
        page = HTMLResponse((HERE / 'index.html').read_text())
        page.set_cookie('tracker_session', SESSION, httponly=True, samesite='strict')
        return page

    app.mount('/storage-api', storage)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', action='append', required=True, help='Local folder the picker may browse')
    parser.add_argument('--allow-network', action='append', default=[], help='CIDR the picker may scan and connect to')
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    uvicorn.run(build(args.root, args.allow_network), host='127.0.0.1', port=args.port)

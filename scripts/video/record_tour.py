#!/usr/bin/env python3
"""Record the remotefs feature tour chapter by chapter against the demo lab (see demo_lab.sh).

Usage: python record_tour.py --out /path/to/captures [--only 02-finder ...]
Each chapter becomes <out>/<chapter>/ with frames and capture.json for render_tour.py.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from recorder import Recorder, launch

BASE = os.environ.get('REMOTEFS_URL', 'http://127.0.0.1:8080')
USER, PASSWORD = 'morgan', os.environ.get('DEMO_PASSWORD', 'demo-password-2026')
SMB_USER, SMB_PASS = 'studio', os.environ.get('SMB_PASSWORD', 'harbour-lane-demo')
CHAPTERS = {}


def chapter(name, title):
    def wrap(fn):
        CHAPTERS[name] = (title, fn)
        return fn
    return wrap


def row(page, name):
    return page.locator('.manager-file-row').filter(has_text=name).first


def tick(page, name):
    return page.get_by_role('checkbox', name=f'Select {name}', exact=True)


def button(page, name, exact=True):
    return page.get_by_role('button', name=name, exact=exact).filter(visible=True).first


def menu_item(page, label):
    return page.locator('button').filter(has_text=label).filter(visible=True).last


def text(page, value, exact=True):
    return page.get_by_text(value, exact=exact).filter(visible=True).first


async def sign_in(page):
    await page.goto(BASE + '/')
    await page.fill('#username', USER)
    await page.fill('#password', PASSWORD)
    await page.get_by_role('button', name='Sign in').click()
    await page.wait_for_timeout(1200)


async def open_manager(page):
    await page.goto(BASE + '/manager')
    await page.wait_for_timeout(1400)


async def run_scan(r, page):
    start = page.get_by_role('button', name='Start scan').or_(page.get_by_role('button', name='Rescan')).filter(visible=True).first
    await r.click(start, pause=0.3)
    r.fast(3)
    await page.get_by_text('services found').filter(has_text='3').first.wait_for(timeout=30000)
    await page.get_by_text('Scanned addresses 1–254').first.wait_for(timeout=30000)
    r.normal()


async def submit_smb(r, page):
    submit = page.locator('button').filter(has_text='Sign in and list shares').or_(
        page.locator('button').filter(has_text='Use saved credentials')).filter(visible=True).first
    await r.click(submit, pause=1.6)


async def go_home(r):
    await r.click(text(r.page, '/home/morgan'), pause=0.9)


# ---------------------------------------------------------------------------
@chapter('01-sign-in', 'Sign in')
async def sign_in_chapter(r, page):
    await page.context.clear_cookies()
    await page.goto(BASE + '/')
    await page.wait_for_timeout(600)
    await r.start()
    r.caption('Open remotefs in any browser', 'The service runs on a machine that can reach your storage. You just need a browser.')
    await r.wait(1.2)
    await r.type(page.locator('#username'), USER)
    await r.type(page.locator('#password'), PASSWORD, cps=22)
    r.mark('signin')
    await r.click(page.get_by_role('button', name='Sign in'), pause=1.2)
    await open_manager(page)
    r.caption('One window for everything', 'Local folders, network shares, cloud buckets and VM storage live in the sidebar.')
    for label in ['SHORTLIST', 'THIS MACHINE', 'CLOUD STORAGE', 'NETWORK']:
        await r.hover(text(page, label, exact=False), dx=0.2, pause=0.35)
    await r.hover(row(page, 'Photos'), dx=0.3, pause=0.6)
    await r.stop()


@chapter('02-finder', 'Work like Finder')
async def finder(r, page):
    await open_manager(page)
    await r.start()
    r.caption('Feels like Finder', 'Click a folder to open it. Breadcrumbs and Back take you up again.')
    await r.click(row(page, 'Photos'), dx=0.3, pause=0.9)
    await r.click(row(page, '2026-09 Harbour shoot'), dx=0.3, pause=1.1)
    r.caption('Tick to select, Shift-click for a range', 'Just like a Mac list view: pick one file, then Shift-click to grab everything in between.')
    await r.click(tick(page, 'IMG_4121.jpg'), pause=0.7)
    r.mark('shift')
    await r.click(tick(page, 'IMG_4126.jpg'), modifiers=['Shift'], pause=1.2)
    r.caption('⌘-click to add or drop one file', 'Fine-tune the selection without starting over.')
    await r.click(tick(page, 'IMG_4123.jpg'), modifiers=['Meta'], pause=0.9)
    await r.click(tick(page, 'IMG_4129.jpg'), modifiers=['Meta'], pause=1.2)
    await r.press('Escape', ['Esc'], pause=0.7)
    r.caption('Drag to select', 'Draw a box across the list. Rows light up as the box touches them.')
    r.mark('drag')
    await r.drag((820, 150), (700, 480), duration=1.6, pause=1.4)
    r.caption('Right-click for everything else', 'Download, zip, copy, cut, rename, shortlist and delete, all in one menu.')
    r.mark('menu')
    await r.right_click(row(page, 'IMG_4122.jpg'), dx=0.45, pause=0.6)
    for item in ['Download as multi-part zip…', 'Copy', 'Cut', 'Delete']:
        await r.hover(menu_item(page, item), dx=0.3, pause=0.45)
    await r.press('Escape', ['Esc'], pause=0.7)
    r.caption('Get Info on any file', 'Size, type and modification time, straight from the storage.')
    await r.right_click(row(page, 'IMG_4127.jpg'), dx=0.45, pause=0.6)
    await r.click(menu_item(page, 'Get info'), dx=0.3, pause=2.2)
    await r.press('Escape', ['Esc'], pause=0.7)
    r.caption('Keyboard shortcuts work too', '⌘A selects all. ⌘C, ⌘X and ⌘V copy, cut and paste. ⌘/ lists the rest.')
    await r.hover((640, 600), pause=0.2)
    await r.press('Meta+a', ['⌘', 'A'], pause=1.2)
    await r.press('Escape', ['Esc'], pause=0.6)
    r.caption('Filter and sort', 'Type to narrow the folder. Click a column to sort.')
    await r.type(page.get_by_placeholder('Filter this folder'), '412', cps=6, pause=1.2)
    await r.type(page.get_by_placeholder('Filter this folder'), '', pause=0.6)
    await r.click(button(page, 'Size', exact=False), pause=1.2)
    await r.press('Meta+/', ['⌘', '/'], pause=2.6)
    await r.press('Escape', ['Esc'], pause=0.6)
    await r.stop()


@chapter('03-organise', 'Organise files')
async def organise(r, page):
    await open_manager(page)
    await r.start()
    r.caption('Make a folder', 'New folder is in the toolbar and on the right-click menu.')
    await r.right_click((700, 520), pause=0.7)
    await r.click(menu_item(page, 'New folder'), dx=0.3, pause=0.8)
    await r.type(None, 'Client picks', cps=11, pause=0.5)
    await r.press('Enter', pause=1.2)
    r.caption('Copy, then paste somewhere else', 'Select files, copy them, open the destination and paste.')
    await r.click(row(page, 'Photos'), dx=0.3, pause=0.8)
    await r.click(row(page, '2026-09 Harbour shoot'), dx=0.3, pause=1.0)
    await r.drag((820, 190), (700, 320), duration=1.0, pause=0.7)
    await r.press('Meta+c', ['⌘', 'C'], pause=0.8)
    r.mark('paste')
    await go_home(r)
    await r.click(row(page, 'Client picks'), dx=0.3, pause=0.9)
    await r.press('Meta+v', ['⌘', 'V'], pause=2.0)
    r.caption('Rename in place', 'Right-click, Rename, type. Done.')
    await r.right_click(row(page, 'IMG_4122.jpg'), dx=0.45, pause=0.6)
    await r.click(menu_item(page, 'Rename'), dx=0.3, pause=0.7)
    await r.type(None, 'hero-option-A.jpg', cps=12, pause=0.5)
    await r.press('Enter', pause=1.4)
    r.caption('Open and edit text files', 'Notes, CSVs and Markdown open in a built-in editor and save back to the same storage.')
    await go_home(r)
    await r.click(row(page, 'Launch kit'), dx=0.3, pause=0.9)
    await r.click(row(page, 'README.md'), dx=0.3, pause=1.2)
    editor = page.locator('dialog[open] textarea').first
    await r.click(editor, dx=0.6, dy=0.3, pause=0.3)
    await page.keyboard.press('Control+End')
    await r.type(None, '- Shortlisted picks: Client picks folder\n', cps=16, clear=False, pause=0.6)
    await r.click(page.locator('dialog[open] button').filter(has_text='Save').first, pause=1.6)
    await r.stop()


@chapter('04-network-scan', 'Find network shares')
async def network_scan(r, page):
    await open_manager(page)
    await r.start()
    r.caption('Find every file server on your network', 'Scan network probes the subnets you allow for SMB and NFS services.')
    await r.click(text(page, 'Scan network'), pause=0.9)
    await r.hover(page.locator('input').filter(visible=True).first, pause=0.8)
    r.mark('scan')
    await run_scan(r, page)
    r.caption('Names, not just addresses', 'Each device shows its DNS name, NetBIOS name and IP, so you can tell the NAS from the reception PC.')
    r.mark('scan-done')
    await r.wait(1.0)
    for col in ['studio-nas.lan', 'STUDIO-NAS', '192.168.50.10']:
        await r.hover(text(page, col), pause=0.6)
    await r.hover(text(page, 'BACKUP-BOX'), pause=0.8)
    r.caption('Map a share in two clicks', 'Sign in with the NAS account. Tick Save to keep the login encrypted on the service host.')
    r.mark('map')
    await r.click(page.get_by_role('button', name='Map').filter(visible=True).first, pause=0.9)
    await r.type(page.get_by_label('Username', exact=True), SMB_USER, pause=0.3)
    await r.type(page.get_by_label('Password', exact=True), SMB_PASS, cps=24, pause=0.4)
    await r.click(text(page, 'Save these credentials for this host'), dx=0.1, pause=0.6)
    await submit_smb(r, page)
    r.caption('Shares appear in the sidebar', 'No drive letters and no mount commands. Nothing is mounted on your computer or the server.')
    r.mark('shares')
    for share in ['Projects', 'Media', 'Archive']:
        await r.hover(text(page, share), dx=0.3, pause=0.5)
    await r.click(text(page, 'Projects'), dx=0.3, pause=1.2)
    await r.click(row(page, 'Harbour Lane Rebrand'), dx=0.3, pause=1.0)
    await r.click(row(page, 'brief.md'), dx=0.3, pause=2.0)
    await r.press('Escape', ['Esc'], pause=0.8)
    await r.stop()


@chapter('05-mount', 'Mount and unmount')
async def mount(r, page):
    await r.start()
    r.caption('Right-click a server for its options', 'List shares, reconnect as someone else, copy its address, forget the saved login, or unmount.')
    host = page.locator('button').filter(has_text='studio-nas.lan').filter(visible=True).first
    await r.right_click(host, dx=0.4, pause=0.8)
    for item in ['Reconnect as a different user', 'Copy IP address', 'Forget stored credentials']:
        await r.hover(menu_item(page, item), dx=0.3, pause=0.5)
    r.caption('Unmount when you are done', 'The connection closes. Nothing was ever mounted on your computer, and your files stay put.')
    r.mark('unmount')
    await r.click(menu_item(page, 'Unmount'), dx=0.3, pause=1.6)
    r.caption('Saved logins reconnect in one click', 'The scan shows which servers already have a stored login.')
    await r.click(text(page, 'Scan network'), pause=0.8)
    await run_scan(r, page)
    await r.wait(0.6)
    await r.hover(text(page, 'Stored'), pause=0.9)
    await r.click(page.get_by_role('button', name='Map').filter(visible=True).first, pause=1.0)
    await r.hover(text(page, 'Saved for 192.168.50.10', exact=False), dx=0.3, pause=0.8)
    await submit_smb(r, page)
    r.caption('Map as many servers as you like', 'Each server keeps its own login. Here the backup box joins the NAS in the sidebar.')
    await r.click(text(page, 'Scan network'), pause=0.8)
    await r.wait(0.4)
    await r.click(page.get_by_role('button', name='Map').filter(visible=True).nth(1), pause=0.8)
    new = page.get_by_label('Username', exact=True)
    await r.type(new, SMB_USER, pause=0.3)
    await r.type(page.get_by_label('Password', exact=True), SMB_PASS, cps=24, pause=0.3)
    await r.click(text(page, 'Save these credentials for this host'), dx=0.1, pause=0.4)
    await submit_smb(r, page)
    await r.click(text(page, 'Backups'), dx=0.3, pause=1.2)
    await r.click(row(page, 'laptop-morgan'), dx=0.3, pause=1.4)
    await r.stop()


@chapter('06-shortlist', 'Shortlist favourites')
async def shortlist(r, page):
    await r.start()
    r.caption('Keep favourite folders one click away', 'Star a folder, or right-click it and choose Shortlist folder.')
    await r.click(text(page, 'Projects'), dx=0.3, pause=1.0)
    r.mark('star')
    await r.click(row(page, 'Harbour Lane Rebrand').get_by_role('button').filter(has_text='☆'), pause=1.2)
    await go_home(r)
    await r.right_click(row(page, 'Launch kit'), dx=0.4, pause=0.7)
    await r.click(menu_item(page, 'Shortlist folder'), dx=0.3, pause=1.2)
    r.caption('It remembers across sessions', 'Shortlisted network folders reopen with the saved login, even after a reload.')
    await page.reload()
    await page.wait_for_timeout(1500)
    await r.hover(text(page, 'SHORTLIST', exact=False), dx=0.2, pause=0.6)
    await r.click(page.locator('button').filter(has_text='Harbour Lane Rebrand').filter(visible=True).first, dx=0.3, pause=1.8)
    r.caption('Right-click a shortlist entry to manage it', 'Open it, copy its path, or forget it.')
    await r.right_click(page.locator('button').filter(has_text='Launch kit').filter(visible=True).first, dx=0.3, pause=1.0)
    await r.hover(menu_item(page, 'Copy path'), dx=0.3, pause=0.5)
    await r.hover(menu_item(page, 'Forget'), dx=0.3, pause=0.8)
    await r.press('Escape', ['Esc'], pause=0.6)
    await r.stop()


@chapter('07-cloud', 'Copy across storage')
async def cloud(r, page):
    await open_manager(page)
    await r.start()
    r.caption('Add cloud storage from the sidebar', 'S3 and S3-compatible storage, Backblaze B2, Dropbox, Google Drive, OneDrive, WebDAV and Azure Blob.')
    await r.click(text(page, 'Add / manage'), pause=0.9)
    prov = page.locator('select').filter(visible=True).first
    await r.hover(prov, pause=0.6)
    await r.type(page.get_by_label('Connection name', exact=True), 'Studio S3', pause=0.3)
    await r.type(page.get_by_label('S3 provider (AWS, Minio, Other…)', exact=True), 'Other', pause=0.2)
    await r.type(page.get_by_label('Access key ID', exact=True), 'studio-demo', pause=0.2)
    await r.type(page.get_by_label('Secret access key', exact=True), 'not-a-real-secret', cps=26, pause=0.2)
    await r.type(page.get_by_label('Region', exact=True), 'us-east-1', pause=0.2)
    await r.type(page.get_by_label('Endpoint URL (optional for AWS)', exact=True), 'http://127.0.0.1:9000', cps=20, pause=0.2)
    await r.type(page.get_by_placeholder('/my-bucket/projects'), '/studio-archive', pause=0.4)
    await r.click(text(page, 'Save & connect', exact=False), pause=2.0)
    r.caption('Copy from your computer…', 'Select a folder and copy it, just like in Finder.')
    await go_home(r)
    r.mark('copy')
    await r.click(tick(page, 'Launch kit'), pause=0.5)
    await r.press('Meta+c', ['⌘', 'C'], pause=0.8)
    r.caption('…and paste into the cloud', 'The service moves the bytes directly. Nothing goes through your browser.')
    await r.click(text(page, 'Studio S3'), dx=0.3, pause=1.2)
    r.mark('paste')
    await r.press('Meta+v', ['⌘', 'V'], pause=2.4)
    await r.click(row(page, 'Launch kit'), dx=0.3, pause=1.2)
    r.caption('Folders, images and documents arrive intact', 'Open files in the bucket to check them.')
    await r.click(row(page, 'README.md'), dx=0.3, pause=2.2)
    await r.press('Escape', ['Esc'], pause=0.6)
    r.caption('The same trick works for network shares', 'Copy from S3 onto the NAS (via the shortlist), or between any two connections.')
    await r.click(tick(page, 'schedule.csv'), pause=0.4)
    await r.press('Meta+c', ['⌘', 'C'], pause=0.6)
    await r.click(page.locator('button').filter(has_text='Harbour Lane Rebrand').filter(visible=True).first, dx=0.3, pause=1.6)
    await r.press('Meta+v', ['⌘', 'V'], pause=2.2)
    await r.stop()


@chapter('08-downloads', 'Big downloads')
async def downloads(r, page):
    await open_manager(page)
    await r.start()
    r.caption('Download big folders in parts', 'Zip a large selection on the server and split it into parts that are easy to download.')
    await r.click(row(page, 'Footage'), dx=0.3, pause=0.9)
    await r.press('Meta+a', ['⌘', 'A'], pause=0.7)
    r.mark('zip')
    await r.click(button(page, 'Zip…'), pause=1.2)
    r.caption('Choose where the ZIP is built and how big each part is', 'Packing happens on the server, using its disk, not yours.')
    await r.hover(text(page, 'BUILD THE ZIP ON', exact=False), dx=0.1, pause=0.4)
    await r.hover(page.get_by_text('/srv/remotefs/staging').filter(visible=True).first, pause=0.8)
    await r.click(button(page, 'Custom'), pause=0.7)
    custom = page.locator('input[type=number]').filter(visible=True).first
    if await custom.count():
        await r.type(custom, '40', pause=0.6)
    await r.click(button(page, 'Start packing'), pause=0.6)
    r.caption('Pause and resume packing', 'Jobs keep running on the server even if you close this view.')
    await r.click(button(page, 'Downloads', exact=False), pause=0.4)
    pause = page.get_by_role('button', name='Pause packing').filter(visible=True).first
    if await pause.count():
        await r.click(pause, pause=1.4)
        await r.click(page.get_by_role('button', name='Resume packing').filter(visible=True).first, pause=0.4)
    r.fast(4)
    await page.get_by_text('Ready to download', exact=False).filter(visible=True).first.wait_for(timeout=120000)
    r.normal()
    r.mark('parts')
    r.caption('Download each part, then free the space', 'Parts resume if a download drops. Purge removes the staged copy when you are done.')
    links = page.get_by_role('button', name='Show ready part links').filter(visible=True)
    if await links.count():
        await r.click(links.first, pause=1.0)
    for name in ['.001', '.002', '.003']:
        loc = page.get_by_text(name, exact=False).filter(visible=True)
        if await loc.count():
            await r.hover(loc.first, pause=0.5)
    purge = page.locator('button').filter(has_text='Purge').filter(visible=True)
    if await purge.count():
        await r.hover(purge.first, pause=1.2)
    await r.stop()


@chapter('09-vm', 'VM storage')
async def vm(r, page):
    await open_manager(page)
    await r.start()
    r.caption('See your VM storage too', 'Connect to a hypervisor the administrator has configured, and browse its storage pools.')
    await r.click(text(page, '+ Add a location'), pause=0.8)
    await r.click(text(page, 'Libvirt pools'), pause=0.9)
    await r.click(button(page, 'Open hypervisor'), pause=1.4)
    r.caption('Volumes, sizes and formats at a glance', 'Read-only inventory: remotefs never opens or changes a VM disk.')
    await r.click(row(page, 'vm-images'), dx=0.3, pause=1.4)
    for name in ['render-node-01.qcow2', 'asset-server.qcow2', 'ubuntu-24.04.iso']:
        await r.hover(row(page, name), dx=0.3, pause=0.6)
    await r.right_click(row(page, 'render-node-01.qcow2'), dx=0.4, pause=0.7)
    await r.click(menu_item(page, 'Get info'), dx=0.3, pause=2.2)
    await r.press('Escape', ['Esc'], pause=0.6)
    await r.stop()


class Shell:
    """One persistent bash; every command shown on screen is exactly the one that runs."""
    def __init__(self, cwd, env):
        self.cwd, self.env = cwd, env

    async def open(self):
        self.proc = await asyncio.create_subprocess_exec('bash', '--noprofile', '--norc', cwd=self.cwd, env=self.env,
                                                         stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.STDOUT)

    async def run(self, command):
        marker = '__RFS_DONE__'
        self.proc.stdin.write(f'{command}\necho {marker}\n'.encode()); await self.proc.stdin.drain()
        lines = []
        while True:
            raw = (await self.proc.stdout.readline()).decode(errors='replace').rstrip('\n')
            if raw == marker: return lines
            lines.append(raw)


async def terminal(r, page, shell, steps):
    for step in steps:
        if step[0] == '#':
            await page.evaluate('t => term.comment(t)', step[1:].strip()); await r.wait(0.9); continue
        if step == 'clear':
            await page.evaluate('term.clear()'); continue
        await page.evaluate('term.prompt()'); await r.wait(0.5)
        for ch in step:
            await page.evaluate('c => term.key(c)', ch)
            await asyncio.sleep(r.rng.uniform(0.025, 0.07))
        await r.wait(0.35)
        output = await shell.run(step)
        for line in output:
            await page.evaluate('t => term.out(t)', line)
            await asyncio.sleep(0.03)
        await r.wait(1.3 if output else 0.4)


def lab_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith('RCLONE')}
    env.update(REMOTEFS_URL=BASE, REMOTEFS_PASSWORD=PASSWORD, XDG_CONFIG_HOME=str(Path(os.environ.get('RFS_CLI_HOME', '/tmp/rfs-cli'))),
               PATH=f"{Path(os.environ.get('VENV', '/opt/rfv')) / 'bin'}:{env.get('PATH', '')}", PS1='')
    Path(env['XDG_CONFIG_HOME']).mkdir(parents=True, exist_ok=True)
    return env


TERMINAL = 'file://' + str(Path(__file__).resolve().parent / 'terminal.html')


@chapter('10-cli', 'Command line')
async def cli(r, page):
    shell = Shell('/home/morgan', lab_env()); await shell.open()
    await page.goto(TERMINAL); await page.wait_for_timeout(500)
    await r.start()
    r.caption('Everything in the app works from the terminal', 'The remotefs command talks to the same service, so scripts and cron jobs get the same storage.')
    await terminal(r, page, shell, [
        '# sign in with the same account as the browser',
        'printf %s "$REMOTEFS_PASSWORD" | remotefs login --username morgan --password-stdin',
    ])
    r.caption('Scan the network', 'Same scan as the Scan button: DNS name, NetBIOS name and address for every file server.')
    r.mark('cli-scan')
    await terminal(r, page, shell, [
        "remotefs scan --ranges 192.168.50.0/24 | jq -r '.hosts[] | [.host, .name, .netbios_name] | @tsv'",
    ])
    r.caption('List shares with the login saved in the app', 'Credentials stay encrypted on the service. The CLI only uses their ID.')
    await terminal(r, page, shell, [
        "CRED=$(remotefs credentials list | jq -r '.credentials[0].id')",
        "remotefs shares 192.168.50.10 --credential-id $CRED | jq -r '.shares[].name'",
        'clear',
    ])
    r.caption('Connect, list and read files', 'connect returns a session ID; ls, get, put, copy, rename and remove all take it.')
    await terminal(r, page, shell, [
        'NAS=$(remotefs connect --type smb --host 192.168.50.10 --share Projects --credential-id $CRED | jq -r .id)',
        "remotefs ls $NAS / | jq -r '.entries[] | [.type, .name] | @tsv'",
        'remotefs get $NAS "/Read me first.txt" -',
    ])
    r.caption('Copy between storage, from a script', 'Copy a file from this machine straight onto the NAS. The service moves the bytes.')
    r.mark('cli-copy')
    await terminal(r, page, shell, [
        'HOME_S=$(remotefs connect --type local --root /home/morgan | jq -r .id)',
        'remotefs copy $HOME_S "/Documents/Invoice 2026-114.pdf" "/Invoice 2026-114.pdf" --target-session $NAS',
        "remotefs ls $NAS / | jq -r '.entries[].name'",
        'clear',
    ])
    r.caption('Cloud connections, ZIP jobs and favourites too', 'remotes, downloads and saved cover the rest of the app. Run remotefs --help for the full list.')
    await terminal(r, page, shell, [
        "remotefs remotes list | jq -r '.[] | [.label, .provider] | @tsv'",
        "remotefs downloads create --session $HOME_S --paths /Photos --store 'Studio scratch' --part-size 41943040 | jq -r '[.name, .status] | @tsv'",
        "remotefs downloads list | jq -r '.jobs[] | [.name, .status, .stage] | @tsv'",
        "remotefs saved list | jq -r '.locations[].label'",
        'remotefs --help | sed -n "1,4p"',
    ])
    await r.wait(1.5)
    await r.stop()


@chapter('11-embed', 'Build it into your app')
async def embed(r, page):
    shell = Shell(str(Path(__file__).resolve().parents[2]), lab_env()); await shell.open()
    await page.goto(TERMINAL); await page.wait_for_timeout(500)
    await r.start()
    r.caption('Drop the picker into your own app', 'The repo ships the templates: mount the API inside your FastAPI app and add one custom element.')
    await terminal(r, page, shell, [
        '# examples/embed: a job tracker built from the README templates',
        "sed -n '/storage = create_app/,/app.mount/p' examples/embed/app.py",
    ])
    r.caption('Mount the API and add the element', 'Your login protects it through an authenticate hook. No React, Vue or build step needed.')
    await terminal(r, page, shell, [
        "grep -E 'remote-fs-browser mode|RemoteFsClient|path-selected' examples/embed/index.html",
        'python examples/embed/app.py --root /home/morgan --allow-network 192.168.50.0/24 >/tmp/embed.log 2>&1 &',
        'sleep 2; curl -s -o /dev/null -w "%{http_code}\\n" http://127.0.0.1:8090/',
    ])
    await page.goto('http://127.0.0.1:8090/'); await page.wait_for_timeout(900)
    r.caption('Your users pick a folder…', 'Here a job tracker asks where a job’s files live.')
    r.mark('embed')
    await r.hover(page.locator('input').first, pause=0.5)
    await r.click(page.locator('#choose'), pause=1.4)
    await r.click(page.locator('remote-fs-browser').get_by_text('morgan', exact=True), pause=1.2)
    await r.click(page.locator('remote-fs-browser').get_by_text('Launch kit', exact=True), pause=1.2)
    r.caption('…and your app gets a descriptor, never a password', 'Store it with your record. The service resolves access when the folder is opened again.')
    await r.click(page.locator('remote-fs-browser').get_by_role('button', name='Select this folder'), pause=1.2)
    await r.hover(page.locator('#descriptor'), pause=2.5)
    await shell.run('kill %1')
    await r.stop()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    names = args.only or list(CHAPTERS)
    async with async_playwright() as p:
        browser, context = await launch(p)
        page = await context.new_page()
        await sign_in(page)
        for name in names:
            title, fn = CHAPTERS[name]
            print('recording', name, flush=True)
            r = Recorder(page, args.out / name)
            try:
                await fn(r, page)
            except Exception:
                await page.screenshot(path=str(args.out / f'{name}-failed.png'))
                if r.t0 is not None:
                    await r.stop()
                raise
            meta = json.loads((args.out / name / 'capture.json').read_text())
            meta['title'] = title
            (args.out / name / 'capture.json').write_text(json.dumps(meta, indent=1))
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())

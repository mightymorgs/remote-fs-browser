#!/usr/bin/env python3
"""Write the fictional studio files used by the demo lab. Usage: demo_lab_files.py LAB_DIR HOME_DIR"""
import os
import random
import sys
from pathlib import Path
from PIL import Image, ImageDraw

lab = Path(sys.argv[1])
rng = random.Random(2026)


def text(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def photo(path, hue):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new('RGB', (1600, 1067))
    d = ImageDraw.Draw(img)
    for y in range(1067):
        t = y / 1067
        d.line([(0, y), (1600, y)], fill=(int(40 + 150 * t * hue[0]), int(70 + 120 * (1 - t) * hue[1]), int(110 + 120 * hue[2])))
    for _ in range(6):
        x, y, r = rng.randrange(1600), rng.randrange(500, 1067), rng.randrange(80, 260)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(rng.randrange(30, 90),) * 3)
    img.save(path, quality=88)


def blob(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as out:
        left = size
        while left:
            chunk = min(left, 1 << 20)
            out.write(os.urandom(chunk))
            left -= chunk


def pdf(path, title):
    body = f'BT /F1 18 Tf 72 720 Td ({title}) Tj ET'.encode()
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
            b'<< /Length %d >>stream\n' % len(body) + body + b'\nendstream', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out)); out += b'%d 0 obj\n' % i + obj + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(bytes(out))


home = Path(sys.argv[2])
kit = home / 'Launch kit'
text(kit / 'README.md', '# Harbour Lane launch kit\n\nEverything the print shop and web team need for Monday.\n\n- Hero shot: product-shot.png\n- Run sheet: schedule.csv\n')
text(kit / 'schedule.csv', 'day,time,task,owner\nMon,09:00,Print proofs,Ari\nMon,14:00,Web embargo lifts,Sam\nTue,10:00,Social posts,Jo\n')
text(kit / 'Approved/launch-notes.txt', 'Final copy approved by client.\n')
photo(kit / 'product-shot.png', (0.9, 0.4, 0.6))
shoot = home / 'Photos/2026-09 Harbour shoot'
for i in range(18):
    photo(shoot / f'IMG_{4120 + i}.jpg', (rng.random(), rng.random(), rng.random()))
text(home / 'Documents/Quote - Harbour Lane.md', '# Quote\n\nBrand refresh, photography and launch kit.\n')
text(home / 'Documents/Meeting notes.txt', 'Tuesday: client wants the warmer palette.\n')
pdf(home / 'Documents/Invoice 2026-114.pdf', 'Invoice 2026-114')
blob(home / 'Footage/drone-flyover-4k.mov', 96 * 1024 * 1024)
blob(home / 'Footage/interview-take-3.mov', 18 * 1024 * 1024)
(home / 'Deliverables').mkdir(parents=True, exist_ok=True)

shares = lab / 'shares'
proj = shares / 'STUDIO-NAS/Projects'
for name in ['Harbour Lane Rebrand', 'Autumn Campaign', 'Website 2027', 'Brand Guidelines']:
    text(proj / name / 'brief.md', f'# {name}\n\nScope, timeline and contacts.\n')
    text(proj / name / 'contacts.csv', 'name,role\nAri,Producer\nSam,Designer\n')
text(proj / 'Studio rates 2026.csv', 'service,day rate\nPhotography,1400\nDesign,1100\n')
text(proj / 'Read me first.txt', 'Projects live here. Archive anything older than a year.\n')
for i in range(6):
    photo(shares / f'STUDIO-NAS/Media/Stills/still-{i + 1:02}.jpg', (rng.random(), rng.random(), rng.random()))
for year in ['2024', '2025']:
    text(shares / f'STUDIO-NAS/Archive/{year}/index.txt', f'Closed projects from {year}.\n')
text(shares / 'BACKUP-BOX/Backups/laptop-morgan/README.txt', 'Nightly backup target.\n')
blob(shares / 'BACKUP-BOX/Backups/laptop-morgan/home-2026-09-29.tar', 4 * 1024 * 1024)
for n in range(1, 5):
    pdf(shares / f'RECEPTION/Scans/scan-2026-09-{20 + n:02}.pdf', f'Scanned document {n}')
print(f'Demo files written under {lab}')

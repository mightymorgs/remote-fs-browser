#!/usr/bin/env python3
"""Edit recorded chapters (record_tour.py) into the walkthrough, per-chapter videos and the promo cut.

Usage: python render_tour.py --capture /path/to/captures --out /path/to/output [--only walkthrough|promo]
Requires ffmpeg (libx264) and Pillow. Uses Inter when installed, else DejaVu Sans (see --font-dir).
Outputs:
  chapters/NN-slug.mp4 + .vtt   one video per chapter, each with its own title card
  <walkthrough asset>.mp4       all chapters, with embedded chapter markers
  walkthrough.vtt, chapters.json
  <promo asset>.mp4, promo.vtt  the short marketing cut
  posters/*.jpg
"""
import argparse
import json
import subprocess
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
W, H, FPS = 1920, 1080, 30
INK, BLUE, NAVY, MUTED, PAPER = '#172747', '#3f6fd1', '#14223f', '#536481', '#eef2f8'
TITLE_SECONDS, XFADE = 2.8, 0.45


# ---------------------------------------------------------------- helpers
def run(cmd):
    subprocess.run(cmd, check=True)


def stamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


class Fonts:
    def __init__(self, font_dir):
        inter = Path(font_dir or '/usr/share/fonts/opentype/inter')
        dejavu = Path('/usr/share/fonts/truetype/dejavu')
        pick = lambda name, fallback: str(inter / name) if (inter / name).exists() else str(dejavu / fallback)
        self.paths = {'regular': pick('Inter-Regular.otf', 'DejaVuSans.ttf'), 'medium': pick('Inter-Medium.otf', 'DejaVuSans.ttf'),
                      'semibold': pick('Inter-SemiBold.otf', 'DejaVuSans-Bold.ttf'), 'bold': pick('Inter-Bold.otf', 'DejaVuSans-Bold.ttf'),
                      'mono': str(dejavu / 'DejaVuSansMono.ttf')}

    def __call__(self, weight, size):
        return ImageFont.truetype(self.paths[weight], size)


def wrap(draw, text, font, width):
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = f'{line} {word}'.strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line); line = word
    return lines + ([line] if line else [])


def gradient(size, top, bottom):
    img = Image.new('RGB', size, top)
    d = ImageDraw.Draw(img)
    (r1, g1, b1), (r2, g2, b2) = Image.new('RGB', (1, 1), top).getpixel((0, 0)), Image.new('RGB', (1, 1), bottom).getpixel((0, 0))
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        d.line([(0, y), (size[0], y)], fill=(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t)))
    return img


# ---------------------------------------------------------------- capture timing
class Capture:
    def __init__(self, path, speedups=(), speed=1.0):
        self.dir = Path(path)
        data = json.loads((self.dir / 'capture.json').read_text())
        self.frames, self.cues, self.marks, self.duration = data['frames'], data['cues'], data['marks'], data['duration']
        self.segments = sorted([(0.0, 1.0)] + [(s['t'], s['factor']) for s in data['speed']])
        # Edit-time speed-ups: [{"from": s, "to": s, "factor": f}] on top of the recorder's own.
        self.speedups, self.speed = list(speedups), speed
        self.edges = sorted({s for s, _ in self.segments} | {x for u in self.speedups for x in (u['from'], u['to'])})

    def factor(self, t):
        f = 1.0
        for start, factor in self.segments:
            if start <= t: f = factor
        for u in self.speedups:
            if u['from'] <= t < u['to']: f *= u['factor']
        return f * self.speed

    def out(self, t, origin=0.0, speed=1.0):
        """Output seconds for capture time t, counting from capture time origin."""
        total, prev = 0.0, origin
        for edge in [e for e in self.edges if origin < e < t] + [t]:
            total += (edge - prev) / (self.factor(prev) * speed)
            prev = edge
        return total

    def concat(self, dest, start, end, speed=1.0):
        """ffconcat list playing capture [start, end] at recorded pace (with speed segments)."""
        frames = self.frames
        first = max([i for i, f in enumerate(frames) if f['t'] <= start] or [0])
        lines = ['ffconcat version 1.0']
        last = None
        for i in range(first, len(frames)):
            f = frames[i]
            a = max(f['t'], start)
            if a >= end: break
            b = min(frames[i + 1]['t'] if i + 1 < len(frames) else end, end)
            dur = self.out(b, a, speed)
            if dur <= 0.0005: continue
            path = (self.dir / f['file']).resolve()
            lines += [f"file '{path}'", f'duration {dur:.6f}']
            last = path
        lines.append(f"file '{last}'")
        Path(dest).write_text('\n'.join(lines) + '\n')
        return self.out(end, start, speed)


# ---------------------------------------------------------------- stills
def caption_png(fonts, title, text, dest):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tf, bf = fonts('semibold', 38), fonts('regular', 28)
    width = 1040
    body = wrap(d, text, bf, width - 72) if text else []
    h = 36 + 46 + (14 + 38 * len(body) if body else 0) + 30
    x0 = 408 + (W - 408 - width) // 2
    y0 = H - 22 - h
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + 10, x0 + width, y0 + h + 10), 24, fill=(10, 20, 40, 90))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x0 + width, y0 + h), 24, fill=(20, 34, 63, 238))
    d.rounded_rectangle((x0, y0, x0 + 8, y0 + h), 4, fill=BLUE)
    d.text((x0 + 40, y0 + 30), title, font=tf, fill='#ffffff')
    for i, line in enumerate(body):
        d.text((x0 + 40, y0 + 30 + 58 + i * 38), line, font=bf, fill='#cfd8ea')
    img.save(dest)


def chapter_card(fonts, number, total, title, summary, dest):
    img = gradient((W, H), '#e7ecf5', '#f4f2ef')
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((160, 402, 196, 432), 6, fill=BLUE)
    d.text((216, 398), f'remotefs 0.3.0  ·  Chapter {number} of {total}', font=fonts('medium', 30), fill=MUTED)
    d.text((156, 460), title, font=fonts('bold', 108), fill=INK)
    for i, line in enumerate(wrap(d, summary, fonts('regular', 40), 1500)):
        d.text((160, 610 + i * 56), line, font=fonts('regular', 40), fill=MUTED)
    img.save(dest)


def promo_background():
    img = gradient((W, H), '#1b2d57', '#2f56b3')
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((1100, -500, 2500, 700), fill=(120, 160, 255, 70))
    return Image.alpha_composite(img.convert('RGBA'), glow.filter(ImageFilter.GaussianBlur(160)))


FRAME = (220, 190, 1700, 1022)  # footage window in the promo layout (16:9, 1480×832)


def promo_layers(fonts, headline, detail, base, top):
    bg = promo_background()
    x0, y0, x1, y1 = FRAME
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + 24, x1, y1 + 24), 26, fill=(5, 10, 30, 150))
    bg = Image.alpha_composite(bg, shadow.filter(ImageFilter.GaussianBlur(34)))
    bg.convert('RGB').save(base)
    # Top layer: everything outside the rounded window is opaque background; the window is transparent.
    mask = Image.new('L', (W, H), 255)
    ImageDraw.Draw(mask).rounded_rectangle(FRAME, 26, fill=0)
    layer = bg.copy(); layer.putalpha(mask)
    d = ImageDraw.Draw(layer)
    d.text((x0, 52), headline, font=fonts('bold', 72), fill='#ffffff')
    if detail:
        d.text((x0 + d.textlength(headline, font=fonts('bold', 72)) + 34, 80), detail, font=fonts('medium', 38), fill='#b9c9ee')
    layer.save(top)


def promo_card(fonts, title, lines, dest, big=96):
    img = promo_background()
    d = ImageDraw.Draw(img)
    y = 380 if len(lines) < 3 else 300
    for line in wrap(d, title, fonts('bold', big), 1600):
        d.text((160, y), line, font=fonts('bold', big), fill='#ffffff'); y += int(big * 1.2)
    y += 26
    for line in lines:
        mono = line.startswith('pipx ')
        f = fonts('mono', 44) if mono else fonts('medium', 44)
        if mono:
            d.rounded_rectangle((150, y - 12, 170 + d.textlength(line, font=f), y + 64), 14, fill=(10, 20, 45, 150))
        d.text((164 if mono else 160, y), line, font=f, fill='#ffffff' if mono else '#c8d6f5'); y += 92
    img.convert('RGB').save(dest)


# ---------------------------------------------------------------- encoding
def encode(inputs, graph, out_label, dest, seconds):
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', *inputs, '-filter_complex', graph, '-map', f'[{out_label}]',
         '-t', f'{seconds:.3f}', '-r', str(FPS), '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', '-an', str(dest)])


def cue_windows(cap, start, end, speed=1.0):
    rows = []
    cues = [c for c in cap.cues if start <= c['t'] < end]
    for i, cue in enumerate(cues):
        a = cap.out(cue['t'], start, speed)
        nxt = cap.out(cues[i + 1]['t'], start, speed) if i + 1 < len(cues) else cap.out(end, start, speed)
        # Long captions stay long enough to read, then get out of the way of the footage.
        hold = max(4.2, 1.6 + len(cue['title'] + cue['text']) / 16)
        rows.append({'start': a, 'end': min(nxt - 0.05, a + hold), 'title': cue['title'], 'text': cue['text']})
    return rows


def render_chapter(fonts, cap, number, total, meta, work, dest):
    work.mkdir(parents=True, exist_ok=True)
    card = work / 'card.png'
    chapter_card(fonts, number, total, meta['title'], meta['summary'], card)
    listing = work / 'frames.txt'
    footage = cap.concat(listing, 0, cap.duration)
    cues = cue_windows(cap, 0, cap.duration)
    inputs = ['-loop', '1', '-t', f'{TITLE_SECONDS}', '-framerate', str(FPS), '-i', str(card),
              '-f', 'concat', '-safe', '0', '-i', str(listing)]
    graph = [f'[0:v]format=yuv420p,setsar=1,settb=AVTB[card]',
             f'[1:v]fps={FPS},scale={W}:{H},setsar=1,format=rgba,tpad=stop_mode=clone:stop_duration=1[f0]']
    for i, cue in enumerate(cues):
        png = work / f'cue-{i:02}.png'
        caption_png(fonts, cue['title'], cue['text'], png)
        inputs += ['-loop', '1', '-t', f'{footage + 1:.3f}', '-framerate', str(FPS), '-i', str(png)]
        n = i + 2
        a, b = cue['start'], cue['end']
        graph.append(f'[{n}:v]format=rgba,fade=in:st={a:.3f}:d=0.3:alpha=1,fade=out:st={b - 0.3:.3f}:d=0.3:alpha=1[c{i}]')
        graph.append(f"[f{i}][c{i}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[f{i + 1}]")
    body = footage + 0.6
    graph.append(f'[f{len(cues)}]trim=duration={body:.3f},format=yuv420p,fade=out:st={body - 0.5:.3f}:d=0.5:color={PAPER},settb=AVTB[foot]')
    graph.append(f'[card][foot]xfade=transition=fade:duration={XFADE}:offset={TITLE_SECONDS - XFADE:.3f}[v]')
    total_seconds = TITLE_SECONDS - XFADE + body
    encode(inputs, ';'.join(graph), 'v', dest, total_seconds)
    offset = TITLE_SECONDS - XFADE
    return total_seconds, [{**c, 'start': c['start'] + offset, 'end': c['end'] + offset} for c in cues]


def write_vtt(dest, cues):
    body = ['WEBVTT', '']
    for c in cues:
        body += [f"{stamp(c['start'])} --> {stamp(c['end'])}", c['title']] + ([c['text']] if c.get('text') else []) + ['']
    Path(dest).write_text('\n'.join(body))


def walkthrough(fonts, args, edit):
    spec = edit['walkthrough']
    out = args.out; (out / 'chapters').mkdir(parents=True, exist_ok=True); (out / 'posters').mkdir(exist_ok=True)
    chapters = [c for c in spec['chapters'] if (args.capture / c['capture'] / 'capture.json').exists()]
    files, all_cues, markers, elapsed = [], [], [], 0.0
    for number, meta in enumerate(chapters, 1):
        cap = Capture(args.capture / meta['capture'], meta.get('speedups', ()), meta.get('speed', 1.0))
        dest = out / 'chapters' / f"{meta['slug']}.mp4"
        seconds, cues = render_chapter(fonts, cap, number, len(chapters), meta, out / 'work' / meta['slug'], dest)
        write_vtt(out / 'chapters' / f"{meta['slug']}.vtt", cues)
        run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', f'{min(seconds - 0.5, TITLE_SECONDS + 3):.2f}', '-i', str(dest),
             '-frames:v', '1', '-q:v', '2', str(out / 'posters' / f"{meta['slug']}.jpg")])
        markers.append({'start': round(elapsed, 3), 'title': meta['title'], 'file': dest.name, 'seconds': round(seconds, 3)})
        all_cues += [{**c, 'start': c['start'] + elapsed, 'end': c['end'] + elapsed} for c in cues]
        files.append(dest); elapsed += seconds
        print(f"chapter {meta['slug']}: {seconds:.1f}s", flush=True)
    listing = out / 'work' / 'chapters.txt'
    listing.write_text(''.join(f"file '{f.resolve()}'\n" for f in files))
    meta_lines = [';FFMETADATA1', f"title={spec['title']}"]
    for i, m in enumerate(markers):
        end = markers[i + 1]['start'] if i + 1 < len(markers) else elapsed
        meta_lines += ['[CHAPTER]', 'TIMEBASE=1/1000', f"START={round(m['start'] * 1000)}", f'END={round(end * 1000)}', f"title={m['title']}"]
    (out / 'work' / 'chapters.ffmeta').write_text('\n'.join(meta_lines) + '\n')
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
         '-i', str(out / 'work' / 'chapters.ffmeta'), '-map_metadata', '1', '-map_chapters', '1', '-c', 'copy',
         '-movflags', '+faststart', str(out / spec['asset'])])
    write_vtt(out / 'walkthrough.vtt', all_cues)
    (out / 'chapters.json').write_text(json.dumps({'duration': round(elapsed, 3), 'chapters': markers}, indent=2))
    print(f'walkthrough: {elapsed:.1f}s, {len(markers)} chapters')


def promo(fonts, args, edit):
    spec = edit['marketing']
    work = args.out / 'work' / 'promo'; work.mkdir(parents=True, exist_ok=True)
    clips, cues = [], []
    promo_card(fonts, spec['open']['title'], [spec['open']['subtitle']], work / 'open.png')
    clips.append(('card', work / 'open.png', 3.0, spec['open']['title'], spec['open']['subtitle']))
    x0, y0, x1, y1 = FRAME
    for i, shot in enumerate(spec['shots']):
        cap = Capture(args.capture / shot['capture'])
        start = cap.marks[shot['from']] - 0.3
        end = cap.marks[shot['to']] + shot.get('pad', 0) if 'to' in shot else cap.marks[shot['from']] + shot['seconds']
        end = min(end, cap.duration)
        listing = work / f'shot-{i}.txt'
        seconds = cap.concat(listing, start, end, shot.get('speed', 1))
        base, top = work / f'base-{i}.png', work / f'top-{i}.png'
        promo_layers(fonts, shot['headline'], shot.get('detail', ''), base, top)
        dest = work / f'shot-{i}.mp4'
        graph = (f'[1:v]fps={FPS},scale={x1 - x0}:{y1 - y0},setsar=1[s];[0:v][s]overlay={x0}:{y0}[b];'
                 f'[b][2:v]overlay=0:0,format=yuv420p[v]')
        encode(['-loop', '1', '-framerate', str(FPS), '-t', f'{seconds:.3f}', '-i', str(base), '-f', 'concat', '-safe', '0', '-i', str(listing),
                '-loop', '1', '-framerate', str(FPS), '-t', f'{seconds:.3f}', '-i', str(top)], graph, 'v', dest, seconds)
        clips.append(('clip', dest, seconds, shot['headline'], shot.get('detail', '')))
    promo_card(fonts, spec['close']['title'], spec['close']['lines'], work / 'close.png', big=120)
    clips.append(('card', work / 'close.png', 4.5, spec['close']['title'], ' · '.join(spec['close']['lines'])))
    inputs, graph, offset, label = [], [], 0.0, None
    for i, (kind, path, seconds, title, detail) in enumerate(clips):
        if kind == 'card':
            inputs += ['-loop', '1', '-framerate', str(FPS), '-t', f'{seconds:.3f}', '-i', str(path)]
        else:
            inputs += ['-i', str(path)]
        graph.append(f'[{i}:v]fps={FPS},format=yuv420p,setsar=1,settb=AVTB[p{i}]')
        start = 0.0 if i == 0 else offset
        cues.append({'start': start, 'end': start + seconds - (XFADE if i + 1 < len(clips) else 0), 'title': title, 'text': detail})
        if i == 0:
            label, offset = 'p0', seconds - XFADE
        else:
            graph.append(f'[{label}][p{i}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[x{i}]')
            label, offset = f'x{i}', offset + seconds - XFADE
    total = offset + XFADE
    graph.append(f'[{label}]fade=in:st=0:d=0.4,fade=out:st={total - 0.6:.3f}:d=0.6[v]')
    encode(inputs, ';'.join(graph), 'v', args.out / spec['asset'], total)
    write_vtt(args.out / 'promo.vtt', cues)
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', '6', '-i', str(args.out / spec['asset']),
         '-frames:v', '1', '-q:v', '2', str(args.out / 'posters' / 'promo.jpg')])
    print(f'promo: {total:.1f}s')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--edit', type=Path, default=ROOT / 'docs/video/tour-0.3.0.json')
    parser.add_argument('--font-dir')
    parser.add_argument('--only', choices=['walkthrough', 'promo'])
    args = parser.parse_args()
    edit = json.loads(args.edit.read_text())
    fonts = Fonts(args.font_dir)
    args.out.mkdir(parents=True, exist_ok=True); (args.out / 'posters').mkdir(exist_ok=True)
    if args.only != 'promo': walkthrough(fonts, args, edit)
    if args.only != 'walkthrough': promo(fonts, args, edit)


if __name__ == '__main__':
    main()

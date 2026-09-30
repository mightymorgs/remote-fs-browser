#!/usr/bin/env python3
"""Edit CUA/CDP screencast frames into a captioned, chaptered product video.

Capture JSON: [{"file": "shot-0000.jpg", "t": <CDP timestamp seconds>}, ...].
No browser automation is performed here. Keep raw footage outside the repository.
Requires ffmpeg and Pillow. Usage:
  python render_demo.py --capture /path/to/capture --out /path/to/output
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
W, H, FPS = 1920, 1080, 30
BG, INK, BLUE, MUTED = '#edf1f8', '#172747', '#4867ce', '#536481'

def stamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'

def font_path():
    for p in ['/System/Library/Fonts/Supplemental/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if Path(p).exists(): return p
    raise RuntimeError('Pass --font with an installed TrueType font')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeline', type=Path, default=ROOT/'docs/video/demo-0.3.0.json')
    parser.add_argument('--font', default=None)
    args = parser.parse_args()
    timeline = json.loads(args.timeline.read_text())
    out = args.out; out.mkdir(parents=True, exist_ok=True)
    face = args.font or font_path()
    font = lambda size: ImageFont.truetype(face, size)
    scenes = timeline['scenes']
    elapsed, chapters, captions = 0, [], ['WEBVTT\n']
    for i, s in enumerate(scenes):
        s['start'] = elapsed
        if 'chapter' in s: chapters.append({'start':elapsed, 'title':s['chapter']})
        elapsed += s['seconds']
        captions.append(f"{stamp(s['start'])} --> {stamp(elapsed)}\n{s['title']}\n{s['subtitle']}" + (f"\n{s['note']}" if s.get('note') else '')+'\n')
        canvas = Image.new('RGBA', (W,H), (0,0,0,0))
        d = ImageDraw.Draw(canvas)
        d.rectangle((0,0,W,177),fill=BG)
        d.rectangle((0,1038,W,H),fill=BG)
        d.text((60,22), 'remotefs / 0.3.0', font=font(22), fill=BLUE)
        d.text((60,58),s['title'],font=font(48),fill=INK)
        d.text((60,122),s['subtitle'],font=font(27),fill=MUTED)
        d.rectangle((0,1074,W,H), fill='#d6ddeb')
        d.rectangle((0,1074,round(W*elapsed/sum(x['seconds'] for x in scenes)),H),fill=BLUE)
        if s.get('note'): d.text((60,1046),s['note'],font=font(21),fill=MUTED)
        else: d.text((60,1046),'Actual app footage • edited for pace' if 'clip' in s else 'remotefs • your storage, through your service',font=font(21),fill=MUTED)
        canvas.save(out/f'overlay-{i:02}.png')
        if 'card' in s:
            card=Image.new('RGB',(W,H),BG);c=ImageDraw.Draw(card)
            c.rounded_rectangle((60,212,1860,1004),radius=20,fill='#ffffff',outline='#d3dcee',width=2)
            y=290
            for line in s['lines']:
                c.text((112,y),line,font=font(38 if s['card'] not in ('opening','closing') else 48),fill=INK if not line.startswith('remotefs') else BLUE)
                y+=82
            card.save(out/f'card-{i:02}.png')
    total=elapsed
    (out/'demo.vtt').write_text('\n'.join(captions))
    (out/'chapters.json').write_text(json.dumps({'duration':total,'chapters':chapters},indent=2))
    (out/'edit.json').write_text(json.dumps(timeline,indent=2))

    def render(item):
        i,s=item; dest=out/f'scene-{i:02}.mp4'
        inputs=[]; vf=''
        if 'card' in s:
            inputs=['-loop','1','-framerate',str(FPS),'-i',str(out/f'card-{i:02}.png')]
            vf='[0:v]setsar=1[base];'
        else:
            rows=json.loads((args.capture/(s['clip']+'.json')).read_text())
            if not rows: raise RuntimeError(f"No frames: {s['clip']}")
            lines=['ffconcat version 1.0']
            for n,row in enumerate(rows):
                p=(args.capture/row['file']).resolve()
                if "'" in str(p):raise ValueError('Capture path cannot contain an apostrophe')
                lines.append(f"file '{p}'")
                dt=rows[n+1]['t']-row['t'] if n+1<len(rows) else 1/FPS
                lines.append(f'duration {max(1/120,min(dt,.5)):.6f}')
            lines.append(f"file '{(args.capture/rows[-1]['file']).resolve()}'")
            concat=out/f'frames-{i:02}.txt';concat.write_text('\n'.join(lines)+'\n')
            inputs=['-f','concat','-safe','0','-i',str(concat)]
            duration=max(.1,rows[-1]['t']-rows[0]['t'])
            speed=min(1,s['seconds']/duration)
            crop=s.get('crop')
            region=f'crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]},' if crop else ''
            vf=f'[0:v]setpts={speed:.6f}*(PTS-STARTPTS),fps={FPS},{region}scale=1800:850:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:178+(850-ih)/2:color={BG},setsar=1,tpad=stop_mode=clone:stop_duration={s["seconds"]}[base];'
        inputs+=['-loop','1','-i',str(out/f'overlay-{i:02}.png')]
        vf+='[base][1:v]overlay=0:0,format=yuv420p[v]'
        cmd=['ffmpeg','-y','-hide_banner','-loglevel','error',*inputs,'-filter_complex',vf,'-map','[v]','-t',str(s['seconds']),'-r',str(FPS),'-c:v','libx264','-preset','fast','-crf','19','-threads','2','-an',str(dest)]
        subprocess.run(cmd,check=True)
        return dest
    with ThreadPoolExecutor(max_workers=3) as pool:
        files=list(pool.map(render,enumerate(scenes)))
    concat=out/'scenes.txt';concat.write_text('\n'.join(f"file '{p.resolve()}'" for p in files)+'\n')
    metadata=[';FFMETADATA1','title=remotefs 0.3.0 — Your files across storage','comment=Actual app workflows, explanatory command cards, and labelled demo fixtures.']
    for i,ch in enumerate(chapters):
        end=chapters[i+1]['start'] if i+1<len(chapters) else total
        metadata += ['[CHAPTER]','TIMEBASE=1/1000',f'START={round(ch["start"]*1000)}',f'END={round(end*1000)}','title='+ch['title']]
    (out/'chapters.ffmeta').write_text('\n'.join(metadata)+'\n')
    movie=out/timeline['asset']
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(concat),'-i',str(out/'chapters.ffmeta'),'-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',str(movie)],check=True)
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss','7','-i',str(movie),'-frames:v','1','-q:v','2',str(out/'demo-poster.jpg')],check=True)
    print(json.dumps({'video':str(movie),'seconds':total,'scenes':len(scenes),'chapters':len(chapters)}))

if __name__=='__main__':main()

"""Human-paced Playwright driving plus CDP screencast capture for the feature tour.

A Recorder writes JPEG frames and ``capture.json`` into one directory per chapter:
  frames: [{"file": "f-00001.jpg", "t": seconds}]
  cues:   [{"t": seconds, "title": str, "text": str}]      captions, each lasting until the next cue
  speed:  [{"t": seconds, "factor": float}]                playback speed from t onwards
  marks:  {name: seconds}                                   named moments used by the marketing cut
All times are seconds from the start of capture.
"""
import asyncio
import base64
import json
import math
import random
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROMIUM = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'
VIEW = {'width': 1280, 'height': 720}
SCALE = 1.5  # 1280×720 CSS pixels captured as 1920×1080 frames


class Recorder:
    def __init__(self, page, out):
        self.page, self.out = page, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.frames, self.cues, self.speed, self.marks = [], [], [], {}
        self.t0 = None
        self.pos = (VIEW['width'] * 0.62, VIEW['height'] * 0.55)
        self.rng = random.Random(7)

    # ---------- capture ----------
    async def start(self):
        self.cdp = await self.page.context.new_cdp_session(self.page)
        self.cdp.on('Page.screencastFrame', self._frame)
        self.t0 = time.time()
        await self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 90,
                                                     'maxWidth': int(VIEW['width'] * SCALE), 'maxHeight': int(VIEW['height'] * SCALE)})
        await self.page.mouse.move(*self.pos)
        await self.wait(0.6)

    def _frame(self, event):
        n = len(self.frames) + 1
        name = f'f-{n:05}.jpg'
        (self.out / name).write_bytes(base64.b64decode(event['data']))
        self.frames.append({'file': name, 't': event['metadata']['timestamp'] - self.t0})
        asyncio.ensure_future(self.cdp.send('Page.screencastFrameAck', {'sessionId': event['sessionId']}))

    async def stop(self):
        await self.wait(0.8)
        await self.cdp.send('Page.stopScreencast')
        await asyncio.sleep(0.3)
        self.frames.sort(key=lambda f: f['t'])
        data = {'frames': self.frames, 'cues': self.cues, 'speed': self.speed, 'marks': self.marks, 'duration': self.now()}
        (self.out / 'capture.json').write_text(json.dumps(data, indent=1))

    def now(self):
        return time.time() - self.t0

    # ---------- edit markers ----------
    def caption(self, title, text=''):
        self.cues.append({'t': self.now(), 'title': title, 'text': text})

    def mark(self, name):
        self.marks[name] = self.now()

    def fast(self, factor):
        self.speed.append({'t': self.now(), 'factor': factor})

    def normal(self):
        self.fast(1)

    async def wait(self, seconds):
        await asyncio.sleep(seconds)

    # ---------- human input ----------
    async def move(self, x, y, duration=None):
        x0, y0 = self.pos
        dist = math.hypot(x - x0, y - y0)
        duration = duration or min(0.95, 0.28 + dist / 1400)
        steps = max(8, int(duration * 60))
        # A slight arc reads as a hand rather than a robot.
        bend = self.rng.uniform(-0.12, 0.12) * dist
        nx, ny = (-(y - y0) / dist, (x - x0) / dist) if dist else (0, 0)
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)
            arc = math.sin(math.pi * e) * bend
            await self.page.mouse.move(x0 + (x - x0) * e + nx * arc, y0 + (y - y0) * e + ny * arc)
            await asyncio.sleep(duration / steps)
        self.pos = (x, y)

    async def point(self, target, dx=0.5, dy=0.5):
        if isinstance(target, tuple):
            return target
        await target.scroll_into_view_if_needed()
        box = await target.bounding_box()
        return box['x'] + box['width'] * dx, box['y'] + box['height'] * dy

    async def hover(self, target, dx=0.5, dy=0.5, pause=0.25):
        await self.move(*await self.point(target, dx, dy))
        await self.wait(pause)

    async def click(self, target, dx=0.5, dy=0.5, button='left', modifiers=(), pause=0.55):
        await self.hover(target, dx, dy, pause=0.18)
        for key in modifiers:
            await self.page.keyboard.down(key)
        await self.page.mouse.down(button=button)
        await asyncio.sleep(0.07)
        await self.page.mouse.up(button=button)
        for key in modifiers:
            await self.page.keyboard.up(key)
        await self.wait(pause)

    async def right_click(self, target, dx=0.5, dy=0.5, pause=0.9):
        await self.click(target, dx, dy, button='right', pause=pause)

    async def drag(self, start, end, duration=1.3, pause=0.6):
        await self.move(*await self.point(start))
        await self.wait(0.15)
        await self.page.mouse.down()
        x1, y1 = await self.point(end)
        await self.move(x1, y1, duration=duration)
        await self.wait(0.2)
        await self.page.mouse.up()
        await self.wait(pause)

    async def type(self, target, text, cps=13, clear=True, pause=0.4):
        if target is not None:
            await self.click(target, pause=0.2)
            if clear:
                await self.page.keyboard.press('Control+a')
                await self.page.keyboard.press('Backspace')
        for ch in text:
            await self.page.keyboard.type(ch)
            await asyncio.sleep(self.rng.uniform(0.6, 1.4) / cps)
        await self.wait(pause)

    async def press(self, combo, label=None, pause=0.8):
        """Press a shortcut and show it as keycaps, e.g. press('Meta+a', ['⌘', 'A'])."""
        if label:
            await self.page.evaluate('([k]) => window.__rfsKeys && window.__rfsKeys(k, "", 1600)', [label])
            await self.wait(0.25)
        await self.page.keyboard.press(combo)
        await self.wait(pause)

    async def scroll(self, dy, steps=12, duration=0.8):
        for _ in range(steps):
            await self.page.mouse.wheel(0, dy / steps)
            await asyncio.sleep(duration / steps)


async def launch(p):
    # Screencast frames follow the compositor, not Playwright's emulated scale, so force the scale at launch:
    # layout stays 1280×720 CSS pixels while frames arrive at 1920×1080.
    browser = await p.chromium.launch(executable_path=CHROMIUM, args=['--font-render-hinting=none', f'--force-device-scale-factor={SCALE}'])
    context = await browser.new_context(viewport=VIEW, accept_downloads=True)
    await context.add_init_script(path=str(HERE / 'overlay.js'))
    return browser, context

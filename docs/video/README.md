# Rendering the feature tour

`demo-0.3.0.json` is the edit timeline: clip names, durations, captions, crop rectangles and chapter starts. Record actual browser interactions through the supported CUA/CDP screencast capability. Each clip consists of JPEG frames and a JSON array of `{"file":"clip-0000.jpg","t":123.456}` entries, using the screencast timestamps. Keep captures and private service configuration outside this repository.

Install Pillow in a virtual environment and install ffmpeg with libx264 support. Then run:

```sh
python scripts/video/render_demo.py --capture /path/to/capture --out /path/to/edit
```

The renderer produces a 1920×1080, 30 fps H.264 MP4, built-in feature labels, embedded chapters, WebVTT captions and a poster. It uses Arial on macOS or DejaVu Sans on Linux; `--font` accepts another installed TrueType font. Inspect the result before publishing, especially text fitting and any credential fields. Original footage is required to reproduce this edit; it is not committed.

Copy `demo.vtt` and `demo-poster.jpg` into `docs/site/`. Upload the MP4 as a new release asset without replacing historical assets. Keep the homepage chapter buttons and transcript aligned with the generated `chapters.json`. Build the website with `python scripts/build_docs.py`.

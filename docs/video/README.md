# Recording the feature tour

The 0.3.0 tour is recorded from the real app, driven at human pace by Playwright, and edited automatically. It produces three kinds of output from one recording:

- **Walkthrough**: every chapter in one video, with embedded chapter markers.
- **Chapter videos**: each chapter as its own short video with a title card, for hosting separately.
- **Promo**: a short marketing cut built from marked moments in the chapters.

`tour-0.3.0.json` is the edit plan: chapter order, titles and summaries, and the promo's shots, headlines and speeds. Captions come from the recording itself. The recorder notes each caption at the moment its action happens, so captions stay in sync when the app's timing changes.

## 1. Build the demo lab (throwaway Linux container only)

`scripts/video/demo_lab.sh` creates everything the tour films: three SMB servers on a private 192.168.50.0/24 loopback network (with DNS and NetBIOS names), a local S3-compatible server, a libvirt test-driver pool, fictional studio files and a remotefs config. It changes loopback addresses, routes and `/etc/hosts`, so run it only in a disposable container as root.

```sh
apt-get install -y iproute2 samba smbclient rclone jq libvirt-dev pkg-config fonts-inter ffmpeg
python3 -m venv /opt/rfv
/opt/rfv/bin/pip install -e '.[libvirt]' 'moto[server]' pillow playwright
LAB=/tmp/rfs-lab scripts/video/demo_lab.sh      # prints the serve command and demo logins
```

Start the service with the printed `remotefs serve …` command and leave it running.

## 2. Record

```sh
/opt/rfv/bin/python scripts/video/record_tour.py --out /tmp/tour-capture
```

This records all chapters in order into one browser session, because later chapters build on earlier ones (a mapped NAS, saved logins, shortlist entries). `--only` re-records single chapters for iteration. Each chapter directory holds screencast JPEG frames and `capture.json` with frame times, captions, speed-ups and named marks.

The recorder injects `overlay.js` into recorded pages only. It draws a visible pointer, click ripples and keycap badges (⇧, ⌘, right-click) so a silent video shows what the hands are doing. The app itself is not modified. The command-line chapters type into `terminal.html` and run each command for real in a persistent bash session; the output shown is the genuine output.

## 3. Render

```sh
/opt/rfv/bin/python scripts/video/render_tour.py --capture /tmp/tour-capture --out /tmp/tour-edit
```

Outputs, all 1920×1080, 30 fps, H.264:

- `remotefs-0.3.0-walkthrough.mp4`, `walkthrough.vtt`, `chapters.json`
- `chapters/NN-slug.mp4` and `.vtt`, one per chapter
- `remotefs-0.3.0-promo.mp4`, `promo.vtt`
- `posters/*.jpg`

Watch the results before publishing. Upload the MP4s as release assets; do not commit them. Copy `walkthrough.vtt`, `promo.vtt` and the posters you use into `docs/site/`, keep the homepage chapter buttons aligned with `chapters.json`, and rebuild the site with `python scripts/build_docs.py`.

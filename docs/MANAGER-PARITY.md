# Manager parity with the picker-redesign handoff

Audit of `src/remote_fs_browser/web/manager.js` + `manager.html` (the `/manager` UI) against the
design handoff (`IMPLEMENTATION.md` and `Picker Redesign.dc.html`). Status is after this change;
"was" records the state before it. Tests: `frontend/manager.test.js` (node) unless noted.

| Requirement | Where | Status | What changed |
| --- | --- | --- | --- |
| **Layout** | | | |
| Collapsible sidebar, 272 px / 56 px icon rail; rail holds Shortlist, This machine, Network; Scan / Add in the rail footer | `renderVals` `railWidth`, `railIcons`; `manager.html` `<aside>` | met | test: responsive rules |
| One 53 px toolbar: toggle, parent, breadcrumb, filter, New folder, Downloads, refresh, sign out | `manager.html` `.manager-toolbar` | met | — |
| Secondary buttons fold into `⋯` below ~1040 px | `roomy`/`tight`, `overflowMenu` (toolbar menu) | met | test: responsive rules |
| Kind drops below 820 px of *pane* width, Modified below 560 px | `showKind`, `showDate` (pane = window − rail) | met | test: responsive rules |
| Scan table: Protocol + Credentials collapse into the name cell below 820 px | `wideScan`/`narrowScan`, `deviceCols` | met | test: responsive rules |
| Selection bar: count, total bytes, Download / Zip… / Copy / Cut / Paste / Delete, Clear | `selectionActions`, `manager-selection` | met | test: selection bar |
| **Finder behaviour** | | | |
| Tick boxes are the only selector; clicking a row navigates (folder) / previews (file) | `row.click`, `row.check` | met | — |
| Shift-tick selects a range; shift-tick on a ticked row clears the run | `clickRow` | met | — |
| ⌘/Ctrl-tick adds or removes one | `row.check` → `clickRow` | met | — |
| Right-click menus on file rows, list background, scan devices, sidebar mounts, sidebar shares, shortlist pins | `onContextMenu` ×6 in `manager.html`; `openMenu`, `openDeviceMenu`, `openMountMenu`, `openShareMenu`, `openPinMenu` | met | test: six surfaces (was untested) |
| File menu: Open, Download, Download as multi-part zip…, Copy, Cut, Paste, New folder, Upload files here, Rename, Shortlist folder, Delete, Get info | `items()` | **was partial → met** | Shortcut hints (⌘C/⌘X/⌘V/⇧⌘N/⌘⌫, Ctrl+ off Mac) for the keys that work; count-aware labels (Download folder as zip, Download N files, Paste N items, Delete N items); "Shortlist this folder" when the target is the folder shown. Extra items kept: New text file, Mount on this computer…. Test: twelve items |
| Write items disable from the session's `operations` | `items()` `on: this.can(op)` | met | test: twelve items (read-only session) |
| ⌘C gated like the menu/selection bar | `copy()` | **was partial → met** | ⌘C checked `read` while the menu and bar checked `copy` (the op the source session's `/copy` needs), so ⌘C on a read-only location filled a clipboard that could never paste. Test: ⌘C needs copy |
| `☆` on folder rows / pins in the rail; `↓` on file rows downloads directly | `row.pin`, `row.grab`, `shortlist` | met | — |
| **Windows** | | | |
| Downloads, Scan network, Add a location are floating windows, each with Close | `transfersView`, `scanning`, `addView` (fixed-position panels) | met | — |
| ⌘/Ctrl+D / S / N toggle and return to the browser | `keydown` → `toView` | **was partial → met** | Shortcuts were dead while the filter field had focus; window toggles (D, S, N, ⇧Q, /) now work from a field, file shortcuts (A, C, X, V, ⌫) still leave fields alone. Test: window shortcuts |
| ⌘/Ctrl+⇧+Q sign out; ⌘/Ctrl+A/C/X/V/⌫ | `keydown` | met | test: window shortcuts |
| An open sheet owns the keyboard | `keydown` | **was missing → met** | ⌘A, ⌘⌫, ⌘D etc. fired behind the SMB sign-in, ZIP, confirm and sign-out sheets (⌘⌫ could open Delete behind a sheet). Test: open sheet |
| `Esc`: close window / clear selection | `escape()` | **was partial → met** | Esc closed everything *and* cleared the selection in one press. Now: menu/sheet/shortcut list first, then the window, then the selection. Test: Esc order |
| `⌘/Ctrl + /` shortcut list | `keysOpen`, `shortcuts` | **was partial → met** | List gains ⇧⌘N (New folder) and the Esc order. Test: shortcut list |
| **Scan window** | | | |
| Live progress bar, `Scanned addresses n–m of total`, device count | `scanPercent`, `scanStatus`, `scanFound`, `scanBatch` (server `notes`) | **was partial → met** | Count was services ("N services found"); now "N devices answered · M services". Stopped reads "Stopped at address n of total". Test: scan resume |
| Editable CIDR field, Start / Stop / Rescan, Close | `ranges`, `startScan`, `cancelScan`, `scanButton` | **was partial → met** | Stop then Start restarted from address 1; now **Resume scan** continues from `next_offset` of the same ranges (new ranges start over). Test: scan resume |
| `POST /api/discover {ranges, offset}` with `next_offset` and `notes` | `startScan`; `discovery.py` | met | existing pagination test |
| Device table Name (DNS) / NetBIOS / IP / Protocol / Credentials / Map | `devices`, `manager.html` | met | — |
| SMB: saved credential cards, username / password / domain fields, "Save these credentials for this host"; `DOMAIN\username`; IPv4 only | `credOptions`, `promptUser…`, `togglePromptStore`; `backends.py` rejects IPv6 | met | — |
| NFS: version (4 or 3, plus automatic) and optional absolute export path | `promptVersion`, `promptExport` | met | — |
| Mapped hosts under Network with shares beneath, saved/shared marker, `⏏` | `hosts`, `credsMark`, `host.unmount` | met | — |
| **Downloads window** | | | |
| Pack: store list with free/total | `zipStores`, `storeUse`; `/api/downloads/estimate` | met | — |
| Requirement = payload + ~2 % | server `needed` (`jobs.plan`) | met | — |
| Start blocked when it will not fit | `zipProblem`, `zipBlocked`, `zipBlockedNote` | met | test: ZIP guards |
| Split: single / 1 / 2 / 4 GB / custom MB or GB; guards ≥ 1 MB and ≤ 999 parts | `zipSplits`, `zipLimit`, `zipProblem` | **was partial → met** | Only the 1 MB guard ran (on submit); 999 parts was left to the server's 422 and Start stayed enabled. Start now disables with the reason for all three guards, and `confirmZip` refuses the same cases. Test: ZIP guards |
| Download: each ready part is a link; nothing auto-fires | `grabAll`, `part.grab` | met | — |
| "Already downloaded" confirm on re-fetch | `grabPart`, `confirmOpen` | **was partial → met** | Also asks when the same file was handed over by another job. "Download again" from ↓ re-lists *every* picked file (before, only the first already-downloaded one was re-fetched and the rest were dropped). Test: queued reuse |
| A second request for a still-queued file reuses the existing job | `startBatch`, `queuedPart` | **was partial → met** | Reuse was silent and could pick a downloaded part over a queued one; now opens that job and says it is already queued. Mixed selections queue only the new files. Test: queued reuse; verified in browser |
| Purge: states how much it frees, warns when parts were never downloaded | `purgeLabel`, `purgeJob` | met | — |
| Per-part downloaded flag survives polling | server `part['downloaded']` in `/api/downloads/{id}/parts/{i}` | met | — |
| Loose files stream straight from the share as one batch job | `download()` → `startBatch` | met | existing HTTP-origin test |

Unchanged and still covered: `#/<endpoint>/<path>` deep links, managed-mount notices, drag-and-drop upload (#32),
`selector` / select mode (`browser.js`, untouched).

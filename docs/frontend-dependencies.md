# Frontend implementation dependency spike

Evaluated 11 September 2026 for `JS Webapp Design Improvements.zip`.
The requirement is licences we can comply with, rather than exclusively MIT.
No backend dependency was added for the new download features.

| Candidate | Upstream licence / dependency | Decision |
| --- | --- | --- |
| Python `zipfile`, `asyncio`, `shutil` | Python standard library (PSF terms) | Used for ZIP64 output, job coordination and staging capacity. Our split writer and job endpoints use the repository's MIT licence. |
| [stream-zip](https://github.com/uktrade/stream-zip) 0.0.84 | MIT; its wheel requires PyCryptodome (BSD/public-domain and native extensions) | Viable streaming alternative, but unnecessary for staged ZIPs. Wheel metadata inspected in an isolated download directory; not installed as an application dependency. |
| [zipstream-ng](https://github.com/pR0Ps/zipstream-ng) | LGPL-3.0 | No need to add another copyleft dependency when standard-library ZIP output covers the feature. |
| [stream-unzip](https://github.com/uktrade/stream-unzip) | MIT | Extraction is outside this UI's download workflow; not added. |
| [anfs](https://github.com/skelsec/anfs) | MIT; NFSv3, additional authentication/crypto dependencies | Not a drop-in replacement for existing NFSv4 support. Retain tested libnfs backend. |
| [aiosmb](https://github.com/skelsec/aiosmb/blob/main/setup.py) | Modified Apache Software License 1.1 | No licensing simplification over existing share enumeration; no backend replacement. |
| React / ReactDOM 18.3.1 | MIT | The supplied DC layout runtime requires these browser libraries. Production UMD assets are bundled locally with full licence texts. No Node server or runtime CDN request is required. |

The staged ZIP implementation is exercised by `tests/test_jobs.py`, including
binary reconstruction after splitting, empty directories, pause/resume, restart
recovery, ownership, Range requests and purge. The real SMB/NFS fixture also
packs and verifies an archive from each backend.

Existing libraries retain their own terms. In particular libnfs is LGPL, not
MIT; its dynamic replacement, notices and source distribution arrangements are
documented in `THIRD_PARTY_NOTICES.md`. These findings concern the examined
versions, not a blanket statement about future dependencies.

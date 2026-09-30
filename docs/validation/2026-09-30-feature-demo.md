# 0.3.0 feature video validation

Recorded 2026-09-30 against the 0.3.0 app, using isolated demo configuration and actual CUA/CDP browser interactions. Edited to 124 seconds, 1920×1080, 30 fps, H.264, with 42 scenes and nine chapters. Captions are built in and also available as WebVTT. The complete MP4 decoded without errors and played in the in-app browser.

## SmartNAS S3

Used the existing SmartNAS Versity S3 gateway and only a dedicated `nas/remotefs-demo-20260930` prefix. GUI copied a local folder into S3, edited its README and copied it back into an empty local destination. Remote S3 MD5 values matched the local returned files. Local SHA-256 values follow.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `schedule.csv` | 101 | `dc5d1d6cf9b91b842d199491d22ab7d016c2750964231fa3b8a46a4c8709c67d` |
| `product-shot.png` | 9527 | `241de8c7642e82e702cbf914ef346b0d9a117ce15bb3737bac6dd14cc45713c4` |
| `README.md` | 117 | `de279bfbbfe97b9cfab42df0bfe171170e0d9ab383a8222d601be425fead261a` |
| `Approved/launch-notes.txt` | 30 | `5f20b5886a087e2ae6083590bc8f4a8bc897a5c8a562a441610fcb1dbe81b4e1` |

The client CLI also authenticated, connected to this managed rclone endpoint, listed the folder and returned a selection descriptor. The film's CLI card abbreviates commands; it is not a terminal recording.

## Archive and other workflows

A 128 MiB file was packed with 40 MiB parts. The four parts were concatenated, the resulting ZIP passed its integrity check, and the extracted content hash matched the original. A second packing job was paused and resumed through the GUI. Browser download completion is not claimed by this recording.

SMB discovery, authentication, listing and reading used an actual disposable SMB server in an isolated network namespace on SmartNAS. Libvirt used a test-driver pool with two sample volumes (64 and 32 GiB capacities). NFS and non-S3 cloud providers are connection-form demonstrations, not live transfer validation.

Local upload, folder creation, rename, move, shortlist, filtering and keyboard help were captured in the actual application. The embedded picker selected the real SmartNAS S3 folder and displayed a credential-free descriptor.

No production VM operations or changes to the existing SmartNAS remotefs services were needed. Real S3 credentials were kept in private temporary configuration and are absent from captured forms and repository artifacts.

# Third-party software

remote-fs-browser's own code is distributed under the MIT licence in `LICENSE`.
Its dependencies retain their own copyrights and licences. Our MIT licence does
not replace or remove those terms.

## Windows portable distribution

The portable download includes dependency licence texts under `licenses/`.
`licenses/INDEX.json` records the collected Python distributions and versions,
including Python runtime and PyInstaller licensing material where applicable.
Retain these files when redistributing the portable application.

The full licence file from the Windows Python installation is included, along
with notices from the MinGW toolchain used to build libnfs. MinGW and GCC runtime
notices are under `licenses/mingw/`; Python package metadata alone does not cover
these native components.

The principal storage libraries are:

- **smbprotocol**, used for SMB browsing: MIT, copyright Jordan Borean and Red Hat.
  Its copyright and permission notice are included in `licenses/smbprotocol/`.
  The SMB rename helper in `mutations.py` adapts its rename transaction to use
  metadata access instead of execute permission when resolving the destination.
  That notice is also included in the Python source and wheel distributions.
- **libnfs**, used for NFS: the library is LGPL-2.1-or-later; its protocol
  definitions and generated protocol code have BSD terms. Full upstream
  licensing material is included in `licenses/libnfs/` and the source archive.
  The utility/example programs are not built into this application.

The application dynamically loads `libnfs.dll` from beside `remotefs.exe`. You may
replace that DLL with a modified, interface-compatible build. We impose no
restriction on reverse engineering this application for debugging modifications
to that library. The source used to build the supplied library, including local
changes, is provided in `sources/libnfs-<commit>.tar.gz` inside the download.
See `licenses/libnfs/BUILDING.md`, `PROVENANCE.json`, and `local-changes.patch`
for the source revision, local changes, build recipe and replacement instructions.

## Python and Homebrew installations

Python package managers install dependencies separately; their licence texts
remain in those installed distributions. Homebrew installs libnfs separately
under its own licence. The Python wheel does not include a libnfs binary.

**Impacket** is used for SMB share enumeration on supported installations. It is
an optional extra on Windows and is included in the portable licence inventory
only when installed in that build. Its licence includes modified Apache-1.1
terms and additional notices for individual components.

This product includes software developed by SecureAuth Corporation
(https://www.secureauth.com/) and Fortra (https://www.fortra.com).

## Upstream licensing references

- smbprotocol: https://github.com/jborean93/smbprotocol/blob/master/LICENSE
- libnfs: https://github.com/sahlberg/libnfs/blob/master/COPYING
- Impacket: https://github.com/fortra/impacket/blob/master/LICENSE
- Python: https://docs.python.org/3/license.html
- PyInstaller: https://pyinstaller.org/en/stable/license.html

The full licence texts shipped with each release take precedence over this
summary. The inventory is generated from the packages installed for that build.

## Browser manager assets

The redesigned browser bundles React and ReactDOM 18.3.1 under MIT terms, with
copyright Meta Platforms, Inc. and affiliates. Full notices are included beside
the JavaScript as `web/react-LICENSE.txt` and `web/react-dom-LICENSE.txt` in the
Python package (and the corresponding package data in portable builds).
The declarative layout and DC support runtime came from the supplied design ZIP.
The browser loads the included assets locally; no Node server is required.

ZIP packing and job coordination use Python's standard library. No additional
Python package is required for those features.

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-folder spec for the portable Windows build.
#
# Run from the repository root:  pyinstaller --noconfirm packaging/remotefs.spec
# Output lands in dist/remotefs/ with remotefs.exe at its root.
#
# libnfs is NOT collected here: release.yml copies the MinGW-built libnfs.dll
# into dist/remotefs/ after this spec runs, and cli.py sets LIBNFS_LIBRARY to
# that bundled libnfs.dll (next to sys.executable) when sys.frozen is set.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = (
    # SMB stack: smbprotocol and smbclient import their transports and
    # authentication providers lazily, as does pyspnego underneath them.
    collect_submodules("smbprotocol")
    + collect_submodules("smbclient")
    + collect_submodules("spnego")
    # impacket's DCE/RPC layer (SRVSVC share enumeration) is loaded by name.
    + ["impacket", "impacket.smbconnection", "impacket.nmb", "impacket.ntlm"]
    + collect_submodules("impacket.dcerpc.v5")
    # uvicorn selects its loop and protocol implementations from strings.
    + collect_submodules("uvicorn")
    + collect_submodules("remote_fs_browser")
)

a = Analysis(
    [os.path.join(SPECPATH, "remotefs_entry.py")],
    pathex=[],
    binaries=[],
    # Ships web/*.js and web/*.html (declared as package data in pyproject.toml).
    datas=collect_data_files("remote_fs_browser"),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="remotefs",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="remotefs",
)

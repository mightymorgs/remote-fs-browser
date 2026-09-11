# Installation demonstration

This silent recording shows real command output and browser interactions on macOS. Python 3.11+ and pipx are already installed. The installation uses isolated pipx and application configuration directories, and all files and credentials are disposable examples.

1. Install the published package with `pipx install remote-fs-browser==0.2.1`.
2. Create the demo account using `remotefs account --config demo.json --username demo --password-stdin`. The demo password is supplied through standard input and is not displayed.
3. Start the application with `remotefs serve --config demo.json --root "Demo files" --no-defaults --port 8110`. This limits the example to a single local folder.
4. Open `http://127.0.0.1:8110/` and sign in.
5. Browse the demo files, open `Welcome.txt`, edit its contents and save.
6. Create `My workspace`, add it to favourites and browse it.
7. Return to the root and download `Welcome.txt`. The recording script verifies that the downloaded bytes match the saved file.

The recording demonstrates local file management. For remote SMB/NFS connections, multipart archives and installation on other platforms, see the [quickstart](QUICKSTART.md).

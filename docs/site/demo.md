# Installation and network demonstration

The recording uses the published 0.2.1 package and real browser interactions. The opening shows installation and local file management on macOS. The network section uses the same package on a Linux hypervisor, reached from the Mac through an SSH tunnel over Tailscale. The SMB server is SmartNAS, with a temporary read-only share containing a clean checkout of this public repository.

## Installation and local files

1. Install `remote-fs-browser==0.2.1` with pipx. Python 3.11+ and pipx are already installed.
2. Create a demo account and start the service with an isolated local root. The password is supplied privately; paths in the terminal are shortened for readability.
3. Sign in, open and edit a text file, create a folder and add it to favourites.
4. Download the edited file. The recording script checks the downloaded bytes against the saved file.

## Network workflow

1. Sign in to the Linux service from the Mac browser over the Tailscale SSH tunnel.
2. Scan `192.168.0.0/24` for SMB/NFS services. The table has separate DNS, NetBIOS and IP columns; names appear only when the network supplies them.
3. Select `192.168.122.0/24`, the hypervisor’s NAT VM subnet, and scan it. No SMB/NFS services answered on that subnet during this recording. Discovery finds file services, not every running VM.
4. Scan the NAS address, select **Map**, enter SMB credentials and save them.
5. Open the `remotefs-demo` share and add its repo folder to the shortlist.
6. Browse `README.md`, then open the Python source under `src/remote_fs_browser/cli.py` directly from the NAS.
7. Click one checkbox, then Shift-click another to select a range of files.
8. Right-click `README.md`, choose **Download** and save it. The recording script compares the downloaded file with the NAS copy byte for byte.
9. Reload the page and reopen the saved network location from the shortlist.
10. Map the server again using its saved credentials, then **Unmount** it. The recording checks that the session deletion succeeds and the sidebar mapping disappears.

## How it works

One Python service connects to the shares its host can reach. The viewing device needs a browser and a permitted connection to that service; file servers need no remotefs agent. Tailscale can carry the browser-to-service connection without installing Tailscale on every LAN file server.

**Map** and **Unmount** manage application sessions. They do not create or remove operating-system mounts on either computer. Saved locations and credentials persist separately from page-local mappings. Network routes, policy, share credentials and filesystem permissions still apply.

The service uses Python packages for local access and SMB. NFS additionally uses libnfs 6+; the browser interface uses JavaScript. The network portion demonstrates SMB; NFS connection setup is covered in the quickstart. See the [quickstart](QUICKSTART.md#one-service-network-access-through-tailscale) for setup and the complete platform instructions.

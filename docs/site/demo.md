# Installation and network demonstration

The recording uses the published 0.2.1 package and real browser interactions. The opening includes a short installation excerpt on macOS. The network section uses the same package on a Linux hypervisor, reached from the Mac through an SSH tunnel over Tailscale. The SMB server is SmartNAS, with a temporary read-only share containing a clean checkout of this public repository.

## Short installation excerpt

The feature cut briefly shows installing `remote-fs-browser==0.2.1` with pipx. Python and pipx are already installed. The longer [installation and local-file walkthrough](https://github.com/mightymorgs/remote-fs-browser/releases/download/v0.2.1/remotefs-demo.mp4) also shows account setup, editing, folder creation and a local-file download.

The 70-second feature cut removes scan waits and repeated navigation. Feature labels are built into the MP4, including explicit SMB connection and download proof. These are edited recordings of actual interactions; filesystem responses are not simulated.

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

## SMB proof

The service connected to `smb://192.168.0.107/remotefs-demo`. The browser downloaded `remote-fs-browser/README.md` through that SMB session, and the recording script compared the downloaded bytes with the NAS source over SSH. They matched. The downloaded file also matches the README in the public v0.2.1 tag:

```text
SHA-256: 2166f9029173896511b2feeb5c98f255df7d840c323ddb998291a88ecc4036d6
```

## How it works

Open a browser from another device, from anywhere. One Python service connects to the shares its host can reach. The viewing device needs a browser and a permitted connection to that service; file servers need no remotefs agent. Tailscale can carry the browser-to-service connection without installing Tailscale on every LAN file server.

**Map** and **Unmount** manage application sessions. They do not create or remove operating-system mounts on either computer. Saved locations and credentials persist separately from page-local mappings. Network routes, policy, share credentials and filesystem permissions still apply.

The service uses Python packages for local access and SMB. NFS additionally uses libnfs 6+; the browser interface uses JavaScript. The network portion demonstrates SMB; NFS connection setup is covered in the quickstart. See the [quickstart](QUICKSTART.md#one-service-network-access-through-tailscale) for setup and the complete platform instructions.

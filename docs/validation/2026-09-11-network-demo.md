# Network demonstration — 11 September 2026

The expanded video uses the published `remote-fs-browser==0.2.1` package. The local installation segment runs on macOS. The network segment runs the Python service on a Linux hypervisor, with Chromium on the Mac accessing it through an SSH tunnel over Tailscale. A temporary, read-only Samba share on SmartNAS contains a clean checkout of the public v0.2.1 repository.

Verified through actual Chromium interactions:

- LAN scan of `192.168.0.0/24` finds SMB/NFS services.
- Changing the scanner to `192.168.122.0/24` completes a second subnet scan. No SMB/NFS services answered there; the running VM’s ports 445 and 2049 also timed out in a direct connection check.
- Mapping the NAS, saving SMB credentials, enumerating shares and browsing the temporary share.
- Saving the repo folder to the shortlist and reopening it after a page reload.
- Previewing the remote README and `src/remote_fs_browser/cli.py`.
- Shift-clicking checkboxes selects a range containing multiple files.
- Right-clicking the README opens the action menu; downloading it produces bytes identical to the NAS copy.
- Reusing saved credentials to map the NAS after reload.
- Unmount sends a successful session DELETE and removes the sidebar mapping.
- The service host’s CIFS/NFS mount list is identical before and after the workflow.

## Compatibility issue discovered

On a plain-HTTP network origin, Chromium does not expose `crypto.randomUUID`. The published download queue calls that method and fails before displaying its transfer. The source fix generates its local transfer identifier with `crypto.getRandomValues`, which is available on these origins.

Validation: all 14 frontend tests pass, including a regression that constructs a download with `randomUUID` absent. An actual Chromium test against the HTTP Tailscale address, serving the patched manager asset, also downloads a file successfully. This fix is in source; the video uses the unmodified published package over the localhost SSH tunnel.

Tailscale Serve was attempted, but certificate issuance failed on the host. The temporary Serve configuration was removed. The demo does not claim to have validated that HTTPS endpoint.

The temporary NAS share and demo services are removed after recording. No personal file contents or passwords are included in the public recording.

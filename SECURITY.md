# Security boundaries

The reference agent grants read access to configured filesystems. Keep it on a private network or behind TLS and restrict its listener/firewall to intended clients. A VPN is transport, not authentication. Supply a unique random service token or an authentication hook. The stock CLI is a single-principal reference service; use authorization hooks and credential ownership checks in multi-user applications.

Default roots and network ranges are empty. Connections are checked against allowlists and hostnames are resolved/pinned inside the worker. Python SMB redirects to other servers are blocked. Protocols and operations are read-only. Local traversal, alternate Windows data streams and symlink/reparse entries are rejected. POSIX file access walks directory descriptors with `O_NOFOLLOW`; Windows file reads validate the final opened handle against the selected root. Windows directory metadata enumeration still uses pathname APIs: do not expose a writable adversarial namespace as a security boundary. Remote SMB/NFS servers and their filesystem namespace are trusted to enforce their own permissions; this is not an OS sandbox against a malicious NAS.

A worker owns one backend connection and at most four file streams. Operations time out and the worker is terminated if necessary. Workers expire after inactivity; streams close on completion/disconnect. Explicit session deletion closes immediately. HTTP control bodies are limited to 16 KiB; authenticated requests are rate-limited per principal. Native directory enumeration is capped and signals truncation. File responses are bounded chunks, with single-range support and attachment/nosniff headers.

Do not put passwords in descriptors, URLs, CLI arguments, logs or source control. Credential resolvers must check that the requesting principal owns each reference. Hook implementations must not log secrets. Config files contain the service token and need restrictive permissions.

System installers run the service as root/SYSTEM so NFS can use reserved source ports and local roots are visible. Narrow the policy carefully. Prefer an unprivileged service account when your NAS permissions allow it; filesystem permissions can then further limit access. Windows desktop drive mappings may not be visible to SYSTEM; connect to the SMB share directly instead.

If you identify a vulnerability, use GitHub's private vulnerability reporting for this repository. Do not post credentials, real filesystem data, or exploitable access details in public issues.

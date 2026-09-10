# Disposable protocol servers

This fixture runs Samba and NFS-Ganesha with an in-memory NFS filesystem. It uses
public test credentials and no host volume mounts. Publish its ports on loopback
only. It is not a production server configuration.

With Docker and libnfs installed:

```sh
docker build -t remotefs-protocol-tests:local tests/protocol
docker run -d --name remotefs-protocol-tests -p 127.0.0.1:445:445 -p 127.0.0.1:2049:2049 remotefs-protocol-tests:local
# Wait for both server ports to be ready.
python tests/protocol/exercise.py
docker rm -f remotefs-protocol-tests
```

Use an environment with ports 445 and 2049 free. The exercise covers binary
writes/readback, conflicts, replacement, recursive copy, folder move and deletion
through SMB and NFSv4. The CI protocol-integration job runs this fixture.

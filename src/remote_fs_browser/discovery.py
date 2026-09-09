"""Bounded, opt-in TCP discovery plus protocol-native share/export enumeration."""
from concurrent.futures import ThreadPoolExecutor
import ctypes as c
import ipaddress
from pathlib import PurePath
import socket
from .policy import Policy


def grouped(policy: Policy, roots, hosts, scanned):
    """The picker's tree: This Computer, then SMB and NFS servers seen from this host."""
    local = [{'type': 'local', 'root': row['root'], 'kind': row['kind'],
              'label': 'Home' if row['kind'] == 'home' else PurePath(row['root']).name or row['root']} for row in roots]
    hint = None
    if not scanned:
        hint = ('Press Discover to scan ' + ', '.join(policy.network_ranges) + ', or enter a server above.'
                if policy.network_ranges else 'No networks are permitted for SMB/NFS on this service.')
    groups = [{'id': 'local', 'label': 'This Computer', 'items': local}]
    for protocol, label in (('smb', 'SMB'), ('nfs', 'NFS')):
        items = [{'type': protocol, 'host': row['host'], 'label': row['host']} for row in hosts if protocol in row['protocols']]
        groups.append({'id': protocol, 'label': label, 'items': items, 'hint': hint})
    return groups


def discover(policy: Policy, scan=False, root_kinds=None):
    policy.require('discover')
    kinds = root_kinds or {}
    result = {'roots': [{'type': 'local', 'root': root, 'kind': kinds.get(root, 'configured')} for root in policy.local_roots],
              'hosts': [], 'notes': ['Automatic discovery is best effort. A hostname/IP can always be supplied within policy.']}
    if not scan:
        result['groups'] = grouped(policy, result['roots'], [], False)
        return result
    hosts = set()
    for network in policy.network_ranges:
        network = ipaddress.ip_network(network)
        if network.num_addresses > 256:
            result['notes'].append('Skipped a range larger than 256 addresses; configure narrower discovery ranges.')
            continue
        hosts.update(str(host) for host in network.hosts())
    if policy.servers:
        hosts &= {policy.host(host) for host in policy.servers}
    hosts = sorted(hosts, key=ipaddress.ip_address)
    if len(hosts) > 256:
        result['notes'].append(f'Scanned the first 256 of {len(hosts)} candidate addresses; narrow the permitted ranges to scan the rest.')
        hosts = hosts[:256]

    def probe(host):
        protocols = []
        for port, name in [(445, 'smb'), (2049, 'nfs')]:
            try:
                with socket.create_connection((host, port), timeout=0.25):
                    protocols.append(name)
            except OSError:
                pass
        return {'host': host, 'protocols': protocols} if protocols else None

    with ThreadPoolExecutor(max_workers=32) as executor:
        result['hosts'] = [row for row in executor.map(probe, hosts) if row]
    result['groups'] = grouped(policy, result['roots'], result['hosts'], True)
    return result


def smb_shares(host, credentials):
    from impacket.smbconnection import SMBConnection
    from impacket.smb3structs import SMB2_DIALECT_21
    # Explicit SMB2 dialect prevents falling back to SMB1 browser services.
    connection = SMBConnection(host, host, sess_port=445, timeout=5, preferredDialect=SMB2_DIALECT_21)
    try:
        connection.login(credentials.get('username', ''), credentials.get('password', ''), credentials.get('domain', ''))
        from impacket.dcerpc.v5 import transport, srvs
        rpc = transport.SMBTransport(host, host, filename=r'\srvsvc', smb_connection=connection).get_dce_rpc()
        rows, resume, truncated = [], 0, False
        try:
            rpc.connect()
            rpc.bind(srvs.MSRPC_UUID_SRVS)
            for _ in range(32):
                try:
                    response = srvs.hNetrShareEnum(rpc, 1, resumeHandle=resume, preferedMaximumLength=65536, serverName='\\\\' + host)
                    more = False
                except srvs.DCERPCSessionError as error:
                    if error.get_error_code() != 234:  # ERROR_MORE_DATA
                        raise
                    response, more = error.get_packet(), True
                for row in response['InfoStruct']['ShareInfo']['Level1']['Buffer']:
                    if int(row['shi1_type']) & 0xFFFF == 0:
                        rows.append({'name': str(row['shi1_netname']).rstrip('\x00'), 'description': str(row['shi1_remark']).rstrip('\x00')})
                        if len(rows) == 1000:
                            truncated = True
                            break
                if not more or truncated:
                    break
                next_resume = int(response['ResumeHandle'])
                if next_resume == resume:
                    truncated = True
                    break
                resume = next_resume
            else:
                truncated = True
            return {'shares': rows, 'truncated': truncated}
        finally:
            rpc.disconnect()

    finally:
        connection.close()


class Export(c.Structure):
    pass


Export._fields_ = [('directory', c.c_char_p), ('groups', c.c_void_p), ('next', c.POINTER(Export))]


def nfs_exports(host):
    from .nfs import library
    lib = library()
    lib.mount_getexports_timeout.argtypes = [c.c_char_p, c.c_int]
    lib.mount_getexports_timeout.restype = c.POINTER(Export)
    lib.mount_free_export_list.argtypes = [c.POINTER(Export)]
    lib.mount_free_export_list.restype = None
    head = lib.mount_getexports_timeout(host.encode(), 5)
    rows, current = [], head
    try:
        while current and len(rows) < 1000:
            rows.append(current.contents.directory.decode('utf-8', errors='replace'))
            current = current.contents.next
    finally:
        if head:
            lib.mount_free_export_list(head)
    return {'exports': rows, 'truncated': bool(current),
            'notes': ['Uses mountd export discovery. Empty results do not mean no exports: NFSv4-only servers may require a manually entered export.']}

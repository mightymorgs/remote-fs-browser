"""Bounded, opt-in TCP discovery plus protocol-native share/export enumeration."""
from concurrent.futures import ThreadPoolExecutor
import ctypes as c
import ipaddress
from pathlib import PurePath
import socket
from .policy import Policy
from .hostnames import dns_name, netbios_name

# Candidate addresses probed per scan request: one page at a time, keeping large subnets within the operation timeout.
SCAN_BUDGET = 256


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
        items = [{'type': protocol, 'host': row['host'], 'label': row.get('name') or row['host'],
                  **{key: row[key] for key in ('dns_name', 'netbios_name') if row.get(key)}}
                 for row in hosts if protocol in row['protocols']]
        groups.append({'id': protocol, 'label': label, 'items': items, 'hint': hint})
    return groups


def discover(policy: Policy, scan=False, root_kinds=None, ranges=None, offset=0):
    policy.require('discover')
    if ranges is not None and (not isinstance(ranges, list) or not ranges or len(ranges) > 16):
        raise ValueError('Enter between one and sixteen CIDR ranges')
    selected = ranges if ranges is not None else (policy.discovery_ranges if policy.discovery_ranges is not None else policy.network_ranges)
    parsed = [ipaddress.ip_network(value, strict=False) for value in selected]
    networks = [net for version in (4, 6) for net in ipaddress.collapse_addresses([net for net in parsed if net.version == version])]
    allowed_networks = [ipaddress.ip_network(value) for value in policy.network_ranges]
    permitted = [net for version in (4, 6) for net in ipaddress.collapse_addresses([net for net in allowed_networks if net.version == version])]
    if any(not any(net.version == allowed.version and net.subnet_of(allowed) for allowed in permitted) for net in networks):
        raise PermissionError('Scan range is outside permitted networks')
    if not isinstance(offset, int) or offset < 0:
        raise ValueError('Invalid scan offset')
    kinds = root_kinds or {}
    result = {'roots': [{'type': 'local', 'root': root, 'kind': kinds.get(root, 'configured')} for root in policy.local_roots],
              'scan_ranges': [str(net) for net in networks], 'next_offset': None, 'hosts': [], 'notes': ['Automatic discovery is best effort. A hostname/IP can always be supplied within policy.']}
    if not scan:
        result['groups'] = grouped(policy, result['roots'], [], False)
        return result
    # Generate only the requested page, including for very large subnets.
    hosts = []
    skip = offset
    total = sum(net.num_addresses - (2 if net.version == 4 and net.prefixlen < 31 else 1 if net.version == 6 and net.prefixlen < 127 else 0) for net in networks)
    for net in networks:
        excluded = 2 if net.version == 4 and net.prefixlen < 31 else 1 if net.version == 6 and net.prefixlen < 127 else 0
        count = net.num_addresses - excluded
        if skip >= count:
            skip -= count
            continue
        first = int(net.network_address) + (1 if excluded else 0) + skip
        take = min(SCAN_BUDGET - len(hosts), count - skip)
        hosts.extend(str(type(net.network_address)(first + index)) for index in range(take))
        skip = 0
        if len(hosts) == SCAN_BUDGET:
            break
    scanned = len(hosts)
    result.update(scan_offset=offset, scanned=scanned, total_addresses=total)
    if offset + scanned < total:
        result['next_offset'] = offset + scanned
    result['notes'].append(f'Scanned addresses {offset + 1 if scanned else 0}–{offset + scanned} of {total}. Continue with the next batch for larger subnets.')
    if policy.servers:
        allowed_hosts = {policy.host(host) for host in policy.servers}
        hosts = [host for host in hosts if host in allowed_hosts]

    def probe(host):
        protocols = []
        for port, name in [(445, 'smb'), (2049, 'nfs')]:
            try:
                # One second covers ARP resolution on Wi-Fi clients; a quarter second missed live LAN hosts.
                with socket.create_connection((host, port), timeout=1.0):
                    protocols.append(name)
            except OSError:
                pass
        if not protocols:
            return None
        names = {key: value for key, value in (
            ('dns_name', dns_name(host)), ('netbios_name', netbios_name(host))) if value}
        name = names.get('dns_name') or names.get('netbios_name')
        return {'host': host, 'protocols': protocols, **names, **({'name': name} if name else {})}

    with ThreadPoolExecutor(max_workers=64) as executor:
        result['hosts'] = [row for row in executor.map(probe, hosts) if row]
    result['groups'] = grouped(policy, result['roots'], result['hosts'], True)
    return result


def share_enumeration_available():
    import importlib.util
    return importlib.util.find_spec('impacket') is not None


def smb_shares(host, credentials):
    if not share_enumeration_available():
        raise RuntimeError('SMB share enumeration needs the impacket package (pip install "remote-fs-browser[smb-enum]"); enter the share name instead')
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

"""Bounded, opt-in TCP discovery plus protocol-native share/export enumeration."""
from concurrent.futures import ThreadPoolExecutor
import os
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
              'endpoints': [{'type': value['type'], 'endpoint': name, 'label': name} for name, value in policy.endpoints.items()],
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


class DiscoveryError(ValueError):
    """Why shares could not be listed, in words the person signing in can act on."""
    shown = True


def share_enumeration_available():
    import importlib.util
    return os.name == 'nt' or importlib.util.find_spec('impacket') is not None


# Windows network API results that deserve their own message; anything else is reported by number.
WINDOWS_SHARE_ERRORS = {
    5: 'The server refused to list its shares for this login (access denied)',
    53: 'The server could not be reached; check the address and that file sharing is on',
    67: 'The server could not be reached; check the address and that file sharing is on',
    86: 'Incorrect username or password',
    1219: 'This computer already has a connection to that server with a different login; try again in a minute',
    1326: 'Incorrect username or password',
    1331: 'That account is disabled on the server',
    1909: 'That account is locked out on the server',
}


def windows_smb_shares(host, credentials, api=None):
    """List a server's disk shares with Windows' own API. impacket is not used on Windows: Defender quarantines
    its bundled tools. The IPC$ connection lives in this service's logon session only and is closed at once."""
    import ctypes
    from ctypes import wintypes
    from .backends import smb_username
    mpr, netapi = api or (ctypes.WinDLL('mpr'), ctypes.WinDLL('netapi32'))

    class NETRESOURCEW(ctypes.Structure):
        _fields_ = [('dwScope', wintypes.DWORD), ('dwType', wintypes.DWORD), ('dwDisplayType', wintypes.DWORD),
                    ('dwUsage', wintypes.DWORD), ('lpLocalName', wintypes.LPWSTR), ('lpRemoteName', wintypes.LPWSTR),
                    ('lpComment', wintypes.LPWSTR), ('lpProvider', wintypes.LPWSTR)]

    class SHARE_INFO_1(ctypes.Structure):
        _fields_ = [('shi1_netname', wintypes.LPWSTR), ('shi1_type', wintypes.DWORD), ('shi1_remark', wintypes.LPWSTR)]

    def failed(code):
        return DiscoveryError(WINDOWS_SHARE_ERRORS.get(code, f'Could not list shares on {host} (Windows error {code})'))

    server = '\\\\' + host
    remote = server + '\\IPC$'
    user = smb_username(host, credentials.get('username'), credentials.get('domain'), windows=True) or None
    code = mpr.WNetAddConnection2W(ctypes.byref(NETRESOURCEW(dwType=0, lpRemoteName=remote)),
                                   credentials.get('password') or None, user, 0)
    if code:
        raise failed(code)
    try:
        rows, resume, truncated = [], wintypes.DWORD(0), False
        while True:
            buffer, read, total = ctypes.c_void_p(), wintypes.DWORD(), wintypes.DWORD()
            status = netapi.NetShareEnum(server, 1, ctypes.byref(buffer), 0xFFFFFFFF, ctypes.byref(read),
                                         ctypes.byref(total), ctypes.byref(resume))
            if status not in (0, 234):  # 234: ERROR_MORE_DATA
                raise failed(status)
            try:
                if buffer.value:
                    for row in ctypes.cast(buffer, ctypes.POINTER(SHARE_INFO_1 * read.value)).contents:
                        if row.shi1_type & 0xFFFF == 0 and len(rows) < 1000:  # disk shares, not IPC$ or printers
                            rows.append({'name': row.shi1_netname or '', 'description': row.shi1_remark or ''})
            finally:
                if buffer.value:
                    netapi.NetApiBufferFree(buffer)
            if len(rows) >= 1000:
                truncated = True
            if status == 0 or truncated:
                return {'shares': rows, 'truncated': truncated}
    finally:
        mpr.WNetCancelConnection2W(remote, 0, True)


def smb_shares(host, credentials):
    if os.name == 'nt':
        return windows_smb_shares(host, credentials)
    if not share_enumeration_available():
        raise DiscoveryError('SMB share enumeration needs the impacket package (pip install "remote-fs-browser[smb-enum]"); enter the share name instead')
    from impacket.smbconnection import SMBConnection, SessionError
    from impacket.smb3structs import SMB2_DIALECT_21
    # Explicit SMB2 dialect prevents falling back to SMB1 browser services.
    connection = SMBConnection(host, host, sess_port=445, timeout=5, preferredDialect=SMB2_DIALECT_21)
    try:
        try:
            connection.login(credentials.get('username', ''), credentials.get('password', ''), credentials.get('domain', ''))
        except SessionError as error:
            raise DiscoveryError('Incorrect username or password' if 'LOGON_FAILURE' in str(error) else f'The server refused this login ({error})') from None
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

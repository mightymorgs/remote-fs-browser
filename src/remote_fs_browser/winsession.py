"""Start rclone inside a signed-in Windows user's own session, from a service running as SYSTEM.

A drive letter exists only in the logon session that creates it, so a mount made by the SYSTEM
service would belong to no user (or, with --network-mode, be reachable by everyone). Instead the
service finds the mount owner's session, borrows that session's token and starts rclone there, so
the drive appears for that person only. The owner has to be signed in.
"""
import ctypes
import subprocess
from ctypes import wintypes

WTS_ACTIVE, WTS_DISCONNECTED = 0, 4
WTS_USER_NAME, WTS_DOMAIN_NAME = 5, 7
TOKEN_QUERY, TOKEN_USER = 0x0008, 1
CREATE_UNICODE_ENVIRONMENT, CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW = 0x400, 0x200, 0x08000000
WAIT_TIMEOUT, INFINITE = 0x102, 0xFFFFFFFF


class SessionInfo(ctypes.Structure):
    _fields_ = [('SessionId', wintypes.DWORD), ('pWinStationName', wintypes.LPWSTR), ('State', ctypes.c_int)]


class StartupInfo(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                ('lpTitle', wintypes.LPWSTR), ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD), ('dwXCountChars', wintypes.DWORD),
                ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', ctypes.c_void_p),
                ('hStdInput', wintypes.HANDLE), ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class ProcessInformation(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


def same_account(a, b):
    """'PC\\morgan' matches 'morgan'; with both domains given, the domains must match too."""
    a, b = a.strip().casefold(), b.strip().casefold()
    if '\\' in a and '\\' in b:
        return a == b
    return a.rsplit('\\', 1)[-1] == b.rsplit('\\', 1)[-1]


def _dlls():
    dll = lambda name: ctypes.WinDLL(name, use_last_error=True)
    wts, advapi, userenv, kernel = dll('wtsapi32'), dll('advapi32'), dll('userenv'), dll('kernel32')
    H, P = wintypes.HANDLE, ctypes.c_void_p
    for fn, args, result in [
        (wts.WTSEnumerateSessionsW, [H, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(SessionInfo)),
                                     ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (wts.WTSQuerySessionInformationW, [H, wintypes.DWORD, ctypes.c_int, ctypes.POINTER(wintypes.LPWSTR),
                                           ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (wts.WTSFreeMemory, [P], None),
        (wts.WTSQueryUserToken, [wintypes.ULONG, ctypes.POINTER(H)], wintypes.BOOL),
        (advapi.OpenProcessToken, [H, wintypes.DWORD, ctypes.POINTER(H)], wintypes.BOOL),
        (advapi.GetTokenInformation, [H, ctypes.c_int, P, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (advapi.ConvertSidToStringSidW, [P, ctypes.POINTER(wintypes.LPWSTR)], wintypes.BOOL),
        (advapi.CreateProcessAsUserW, [H, wintypes.LPCWSTR, wintypes.LPWSTR, P, P, wintypes.BOOL, wintypes.DWORD, P,
                                       wintypes.LPCWSTR, ctypes.POINTER(StartupInfo),
                                       ctypes.POINTER(ProcessInformation)], wintypes.BOOL),
        (userenv.CreateEnvironmentBlock, [ctypes.POINTER(P), H, wintypes.BOOL], wintypes.BOOL),
        (userenv.DestroyEnvironmentBlock, [P], wintypes.BOOL),
        (userenv.GetUserProfileDirectoryW, [H, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (kernel.GetCurrentProcess, [], H),
        (kernel.CloseHandle, [H], wintypes.BOOL),
        (kernel.LocalFree, [P], P),
        (kernel.WaitForSingleObject, [H, wintypes.DWORD], wintypes.DWORD),
        (kernel.GetExitCodeProcess, [H, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (kernel.TerminateProcess, [H, wintypes.UINT], wintypes.BOOL),
    ]:
        fn.argtypes, fn.restype = args, result
    return wts, advapi, userenv, kernel


def _check(ok):
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _session_text(wts, session, kind):
    buffer, size = wintypes.LPWSTR(), wintypes.DWORD()
    if not wts.WTSQuerySessionInformationW(None, session, kind, ctypes.byref(buffer), ctypes.byref(size)):
        return ''
    try:
        return buffer.value or ''
    finally:
        wts.WTSFreeMemory(ctypes.cast(buffer, ctypes.c_void_p))


def session_of(account):
    """The owner's session id: an active one first, else a disconnected one, else None."""
    wts = _dlls()[0]
    rows, count = ctypes.POINTER(SessionInfo)(), wintypes.DWORD()
    _check(wts.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(rows), ctypes.byref(count)))
    found = {}
    try:
        for i in range(count.value):
            row = rows[i]
            if row.State not in (WTS_ACTIVE, WTS_DISCONNECTED):
                continue
            name = _session_text(wts, row.SessionId, WTS_USER_NAME)
            domain = _session_text(wts, row.SessionId, WTS_DOMAIN_NAME)
            if name and same_account(f'{domain}\\{name}' if domain else name, account):
                found.setdefault(row.State, row.SessionId)
    finally:
        wts.WTSFreeMemory(ctypes.cast(rows, ctypes.c_void_p))
    return found.get(WTS_ACTIVE, found.get(WTS_DISCONNECTED))


class UserSession:
    """The owner's token for one mount. Call close() once the process has started."""

    def __init__(self, session):
        self.wts, self.advapi, self.userenv, self.kernel = _dlls()
        self.token = wintypes.HANDLE()
        _check(self.wts.WTSQueryUserToken(session, ctypes.byref(self.token)))

    def sid(self):
        return token_sid(self.advapi, self.kernel, self.token)

    def profile(self):
        size = wintypes.DWORD(0)
        self.userenv.GetUserProfileDirectoryW(self.token, None, ctypes.byref(size))
        buffer = ctypes.create_unicode_buffer(size.value or 1024)
        _check(self.userenv.GetUserProfileDirectoryW(self.token, buffer, ctypes.byref(size)))
        return buffer.value

    def environment(self):
        block = ctypes.c_void_p()
        _check(self.userenv.CreateEnvironmentBlock(ctypes.byref(block), self.token, False))
        try:
            values, offset = {}, 0
            while True:
                item = ctypes.wstring_at(block.value + offset * ctypes.sizeof(ctypes.c_wchar))
                if not item:
                    return values
                key, _, value = item.partition('=')
                if key:  # entries such as "=C:=C:\\" start with '=' and are skipped
                    values[key] = value
                offset += len(item) + 1
        finally:
            self.userenv.DestroyEnvironmentBlock(block)

    def start(self, argv, env, cwd):
        text = ''.join(f'{key}={value}\0' for key, value in env.items()) + '\0'
        # Raw UTF-16 bytes, so the NUL separators between entries survive.
        block = ctypes.create_string_buffer(text.encode('utf-16-le'))
        startup = StartupInfo(cb=ctypes.sizeof(StartupInfo), lpDesktop='winsta0\\default')
        info = ProcessInformation()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        flags = CREATE_UNICODE_ENVIRONMENT | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        _check(self.advapi.CreateProcessAsUserW(self.token, None, command, None, None, False, flags,
                                                ctypes.cast(block, ctypes.c_void_p), cwd,
                                                ctypes.byref(startup), ctypes.byref(info)))
        self.kernel.CloseHandle(info.hThread)
        return UserProcess(self.kernel, info.hProcess, info.dwProcessId, argv)

    def close(self):
        if self.token:
            self.kernel.CloseHandle(self.token)
            self.token = wintypes.HANDLE()


def token_sid(advapi, kernel, token):
    needed = wintypes.DWORD()
    advapi.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    _check(advapi.GetTokenInformation(token, TOKEN_USER, buffer, needed, ctypes.byref(needed)))
    sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER starts with the SID pointer
    text = wintypes.LPWSTR()
    _check(advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
    try:
        return text.value
    finally:
        kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def current_sid():
    _, advapi, _, kernel = _dlls()
    token = wintypes.HANDLE()
    _check(advapi.OpenProcessToken(kernel.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)))
    try:
        return token_sid(advapi, kernel, token)
    finally:
        kernel.CloseHandle(token)


class UserProcess:
    """The subset of subprocess.Popen that MountManager uses, for a process started as another user."""

    def __init__(self, kernel, handle, pid, args):
        self.kernel, self.handle, self.pid, self.args = kernel, handle, pid, args
        self.returncode = None

    def poll(self):
        if self.returncode is None and self.kernel.WaitForSingleObject(self.handle, 0) != WAIT_TIMEOUT:
            code = wintypes.DWORD()
            self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code))
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        wait = INFINITE if timeout is None else int(timeout * 1000)
        if self.returncode is None and self.kernel.WaitForSingleObject(self.handle, wait) == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.poll()

    def kill(self):
        if self.poll() is None:
            self.kernel.TerminateProcess(self.handle, 1)

    terminate = kill

    def send_signal(self, value):
        # A console signal cannot reach another session; rclone is normally stopped over rc instead.
        self.kill()

    def __del__(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None

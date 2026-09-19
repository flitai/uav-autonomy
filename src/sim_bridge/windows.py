"""Windows process identity without an additional native Python dependency."""
import ctypes
from ctypes import wintypes
import os
import socket
import struct

from .codec import require


def process_identity(pid):
    require(os.name == 'nt', 'This qualified runtime requires native Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    require(bool(handle), 'Backend process is absent or inaccessible: ' + str(pid))
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        require(kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(system), ctypes.byref(user)), 'Cannot read backend process times')
        code = wintypes.DWORD()
        require(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259, 'Backend process has exited')
        return {'pid': str(pid), 'created_filetime': str((created.dwHighDateTime << 32) | created.dwLowDateTime)}
    finally:
        kernel.CloseHandle(handle)


def tcp_connections():
    """Read the IPv4 owner table; this function never changes a TCP endpoint."""
    require(os.name == 'nt', 'Native Windows TCP ownership is required')
    library = ctypes.WinDLL('iphlpapi', use_last_error=True)
    function = library.GetExtendedTcpTable
    function.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                         wintypes.ULONG, ctypes.c_int, wintypes.ULONG)
    function.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    require(function(None, ctypes.byref(size), False, socket.AF_INET, 5, 0) in (0, 122), 'Cannot size TCP ownership table')
    for _ in range(3):
        require(4 <= size.value <= 1048576, 'TCP ownership table exceeds bound')
        buffer = ctypes.create_string_buffer(size.value)
        status = function(buffer, ctypes.byref(size), False, socket.AF_INET, 5, 0)
        if status == 122:
            continue
        require(status == 0, 'Cannot read TCP ownership table')
        count = struct.unpack_from('<I', buffer)[0]
        require(4 + count * 24 <= size.value, 'TCP ownership table is truncated')
        result = []
        for index in range(count):
            state, local, local_port, remote, remote_port, pid = struct.unpack_from('<6I', buffer, 4 + index * 24)
            result.append({'state': state, 'local_address': socket.inet_ntoa(struct.pack('<I', local)),
                           'local_port': socket.ntohs(local_port & 65535),
                           'remote_address': socket.inet_ntoa(struct.pack('<I', remote)),
                           'remote_port': socket.ntohs(remote_port & 65535), 'pid': str(pid)})
        return result
    raise RuntimeError('TCP ownership table kept changing size')


def main_connection(pid, remote_port):
    matches = [row for row in tcp_connections() if row['pid'] == str(pid) and row['state'] == 5
               and row['remote_address'] == '127.0.0.1' and row['remote_port'] == remote_port]
    require(len(matches) == 1, 'Main task TCP connection is absent or ambiguous')
    return matches[0]

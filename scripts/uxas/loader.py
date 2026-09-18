"""Observe one owned, pre-service CLI smoke process using Windows debug events."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import msvcrt


class Startup(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                ('x', w.DWORD), ('y', w.DWORD), ('xs', w.DWORD), ('ys', w.DWORD),
                ('xc', w.DWORD), ('yc', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved2', w.WORD), ('bytes', c.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class Process(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class Payload(c.Union):
    _fields_ = [('raw', c.c_ubyte * 160), ('handle', w.HANDLE), ('code', w.DWORD)]


class Event(c.Structure):
    _fields_ = [('kind', w.DWORD), ('pid', w.DWORD), ('tid', w.DWORD), ('data', Payload)]


def observe(exe, output):
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD,
                                     c.c_void_p, w.LPCWSTR, c.POINTER(Startup), c.POINTER(Process)]
    kernel.WaitForDebugEvent.argtypes = [c.POINTER(Event), w.DWORD]
    kernel.ContinueDebugEvent.argtypes = [w.DWORD, w.DWORD, w.DWORD]
    kernel.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    startup = Startup(); startup.cb = c.sizeof(startup); startup.flags = 0x100
    startup.stdin = msvcrt.get_osfhandle(sys.stdin.fileno())
    startup.stdout = msvcrt.get_osfhandle(sys.stdout.fileno())
    startup.stderr = msvcrt.get_osfhandle(sys.stderr.fileno())
    process = Process()
    arguments = [str(exe), '-t05-unknown-中文']
    command = c.create_unicode_buffer(subprocess.list2cmdline(arguments))
    if not kernel.CreateProcessW(str(exe), command, None, None, True, 2, None, str(Path.cwd()),
                                 c.byref(startup), c.byref(process)):
        raise c.WinError(c.get_last_error())
    modules, exited = {}, False
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            event = Event()
            if not kernel.WaitForDebugEvent(c.byref(event), 500):
                if c.get_last_error() == 121:  # ERROR_SEM_TIMEOUT
                    continue
                raise c.WinError(c.get_last_error())
            disposition = 0x10002
            if event.kind in (3, 6):  # CREATE_PROCESS / LOAD_DLL: first field is hFile.
                handle = event.data.handle
                if handle:
                    try:
                        buffer = c.create_unicode_buffer(32768)
                        size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
                        if not size or size >= len(buffer):
                            raise c.WinError(c.get_last_error())
                        path = Path(buffer.value.removeprefix('\\\\?\\'))
                        modules[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                    finally:
                        kernel.CloseHandle(handle)
            elif event.kind == 1:  # Only consume the loader's initial breakpoint.
                if event.data.code != 0x80000003:
                    disposition = 0x80010001
            elif event.kind == 5:
                exited = True
                code = event.data.code
            if not kernel.ContinueDebugEvent(event.pid, event.tid, disposition):
                raise c.WinError(c.get_last_error())
            if exited:
                break
        if not exited:
            raise RuntimeError('owned CLI smoke timed out')
        if code != 0xffffffff:
            raise RuntimeError('unexpected CLI exit: ' + str(code))
        output.write_text(json.dumps(dict(pid=process.pid, exitCode=code, modules=modules,
                                         arguments=arguments, workingDirectory=str(Path.cwd()),
                                         serviceInitialization=False), indent=2), encoding='utf-8')
    finally:
        if not exited:
            kernel.TerminateProcess(process.process, 124)
        kernel.CloseHandle(process.thread); kernel.CloseHandle(process.process)


if __name__ == '__main__':
    observe(Path(sys.argv[1]).resolve(), Path(sys.argv[2]))

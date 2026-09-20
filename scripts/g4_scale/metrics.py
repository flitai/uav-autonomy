"""Bounded native Windows process sampling; no extra Python dependencies."""
import ctypes
from ctypes import wintypes as W
import json
import os
import platform
import time


class Memory(ctypes.Structure):
    _fields_=[('cb',W.DWORD),('PageFaultCount',W.DWORD)]+[(key,ctypes.c_size_t) for key in
        ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
         'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]


class ProcessEntry(ctypes.Structure):
    _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
              ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),
              ('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]


def process_parents():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=(W.DWORD,W.DWORD);kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
    kernel.Process32FirstW.argtypes=(W.HANDLE,ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.argtypes=(W.HANDLE,ctypes.POINTER(ProcessEntry))
    kernel.CloseHandle.argtypes=(W.HANDLE,)
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError()
    try:
        entry=ProcessEntry();entry.dwSize=ctypes.sizeof(entry);parents={}
        available=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while available:
            parents[int(entry.th32ProcessID)]=int(entry.th32ParentProcessID)
            available=kernel.Process32NextW(snapshot,ctypes.byref(entry))
        return parents
    finally:kernel.CloseHandle(snapshot)


def descendants(pid,parents):
    found={int(pid)}
    while True:
        updated=found|{child for child,parent in parents.items() if parent in found}
        if updated==found:return found
        if len(updated)>64:raise RuntimeError('Owned process tree exceeds sampling bound')
        found=updated


def process_group(pid,parents,exclude=()):
    members=[process(member) for member in sorted(descendants(pid,parents)-set(exclude))]
    return {'pid':str(pid),'members':members,
            'private_bytes':str(sum(int(m['private_bytes']) for m in members)),
            'working_set_bytes':str(sum(int(m['working_set_bytes']) for m in members)),
            'cpu_seconds':sum(m['cpu_seconds'] for m in members)}


def process(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True); psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.OpenProcess.argtypes=(W.DWORD,W.BOOL,W.DWORD); kernel.OpenProcess.restype=W.HANDLE
    kernel.CloseHandle.argtypes=(W.HANDLE,)
    kernel.GetProcessTimes.argtypes=(W.HANDLE,*([ctypes.POINTER(W.FILETIME)]*4))
    psapi.GetProcessMemoryInfo.argtypes=(W.HANDLE,ctypes.POINTER(Memory),W.DWORD)
    handle=kernel.OpenProcess(0x410,False,int(pid))
    if not handle:raise RuntimeError('Cannot sample owned process: '+str(pid))
    try:
        mem=Memory();mem.cb=ctypes.sizeof(mem)
        times=[W.FILETIME() for _ in range(4)]
        if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(mem),mem.cb):raise ctypes.WinError()
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):raise ctypes.WinError()
        ticks=lambda t:(t.dwHighDateTime<<32)|t.dwLowDateTime
        return {'pid':str(pid),'private_bytes':str(mem.PrivateUsage),'working_set_bytes':str(mem.WorkingSetSize),
                'cpu_seconds':sum(ticks(t) for t in times[2:])/10_000_000}
    finally:kernel.CloseHandle(handle)


class Sampler:
    def __init__(self,path):
        self.path=path; self.previous={}; self.count=0; self.next=0
    def sample(self,processes,health,simulation_ms,force=False):
        now=time.monotonic()
        if not force and now<self.next:return
        self.next=now+5; values={};parents=process_parents()
        children=set().union(*(descendants(pid,parents) for label,pid in processes.items() if label!='controller'))
        for label,pid in processes.items():
            value=process_group(pid,parents,children if label=='controller' else ()); previous=self.previous.get(label)
            if previous and previous[0]==pid:
                value['cpu_percent_one_core']=100*(value['cpu_seconds']-previous[2])/(now-previous[1])
            self.previous[label]=(pid,now,value['cpu_seconds']);values[label]=value
        if 'gateway' in values and int(values['gateway']['private_bytes'])>1024**3:
            raise RuntimeError('Gateway exceeded the declared 1 GiB private memory bound')
        row={'monotonic_seconds':now,'simulation_ms':str(simulation_ms),'processes':values,'health':health}
        with self.path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        self.count+=1


def machine():return {'platform':platform.platform(),'logical_processors':os.cpu_count(),
                      'cpu':platform.processor(),'python':platform.python_version(),
                      'cpu_percent_basis':'100 percent equals one logical core; each owned process tree is included',
                      'sampling_seconds':5,'gateway_private_bytes_limit':str(1024**3)}

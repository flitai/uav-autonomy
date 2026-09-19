"""Request normal close from the live G3 controller; never kills a process."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if sys.version_info[:3] != (3, 14, 7) or struct.calcsize('P') != 8 or not sys.flags.isolated:
        raise RuntimeError('Expected isolated Python 3.14.7 x64')
    if not re.fullmatch(r'g3-t03-[A-Za-z0-9-]{1,80}', args.run_id):
        raise RuntimeError('Invalid run identity')
    run = args.root.resolve() / 'out/runs' / args.run_id
    ready = json.loads((run / 'gui-ready.json').read_text(encoding='utf-8'))
    result = json.loads((run / 'result.json').read_text(encoding='utf-8'))
    if ready['runId'] != args.run_id or ready['phase'] != 'awaiting-close' or result['status'] != 'running':
        raise RuntimeError('GUI run is not awaiting close')
    pid = ready['controllerPid']
    if type(pid) is not int or pid <= 0: raise RuntimeError('Invalid controller PID')
    command = 'Get-CimInstance Win32_Process -Filter "ProcessId = ' + str(pid) + '" | Select-Object CommandLine | ConvertTo-Json -Compress'
    info = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, timeout=10,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    process = json.loads(info.stdout or b'null')
    if info.returncode or not process or args.run_id not in process['CommandLine'] or 'g3_integration' not in process['CommandLine']:
        raise RuntimeError('Controller identity no longer matches')
    with (run / 'request-gui-close.json').open('x', encoding='utf-8') as output:
        json.dump(dict(runId=args.run_id, controllerPid=pid, requestedAtEpochSeconds=time.time(),
                       purpose='normal-close', manualGuiAcceptance=False), output)
    end = time.monotonic() + 45
    while time.monotonic() < end:
        try:
            result = json.loads((run / 'result.json').read_text(encoding='utf-8'))
            entry = json.loads((run / 'entry-result.json').read_text(encoding='utf-8-sig'))
            if result['status'] != 'running' and entry['status'] != 'running':
                if result['status'] != 'passed' or entry['status'] != 'passed': raise RuntimeError('GUI closed with failed acceptance')
                print('G3 GUI closed normally: ' + args.run_id)
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise RuntimeError('Timeout waiting for normal close receipt')


if __name__ == '__main__':
    main()

"""Bind an explicit current user confirmation, then request normal controller shutdown."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--confirmation-text', required=True)
    args = parser.parse_args()
    require = lambda value, message: None if value else fail(message)
    require(sys.version_info[:3] == (3,14,7) and struct.calcsize('P') == 8 and sys.flags.isolated,
            'Expected isolated Python 3.14.7 x64')
    require(re.fullmatch(r'g3-t07-[A-Za-z0-9-]{1,80}', args.run_id), 'Invalid stage run identity')
    require(args.confirmation_text.strip(), 'Current user confirmation text required')
    root = args.root.resolve(); run = root / 'out/runs' / args.run_id
    spec = importlib.util.spec_from_file_location('finish_amase', root / 'scripts/amase/amase.py')
    amase = importlib.util.module_from_spec(spec); spec.loader.exec_module(amase)
    spec = importlib.util.spec_from_file_location('finish_receipts', Path(__file__).with_name('receipts.py'))
    receipts = importlib.util.module_from_spec(spec); spec.loader.exec_module(receipts)
    ready, result = amase.load(run / 'gui-ready.json'), amase.load(run / 'result.json')
    require(ready['runId'] == args.run_id and ready['phase'] == 'awaiting-confirmation' and
            result['status'] == 'awaiting-gui' and result['task'] == 'G3-T07', 'Stage is not awaiting current GUI confirmation')
    review = run / 'gui/review/review.json'
    require(amase.sha(review) == ready['reviewSHA256'], 'Review changed before confirmation')
    amase.verify_records(review.parent, amase.load(review)['files'])
    pid = ready['controllerPid']
    require(type(pid) is int and pid > 0, 'Invalid controller PID')
    command = 'Get-CimInstance Win32_Process -Filter "ProcessId = ' + str(pid) + '" | Select-Object CommandLine | ConvertTo-Json -Compress'
    info = subprocess.run(['powershell.exe','-NoProfile','-Command',command], capture_output=True, timeout=10,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    process = json.loads(info.stdout or b'null')
    require(info.returncode == 0 and process and args.run_id in process['CommandLine'] and
            'g3_acceptance' in process['CommandLine'], 'Live controller identity no longer matches')
    confirmation = dict(runId=args.run_id, nonce=ready['nonce'], controllerPid=pid,
        javaPid=ready['javaPid'], uxasPid=ready['uxasPid'], readySHA256=amase.sha(run/'gui-ready.json'),
        reviewSHA256=amase.sha(review), manualGuiAcceptance=True, confirmationSource='user',
        confirmationText=args.confirmation_text, requestedAtEpochSeconds=time.time(), requestedAt=amase.stamp())
    receipts.validate_confirmation(ready, confirmation, amase.sha(run/'gui-ready.json'), amase.sha(review))
    with (run / 'request-gui-acceptance.json').open('x', encoding='utf-8') as output:
        json.dump(confirmation, output, ensure_ascii=False, indent=2)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            result, entry = amase.load(run/'result.json'), amase.load(run/'entry-result.json')
            if result['status'] == entry['status'] == 'passed':
                require(result['stageAccepted'] and result['manualGuiAcceptance'] == confirmation, 'Stage acceptance differs')
                print('G3 stage confirmed and normally closed: '+args.run_id)
                return 0
            if result['status'] == 'failed' or entry['status'] == 'failed': fail('Stage close failed; preserve raw receipts')
        except (FileNotFoundError, json.JSONDecodeError): pass
        time.sleep(0.2)
    fail('Timed out waiting for stage close; this command never forcibly terminates a process')


def fail(message): raise RuntimeError(message)


if __name__ == '__main__': sys.exit(main())

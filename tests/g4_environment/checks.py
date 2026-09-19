"""Exercise public G4 environment entry refusal and Chinese working-directory behavior."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline-run-id', required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    run_id = 'g4-t01-checks-' + time.strftime('%Y%m%d-%H%M%S')
    run = root / 'out/runs' / run_id
    run.mkdir()
    cwd = run / '中文 working directory'; cwd.mkdir()
    entry = root / 'scripts/windows/setup-g4.ps1'
    def call(identity, python):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(entry),
            '-PythonExecutable', str(python), '-BaselineRunId', args.baseline_run_id, '-RunId', identity, '-VerifyOnly'],
            cwd=cwd, capture_output=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        (run / (identity + '.stdout')).write_bytes(result.stdout)
        (run / (identity + '.stderr')).write_bytes(result.stderr)
        return result.returncode
    verified = run_id + '-verify'
    assert call(verified, sys.executable) == 0, 'Verify from Chinese working directory failed'
    result_path = root / 'out/runs' / verified / 'result.json'
    original = hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert call(verified, sys.executable) != 0, 'Existing run accepted'
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == original, 'Historical result overwritten'
    missing = run_id + '-missing'
    assert call(missing, run / 'missing-python.exe') != 0, 'Missing Python accepted'
    assert json.loads((root / 'out/runs' / missing / 'entry-result.json').read_text(encoding='utf-8'))['status'] == 'failed'
    accepted = {'task': 'G4-T01', 'runId': run_id, 'status': 'passed', 'cases': ['verified-environment',
        'different-chinese-working-directory', 'existing-run-refused-and-preserved', 'missing-interpreter-refused'],
        'verifyRunId': verified, 'missingRunId': missing}
    (run / 'acceptance.json').write_text(json.dumps(accepted, indent=2) + '\n', encoding='utf-8')
    print('G4_T01_CHECKS=' + run_id)


if __name__ == '__main__':
    main()

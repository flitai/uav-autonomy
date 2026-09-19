"""G4-T01 isolated, hash-locked Windows environment and current input qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def verify_files(root, rows):
    root = Path(root).resolve()
    for item in rows:
        path = (root / item['path']).resolve()
        require(path.is_relative_to(root), 'Source path escapes its root')
        require(path.is_file() and sha(path) == item['sha256'].lower(), 'Source differs: ' + item['path'])


def verify_handoff(root, baseline_id, policy=None):
    policy = policy or load(root / 'config/g4-baseline.json')
    require(re.fullmatch(r'g3-t01-check-[0-9-]+', baseline_id), 'Invalid baseline run identity')
    directory = root / 'out/runs' / baseline_id
    result, entry = load(directory / 'result.json'), load(directory / 'entry-result.json')
    require(result['status'] == entry['status'] == 'passed', 'Current G3 qualification failed')
    require(sha(directory / 'baseline.json') == result['baselineSHA256'].lower(), 'Baseline receipt differs')
    baseline = load(directory / 'baseline.json')
    verify_files(root, baseline['frozenInputs'])
    stage = root / 'out/runs' / policy['g3StageRunId']
    require(stage.resolve().parent == (root / 'out/runs').resolve(), 'Invalid stage run identity')
    require(sha(stage / 'handoff.json') == policy['g3HandoffSHA256'], 'G3 handoff differs')
    handoff = load(stage / 'handoff.json')
    for name in ('result.json', 'entry-result.json', 'acceptance.json', 'handoff.json'):
        require(load(stage / name)['status'] == 'passed', 'G3 stage is not accepted: ' + name)
    verify_files(root, handoff['configurations'])
    pointer = load(root / 'out/artifacts/uxas/current.json')
    require(pointer == handoff['formalUxas'], 'Current UxAS differs from stage handoff')
    uxas = root / 'out/artifacts/uxas' / pointer['path']
    require(uxas.resolve().is_relative_to((root / 'out/artifacts/uxas').resolve()), 'Invalid UxAS package path')
    artifacts = {'uxasSHA256': uxas / 'uxas.exe', 'amaseSHA256': root / 'out/artifacts/amase/OpenAMASE.jar',
                 'lmcpSHA256': root / 'out/artifacts/lmcp/java/lmcplib.jar'}
    for key, path in artifacts.items():
        require(sha(path) == handoff['artifacts'][key].lower(), 'Current formal artifact differs: ' + key)
    generation = load(root / 'out/generated/lmcp/generation-info.json')
    require(generation['runId'] == handoff['lmcpGenerationRunId'], 'Mixed LMCP generations')
    return {'baselineRunId': baseline_id, 'baselineSHA256': sha(directory / 'baseline.json'),
            'g3StageRunId': policy['g3StageRunId'], 'g3HandoffSHA256': sha(stage / 'handoff.json'),
            'artifacts': {key: sha(path) for key, path in artifacts.items()}}


def environment(root):
    pointer = load(root / '.tools/g4/current.json')
    folder = (root / pointer['path']).resolve()
    require(folder.is_relative_to((root / '.tools/g4/environments').resolve()), 'Environment escapes project tools')
    require(sha(root / 'config/g4-python-lock.json') == pointer['lockSHA256'], 'Dependency lock differs')
    require(sha(folder / 'environment.json') == pointer['manifestSHA256'], 'Environment manifest differs')
    manifest = load(folder / 'environment.json')
    verify_files(folder, manifest['files'])
    return folder / 'Scripts/python.exe', manifest


def invoke(arguments, directory, label, timeout=180):
    result = subprocess.run(list(map(str, arguments)), cwd=directory, capture_output=True, timeout=timeout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (directory / (label + '.stdout')).write_bytes(result.stdout)
    (directory / (label + '.stderr')).write_bytes(result.stderr)
    require(result.returncode == 0, label + ' failed; see ' + str(directory / (label + '.stderr')))
    return result


def install(root, run, lock):
    cache = root / '.tools/cache/g4'; cache.mkdir(parents=True, exist_ok=True)
    for package in lock['packages']:
        require(urlparse(package['url']).scheme == 'https' and urlparse(package['url']).hostname == 'files.pythonhosted.org',
                'Untrusted wheel URL')
        target = cache / package['filename']
        require(target.parent == cache and target.suffix == '.whl', 'Invalid wheel filename')
        if not target.exists():
            temporary = target.with_suffix('.download')
            with urlopen(package['url'], timeout=60) as response, temporary.open('wb') as output:
                while data := response.read(1024 * 1024):
                    output.write(data)
            require(sha(temporary) == package['sha256'], 'Wheel hash differs: ' + package['name'])
            temporary.replace(target)
        require(sha(target) == package['sha256'], 'Cached wheel hash differs: ' + package['name'])
    folder = root / '.tools/g4/environments' / run.name
    require(not folder.exists(), 'Candidate environment already exists')
    invoke([sys.executable, '-I', '-m', 'venv', folder], run, 'venv')
    python = folder / 'Scripts/python.exe'
    invoke([python, '-I', '-m', 'pip', 'install', '--no-index', '--no-deps', '--require-hashes', '--find-links', cache,
            '-r', root / 'config/g4-requirements.txt'], run, 'install', timeout=300)
    invoke([python, '-I', '-m', 'pip', 'check'], run, 'pip-check')
    return python


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--baseline-run-id', required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    require(re.fullmatch(r'g4-t01-[A-Za-z0-9-]+', args.run_id), 'Invalid G4 run identity')
    run = root / 'out/runs' / args.run_id
    require(run.is_dir() and not (run / 'result.json').exists(), 'New entry-owned run directory required')
    record = {'task': 'G4-T01', 'runId': args.run_id, 'status': 'running', 'startedAt': time.time(), 'simulationStarted': False}
    try:
        require(sys.flags.isolated and sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8,
                'Explicit isolated Python 3.14.7 x64 required')
        record['provenance'] = verify_handoff(root, args.baseline_run_id)
        paths = [root / p for p in ('config/g4-python-lock.json', 'config/g4-requirements.txt', 'config/g4-baseline.json',
                 'config/g4-gateway.json', 'scripts/g4_environment/manage.py', 'tests/g4_environment/smoke.py',
                 'scripts/windows/setup-g4.ps1', 'tests/g4_environment/checks.py',
                 'tests/windows/g4-environment.tests.ps1', 'docs/g4-browser-contract.md')]
        record['inputs'] = [{'path': p.relative_to(root).as_posix(), 'sha256': sha(p)} for p in paths]
        lock = load(root / 'config/g4-python-lock.json')
        require(lock['python'] == '3.14.7' and lock['platform'] == 'win_amd64', 'Unexpected dependency platform')
        python = environment(root)[0] if args.verify_only else install(root, run, lock)
        invoke([python, '-I', '-B', '-X', 'utf8', root / 'tests/g4_environment/smoke.py', '--root', root,
                '--output', run / 'smoke.json'], run, 'smoke')
        smoke = load(run / 'smoke.json')
        require(smoke['status'] == 'passed', 'Environment smoke failed')
        record['smoke'] = smoke
        # Isolated source rejection checks do not mutate a formal package or receipt.
        bad = dict(load(root / 'config/g4-baseline.json'), g3HandoffSHA256='0' * 64)
        try:
            verify_handoff(root, args.baseline_run_id, bad)
        except RuntimeError as error:
            require(str(error) == 'G3 handoff differs', 'Wrong source rejection')
        else:
            raise RuntimeError('Changed source was accepted')
        try:
            verify_files(root, [{'path': 'config/g4-python-lock.json', 'sha256': '0' * 64}])
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Changed dependency lock was accepted')
        verify_files(root, record['inputs'])
        folder = python.parent.parent
        if not args.verify_only:
            manifest = {'schemaVersion': 1, 'runId': args.run_id, 'lockSHA256': sha(root / 'config/g4-python-lock.json'),
                        'versions': smoke['versions'], 'files': smoke['files']}
            save(folder / 'environment.json', manifest)
            pointer = {'schemaVersion': 1, 'runId': args.run_id, 'path': folder.relative_to(root).as_posix(),
                       'lockSHA256': manifest['lockSHA256'], 'manifestSHA256': sha(folder / 'environment.json')}
            save(root / '.tools/g4/current.json', pointer)
        environment(root)
        record.update(status='passed', verifyOnly=args.verify_only, environment=folder.relative_to(root).as_posix(),
                      checks=['current-source', 'hash-locked-dependencies', 'imports', 'http', 'websocket',
                              'normal-exit-and-port-release', 'source-rejection', 'dependency-hash-rejection'])
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True)
        return 1
    finally:
        record['finishedAt'] = time.time()
        save(run / 'result.json', record)
        print('G4_T01_EVIDENCE=' + str(run), flush=True)


if __name__ == '__main__':
    sys.exit(main())

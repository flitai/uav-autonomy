"""Repeat/path/fault integration checks; all fixtures remain under the project's out/."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def artifact_hashes(root):
    return {p.relative_to(root).as_posix(): sha(p) for directory in ('out/generated/lmcp','out/artifacts/lmcp')
            for p in sorted((root / directory).rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--powershell', required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    run_id = 'g1-t03-validation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    run = root / 'out/runs' / run_id
    temporary = root / 'out/tmp' / run_id
    run.mkdir(parents=True)
    temporary.mkdir(parents=True)
    results = []
    prior = load(root / 'out/artifacts/lmcp/build-info.json')
    head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip()

    def case(name, action):
        try:
            action()
            results.append(dict(name=name, status='passed'))
            print('PASS:', name, flush=True)
        except Exception as error:
            results.append(dict(name=name, status='failed', error=str(error)))
            raise

    def invoke(project, label, expected=None, probe=False, probe_failure=False):
        script = temporary / 'environment-probe.ps1' if probe else project / 'scripts/windows/generate-lmcp.ps1'
        command = [args.powershell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-PythonExecutable',sys.executable]
        if probe:
            command.extend(['-ProjectRoot',str(project)])
            if probe_failure:
                command.append('-ExpectFailure')
        result = subprocess.run(command, cwd=temporary, capture_output=True, encoding='utf-8', timeout=240)
        (run / (label + '.stdout.log')).write_text(result.stdout, encoding='utf-8')
        (run / (label + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
        build_runs = sorted(p for p in (project / 'out/runs').glob('g1-t03-*') if p.name[len('g1-t03-'):].startswith('20'))
        record = load(build_runs[-1] / 'result.json')
        save(run / (label + '.json'), dict(command=command, cwd=str(temporary), exitCode=result.returncode, result=record))
        if expected:
            require(result.returncode == (0 if probe_failure else 1) and record['status'] == 'failed' and expected in record['error'],
                    'Expected failure not observed: ' + label)
        else:
            require(result.returncode == 0 and record['status'] == 'passed', 'Unexpected failure: ' + label)
        if probe:
            require('PROCESS_RESTORATION_OK' in result.stdout, 'Missing process restoration evidence')
        return record

    probe_source = r'''
param([string]$ProjectRoot,[string]$PythonExecutable,[switch]$ExpectFailure)
$ErrorActionPreference = 'Stop'
$names = @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH','ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')
foreach ($name in @('ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')) {
    [Environment]::SetEnvironmentVariable($name,'deliberately-invalid-test-value','Process')
}
$before = @{}
foreach ($name in $names) { $before[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
$cwd = (Get-Location).Path
$encoding = [Console]::OutputEncoding.CodePage
$failed = $false
try { & (Join-Path $ProjectRoot 'scripts/windows/generate-lmcp.ps1') -PythonExecutable $PythonExecutable }
catch { $failed = $true; if (-not $ExpectFailure) { throw } }
if ($ExpectFailure -and -not $failed) { throw 'Expected failure was absent.' }
foreach ($name in $names) {
    if ([Environment]::GetEnvironmentVariable($name,'Process') -cne $before[$name]) { throw "Environment not restored: $name" }
}
if ((Get-Location).Path -ne $cwd -or [Console]::OutputEncoding.CodePage -ne $encoding) { throw 'Location or encoding not restored.' }
Write-Host 'PROCESS_RESTORATION_OK'
'''
    (temporary / 'environment-probe.ps1').write_text(probe_source, encoding='ascii')
    fixture = temporary / 'project \u4e2d\u6587 space'

    def unchanged(expected):
        require(artifact_hashes(fixture) == expected, 'Failure changed previous generated code/artifacts')

    try:
        def repeat():
            current = invoke(root, 'repeat-and-environment', probe=True)
            require(current['runId'] != prior['runId'], 'Run reused prior output')
            generated = load(root / 'out/generated/lmcp/generation-info.json')
            require(generated['runId'] == current['runId'], 'Published run IDs differ')
        case('Repeat from another working directory and restore process environment', repeat)
        formal_info = load(root / 'out/artifacts/lmcp/build-info.json')
        formal_hashes = artifact_hashes(root)

        def relocated():
            # Copies only relevant source/tools; no downloaded archives, repository metadata or old test fixtures.
            for relative in ('LmcpGen','scripts','tests/lmcp','config','OpenUxAS/mdms','OpenAMASE/OpenAMASE/src',
                             'out/artifacts/lmcpgen'):
                target = fixture / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(root / relative, target, ignore=shutil.ignore_patterns('__pycache__','.git','build','dist'))
            old = fixture / 'OpenAMASE/OpenAMASE/lib/lmcplib.jar'
            old.parent.mkdir(parents=True)
            shutil.copyfile(root / 'OpenAMASE/OpenAMASE/lib/lmcplib.jar', old)
            (fixture / '.tools').mkdir()
            for tool in load(root / 'config/windows-java-toolchain.json')['tools']:
                shutil.copytree(root / '.tools' / tool['installDirectory'], fixture / '.tools' / tool['installDirectory'])
            current = invoke(fixture, 'unicode-path')
            require(current['validation']['instantiatedStructs'] == 164, 'Relocated message verification incomplete')
        case('Full generation/compilation/roundtrip in Chinese and spaced path', relocated)
        good = artifact_hashes(fixture)

        def missing_model():
            source = (fixture / 'OpenUxAS/mdms/IMPACT.xml').resolve()
            saved = source.with_suffix('.saved')
            require(source.is_relative_to(temporary) and saved.is_relative_to(temporary), 'Fixture path escaped')
            source.rename(saved)
            try:
                invoke(fixture, 'missing-model', expected='MDM file set mismatch')
                invoke(fixture, 'failure-environment', expected='MDM file set mismatch', probe=True, probe_failure=True)
                unchanged(good)
            finally:
                saved.rename(source)
        case('Missing model rejected; failure environment and previous batch preserved', missing_model)

        def generator_hash():
            path = fixture / 'out/artifacts/lmcpgen/LmcpGen.jar'
            original = path.read_bytes()
            try:
                path.write_bytes(original + b'fault')
                invoke(fixture, 'generator-hash', expected='Generator hash or T02 status mismatch')
                unchanged(good)
            finally:
                path.write_bytes(original)
        case('Generator hash mismatch rejected before generation', generator_hash)

        def malformed_model():
            path = fixture / 'OpenUxAS/mdms/IMPACT.xml'
            config_path = fixture / 'config/lmcp-models.json'
            original, config_bytes = path.read_bytes(), config_path.read_bytes()
            try:
                path.write_text('<MDM>', encoding='utf-8')
                config = load(config_path)
                next(m for m in config['models'] if m['file'] == 'IMPACT.xml')['sha256'] = sha(path)
                save(config_path, config)
                invoke(fixture, 'malformed-model', expected='no element found')
                unchanged(good)
            finally:
                path.write_bytes(original); config_path.write_bytes(config_bytes)
        case('Malformed model rejected even with matching fixture checksum', malformed_model)

        def bad_sample():
            path = fixture / 'tests/lmcp/python_probe.py'
            original = path.read_bytes()
            try:
                fault = "    args = parser.parse_args()\n    damaged = args.java_new / 'basic-checksum.bin'\n    data = bytearray(damaged.read_bytes())\n    data[30] ^= 1\n    damaged.write_bytes(data)\n"
                text = original.decode('utf-8')
                require(text.count('    args = parser.parse_args()\n') == 1, 'Sample fault hook changed')
                path.write_text(text.replace('    args = parser.parse_args()\n', fault), encoding='utf-8')
                record = invoke(fixture, 'bad-sample', expected='python-probe failed')
                error = next(c for c in record['commands'] if c['label'] == 'python-probe')['stderr']
                require('Invalid LMCP checksum' in error, 'Did not reproduce sample checksum failure')
                unchanged(good)
            finally:
                path.write_bytes(original)
        case('Corrupt sample fails validation and prevents publication', bad_sample)

        def interrupted_publish():
            path = fixture / 'scripts/lmcp/generate.py'
            original = path.read_bytes()
            try:
                text = original.decode('utf-8')
                target = '                source.rename(destination)\n'
                require(text.count(target) == 1, 'Publication fault hook changed')
                replacement = "                if destination.parent.name == 'artifacts':\n                    raise OSError('Injected publication failure')\n" + target
                path.write_text(text.replace(target,replacement), encoding='utf-8')
                record = invoke(fixture, 'publication-rollback', expected='Injected publication failure')
                require(record['step'] == 'publish', 'Failure occurred before publication')
                unchanged(good)
            finally:
                path.write_bytes(original)
        case('Interrupted two-directory publication restores the entire previous batch', interrupted_publish)

        def boundaries():
            require(artifact_hashes(root) == formal_hashes, 'Fixtures affected formal output')
            for item in formal_info['inputs']:
                require(sha(root / item['path']) == item['sha256'], 'Formal input changed')
            for directory in ('LmcpGen/build','LmcpGen/dist','OpenAMASE/OpenAMASE/build','OpenAMASE/OpenAMASE/dist'):
                require(not (root / directory).exists(), 'Unexpected upstream output')
            for language in ('java','cpp','py'):
                require(not (root / 'out/generated/lmcp' / language / 'build').exists(), 'Build leaked into generated sources')
            require(not list((root / 'out/generated/lmcp').rglob('__pycache__')), 'Unexpected bytecode cache')
            require(subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip() == head, 'HEAD changed')
            require(not subprocess.check_output(['git','-C',str(root),'status','--porcelain','--','LmcpGen','OpenAMASE','OpenUxAS']), 'Upstream source changed')
        case('Formal inputs/output boundaries and upstream source unchanged', boundaries)
        return 0
    except Exception:
        (run / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
        return 1
    finally:
        save(run / 'results.json', results)
        print('Integration records:', run, flush=True)


if __name__ == '__main__':
    sys.exit(main())

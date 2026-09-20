"""Shared G5 tool/source verification. Does not start a simulation."""
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys


def need(value, message):
    if not value: raise RuntimeError(message)


def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.new')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


def inventory(root, paths):
    return [{'path': p.relative_to(root).as_posix(), 'sha256': sha(p)} for p in sorted(paths)]


def verify_files(root, records):
    for item in records:
        path = (root / item['path']).resolve()
        need(path.is_relative_to(root.resolve()) and path.is_file() and sha(path) == item['sha256'],
             'Source differs or is missing: ' + item['path'])


def source_paths(root):
    paths = list((root/'config').glob('g5-*'))
    for directory in ('scripts/g5_environment', 'tests/g5_environment', 'apps/cesium_viewer'):
        paths += [p for p in (root/directory).rglob('*') if p.is_file() and
                  not {'node_modules', 'dist', '__pycache__'}.intersection(p.relative_to(root/directory).parts)]
    paths += list((root/'scripts/windows').glob('*g5*.ps1'))
    paths += list((root/'tests/windows').glob('g5-*.ps1'))
    return sorted(set(paths))


def process_env(node=None):
    env = dict(os.environ)
    for key in list(env):
        if key.upper().startswith(('PYTHON', 'NPM_CONFIG_', 'NODE_')) or key.upper() in (
            'PROJ_LIB', 'PROJ_DATA', 'GDAL_DATA', 'GDAL_DRIVER_PATH', 'VIRTUAL_ENV'):
            env.pop(key)
    env.update(PYTHONDONTWRITEBYTECODE='1', PROJ_NETWORK='OFF', PIP_CONFIG_FILE=os.devnull,
               PIP_DISABLE_PIP_VERSION_CHECK='1')
    if node: env['PATH'] = str(node) + os.pathsep + env.get('PATH', '')
    return env


def invoke(args, run, label, cwd=None, env=None, timeout=600, expected=0):
    result = subprocess.run(list(map(str, args)), cwd=cwd or run, env=env or process_env(),
                            capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    (run/(label+'.stdout')).write_bytes(result.stdout); (run/(label+'.stderr')).write_bytes(result.stderr)
    save(run/(label+'.command.json'), dict(arguments=list(map(str, args)), cwd=str(cwd or run), exitCode=result.returncode))
    need(result.returncode == expected, label + ' failed; see ' + str(run/(label+'.stderr')))
    return result


def exclusive_port(port):
    probe = socket.socket()
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', port)); return probe
    except BaseException:
        probe.close(); raise


def upstream(root, baseline_id):
    g4 = module('g5_g4_environment', root/'scripts/g4_environment/manage.py')
    provenance = g4.verify_handoff(root, baseline_id)
    entry = module('g5_g4_entry', root/'scripts/g4_stage/entry.py')
    bundle, pointer, python = entry.resolve(root)
    binding = load(root/'out/artifacts/gis-gateway/session.json')
    receipt = (root/binding['path']).resolve()
    need(receipt.is_relative_to(root/'out/runs') and sha(receipt) == binding['sha256'], 'G4 session receipt differs')
    qualification = load(receipt)
    need(qualification['status'] == 'passed' and qualification['pointer'] == pointer, 'G4 session is not qualified')
    verify_files(root, qualification['sources'])
    return dict(backend=provenance, gateway=pointer, session=binding,
                gatewayEnvironment=load(root/'.tools/g4/current.json'),
                generationSHA256=sha(root/'out/generated/lmcp/generation-info.json'))


def raw_inputs(root):
    config = load(root/'config/g5-resources.json')
    records = []
    # Only bounded registration reads. Global archive hashes and tile completeness belong to T02.
    for relative, length in [(config['vector']['path'], 127), (config['archive']['path'], 4),
                             (config['dem']['path']+'/0/0/0.png', 33),
                             (config['dem']['path']+'/10/512/512.png', 33),
                             (config['auxiliaryVector']['path'], 127)]:
        path = root/relative; stat = path.stat()
        with path.open('rb') as stream: header = stream.read(length)
        if relative.endswith('.pmtiles'): need(header[:8] == b'PMTiles\x03', 'PMTiles header differs')
        if relative.endswith('.png'): need(header[:8] == b'\x89PNG\r\n\x1a\n', 'DEM PNG header differs')
        records.append(dict(path=relative, bytes=stat.st_size, modifiedNs=str(stat.st_mtime_ns),
                            prefixBytes=length, prefixSHA256=hashlib.sha256(header).hexdigest()))
    need(records[0]['bytes'] == config['vector']['observedBytes'] and
         records[1]['bytes'] == config['archive']['observedBytes'] and
         records[4]['bytes'] == config['auxiliaryVector']['observedBytes'], 'Registered raw input size differs')
    return dict(qualification='registered-only', fullContentHashed=False, terrainQualified=False, files=records)


def environment(root):
    pointer = load(root/'.tools/g5/current.json')
    folder = (root/pointer['path']).resolve()
    need(folder.is_relative_to(root/'.tools/g5/environments'), 'G5 environment escapes tool root')
    need(sha(folder/'environment.json') == pointer['manifestSHA256'], 'Environment manifest differs')
    manifest = load(folder/'environment.json')
    receipt = root/'out/runs'/pointer['runId']
    need(load(receipt/'result.json')['status'] == load(receipt/'entry-result.json')['status'] == 'passed',
         'G5 environment setup did not pass')
    for row in manifest.get('basePython', []):
        need(sha(Path(row['path'])) == row['sha256'], 'Base Python runtime differs')
    verify_files(root, manifest['locks']); verify_files(folder, manifest['files'])
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    need(actual == {'environment.json'} | {r['path'] for r in manifest['files']}, 'Unexpected environment files')
    return folder, manifest


def npm_arguments(folder):
    node = folder/'node'
    return [node/'node.exe', node/'node_modules/npm/bin/npm-cli.js']


def npm_env(root, folder, project):
    env = process_env(folder/'node')
    env.update(NPM_CONFIG_CACHE=str(root/'.tools/cache/g5/npm'),
               NPM_CONFIG_USERCONFIG=str(project/'.npmrc'), NPM_CONFIG_GLOBALCONFIG=os.devnull)
    return env


def run_id(prefix): return prefix + datetime.now().strftime('-%Y%m%d-%H%M%S-%f')

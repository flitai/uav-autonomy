"""Repeatable, project-local G5-T01 preparation and candidate build entry."""
import argparse
import concurrent.futures
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import time
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (environment, inventory, invoke, load, need, npm_arguments, npm_env, process_env,
                    raw_inputs, save, sha, source_paths, upstream, verify_files)


def download(item, cache, hostname):
    url = urlparse(item['url'])
    need(url.scheme == 'https' and url.hostname == hostname, 'Untrusted download origin')
    need(Path(item['filename']).name == item['filename'], 'Invalid download filename')
    path = cache/item['filename']
    if not path.exists():
        temp = path.with_suffix(path.suffix+'.download')
        with urlopen(item['url'], timeout=120) as response, temp.open('wb') as target:
            need(urlparse(response.url).hostname == hostname, 'Untrusted download redirect')
            shutil.copyfileobj(response, target)
        need(sha(temp) == item['sha256'], 'Download checksum differs: '+item['filename'])
        temp.replace(path)
    need(sha(path) == item['sha256'], 'Cached download checksum differs: '+item['filename'])
    return path


def prepare(root, run):
    cache = root/'.tools/cache/g5'; cache.mkdir(parents=True, exist_ok=True)
    folder = root/'.tools/g5/environments'/run.name
    need(not folder.exists(), 'Environment identity already exists'); folder.mkdir(parents=True)
    node_lock = load(root/'config/g5-node-lock.json')
    node_archive = download(node_lock, cache, 'nodejs.org')
    with zipfile.ZipFile(node_archive) as archive:
        for member in archive.infolist():
            need((folder/member.filename).resolve().is_relative_to(folder.resolve()), 'Unsafe Node archive path')
        archive.extractall(folder)
    (folder/node_lock['filename'].removesuffix('.zip')).rename(folder/'node')
    version = invoke([folder/'node/node.exe', '--version'], run, 'node-version').stdout.decode().strip()
    need(version == 'v'+node_lock['version'], 'Node version differs')
    npm_version = invoke(npm_arguments(folder)+['--version'], run, 'npm-version', env=process_env(folder/'node')).stdout.decode().strip()
    need(npm_version == node_lock['npm'], 'npm version differs')
    geo_lock = load(root/'config/g5-geo-lock.json')
    need(geo_lock['python'] == '3.14.7' and geo_lock['platform'] == 'win_amd64', 'Unsupported geo platform')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda p: download(p, cache, 'files.pythonhosted.org'), geo_lock['packages']))
    invoke([sys.executable, '-I', '-m', 'venv', folder/'geo'], run, 'geo-venv')
    python = folder/'geo/Scripts/python.exe'
    invoke([python, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile', '--require-hashes',
            '--find-links', cache, '-r', root/'config/g5-geo-requirements.txt'], run, 'geo-install')
    invoke([python, '-I', '-B', '-m', 'pip', 'check'], run, 'geo-pip-check')
    invoke([python, '-I', '-B', '-X', 'utf8', root/'tests/g5_environment/geo_smoke.py', '--output', run/'geo-smoke'], run, 'geo-smoke')
    smoke = load(run/'geo-smoke/result.json')
    need(smoke['status'] == 'passed' and not smoke['projNetworkEnabled'], 'Geospatial capability probe failed')
    installed = {name.lower().replace('_','-'):version for name,version in smoke['versions'].items()}
    expected = {p['name'].lower().replace('_','-'):p['version'] for p in geo_lock['packages']}
    need(installed == expected, 'Unrecorded geospatial dependency')
    base_files = [Path(sys.executable), Path(sys.base_prefix)/'python314.dll']
    manifest = dict(schemaVersion=1, task='G5-T01', runId=run.name, node=version, npm=npm_version, geo=smoke,
        basePython=[dict(path=str(p), sha256=sha(p)) for p in base_files],
        locks=inventory(root, [root/p for p in ('config/g5-node-lock.json','config/g5-geo-lock.json','config/g5-geo-requirements.txt')]),
        files=inventory(folder, [p for p in folder.rglob('*') if p.is_file()]))
    save(folder/'environment.json', manifest)
    return folder, manifest


def validate_npm_lock(project):
    lock = load(project/'package-lock.json'); package = load(project/'package.json')
    need(lock['lockfileVersion'] == 3, 'npm lock format differs')
    for key in ('dependencies', 'devDependencies'):
        need(lock['packages'][''][key] == package[key], 'Frontend dependency lock differs')
    for path, item in lock['packages'].items():
        if not path: continue
        need(item.get('resolved', '').startswith('https://registry.npmjs.org/') and
             item.get('integrity', '').startswith('sha512-'), 'Untrusted npm dependency: '+path)
    return lock


def build(root, run, folder, chinese=False):
    directory = root/'out/build/cesium-viewer'/run.name
    if chinese: directory /= '中文 空格工程'
    project = directory/'project'
    need(not project.exists(), 'Build identity already exists'); project.mkdir(parents=True)
    source = root/'apps/cesium_viewer'
    for path in source_paths(root):
        if path.is_relative_to(source):
            target = project/path.relative_to(source); target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path,target)
    lock = validate_npm_lock(project)
    env = npm_env(root, folder, project)
    invoke(npm_arguments(folder)+['ci','--ignore-scripts','--no-audit','--no-fund'], run, 'npm-ci', cwd=project, env=env)
    invoke(npm_arguments(folder)+['run','build'], run, 'frontend-build', cwd=project, env=env)
    dist = project/'dist'
    for resource in ('Workers', 'ThirdParty', 'Assets', 'Widgets'):
        need(any((dist/'cesium'/resource).rglob('*')), 'Missing packaged Cesium resource: '+resource)
    licenses = dist/'licenses'; licenses.mkdir()
    for name in ('LICENSE.md', 'ThirdParty.extra.json', 'ThirdParty.json'):
        path = project/'node_modules/cesium'/name
        if path.is_file(): shutil.copy2(path, licenses/name)
    manifest = dict(schemaVersion=1, task='G5-T01', stageQualified=False, buildRunId=run.name,
        environment=load(root/'.tools/g5/current.json'), project=project.relative_to(root).as_posix(),
        sources=inventory(root, source_paths(root)), packageLockSHA256=sha(project/'package-lock.json'),
        npmPackages=len(lock['packages'])-1, files=inventory(dist,[p for p in dist.rglob('*') if p.is_file()]))
    save(directory/'candidate.json', manifest)
    return dict(path=directory.relative_to(root).as_posix(), manifestSHA256=sha(directory/'candidate.json'),
                project=manifest['project'], files=len(manifest['files']), stageQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--run-id', required=True)
    parser.add_argument('--baseline-run-id', required=True)
    parser.add_argument('--action', choices=['setup','verify','build','test','serve'], required=True)
    parser.add_argument('--chinese-path', action='store_true')
    parser.add_argument('--build-run-id')
    args = parser.parse_args(); root = args.root.resolve(); run = root/'out/runs'/args.run_id
    need(re.fullmatch(r'g5-t01-[a-z0-9-]+', args.run_id), 'Invalid run identity')
    need(run.is_dir() and not (run/'result.json').exists(), 'Fresh entry-owned run required')
    record = dict(task='G5-T01', runId=run.name, action=args.action, status='running', startedAt=time.time(),
                  simulationStarted=False, stageQualified=False)
    before_env, before_cwd = dict(os.environ), Path.cwd()
    try:
        need(sys.flags.isolated and sys.version_info[:3] == (3,14,7) and struct.calcsize('P') == 8,
             'Explicit isolated Python 3.14.7 x64 required')
        record['inputs'] = inventory(root, source_paths(root))
        record['upstream'] = upstream(root, args.baseline_run_id)
        record['rawInputs'] = raw_inputs(root)
        if args.action == 'setup':
            folder, manifest = prepare(root, run)
            verify_files(root, record['inputs'])
            pointer = dict(schemaVersion=1, path=folder.relative_to(root).as_posix(), runId=run.name,
                           manifestSHA256=sha(folder/'environment.json'))
        else: folder, manifest = environment(root)
        record['environment'] = pointer if args.action == 'setup' else load(root/'.tools/g5/current.json')
        if args.action == 'build': record['candidate'] = build(root, run, folder, args.chinese_path)
        if args.action == 'verify':
            invoke([folder/'geo/Scripts/python.exe','-I','-B','-X','utf8',root/'tests/g5_environment/geo_smoke.py',
                    '--output',run/'geo-smoke'],run,'geo-smoke')
        if args.action == 'serve':
            need(args.build_run_id and re.fullmatch(r'g5-t01-[a-z0-9-]+',args.build_run_id), 'Explicit build run identity required')
            build_result = load(root/'out/runs'/args.build_run_id/'result.json')
            need(build_result['status']=='passed', 'Build did not pass')
            candidate = build_result['candidate']; directory=(root/candidate['path']).resolve()
            need(directory.is_relative_to(root/'out/build/cesium-viewer') and
                 sha(directory/'candidate.json')==candidate['manifestSHA256'], 'Candidate manifest differs')
            candidate_manifest=load(directory/'candidate.json')
            need(candidate_manifest['environment']==record['environment'], 'Candidate environment differs')
            verify_files(root,candidate_manifest['sources'])
            project=(root/candidate['project']).resolve()
            need(project.is_relative_to(directory), 'Candidate project escapes')
            verify_files(project/'dist',candidate_manifest['files'])
            print('G5_VIEWER_URL=http://127.0.0.1:8080/\nG5_STOP_FILE='+str(run/'request-stop'),flush=True)
            invoke([folder/'node/node.exe',root/'scripts/g5_environment/serve.mjs',project/'dist',run,'8080'],
                   run,'serve',timeout=None)
            record['candidate']=candidate
        if args.action == 'test':
            sys.path.insert(0, str(root/'tests/g5_environment'))
            from checks import checks
            record['checks'] = checks(root, run, folder, args.baseline_run_id)
        verify_files(root, record['inputs'])
        need(raw_inputs(root) == record['rawInputs'], 'Raw data registration changed during task')
        need(upstream(root, args.baseline_run_id) == record['upstream'], 'Upstream qualification changed during task')
        need(dict(os.environ)==before_env and Path.cwd()==before_cwd,'Process environment or directory changed')
        if args.action == 'setup': save(root/'.tools/g5/current.json',pointer)
        record['status'] = 'passed'; return 0
    except BaseException as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], flush=True); return 1
    finally:
        record.update(finishedAt=time.time(), environmentUnchanged=dict(os.environ)==before_env,
                      locationUnchanged=Path.cwd()==before_cwd)
        if not record['environmentUnchanged'] or not record['locationUnchanged']: record['status']='failed'
        save(run/'result.json', record); print('G5_T01_EVIDENCE='+str(run), flush=True)


if __name__ == '__main__': sys.exit(main())

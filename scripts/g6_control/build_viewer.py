"""Compose a G6 control candidate from the qualified G5 source project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, run, label, cwd=None, env=None):
    result = subprocess.run([str(x) for x in argv], cwd=cwd or ROOT, env=env,
                            capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    (run / (label + '.stdout')).write_bytes(result.stdout)
    (run / (label + '.stderr')).write_bytes(result.stderr)
    need(result.returncode == 0, label + ' failed; see this run directory')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(args.run_id.startswith('g6-a03-build-') and all(c.isascii() and (c.isalnum() or c == '-') for c in args.run_id),
         'Invalid viewer build identity')
    run = ROOT / 'out/runs' / args.run_id
    build = ROOT / 'out/build/g6-control' / args.run_id
    need(not run.exists() and not build.exists(), 'Viewer build identity already exists')
    run.mkdir(parents=True)
    build.mkdir(parents=True)
    record = {'task': 'G6-A03', 'runId': args.run_id, 'status': 'running', 'controlViewerQualified': False}
    try:
        pointer = load(ROOT / 'out/artifacts/g5-stage/current.json')
        need(pointer['task'] == 'G5-T11' and pointer['stageQualified'], 'G5 formal package missing')
        package = Path(pointer['package']).resolve()
        manifest = load(package / 'manifest.json')
        need(sha(package / 'manifest.json') == pointer['manifestSHA256'], 'G5 manifest differs')
        matches = [p.parent for p in (ROOT / 'out/build/g5-coverage').glob('*/candidate.json')
                   if sha(p) == manifest['coverageCandidateSHA256']]
        need(len(matches) == 1, 'G5 coverage source candidate is missing or ambiguous')
        candidate = matches[0]
        parent = load(candidate / 'candidate.json')
        for row in parent['inputs']:
            need(sha(ROOT / row['path']).lower() == row['sha256'].lower(), 'G5 source changed: ' + row['path'])
        project = build / 'project'
        shutil.copytree(candidate / 'project', project,
                        ignore=shutil.ignore_patterns('node_modules', 'dist', 'layer-unit', 'mission-unit',
                                                      'coverage-unit', 'numerical'))
        dependency = (candidate / 'project/node_modules').resolve()
        need((dependency / 'typescript/bin/tsc').is_file(), 'Qualified Node dependency missing')
        target = str(dependency).replace("'", "''")
        link = str(project / 'node_modules').replace("'", "''")
        command(['powershell.exe', '-NoProfile', '-Command',
                 "New-Item -ItemType Junction -Path '" + link + "' -Target '" + target + "' | Out-Null"],
                run, 'dependency-junction')
        shutil.copytree(ROOT / 'apps/cesium_control', project / 'control')
        path = project / 'entities/main.ts'
        text = path.read_text(encoding='utf-8')
        text = "import { ControlPanel } from '../control/panel';\n" + text
        for old, new in [
            ('const connection=new ReadOnlyConnection(location.origin,stateConfig.limits,()=>{layer?.update();missions?.update();coverage?.update();});',
             'const connection=new ReadOnlyConnection(location.origin,stateConfig.limits,()=>{layer?.update();missions?.update();coverage?.update();});\n  const control=new ControlPanel(connection);'),
            ('coverage?.destroy();missions?.destroy();connection.stop();',
             'control.destroy();coverage?.destroy();missions?.destroy();connection.stop();')]:
            need(text.count(old) == 1, 'G5 composition anchor differs: ' + old)
            text = text.replace(old, new)
        path.write_text(text, encoding='utf-8')
        config = load(project / 'tsconfig.json')
        config['include'].append('control')
        save(project / 'tsconfig.json', config)
        node = ROOT / '.tools/g5/current.json'
        node_path = ROOT / load(node)['path'] / 'node/node.exe'
        command([node_path, dependency / 'typescript/bin/tsc', '--project', project / 'tsconfig.json'],
                run, 'typescript', cwd=project)
        env = dict(os.environ)
        env['PATH'] = str(node_path.parent) + os.pathsep + env['PATH']
        command([node_path, dependency / 'vite/bin/vite.js', 'build'], run, 'vite-build', cwd=project, env=env)
        shutil.copytree(package / 'dist/licenses', project / 'dist/licenses')
        service = load(package / 'config.json')
        service.update(dist=str(project / 'dist'), project=str(project),
                       vector=dict(service['vector'], path=str(package / 'vector/planet.pmtiles')),
                       heightfield=dict(service['heightfield'], path=str(package / 'terrain/cesium-heightfield.f32')))
        save(build / 'service.json', service)
        source = [ROOT / 'apps/cesium_control/panel.ts', ROOT / 'apps/cesium_control/style.css', Path(__file__)]
        record.update(status='passed', stageManifestSHA256=pointer['manifestSHA256'],
                      coverageCandidateSHA256=manifest['coverageCandidateSHA256'],
                      inputs=[{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)} for p in source],
                      dist=str(project / 'dist'), service=str(build / 'service.json'),
                      controlViewerQualified=False)
        print('G6_A03_BUILD_ID=' + args.run_id + ' STATUS=passed')
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error))
        print('G6_A03_BUILD_ID=' + args.run_id + ' STATUS=failed ERROR=' + str(error), file=sys.stderr)
        return 1
    finally:
        save(run / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())

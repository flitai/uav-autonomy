"""Build B06 viewer by adding the live-replanning panel to qualified B05."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release


def need(value, message):
    if not value:
        raise RuntimeError(message)


def command(argv, run, label, cwd=None, env=None):
    done = subprocess.run([str(item) for item in argv], cwd=cwd or ROOT, env=env,
                          capture_output=True, timeout=180,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    (run / (label + '.stdout')).write_bytes(done.stdout)
    (run / (label + '.stderr')).write_bytes(done.stderr)
    need(done.returncode == 0, label + ' failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(args.run_id.startswith('g6-b06-build-'), 'B06 build ID required')
    run = ROOT / 'out/runs' / args.run_id
    build = ROOT / 'out/build/g6-replanning' / args.run_id
    need(not run.exists() and not build.exists(), 'B06 build ID exists')
    run.mkdir(parents=True)
    build.mkdir(parents=True)
    record = dict(task='G6-B06', runId=args.run_id, status='running', viewerQualified=False)
    try:
        parent_id = 'g6-b05-build-20260930-05'
        parent_receipt = ROOT / 'out/runs' / parent_id / 'result.json'
        parent = release.load(parent_receipt)
        need(parent['status'] == 'passed' and parent['task'] == 'G6-B05',
             'Qualified B05 viewer missing')
        need(all(release.digest(ROOT / item['path']).lower() == item['sha256'].lower()
                 for item in parent['inputs']), 'B05 input changed')
        source = ROOT / 'out/build/g6-assignment' / parent_id / 'project'
        project = build / 'project'
        shutil.copytree(source, project, ignore=shutil.ignore_patterns('node_modules', 'dist'))
        dependency = ROOT / 'out/build/g6-drafts/g6-b03-build-20260924-2438/project/node_modules'
        need((dependency / 'typescript/bin/tsc').is_file(), 'Qualified TypeScript dependency missing')
        command(['powershell.exe', '-NoProfile', '-Command',
                 "New-Item -ItemType Junction -Path '" + str(project / 'node_modules').replace("'", "''") +
                 "' -Target '" + str(dependency.resolve()).replace("'", "''") + "' | Out-Null"],
                run, 'dependency-junction')
        shutil.copytree(ROOT / 'apps/cesium_replanning', project / 'replanning')
        entry = project / 'entities/main.ts'
        source_text = entry.read_text(encoding='utf-8')
        anchor = '  const assignmentPanel=new AssignmentPanel();'
        need(source_text.count(anchor) == 1, 'B05 viewer entry changed')
        source_text = "import { ReplanningPanel } from '../replanning/panel';\n" + \
            source_text.replace(anchor, anchor + '\n  const replanningPanel=new ReplanningPanel();')
        anchor = 'assignmentPanel.destroy();'
        need(source_text.count(anchor) == 1, 'B05 viewer cleanup changed')
        source_text = source_text.replace(anchor, 'replanningPanel.destroy();' + anchor)
        entry.write_text(source_text, encoding='utf-8')
        tsconfig = release.load(project / 'tsconfig.json')
        tsconfig['include'].append('replanning')
        release.save(project / 'tsconfig.json', tsconfig)
        node = ROOT / release.load(ROOT / '.tools/g5/current.json')['path'] / 'node/node.exe'
        command([node, dependency / 'typescript/bin/tsc', '--project', project / 'tsconfig.json'],
                run, 'typescript', cwd=project)
        env = dict(os.environ)
        env['PATH'] = str(node.parent) + os.pathsep + env['PATH']
        command([node, dependency / 'vite/bin/vite.js', 'build'],
                run, 'vite-build', cwd=project, env=env)
        service = release.load(ROOT / 'out/build/g6-assignment' / parent_id / 'service.json')
        service.update(dist=str(project / 'dist'), project=str(project))
        release.save(build / 'service.json', service)
        paths = [path for directory in ('apps/g6_replanning', 'apps/cesium_replanning',
                                        'scripts/g6_replanning')
                 for path in (ROOT / directory).rglob('*')
                 if path.is_file() and '__pycache__' not in path.parts]
        paths.sort()
        record.update(status='passed', viewerQualified=True, b05BuildRunId=parent_id,
                      b05BuildSHA256=release.digest(parent_receipt),
                      inputs=[dict(path=path.relative_to(ROOT).as_posix(),
                                   sha256=release.digest(path)) for path in paths],
                      service=str(build / 'service.json'), dist=str(project / 'dist'))
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error))
        print(error, file=sys.stderr)
        return 1
    finally:
        release.save(run / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())

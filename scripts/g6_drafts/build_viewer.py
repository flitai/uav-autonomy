"""Build a B03 viewer candidate on top of the qualified G6-A viewer."""
import argparse
import json
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


def run(argv, folder, name, cwd=None, env=None):
    result = subprocess.run([str(part) for part in argv], cwd=cwd or ROOT,
                            env=env, capture_output=True, timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    (folder / (name + '.stdout')).write_bytes(result.stdout)
    (folder / (name + '.stderr')).write_bytes(result.stderr)
    need(result.returncode == 0, name + ' failed; see ' + str(folder))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(args.run_id.startswith('g6-b03-build-'), 'B03 build ID required')
    folder = ROOT / 'out/runs' / args.run_id
    build = ROOT / 'out/build/g6-drafts' / args.run_id
    need(not folder.exists() and not build.exists(), 'B03 build ID already exists')
    folder.mkdir(parents=True)
    build.mkdir(parents=True)
    record = dict(task='G6-B03', runId=args.run_id, status='running',
                  taskViewerQualified=False)
    try:
        pointer, manifest = release.resolve()
        b02 = ROOT / 'out/runs/g6-b02-acceptance-20260924-2410/acceptance.json'
        acceptance = release.load(b02)
        need(acceptance['status'] == 'passed' and acceptance['previewIsolationQualified'],
             'B02 preview qualification missing')
        for row in acceptance['sources']:
            need(release.digest(ROOT / row['path']).lower() == row['sha256'].lower(),
                 'B02 source changed: ' + row['path'])
        source_id = manifest['viewerBuildRunId']
        source = ROOT / 'out/build/g6-control' / source_id / 'project'
        previous = release.load(ROOT / 'out/runs' / source_id / 'result.json')
        need(previous['status'] == 'passed' and previous['task'] == 'G6-A03' and
             release.digest(ROOT / 'out/runs' / source_id / 'result.json') ==
             manifest['viewerBuildSHA256'], 'G6-A viewer source changed')
        for row in previous['inputs']:
            need(release.digest(ROOT / row['path']).lower() == row['sha256'].lower(),
                 'G6-A viewer input changed')
        project = build / 'project'
        shutil.copytree(source, project, ignore=shutil.ignore_patterns('node_modules', 'dist'))
        dependency = source / 'node_modules'
        need((dependency / 'typescript/bin/tsc').is_file(), 'Qualified Node dependency missing')
        link = str(project / 'node_modules').replace("'", "''")
        target = str(dependency.resolve()).replace("'", "''")
        run(['powershell.exe', '-NoProfile', '-Command',
             "New-Item -ItemType Junction -Path '" + link + "' -Target '" + target + "' | Out-Null"],
            folder, 'dependency-junction')
        shutil.copytree(ROOT / 'apps/cesium_tasks', project / 'tasks')
        entry = project / 'entities/main.ts'
        source_text = entry.read_text(encoding='utf-8')
        source_text = "import { TaskPanel } from '../tasks/panel';\n" + source_text
        anchor = '  coverage=new CoveragePanel(viewer,connection,layer,missions.model.heights);'
        need(source_text.count(anchor) == 1, 'G6-A viewer initialization anchor changed')
        source_text = source_text.replace(anchor, anchor + '\n  const taskPanel=new TaskPanel(viewer,missions.model.heights);')
        anchor = 'control.destroy();coverage?.destroy();'
        need(source_text.count(anchor) == 1, 'G6-A viewer cleanup anchor changed')
        source_text = source_text.replace(anchor, 'taskPanel.destroy();' + anchor)
        entry.write_text(source_text, encoding='utf-8')
        tsconfig = release.load(project / 'tsconfig.json')
        tsconfig['include'].append('tasks')
        release.save(project / 'tsconfig.json', tsconfig)
        node = ROOT / release.load(ROOT / '.tools/g5/current.json')['path'] / 'node/node.exe'
        run([node, dependency / 'typescript/bin/tsc', '--project', project / 'tsconfig.json'],
            folder, 'typescript', cwd=project)
        env = dict(os.environ)
        env['PATH'] = str(node.parent) + os.pathsep + env['PATH']
        run([node, dependency / 'vite/bin/vite.js', 'build'], folder, 'vite-build', cwd=project, env=env)
        service = release.load(ROOT / 'out/build/g6-control' / source_id / 'service.json')
        service.update(dist=str(project / 'dist'), project=str(project))
        release.save(build / 'service.json', service)
        source_files = [ROOT / path for path in (
            'apps/cesium_tasks/panel.ts', 'apps/cesium_tasks/style.css',
            'apps/g6_drafts/server.py', 'scripts/g6_drafts/build_viewer.py')]
        record.update(status='passed', g6ManifestSHA256=pointer['manifestSHA256'],
                      b02AcceptanceSHA256=release.digest(b02), sourceViewerRunId=source_id,
                      sourceViewerSHA256=manifest['viewerBuildSHA256'],
                      inputs=[dict(path=p.relative_to(ROOT).as_posix(),sha256=release.digest(p))
                              for p in source_files], service=str(build / 'service.json'),
                      dist=str(project / 'dist'))
        print('G6_B03_VIEWER=' + args.run_id + ' STATUS=passed')
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error))
        print('G6_B03_VIEWER=' + args.run_id + ' STATUS=failed ERROR=' + str(error),file=sys.stderr)
        return 1
    finally:
        release.save(folder / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())

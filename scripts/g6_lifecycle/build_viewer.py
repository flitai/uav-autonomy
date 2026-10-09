"""Build an isolated B07 viewer from the qualified B06 candidate."""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('g6_release', ROOT / 'scripts/g6_release/manage.py')
release = module_from_spec(spec)
spec.loader.exec_module(release)


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


def once(source, old, new, message):
    need(source.count(old) == 1, message)
    return source.replace(old, new)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(args.run_id.startswith('g6-b07-build-'), 'B07 build ID required')
    run = ROOT / 'out/runs' / args.run_id
    build = ROOT / 'out/build/g6-lifecycle' / args.run_id
    need(not run.exists() and not build.exists(), 'B07 build ID exists')
    run.mkdir(parents=True)
    build.mkdir(parents=True)
    record = dict(task='G6-B07', runId=args.run_id,
                  status='running', viewerQualified=False)
    try:
        parent_id = 'g6-b06-build-20261004-09'
        parent_file = ROOT / 'out/runs' / parent_id / 'result.json'
        parent = release.load(parent_file)
        need(parent['status'] == 'passed' and parent['task'] == 'G6-B06' and
             all(release.digest(ROOT / row['path']).lower() == row['sha256'].lower()
                 for row in parent['inputs']), 'Qualified B06 viewer source changed')
        source = ROOT / 'out/build/g6-replanning' / parent_id / 'project'
        project = build / 'project'
        shutil.copytree(source, project, ignore=shutil.ignore_patterns('node_modules', 'dist'))
        dependency = ROOT / 'out/build/g6-drafts/g6-b03-build-20260924-2438/project/node_modules'
        need((dependency / 'typescript/bin/tsc').is_file(),
             'Qualified TypeScript dependency missing')
        command(['powershell.exe', '-NoProfile', '-Command',
                 "New-Item -ItemType Junction -Path '" +
                 str(project / 'node_modules').replace("'", "''") + "' -Target '" +
                 str(dependency.resolve()).replace("'", "''") + "' | Out-Null"],
                run, 'dependency-junction')
        shutil.copytree(ROOT / 'apps/cesium_lifecycle', project / 'lifecycle')
        replanning = project / 'replanning/panel.ts'
        source_text = replanning.read_text(encoding='utf-8')
        source_text = once(source_text,
            'review:this.review,key:this.key,status:this.status.textContent})}});',
            'review:this.review,key:this.key,status:this.status.textContent}),'
            'restoreReview:(review:Review)=>this.restoreReview(review)}});',
            'B06 review bridge changed')
        source_text = once(source_text, '  private async api(path:string',
            '''  private async restoreReview(review:Review){
    await this.refresh();
    if(!this.state||this.state.status!=='paused'||
        this.state.identity.streamId!==review.identity.streamId)throw Error('方案身份已变化，请重新规划');
    this.review=review;this.acknowledge.checked=false;
    this.showReview(review);this.root.open=true;
  }

  private async api(path:string''', 'B06 review method changed')
        replanning.write_text(source_text, encoding='utf-8')
        entry = project / 'entities/main.ts'
        source_text = entry.read_text(encoding='utf-8')
        source_text = "import { LifecyclePanel } from '../lifecycle/panel';\n" + \
            once(source_text, '  const replanningPanel=new ReplanningPanel();',
                 '  const replanningPanel=new ReplanningPanel();\n'
                 '  const lifecyclePanel=new LifecyclePanel();',
                 'B06 viewer entry changed')
        source_text = once(source_text, 'replanningPanel.destroy();',
                           'lifecyclePanel.destroy();replanningPanel.destroy();',
                           'B06 viewer cleanup changed')
        entry.write_text(source_text, encoding='utf-8')
        tsconfig = release.load(project / 'tsconfig.json')
        tsconfig['include'].append('lifecycle')
        release.save(project / 'tsconfig.json', tsconfig)
        node = ROOT / release.load(ROOT / '.tools/g5/current.json')['path'] / 'node/node.exe'
        command([node, dependency / 'typescript/bin/tsc', '--project', project / 'tsconfig.json'],
                run, 'typescript', cwd=project)
        env = dict(os.environ)
        env['PATH'] = str(node.parent) + os.pathsep + env['PATH']
        command([node, dependency / 'vite/bin/vite.js', 'build'],
                run, 'vite-build', cwd=project, env=env)
        service = release.load(ROOT / 'out/build/g6-replanning' / parent_id / 'service.json')
        service.update(dist=str(project / 'dist'), project=str(project))
        release.save(build / 'service.json', service)
        paths = [path for directory in ('apps/g6_lifecycle', 'apps/cesium_lifecycle',
                                        'scripts/g6_lifecycle')
                 for path in (ROOT / directory).rglob('*')
                 if path.is_file() and '__pycache__' not in path.parts]
        paths.sort()
        record.update(status='passed', viewerQualified=True, b06BuildRunId=parent_id,
                      b06BuildSHA256=release.digest(parent_file),
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

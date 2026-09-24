"""G6-B03 two-mode browser and backend validation with normal group shutdown."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import api_probe as control
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import isolated_preview


def need(value, message):
    if not value:
        raise RuntimeError(message)


def wait(label, predicate, process, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        need(process.poll() is None, label + ': active session exited')
        try:
            value = predicate()
            if value:
                return value
        except Exception:
            pass
        time.sleep(.2)
    raise TimeoutError(label + ': timeout')


def case(root_run, mode, action, build_id, web_python):
    identity = 'g6-b03-session-' + root_run + '-' + mode.lower() + '-' + action
    folder = ROOT / 'out/runs' / identity
    run = ROOT / 'out/runs' / root_run
    process = None
    result = None
    try:
        with (run / (mode.lower() + '-' + action + '.stdout')).open('wb') as out, \
             (run / (mode.lower() + '-' + action + '.stderr')).open('wb') as err:
            process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8',
                str(ROOT / 'scripts/g6_drafts/session.py'), '--run-id', identity,
                '--viewer-build', 'g6-a03-build-20260924-2330',
                '--draft-build', build_id, '--mode', mode],
                cwd=ROOT, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        ready = wait('B03 ' + mode + ' session', lambda: release.load(folder / 'b03-session-ready.json')
                     if (folder / 'b03-session-ready.json').is_file() else None, process)
        session = folder / 'segment-001/control-session.json'
        before = isolated_preview.active_evidence(session)
        output = run / (mode.lower() + '-' + action)
        script = ROOT / ('tests/g6_drafts/browser.py' if action == 'browser'
                         else 'tests/g6_drafts/api.py')
        command = [str(web_python if action == 'browser' else sys.executable),
                   '-I', '-B', '-X', 'utf8', str(script), '--output', str(output)]
        if action == 'api':
            command += ['--session', str(session)]
        tested = subprocess.run(command, cwd=ROOT, capture_output=True,
                                timeout=200, creationflags=subprocess.CREATE_NO_WINDOW)
        (run / (mode.lower() + '-' + action + '-test.stdout')).write_bytes(tested.stdout)
        (run / (mode.lower() + '-' + action + '-test.stderr')).write_bytes(tested.stderr)
        evidence = release.load(output / 'result.json')
        need(tested.returncode == 0 and evidence['status'] == 'passed',
             action + ' failed: ' + evidence.get('error', str(tested.returncode)))
        if action == 'browser':
            need(not evidence['forcedTermination'] and evidence['exitCode'] == 0 and
                 {row['action'] for row in evidence['steps']} >=
                 {'save-point', 'preview-point', 'draw-line', 'save-line',
                  'save-area', 'refresh-restored'}, 'Browser evidence incomplete')
            saved = list((session.parent / 'task-drafts/items').glob('*.json'))
            need(len(saved) == 3, 'Browser did not persist three drafts')
        else:
            need(len(evidence['steps']) >= 6 and evidence['activeBefore']['streamId'] ==
                 evidence['activeAfter']['streamId'], 'API evidence incomplete')
        after = isolated_preview.active_evidence(session)
        need(before['streamId'] == after['streamId'] and
             before['uxasProcess'] == after['uxasProcess'] and
             before['forbiddenRows'] == after['forbiddenRows'] and
             before['movingStateCount'] == after['movingStateCount'] == 0,
             'Draft and preview changed active execution')
        result = dict(mode=mode,action=action,status='passed',sessionRunId=identity,
                      browserOrApiReceiptSHA256=release.digest(output / 'result.json'),
                      activeBefore=before,activeAfter=after,
                      previewCount=sum(row['action'] in ('preview-point', 'preview')
                                       for row in evidence['steps']))
    finally:
        if process is not None:
            if folder.exists():
                (folder / 'request-stop').touch(exist_ok=True)
            try:
                process.wait(timeout=55)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
    need(result is not None and process.returncode == 0,
         mode + ' ' + action + ' session did not exit normally')
    runtime = release.load(folder / 'runtime-result.json')
    need(runtime['status'] == 'passed' and runtime['normalExit'] and runtime['segments'] == 1,
         mode + ' ' + action + ' runtime receipt failed')
    result['normalExit'] = True
    result['runtimeSHA256'] = release.digest(folder / 'runtime-result.json')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--build-id',required=True)
    args = parser.parse_args()
    need(re.fullmatch(r'g6-b03-[a-z0-9-]+',args.run_id), 'B03 acceptance ID invalid')
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B03 acceptance ID exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B03',runId=args.run_id,status='running',
                  taskDraftQualified=False,executionQualified=False,cases=[])
    try:
        pointer, manifest = release.resolve()
        build = ROOT / 'out/runs' / args.build_id / 'result.json'
        viewer = release.load(build)
        need(viewer['status'] == 'passed' and viewer['task'] == 'G6-B03' and
             viewer['g6ManifestSHA256'] == pointer['manifestSHA256'] and
             viewer['b02AcceptanceSHA256'] == release.digest(ROOT /
               'out/runs/g6-b02-acceptance-20260924-2410/acceptance.json'),
             'B03 viewer parent qualification differs')
        for row in viewer['inputs']:
            need(release.digest(ROOT / row['path']).lower() == row['sha256'].lower(),
                 'B03 viewer input changed')
        source = [ROOT / path for path in ('scripts/g6_drafts/session.py',
            'scripts/g6_drafts/acceptance.py', 'tests/g6_drafts/api.py',
            'tests/g6_drafts/browser.py')]
        record['sources'] = [dict(path=p.relative_to(ROOT).as_posix(),sha256=release.digest(p))
                             for p in source]
        record['buildId'] = args.build_id
        record['buildSHA256'] = release.digest(build)
        _, _, web_python = control.probe.state.entry.resolve(ROOT)
        for mode, action in (('Headless','api'),('Headless','browser'),('Gui','browser')):
            record['cases'].append(case(args.run_id, mode, action, args.build_id, web_python))
        need(all(release.digest(ROOT / row['path']) == row['sha256'] for row in record['sources']),
             'B03 source changed during acceptance')
        record.update(status='passed',taskDraftQualified=True)
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(record['traceback'],file=sys.stderr)
        return 1
    finally:
        release.save(run / 'acceptance.json',record)


if __name__ == '__main__':
    sys.exit(main())

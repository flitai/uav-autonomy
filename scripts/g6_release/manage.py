"""Qualify and publish the workspace-bound G6-A control overlay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / 'out/artifacts/g6-control'
RUNS = ROOT / 'out/runs'
SOURCE_FOLDERS = ('apps/cesium_control', 'apps/g6_control', 'scripts/g6_control',
                  'tests/g6_control', 'scripts/g6_release')


def need(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    hash_value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hash_value.update(block)
    return hash_value.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sources():
    files = [p for name in SOURCE_FOLDERS for p in (ROOT / name).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts]
    return [dict(path=p.relative_to(ROOT).as_posix(), sha256=digest(p)) for p in sorted(files)]


def check_sources(rows):
    need(rows == sources(), 'G6-A source inventory changed')


def receipt(run_id, filename, task=None):
    need(re.fullmatch(r'[A-Za-z0-9-]+', run_id), 'Invalid receipt run identity')
    path = RUNS / run_id / filename
    value = load(path)
    need(value['status'] == 'passed' and (task is None or value['task'] == task),
         'Failed or mismatched receipt: ' + str(path))
    return dict(runId=run_id, path=str(path.relative_to(ROOT)), sha256=digest(path), value=value)


def inputs(args):
    need(args.viewer_build, 'Explicit viewer build required')
    viewer = receipt(args.viewer_build, 'result.json', 'G6-A03')
    need(viewer['value']['inputs'], 'Viewer source record missing')
    for row in viewer['value']['inputs']:
        need(digest(ROOT / row['path']).lower() == row['sha256'].lower(),
             'Viewer source changed: ' + row['path'])
    build = ROOT / 'out/build/g6-control' / args.viewer_build
    need((build / 'service.json').is_file() and (build / 'project/dist/index.html').is_file(),
         'G6-A viewer build artifacts missing')
    formal = ROOT / 'out/artifacts/g5-stage/current.json'
    pointer = load(formal)
    need(pointer['task'] == 'G5-T11' and pointer['stageQualified'] and
         pointer['manifestSHA256'] == viewer['value']['stageManifestSHA256'] and
         digest(Path(pointer['package']) / 'manifest.json') == pointer['manifestSHA256'],
         'G5 formal source differs from G6-A viewer')
    historical = {
        'a01': (args.a01, 'result.json', 'G6-A01'),
        'a02': (args.a02, 'runtime-result.json', 'G6-A02'),
        'a03': (args.a03, 'runtime-result.json', 'G6-A03'),
        'a04Reset': (args.a04_reset, 'runtime-result.json', 'G6-A02'),
        'a04Fault': (args.a04_fault, 'runtime-result.json', 'G6-A02'),
        'a05Http': (args.a05_http, 'result.json', 'G6-A05'),
        'a05Browser': (args.a05_browser, 'result.json', 'G6-A05'),
    }
    need(all(value[0] for value in historical.values()), 'All G6-A automatic run IDs are required')
    accepted = {key: receipt(*value) for key, value in historical.items()}
    current = {row['path']: row['sha256'] for row in sources()}
    for label, accepted_receipt in accepted.items():
        for row in accepted_receipt['value'].get('inputs', []):
            if row['path'] in current:
                need(row['sha256'].lower() == current[row['path']].lower(),
                     label + ' G6-A source changed: ' + row['path'])
    need(accepted['a02']['value']['backendControlObserved'] and
         all(case['apiControlCandidateObserved'] for case in accepted['a02']['value']['cases']) and
         accepted['a03']['value']['browserControlObserved'] and
         accepted['a04Reset']['value']['groupResetObserved'] and
         accepted['a04Fault']['value']['faultMatrixObserved'] and
         accepted['a05Http']['value']['twoModePersistentResetObserved'] and
         accepted['a05Browser']['value']['twoModePersistentResetObserved'],
         'G6-A automatic capability receipts differ')
    need(all(len(accepted[name]['value']['cases']) == count for name, count in
             (('a02', 2), ('a03', 2), ('a04Reset', 4), ('a04Fault', 2))),
         'G6-A mode counts differ')
    for name in ('a02', 'a03', 'a04Reset'):
        need(all(case['status'] == 'passed' and case['normalExit'] and case['portsReleased']
                 for case in accepted[name]['value']['cases']), name + ' case failed')
    for case in accepted['a04Fault']['value']['cases']:
        need(case['expectedBackendExit'] and case['normalExit'] and case['portsReleased'] and
             case['faultEvidence']['amaseExitCode'] == 0, 'Fault negative case differs')
    for name in ('a05Http', 'a05Browser'):
        cases = accepted[name]['value']['modes']
        need(len(cases) == 2 and all(case['exitCode'] == 0 and
             load(RUNS / case['runId'] / 'runtime-result.json')['status'] == 'passed'
             for case in cases), name + ' persistent sessions failed')
    need(accepted['a03']['value']['viewerBuildRunId'] == args.viewer_build and
         accepted['a03']['value']['viewerBuildSHA256'] == viewer['sha256'],
         'Edge receipt did not bind current G6 viewer')
    return dict(viewer=viewer, accepted={key: {k: value[k] for k in ('runId', 'path', 'sha256')}
                                         for key, value in accepted.items()},
                g5PointerSHA256=digest(formal), g5ManifestSHA256=pointer['manifestSHA256'],
                sourceFiles=sources())


def qualify(run, args):
    resolved = inputs(args)
    acceptance = dict(task='G6-A05', status='passed', action='qualify',
                      stageQualified=False, manualReview='pending',
                      viewerBuildRunId=args.viewer_build,
                      viewerBuildSHA256=resolved['viewer']['sha256'],
                      automaticReceipts=resolved['accepted'],
                      g5PointerSHA256=resolved['g5PointerSHA256'],
                      g5ManifestSHA256=resolved['g5ManifestSHA256'],
                      sourceFiles=resolved['sourceFiles'])
    save(run / 'acceptance.json', acceptance)
    return dict(status='passed', qualificationSHA256=digest(run / 'acceptance.json'),
                manualReview='pending', stageQualified=False)


def check_qualification(run_id):
    path = RUNS / run_id / 'acceptance.json'
    value = load(path)
    need(value['task'] == 'G6-A05' and value['status'] == 'passed' and
         value['action'] == 'qualify' and value['manualReview'] == 'pending' and
         not value['stageQualified'], 'G6-A automatic qualification differs')
    check_sources(value['sourceFiles'])
    need(digest(ROOT / 'out/artifacts/g5-stage/current.json') == value['g5PointerSHA256'],
         'G5 formal pointer changed')
    for row in value['automaticReceipts'].values():
        need(digest(ROOT / row['path']) == row['sha256'], 'Automatic receipt changed')
    need(digest(RUNS / value['viewerBuildRunId'] / 'result.json') == value['viewerBuildSHA256'],
         'G6-A viewer build receipt changed')
    return value, digest(path)


def review_session(run_id, qualified):
    review = RUNS / run_id
    ready = load(review / 'session-ready.json')
    source = load(review / 'source-binding.json')
    need(ready['runId'] == run_id and ready['mode'] == 'Gui' and
         source['viewerBuildRunId'] == qualified['viewerBuildRunId'] and
         source['viewerBuildSHA256'] == qualified['viewerBuildSHA256'] and
         source['g5PointerSHA256'] == qualified['g5PointerSHA256'],
         'GUI review source differs: ' + run_id)
    return review


def check_review_inputs(result, qualified):
    current = {row['path']: row['sha256'] for row in qualified['sourceFiles']}
    for row in result.get('inputs', []):
        if row['path'] in current:
            need(row['sha256'].lower() == current[row['path']].lower(),
                 'GUI review source changed: ' + row['path'])


def clean_exit(review, qualified):
    result = load(review / 'runtime-result.json')
    check_review_inputs(result, qualified)
    need(result['task'] == 'G6-A05' and result['status'] == 'passed' and
         result['normalExit'] and all(case['status'] == 'passed' and case['normalExit'] and
         case['portsReleased'] for case in result['cases']), 'GUI exit run did not close normally')
    return result


def visual_evidence(review, qualified):
    result = load(review / 'runtime-result.json')
    check_review_inputs(result, qualified)
    need(result['task'] == 'G6-A05' and result['status'] == 'failed' and
         any(case['status'] == 'passed' and case.get('exitReason') == 'reset'
             for case in result['cases']), 'Failed visual run lacks a completed reset segment')
    actions = [load(path) for segment in review.glob('segment-*')
               for path in (segment / 'control-operations').glob('*.json')]
    need({'start', 'pause', 'resume', 'rate'}.issubset(
         {row['action'] for row in actions if row['status'] == 'confirmed'}) and
         any((review / 'control-reset-receipts').glob('*.json')),
         'Failed visual run lacks confirmed controls and reset')
    return result


def confirm(run, args):
    qualified, qualification_sha = check_qualification(args.qualification_run_id)
    review = review_session(args.review_run_id, qualified)
    exit_run_id = args.normal_exit_run_id or args.review_run_id
    exit_run = review_session(exit_run_id, qualified)
    if exit_run_id != args.review_run_id:
        visual_evidence(review, qualified)
        clean_exit(exit_run, qualified)
    need(not (review / 'manual-confirmation.json').exists(), 'Review was already decided')
    need(args.decision in ('approve', 'reject'), 'Explicit current user decision required')
    confirmation = dict(decision=args.decision, source='current user visual review',
                        runId=args.review_run_id, normalExitRunId=exit_run_id,
                        qualificationRunId=args.qualification_run_id,
                        qualificationSHA256=qualification_sha,
                        viewerBuildSHA256=qualified['viewerBuildSHA256'],
                        recordedAtMs=int(time.time() * 1000), note=args.note or '')
    save(review / 'manual-confirmation.json', confirmation)
    if exit_run_id == args.review_run_id:
        (review / 'request-stop').touch()
    save(run / 'confirmation-result.json', dict(task='G6-A05', status='passed',
         decision=args.decision, reviewRunId=args.review_run_id,
         normalExitRunId=exit_run_id,
         confirmationSHA256=digest(review / 'manual-confirmation.json')))
    return dict(status='passed', decision=args.decision, reviewRunId=args.review_run_id,
                normalExitRunId=exit_run_id)


def check_review(args, qualified, qualification_sha):
    review = review_session(args.review_run_id, qualified)
    confirmation = load(review / 'manual-confirmation.json')
    need(confirmation['decision'] == 'approve' and confirmation['source'] ==
         'current user visual review' and confirmation['runId'] == args.review_run_id and
         confirmation['qualificationRunId'] == args.qualification_run_id and
         confirmation['qualificationSHA256'] == qualification_sha and
         confirmation['viewerBuildSHA256'] == qualified['viewerBuildSHA256'],
         'Current GUI approval differs')
    exit_run_id = confirmation['normalExitRunId']
    exit_run = review_session(exit_run_id, qualified)
    if exit_run_id != args.review_run_id:
        visual_evidence(review, qualified)
    clean_exit(exit_run, qualified)
    return dict(runId=args.review_run_id, normalExitRunId=exit_run_id,
                visualRunStatus=load(review / 'runtime-result.json')['status'],
                confirmationSHA256=digest(review / 'manual-confirmation.json'),
                visualRuntimeSHA256=digest(review / 'runtime-result.json'),
                normalExitRuntimeSHA256=digest(exit_run / 'runtime-result.json'))


def publish(run, args):
    qualified, qualification_sha = check_qualification(args.qualification_run_id)
    review = check_review(args, qualified, qualification_sha)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    package = ARTIFACTS / args.run_id
    need(not package.exists(), 'G6-A publication ID already exists')
    package.mkdir()
    manifest = dict(task='G6-A05', stageQualified=True, packageKind='workspace-bound-overlay',
                    publishRunId=args.run_id, qualificationRunId=args.qualification_run_id,
                    qualificationSHA256=qualification_sha, review=review,
                    viewerBuildRunId=qualified['viewerBuildRunId'],
                    viewerBuildSHA256=qualified['viewerBuildSHA256'],
                    g5PointerSHA256=qualified['g5PointerSHA256'],
                    g5ManifestSHA256=qualified['g5ManifestSHA256'],
                    sourceFiles=qualified['sourceFiles'], automaticReceipts=qualified['automaticReceipts'])
    save(package / 'manifest.json', manifest)
    acceptance = dict(task='G6-A05', status='passed', stageQualified=True,
                      package=str(package), manifestSHA256=digest(package / 'manifest.json'),
                      qualificationSHA256=qualification_sha, review=review)
    save(run / 'acceptance.json', acceptance)
    pointer = ARTIFACTS / 'current.json'
    temporary = ARTIFACTS / (args.run_id + '.pointer.tmp')
    save(temporary, dict(task='G6-A05', stageQualified=True, package=str(package),
         publishRunId=args.run_id, manifestSHA256=acceptance['manifestSHA256'],
         acceptanceSHA256=digest(run / 'acceptance.json')))
    os.replace(temporary, pointer)
    return dict(status='passed', stageQualified=True, package=str(package), pointer=str(pointer))


def resolve():
    pointer = load(ARTIFACTS / 'current.json')
    need(pointer['task'] == 'G6-A05' and pointer['stageQualified'], 'G6-A formal pointer unavailable')
    package = Path(pointer['package']).resolve()
    need(package.is_relative_to(ARTIFACTS.resolve()) and
         digest(package / 'manifest.json') == pointer['manifestSHA256'],
         'G6-A package differs')
    manifest = load(package / 'manifest.json')
    need(manifest['stageQualified'] and manifest['publishRunId'] == pointer['publishRunId'],
         'G6-A formal manifest differs')
    acceptance = RUNS / pointer['publishRunId'] / 'acceptance.json'
    need(digest(acceptance) == pointer['acceptanceSHA256'] and
         load(acceptance)['stageQualified'], 'G6-A publication receipt differs')
    check_sources(manifest['sourceFiles'])
    need(digest(ROOT / 'out/artifacts/g5-stage/current.json') == manifest['g5PointerSHA256'] and
         digest(RUNS / manifest['viewerBuildRunId'] / 'result.json') == manifest['viewerBuildSHA256'],
         'G6-A parent pointer or viewer changed')
    return pointer, manifest


def production(run, args):
    pointer, manifest = resolve()
    child_id = args.run_id + '-session'
    child = RUNS / child_id
    need(not child.exists(), 'Production child run identity already exists')
    save(run / 'production-session.json', dict(runId=child_id,
         stopFile=str(child / 'request-stop'), url='http://127.0.0.1:8080/'))
    command = [sys.executable, '-I', '-B', '-X', 'utf8', str(ROOT / 'scripts/g6_control/session.py'),
               '--run-id', child_id, '--viewer-build', manifest['viewerBuildRunId'],
               '--mode', args.mode]
    with (run / 'session.stdout').open('wb') as out, (run / 'session.stderr').open('wb') as err:
        process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            if args.auto_stop:
                deadline = time.monotonic() + 90
                while not (child / 'session-ready.json').exists():
                    need(process.poll() is None, 'Production session exited before ready')
                    need(time.monotonic() < deadline, 'Production session readiness timed out')
                    time.sleep(.2)
                (child / 'request-stop').touch()
            process.wait(timeout=args.timeout_seconds)
        except BaseException:
            (child / 'request-stop').touch()
            try:
                process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    result = load(child / 'runtime-result.json')
    need(process.returncode == 0 and result['status'] == 'passed' and result['normalExit'],
         'G6-A formal production session failed')
    save(run / 'production-result.json', dict(task='G6-A05', status='passed',
         stageQualified=True, pointerSHA256=digest(ARTIFACTS / 'current.json'),
         sessionRunId=child_id, runtimeSHA256=digest(child / 'runtime-result.json'), normalExit=True))
    return dict(status='passed', stageQualified=True, normalExit=True,
                segments=result['segments'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('qualify', 'confirm', 'publish', 'run'), required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build')
    parser.add_argument('--a01')
    parser.add_argument('--a02')
    parser.add_argument('--a03')
    parser.add_argument('--a04-reset')
    parser.add_argument('--a04-fault')
    parser.add_argument('--a05-http')
    parser.add_argument('--a05-browser')
    parser.add_argument('--qualification-run-id')
    parser.add_argument('--review-run-id')
    parser.add_argument('--normal-exit-run-id')
    parser.add_argument('--decision', choices=('approve', 'reject'))
    parser.add_argument('--note')
    parser.add_argument('--mode', choices=('Gui', 'Headless'), default='Gui')
    parser.add_argument('--timeout-seconds', type=int, default=28800)
    parser.add_argument('--auto-stop', action='store_true')
    args = parser.parse_args()
    need(re.fullmatch(r'g6-a05-(qualify|confirm|publish)-[a-z0-9-]+', args.run_id)
         if args.action != 'run' else re.fullmatch(r'g6-control-[a-z0-9-]+', args.run_id),
         'Invalid G6-A run identity')
    run = RUNS / args.run_id
    need(not run.exists(), 'Run identity already exists')
    run.mkdir(parents=True)
    record = dict(task='G6-A05', action=args.action, status='running', runId=args.run_id,
                  stageQualified=False)
    try:
        action = {'qualify': qualify, 'confirm': confirm, 'publish': publish,
                  'run': production}[args.action]
        record.update(action(run, args))
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr, flush=True)
        return 1
    finally:
        save(run / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())

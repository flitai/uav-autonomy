"""Build, qualify, and publish the workspace-bound G6-B08 combination."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'out/runs'
BUILDS = ROOT / 'out/build/g6-stage'
ARTIFACTS = ROOT / 'out/artifacts/g6-stage'
PARENTS = {
    'g5': ROOT / 'out/artifacts/g5-stage/current.json',
    'g6a': ROOT / 'out/artifacts/g6-control/current.json',
    'b07': RUNS / 'g6-b07-acceptance-20261009-final/acceptance.json',
    'b07Build': RUNS / 'g6-b07-build-20261009-09/result.json',
}
SOURCE_DIRS = ('scripts/g6_stage', 'tests/g6_stage')


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def files(directory):
    return [dict(path=p.relative_to(directory).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
            for p in sorted(directory.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]


def sources():
    result = []
    for name in SOURCE_DIRS:
        directory = ROOT / name
        result += [dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p))
                   for p in sorted(directory.rglob('*'))
                   if p.is_file() and '__pycache__' not in p.parts]
    return result


def parents():
    g5, g6a, b07, build = (load(PARENTS[key]) for key in PARENTS)
    need(g5['stageQualified'] and g6a['stageQualified'] and
         b07['status'] == 'passed' and b07['lifecycleQualified'] and
         b07['buildRunId'] == 'g6-b07-build-20261009-09' and
         build['status'] == 'passed' and build['task'] == 'G6-B07',
         'G5/G6-A/B07 parent qualification differs')
    need(sha(Path(g5['package']) / 'manifest.json') == g5['manifestSHA256'] and
         sha(Path(g6a['package']) / 'manifest.json') == g6a['manifestSHA256'],
         'Formal parent manifest differs')
    return {key: sha(path) for key, path in PARENTS.items()}


def check_files(base, rows):
    need(files(base) == rows, 'Packaged viewer files changed')


def build(run_id):
    binding = parents()
    source = ROOT / 'out/build/g6-lifecycle/g6-b07-build-20261009-09/project/dist'
    need((source / 'index.html').is_file(), 'B07 viewer dist missing')
    stage = BUILDS / run_id
    need(not stage.exists(), 'Stage build exists')
    package = stage / 'package'
    package.mkdir(parents=True)
    shutil.copytree(source, package / 'dist')
    service = load(ROOT / 'out/build/g6-lifecycle/g6-b07-build-20261009-09/service.json')
    service['dist'] = str(package / 'dist')
    service['project'] = str(package)
    save(package / 'service.json', service)
    inventory = files(package / 'dist')
    need(len(inventory) > 100, 'Incomplete viewer package')
    manifest = dict(task='G6-B08', status='candidate', buildRunId=run_id,
                    b07BuildRunId='g6-b07-build-20261009-09', parentSHA256=binding,
                    sourceFiles=sources(), distFiles=inventory,
                    serviceSHA256=sha(package / 'service.json'),
                    fileCount=len(inventory), totalBytes=sum(row['bytes'] for row in inventory),
                    resourceBinding=dict(vector=service['vector'], heightfield=service['heightfield']))
    save(stage / 'manifest.json', manifest)
    save(RUNS / run_id / 'result.json', dict(task='G6-B08', status='passed',
         action='build', stageQualified=False, candidate=str(stage),
         manifestSHA256=sha(stage / 'manifest.json'), fileCount=len(inventory),
         totalBytes=manifest['totalBytes']))
    return stage


def check_candidate(run_id, full_resources=False):
    need(re.fullmatch(r'g6-b08-build-[a-z0-9-]+', run_id), 'Invalid build identity')
    stage = BUILDS / run_id
    result = load(RUNS / run_id / 'result.json')
    need(result['status'] == 'passed' and result['task'] == 'G6-B08' and
         result['candidate'] == str(stage) and
         sha(stage / 'manifest.json') == result['manifestSHA256'],
         'B08 candidate receipt differs')
    manifest = load(stage / 'manifest.json')
    need(manifest['buildRunId'] == run_id and manifest['parentSHA256'] == parents() and
         manifest['sourceFiles'] == sources(), 'B08 parent or source changed')
    package = stage / 'package'
    check_files(package / 'dist', manifest['distFiles'])
    need(sha(package / 'service.json') == manifest['serviceSHA256'],
         'B08 service config changed')
    service = load(package / 'service.json')
    need(Path(service['dist']).resolve() == (package / 'dist').resolve() and
         Path(service['project']).resolve() == package.resolve() and
         service['vector'] == manifest['resourceBinding']['vector'] and
         service['heightfield'] == manifest['resourceBinding']['heightfield'],
         'B08 service resource binding differs')
    vector = Path(service['vector']['path'])
    need(vector.is_file() and vector.stat().st_size == service['vector']['bytes'] and
         str(vector.stat().st_mtime_ns) == str(service['vector']['modifiedNs']),
         'B08 external vector identity changed')
    heightfield = Path(service['heightfield']['path'])
    need(heightfield.is_file() and sha(heightfield) == service['heightfield']['sha256'],
         'B08 external heightfield changed')
    if full_resources:
        need(sha(vector) == service['vector']['sha256'],
             'B08 external vector content changed')
    return stage / 'package'


def receipt(run_id, filename, task):
    need(re.fullmatch(r'[a-z0-9-]+', run_id), 'Invalid receipt identity')
    path = RUNS / run_id / filename
    value = load(path)
    need(value['status'] == 'passed' and value['task'] == task,
         'Failed receipt: ' + str(path))
    return dict(runId=run_id, path=str(path.relative_to(ROOT)), sha256=sha(path))


def qualify(run_id, args):
    package = check_candidate(args.build_run_id)
    cases = {}
    for label in ('headless', 'gui'):
        session_id = getattr(args, label + '_session')
        browser_id = getattr(args, label + '_browser')
        audit_id = getattr(args, label + '_audit')
        session = receipt(session_id, 'runtime-result.json', 'G6-B08')
        browser = receipt(browser_id, 'result.json', 'G6-B08')
        audit = receipt(audit_id, 'result.json', 'G6-B08')
        run = load(ROOT / session['path'])
        page = load(ROOT / browser['path'])
        stats = load(ROOT / audit['path'])
        need(run['normalExit'] and all(case['status'] == 'passed' and
             case['normalExit'] and case['portsReleased'] for case in run['cases']) and
             run['b08StageBuildRunId'] == args.build_run_id and
             page['mode'] == ('parallel' if label == 'headless' else 'sequence') and
             len(page['receipt']['tasks']) == 3 and stats['sessionRunId'] == session_id and
             stats['browserRunId'] == browser_id and stats['replayMatches'],
             'B08 combined case differs: ' + label)
        cases[label] = dict(session=session, browser=browser, audit=audit)
    qualification = dict(task='G6-B08', status='passed', action='qualify',
                         stageQualified=False, manualReview='pending',
                         buildRunId=args.build_run_id,
                         buildManifestSHA256=sha(package.parent / 'manifest.json'),
                         parentSHA256=parents(), sourceFiles=sources(), cases=cases)
    path = RUNS / run_id / 'acceptance.json'
    save(path, qualification)
    return dict(status='passed', qualificationSHA256=sha(path),
                stageQualified=False, manualReview='pending')


def check_qualification(run_id):
    path = RUNS / run_id / 'acceptance.json'
    value = load(path)
    need(value['task'] == 'G6-B08' and value['status'] == 'passed' and
         value['manualReview'] == 'pending' and not value['stageQualified'] and
         value['parentSHA256'] == parents() and value['sourceFiles'] == sources(),
         'B08 automatic qualification changed')
    package = check_candidate(value['buildRunId'])
    need(sha(package.parent / 'manifest.json') == value['buildManifestSHA256'],
         'B08 candidate changed after qualification')
    for case in value['cases'].values():
        for row in case.values():
            need(sha(ROOT / row['path']) == row['sha256'], 'B08 receipt changed')
    return value, sha(path)


def confirm(run_id, args):
    qualified, qualification_sha = check_qualification(args.qualification_run_id)
    review = RUNS / args.review_session
    ready = load(review / 'b07-session-ready.json')
    runtime = load(review / 'runtime-result.json')
    need(ready['mode'] == 'Gui' and runtime['status'] == 'passed' and
         runtime['normalExit'] and runtime['b08StageBuildRunId'] == qualified['buildRunId'],
         'Current GUI review session did not close normally')
    decision = dict(task='G6-B08', decision=args.decision,
                    source='current user visual review', reviewSession=args.review_session,
                    reviewRuntimeSHA256=sha(review / 'runtime-result.json'),
                    qualificationRunId=args.qualification_run_id,
                    qualificationSHA256=qualification_sha,
                    recordedAtMs=int(time.time() * 1000), note=args.note or '')
    need(args.decision in ('approve', 'reject'), 'Explicit current review decision required')
    need(not (review / 'manual-confirmation.json').exists(), 'Review was already decided')
    save(review / 'manual-confirmation.json', decision)
    save(RUNS / run_id / 'confirmation-result.json', dict(task='G6-B08', status='passed',
         decision=args.decision, confirmationSHA256=sha(review / 'manual-confirmation.json')))
    return dict(status='passed', decision=args.decision)


def publish(run_id, args):
    qualified, qualification_sha = check_qualification(args.qualification_run_id)
    review = RUNS / args.review_session
    decision = load(review / 'manual-confirmation.json')
    runtime = load(review / 'runtime-result.json')
    need(decision['decision'] == 'approve' and
         decision['source'] == 'current user visual review' and
         decision['reviewSession'] == args.review_session and
         decision['reviewRuntimeSHA256'] == sha(review / 'runtime-result.json') and
         decision['qualificationRunId'] == args.qualification_run_id and
         decision['qualificationSHA256'] == qualification_sha and
         runtime['status'] == 'passed' and runtime['normalExit'],
         'B08 current GUI review or normal exit differs')
    source = check_candidate(qualified['buildRunId'], full_resources=True)
    package = ARTIFACTS / run_id
    need(not package.exists(), 'Publication ID already exists')
    package.mkdir(parents=True)
    shutil.copytree(source / 'dist', package / 'dist')
    service = load(source / 'service.json')
    service['dist'] = str(package / 'dist')
    service['project'] = str(package)
    save(package / 'service.json', service)
    candidate = load(source.parent / 'manifest.json')
    check_files(package / 'dist', candidate['distFiles'])
    manifest = dict(task='G6-B08', stageQualified=True,
                    packageKind='workspace-bound-combination', publishRunId=run_id,
                    qualificationRunId=args.qualification_run_id,
                    qualificationSHA256=qualification_sha,
                    reviewSession=args.review_session,
                    confirmationSHA256=sha(review / 'manual-confirmation.json'),
                    reviewRuntimeSHA256=sha(review / 'runtime-result.json'),
                    buildRunId=qualified['buildRunId'],
                    buildManifestSHA256=qualified['buildManifestSHA256'],
                    parentSHA256=parents(), sourceFiles=sources(),
                    distFiles=candidate['distFiles'], serviceSHA256=sha(package / 'service.json'))
    save(package / 'manifest.json', manifest)
    acceptance = dict(task='G6-B08', status='passed', stageQualified=True,
                      package=str(package), manifestSHA256=sha(package / 'manifest.json'),
                      qualificationSHA256=qualification_sha,
                      confirmationSHA256=manifest['confirmationSHA256'])
    save(RUNS / run_id / 'acceptance.json', acceptance)
    pointer = ARTIFACTS / 'current.json'
    temporary = ARTIFACTS / (run_id + '.pointer.tmp')
    save(temporary, dict(task='G6-B08', stageQualified=True, package=str(package),
         publishRunId=run_id, manifestSHA256=acceptance['manifestSHA256'],
         acceptanceSHA256=sha(RUNS / run_id / 'acceptance.json')))
    os.replace(temporary, pointer)
    return dict(status='passed', stageQualified=True, package=str(package))


def resolve():
    pointer = load(ARTIFACTS / 'current.json')
    need(pointer['task'] == 'G6-B08' and pointer['stageQualified'],
         'B08 formal pointer unavailable')
    package = Path(pointer['package']).resolve()
    need(package.is_relative_to(ARTIFACTS.resolve()) and
         sha(package / 'manifest.json') == pointer['manifestSHA256'] and
         sha(RUNS / pointer['publishRunId'] / 'acceptance.json') == pointer['acceptanceSHA256'],
         'B08 publication changed')
    manifest = load(package / 'manifest.json')
    need(manifest['stageQualified'] and manifest['parentSHA256'] == parents() and
         manifest['sourceFiles'] == sources() and
         sha(package / 'service.json') == manifest['serviceSHA256'],
         'B08 formal sources changed')
    check_files(package / 'dist', manifest['distFiles'])
    return pointer, manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('build', 'qualify', 'confirm', 'publish', 'resolve'), required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--build-run-id')
    for label in ('headless', 'gui'):
        for kind in ('session', 'browser', 'audit'):
            parser.add_argument('--' + label + '-' + kind)
    parser.add_argument('--qualification-run-id')
    parser.add_argument('--review-session')
    parser.add_argument('--decision', choices=('approve', 'reject'))
    parser.add_argument('--note')
    args = parser.parse_args()
    if args.action == 'resolve':
        pointer, _ = resolve()
        print(json.dumps(pointer, ensure_ascii=False))
        return 0
    need(args.run_id and re.fullmatch(r'g6-b08-(build|qualify|confirm|publish)-[a-z0-9-]+',
         args.run_id) and args.run_id.startswith('g6-b08-' + args.action + '-'),
         'Invalid B08 action identity')
    run = RUNS / args.run_id
    need(not run.exists(), 'Action run ID already exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B08', action=args.action, runId=args.run_id,
                  status='running', stageQualified=False)
    try:
        if args.action == 'build':
            stage = build(args.run_id)
            record.update(status='passed', candidate=str(stage))
        else:
            record.update({'qualify': qualify, 'confirm': confirm,
                           'publish': publish}[args.action](args.run_id, args))
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr)
        return 1
    finally:
        save(run / 'action-result.json', record)


if __name__ == '__main__':
    sys.exit(main())

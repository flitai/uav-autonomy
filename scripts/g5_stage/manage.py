"""Build, qualify, review, publish and consume the local G5 stage package."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g5_stage_common', Path(__file__).with_name('common.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

def build(run, args, parents):
    package = c.package_dir(args.build_run_id)
    c.need(not package.exists(), 'Stage build identity already exists')
    package.mkdir(parents=True)
    source = parents['candidate']
    service = parents['service']
    shutil.copytree(source/'project/dist', package/'dist')
    (package/'terrain').mkdir()
    shutil.copy2(service['heightfield']['path'], package/'terrain/cesium-heightfield.f32')
    (package/'vector').mkdir()
    os.link(service['vector']['path'], package/'vector/planet.pmtiles')
    for name in ('g5_map/server.mjs', 'g5_map/terrain.mjs', 'g5_coverage/server.mjs'):
        destination = package/'scripts'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/'scripts'/name, destination)
    config = dict(service, dist='dist', project='.',
                  vector=dict(service['vector'], path='vector/planet.pmtiles'),
                  heightfield=dict(service['heightfield'], path='terrain/cesium-heightfield.f32'))
    c.save(package/'config.json', config)
    for relative in ('dist/cesium', 'dist/fonts/NotoSansCJKsc-Regular.otf',
                     'dist/fonts/OFL.txt', 'dist/licenses/LICENSE.md',
                     'dist/entities/ucav.glb', 'dist/entities/texture-0.png'):
        c.need((package/relative).exists(), 'Local package dependency missing: '+relative)
    c.need(c.sha(package/'vector/planet.pmtiles') == service['vector']['sha256'],
           'Global vector full digest differs')
    records = c.base.inventory(package, [p for p in package.rglob('*')
                                         if p.is_file() and p.name != 'planet.pmtiles'])
    stat = (package/'vector/planet.pmtiles').stat()
    manifest = dict(task='G5-T11', buildRunId=args.build_run_id, status='candidate',
                    inputs=c.sources(), parentBinding=parents['binding'],
                    coverageCandidateSHA256=parents['candidateSHA256'], parents=parents['parents'],
                    files=records, vector=dict(sourcePath=service['vector']['path'],
                                               bytes=stat.st_size, modifiedNs=stat.st_mtime_ns,
                                               sha256=service['vector']['sha256'], hardlinked=True),
                    stageQualified=False)
    c.save(package/'manifest.json', manifest)
    c.verify_package(args.build_run_id, full_vector=False)
    c.save(run/'build-result.json', dict(status='passed', package=str(package),
                                         manifestSHA256=c.sha(package/'manifest.json'),
                                         fileCount=len(records)+1, vectorBytes=stat.st_size))
    return package, manifest

def check_build(run, args, parents, full_vector=False):
    package, manifest = c.verify_package(args.build_run_id, full_vector=full_vector)
    c.need(manifest['inputs'] == c.sources() and
           manifest['parentBinding'] == parents['binding'] and
           manifest['coverageCandidateSHA256'] == parents['candidateSHA256'] and
           manifest['parents'] == parents['parents'], 'Stage source or parent receipts changed')
    build_run = ROOT/'out/runs'/args.build_run_id
    c.need(c.load(build_run/'result.json')['status'] == 'passed' and
           c.load(build_run/'entry-result.json')['status'] == 'passed' and
           c.load(build_run/'build-result.json')['manifestSHA256'] == c.sha(package/'manifest.json'),
           'Stage build receipt differs')
    return package, manifest

def qualification(run, args, parents):
    package, manifest = check_build(run, args, parents, full_vector=True)
    service_dir = run/'service';service_dir.mkdir()
    service = c.service_for(package, service_dir/'service.json')
    checks = c.module('g5_stage_map_checks', ROOT/'tests/g5_map/checks.py')
    node = ROOT/c.load(ROOT/'.tools/g5/current.json')['path']/'node/node.exe'
    for port in (8080, 9223):checks.exclusive_port(port).close()
    output = run/'map-service'
    with checks.running([node, package/'scripts/g5_coverage/server.mjs',
                         service_dir/'service.json', output, run/'coverage/live.json'], output):
        http = checks.http_checks(service)
        browser = ROOT/c.load(ROOT/'.tools/g4/current.json')['path']/'Scripts/python.exe'
        c.base.invoke([browser, '-I', '-B', '-X', 'utf8', ROOT/'tests/g5_map/map_browser.py',
                       '--url', 'http://127.0.0.1:8080/', '--output', run/'browser', '--quick'],
                      run, 'offline-browser', timeout=240)
        browser_result = c.load(run/'browser/result.json')
        c.need(browser_result['status'] == 'passed' and browser_result['exitCode'] == 0 and
               not browser_result['forcedTermination'], 'Packaged browser smoke failed')
        for path in ('/fonts/OFL.txt',
                     '/licenses/LICENSE.md', '/entities/ucav.glb', '/entities/texture-0.png'):
            code, headers, body = checks.request('http://127.0.0.1:8080'+path)
            c.need(code == 200 and body, 'Packaged resource failed: '+path)
        code, headers, body = checks.request('http://127.0.0.1:8080/fonts/NotoSansCJKsc-Regular.otf', method='HEAD')
        c.need(code == 200 and int(headers['Content-Length']) ==
               (package/'dist/fonts/NotoSansCJKsc-Regular.otf').stat().st_size and not body,
               'Packaged Noto font failed')
        c.need(checks.request('http://127.0.0.1:8080/api/coverage/v1/snapshot')[0] == 503,
               'Coverage endpoint should be unavailable without live backend')
    c.need(c.load(output/'lifecycle.json')['normalExit'], 'Packaged service did not exit normally')
    c.need(manifest['inputs'] == c.sources(), 'Stage inputs changed during validation')
    receipt = dict(task='G5-T11', status='passed', action='qualify', buildRunId=args.build_run_id,
                   manifestSHA256=c.sha(package/'manifest.json'), inputs=manifest['inputs'],
                   parentBinding=manifest['parentBinding'], parents=manifest['parents'],
                   frontEndQualified=True, geographyQualified=True, runtimeEntryQualified=True,
                   packageQualified=True, stageQualified=False, manualReview='pending',
                   resourceChecks=http, browser=dict(status='passed',
                      renderer=browser_result.get('initial', {}).get('renderer')))
    c.save(run/'acceptance.json', receipt)
    return package, receipt

def check_qualification(args, parents):
    package, manifest = check_build(ROOT/'out/runs'/args.run_id, args, parents)
    validation = ROOT/'out/runs'/args.qualification_run_id
    receipt = c.load(validation/'acceptance.json')
    c.need(receipt['task'] == 'G5-T11' and receipt['status'] == 'passed' and
           receipt['action'] == 'qualify' and receipt['buildRunId'] == args.build_run_id and
           receipt['manifestSHA256'] == c.sha(package/'manifest.json') and
           receipt['inputs'] == c.sources() and receipt['parents'] == manifest['parents'] and
           all(receipt[x] for x in ('frontEndQualified', 'geographyQualified',
                                   'runtimeEntryQualified', 'packageQualified')),
           'Stage qualification differs')
    for name in ('result.json', 'entry-result.json'):
        c.need(c.load(validation/name)['status'] == 'passed', 'Stage qualification entry failed')
    c.need(c.load(validation/'result.json')['acceptanceSHA256'] == c.sha(validation/'acceptance.json'),
           'Stage qualification receipt hash differs')
    return package, receipt

def review(run, args, parents):
    package, qualified = check_qualification(args, parents)
    service_dir = run/'package-service';service_dir.mkdir()
    c.service_for(package, service_dir/'service.json')
    context = dict(binding=parents['binding'], inputs=c.coverage.sources(),
                   baselineRunId=args.baseline_run_id, configuration=str(ROOT/'config/g3-startup.json'),
                   javaHome=str(ROOT/'.tools/jdk-11.0.32.1+1'),
                   terrainCandidate=str(parents['backend']),
                   terrainCandidateSHA256=c.sha(parents['backend']/'candidate.json'),
                   buildRunId=parents['backend'].name, entityCandidate=str(parents['candidate']),
                   stateCandidate=str(service_dir), stagePackage=str(package))
    c.save(run/'context.json', context)
    c.save(run/'review-meta.json', dict(task='G5-T11', status='awaiting-gui',
           buildRunId=args.build_run_id, manifestSHA256=qualified['manifestSHA256'],
           qualificationRunId=args.qualification_run_id,
           qualificationSHA256=c.sha(ROOT/'out/runs'/args.qualification_run_id/'acceptance.json'),
           url='http://127.0.0.1:8080/', stopFile=str(run/'request-stop')))
    process = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                 str(ROOT/'scripts/g5_stage/session.py'), '--run-id', args.run_id],
                 cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
    result = c.load(run/'runtime-result.json')
    c.need(process.returncode == 0 and result['status'] == 'passed', 'Stage review session failed')
    confirmation = c.load(run/'manual-confirmation.json')
    c.need(confirmation['decision'] == 'approve' and confirmation['runId'] == args.run_id and
           confirmation['manifestSHA256'] == qualified['manifestSHA256'],
           'Current page was not approved')
    c.need((run/'session-ready.json').exists() and (run/'session-paused.json').exists(),
           'Current real session did not finish normally')
    c.need(qualified['inputs'] == c.sources(), 'Stage sources changed during review')
    c.save(run/'review-acceptance.json', dict(task='G5-T11', status='passed',
           buildRunId=args.build_run_id, qualificationRunId=args.qualification_run_id,
           manifestSHA256=qualified['manifestSHA256'], confirmation=confirmation,
           runtimeResultSHA256=c.sha(run/'runtime-result.json'), normalExit=True))

def confirm(run, args):
    target = ROOT/'out/runs'/args.review_run_id
    meta = c.load(target/'review-meta.json')
    ready = c.load(target/'session-ready.json')
    c.need(meta['status'] == 'awaiting-gui' and ready['runId'] == args.review_run_id and
           (target/'session-paused.json').exists(), 'Review page is not ready and paused')
    c.need(not (target/'manual-confirmation.json').exists(), 'Review already decided')
    c.need(args.decision in ('approve', 'reject'), 'Explicit review decision required')
    c.save(target/'manual-confirmation.json', dict(decision=args.decision,
           runId=args.review_run_id, manifestSHA256=meta['manifestSHA256'],
           source='current user visual review', recordedAt=time.time(), note=args.note or ''))
    (target/'request-stop').touch()
    c.save(run/'confirmation-result.json', dict(status='passed', decision=args.decision,
                                                reviewRunId=args.review_run_id))

def publish(run, args, parents):
    package, qualified = check_qualification(args, parents)
    review_dir = ROOT/'out/runs'/args.review_run_id
    review_receipt = c.load(review_dir/'review-acceptance.json')
    c.need(review_receipt['status'] == 'passed' and review_receipt['normalExit'] and
           review_receipt['manifestSHA256'] == qualified['manifestSHA256'] and
           review_receipt['qualificationRunId'] == args.qualification_run_id and
           c.load(review_dir/'result.json')['status'] == 'passed' and
           c.load(review_dir/'runtime-result.json')['status'] == 'passed' and
           c.load(review_dir/'entry-result.json')['status'] == 'passed',
           'Current review and normal exit not qualified')
    c.verify_package(args.build_run_id, qualified['manifestSHA256'], full_vector=True)
    artifact = ROOT/'out/artifacts/g5-stage'/args.build_run_id/args.run_id
    c.need(not artifact.exists(), 'Stage publication identity already exists')
    artifact.parent.mkdir(parents=True, exist_ok=True)
    # Copy small files and hardlink the qualified local PMTiles archive.
    shutil.copytree(package, artifact, ignore=shutil.ignore_patterns('planet.pmtiles'))
    os.link(package/'vector/planet.pmtiles', artifact/'vector/planet.pmtiles')
    c.need(c.sha(artifact/'manifest.json') == qualified['manifestSHA256'], 'Published manifest differs')
    c.base.verify_files(artifact, c.load(artifact/'manifest.json')['files'])
    c.need(os.path.samefile(package/'vector/planet.pmtiles', artifact/'vector/planet.pmtiles'),
           'Published vector hardlink differs')
    receipt = dict(task='G5-T11', status='passed', stageQualified=True,
                   buildRunId=args.build_run_id, qualificationRunId=args.qualification_run_id,
                   reviewRunId=args.review_run_id, manifestSHA256=qualified['manifestSHA256'],
                   qualificationSHA256=c.sha(ROOT/'out/runs'/args.qualification_run_id/'acceptance.json'),
                   reviewSHA256=c.sha(review_dir/'review-acceptance.json'), package=str(artifact))
    c.save(run/'acceptance.json', receipt)
    pointer = ROOT/'out/artifacts/g5-stage/current.json'
    old = c.load(pointer) if pointer.exists() else None
    if old:c.save(run/'previous-pointer.json', old)
    c.save(pointer, dict(task='G5-T11', stageQualified=True, buildRunId=args.build_run_id,
                         publishRunId=args.run_id, package=str(artifact),
                         manifestSHA256=qualified['manifestSHA256'],
                         acceptanceSHA256=c.sha(run/'acceptance.json')))
    c.save(run/'publish-result.json', dict(status='passed', pointer=str(pointer), package=str(artifact)))

def production(run, args, parents):
    package, qualified = check_qualification(args, parents)
    pointer_file = ROOT/'out/artifacts/g5-stage/current.json'
    pointer = c.load(pointer_file)
    published = (ROOT/pointer['package']).resolve() if not Path(pointer['package']).is_absolute() else Path(pointer['package']).resolve()
    c.need(published.is_relative_to((ROOT/'out/artifacts/g5-stage').resolve()) and
           pointer['task'] == 'G5-T11' and pointer['stageQualified'] and
           pointer['buildRunId'] == args.build_run_id and
           pointer['manifestSHA256'] == qualified['manifestSHA256'] and
           c.sha(published/'manifest.json') == qualified['manifestSHA256'],
           'Formal stage pointer differs')
    publication = ROOT/'out/runs'/pointer['publishRunId']
    c.need(c.sha(publication/'acceptance.json') == pointer['acceptanceSHA256'] and
           c.load(publication/'result.json')['status'] == 'passed' and
           c.load(publication/'entry-result.json')['status'] == 'passed',
           'Formal stage publication receipt differs')
    manifest = c.load(published/'manifest.json')
    c.base.verify_files(published, manifest['files'])
    c.need(os.path.samefile(published/'vector/planet.pmtiles', package/'vector/planet.pmtiles'),
           'Formal stage vector identity differs')
    service_dir = run/'package-service';service_dir.mkdir()
    c.service_for(published, service_dir/'service.json')
    context = dict(binding=parents['binding'], inputs=c.coverage.sources(),
                   baselineRunId=args.baseline_run_id, configuration=str(ROOT/'config/g3-startup.json'),
                   javaHome=str(ROOT/'.tools/jdk-11.0.32.1+1'),
                   terrainCandidate=str(parents['backend']),
                   terrainCandidateSHA256=c.sha(parents['backend']/'candidate.json'),
                   buildRunId=parents['backend'].name, entityCandidate=str(parents['candidate']),
                   stateCandidate=str(service_dir), stagePackage=str(published))
    c.save(run/'context.json', context)
    command = [sys.executable, '-I', '-B', '-X', 'utf8',
               str(ROOT/'scripts/g5_stage/session.py'), '--run-id', args.run_id]
    process = subprocess.Popen(command, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        if args.auto_stop:
            deadline = time.monotonic()+1800
            while not (run/'session-paused.json').exists():
                c.need(process.poll() is None, 'Formal session exited before pause')
                c.need(time.monotonic() < deadline, 'Formal session pause timeout')
                time.sleep(.2)
            (run/'request-stop').touch()
        process.wait(timeout=2700)
    except BaseException:
        (run/'request-stop').touch()
        try:process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill();process.wait()
        raise
    result = c.load(run/'runtime-result.json')
    c.need(process.returncode == 0 and result['status'] == 'passed' and
           (run/'session-ready.json').exists() and (run/'session-paused.json').exists(),
           'Formal production session failed')
    c.need(qualified['inputs'] == c.sources(), 'Stage sources changed during formal run')
    c.save(run/'production-result.json', dict(status='passed', stageQualified=True,
           pointerSHA256=c.sha(pointer_file), publicationSHA256=c.sha(publication/'acceptance.json'),
           runtimeSHA256=c.sha(run/'runtime-result.json'), normalExit=True))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('build', 'qualify', 'review', 'confirm', 'publish', 'run'), required=True)
    parser.add_argument('--run-id', required=True)
    for name in ('baseline-run-id', 'coverage-build-run-id', 'full-run-id', 'scale-run-id',
                 'qualification-run-id', 'review-run-id', 'stage-build-run-id'):
        parser.add_argument('--'+name)
    parser.add_argument('--decision', choices=('approve', 'reject'))
    parser.add_argument('--note')
    parser.add_argument('--auto-stop', action='store_true')
    args = parser.parse_args()
    args.build_run_id = args.run_id if args.action == 'build' else args.stage_build_run_id
    run = ROOT/'out/runs'/args.run_id
    run.mkdir(parents=True, exist_ok=True)
    before = dict(os.environ); location = Path.cwd()
    record = dict(task='G5-T11', runId=args.run_id, action=args.action,
                  status='running', stageQualified=False)
    try:
        if args.action == 'confirm':confirm(run, args)
        else:
            parents = c.parents(args.baseline_run_id, args.coverage_build_run_id,
                                args.full_run_id, args.scale_run_id)
            if args.action == 'build':build(run, args, parents)
            elif args.action == 'qualify':
                _, receipt = qualification(run, args, parents)
                record['acceptanceSHA256'] = c.sha(run/'acceptance.json')
            elif args.action == 'review':review(run, args, parents)
            elif args.action == 'publish':publish(run, args, parents)
            else:production(run, args, parents)
        record['status'] = 'passed'
        if args.action in ('publish', 'run'):record['stageQualified'] = True
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], flush=True)
        return 1
    finally:
        record.update(environmentUnchanged=before == dict(os.environ),
                      locationUnchanged=location == Path.cwd())
        if not record['environmentUnchanged'] or not record['locationUnchanged']:
            record['status'] = 'failed'
        c.save(run/'result.json', record)
        print('G5_T11_RESULT='+str(run/'result.json'), flush=True)

if __name__ == '__main__':sys.exit(main())

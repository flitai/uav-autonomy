"""Run a local G6-A candidate session; reset restarts the owned backend group."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import browser_probe

c = browser_probe.c
state = browser_probe.state


def context_for(run, viewer_build):
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('g6_a_stage', ROOT / 'scripts/g5_stage/common.py')
    stage = module_from_spec(spec)
    spec.loader.exec_module(stage)
    pointer_file = ROOT / 'out/artifacts/g5-stage/current.json'
    pointer = c.load(pointer_file)
    c.need(pointer['task'] == 'G5-T11' and pointer['stageQualified'], 'Formal G5 stage missing')
    package = Path(pointer['package']).resolve()
    c.need(package.is_relative_to((ROOT / 'out/artifacts/g5-stage').resolve()) and
           c.sha(package / 'manifest.json') == pointer['manifestSHA256'], 'Formal G5 pointer differs')
    publication = ROOT / 'out/runs' / pointer['publishRunId']
    c.need(c.sha(publication / 'acceptance.json') == pointer['acceptanceSHA256'] and
           c.load(publication / 'acceptance.json')['stageQualified'], 'Formal G5 acceptance differs')
    _, manifest = stage.verify_package(pointer['buildRunId'], pointer['manifestSHA256'])
    full = c.load(ROOT / 'out/runs' / manifest['parents']['G5-T09']['runId'] / 'acceptance.json')
    c.need(full['candidateSHA256'] == manifest['coverageCandidateSHA256'],
           'Formal G5 coverage candidate differs')
    candidate = ROOT / 'out/build/g5-coverage' / full['buildRunId']
    terrain = ROOT / 'out/build/g5-backend' / manifest['parentBinding']['backendTerrain']['buildRunId']
    viewer = ROOT / 'out/build/g6-control' / viewer_build
    receipt = c.load(ROOT / 'out/runs' / viewer_build / 'result.json')
    c.need(receipt['status'] == 'passed' and receipt['task'] == 'G6-A03' and
           (viewer / 'service.json').is_file(), 'G6 control viewer build missing')
    c.base.verify_files(ROOT, receipt['inputs'])
    c.need(c.sha(terrain / 'candidate.json') == manifest['parentBinding']['backendTerrain']['candidateSHA256'],
           'Formal G5 terrain candidate differs')
    context = dict(binding=manifest['parentBinding'], inputs=stage.coverage.sources(),
                   baselineRunId=manifest['parentBinding']['upstream']['backend']['baselineRunId'],
                   configuration=str(ROOT / 'config/g3-startup.json'),
                   javaHome=str(ROOT / '.tools/jdk-11.0.32.1+1'), terrainCandidate=str(terrain),
                   terrainCandidateSHA256=c.sha(terrain / 'candidate.json'), buildRunId=terrain.name,
                   entityCandidate=str(candidate), stateCandidate=str(viewer), stagePackage=str(package))
    c.save(run / 'context.json', context)
    c.save(run / 'source-binding.json', dict(g5PointerSHA256=c.sha(pointer_file),
           stageManifestSHA256=pointer['manifestSHA256'], g5PublicationSHA256=pointer['acceptanceSHA256'],
           viewerBuildRunId=viewer_build, viewerBuildSHA256=c.sha(ROOT / 'out/runs' / viewer_build / 'result.json')))


class SessionRun(browser_probe.BrowserRun):
    def browser_exercise(self, session):
        return self.session_exercise(session)

    def session_exercise(self, session):
        if getattr(self, 'pending_reset', None):
            old = self.pending_reset
            health = self.host.health()
            c.need(session['segmentId'] != old['segmentId'] and
                   session['backendRunId'] != old['backendRunId'] and
                   health['stream_id'] != old['streamId'], 'Reset reused backend identity')
            current = self.amase.events(self.java_dir)
            initialized = next(row for row in current if row['kind'] == 'initialized-paused')
            c.need(float(initialized['simTimeSeconds']) == 0, 'Reset did not return to time zero')
            history = self.run / 'control-reset-receipts'
            history.mkdir(exist_ok=True)
            receipt = dict(key=old['key'], sequence=old['sequence'], action='reset',
                           status='confirmed', submittedAtMs=old['submittedAtMs'],
                           fromRunId=old['runId'], fromSegmentId=old['segmentId'],
                           fromBackendRunId=old['backendRunId'], toSegmentId=session['segmentId'],
                           toBackendRunId=session['backendRunId'], toStreamId=health['stream_id'],
                           newSimulationTimeMs='0')
            c.save(history / (old['key'] + '.json'), receipt)
            code, found = browser_probe.api_probe.http('GET', '/operations/' + old['key'])
            c.need(code == 200 and found == receipt, 'Reset receipt not queryable')
            self.item['resetFrom'] = receipt
            self.pending_reset = None
        ready = dict(runId=session['runId'], segmentId=session['segmentId'],
                     backendRunId=session['backendRunId'], url='http://127.0.0.1:8080/',
                     controlUrl='http://127.0.0.1:8001/', mode=self.mode,
                     stopFile=str(self.run / 'request-stop'))
        c.save(self.run / 'session-ready.json', ready)
        print('G6_CONTROL_SESSION_READY=' + session['runId'] + ' SEGMENT=' + session['segmentId'], flush=True)
        while not (self.run / 'request-stop').exists():
            self.alive()
            if (self.directory / 'request-reset').exists():
                code, rows = browser_probe.api_probe.http('GET', '/operations')
                pending = [row for row in rows['items'] if row['action'] == 'reset' and row['status'] == 'pending']
                c.need(code == 200 and len(pending) == 1, 'Reset marker lacks one pending operation')
                row = pending[0]
                self.pending_reset = dict(key=row['key'], sequence=row['sequence'],
                    submittedAtMs=row['submittedAtMs'], runId=row['runId'], segmentId=row['segmentId'],
                    backendRunId=session['backendRunId'], streamId=self.host.health()['stream_id'])
                self.item['resetRequested'] = self.pending_reset
                self.item['exitReason'] = 'reset'
                return
            time.sleep(.1)
        self.item['exitReason'] = 'stop'

    def audit(self):
        c.need(self.item.get('exitReason') in ('reset', 'stop'), 'Session did not reach requested exit')
        c.base.verify_files(self.java_dir, self.item['runtimeInputs'])
        c.need(not (self.java_dir / 'terrain-error').exists(), 'Terrain error in control session')
        self.item['sessionNormalExit'] = True

    def execute(self):
        self.prepare()
        self.record.update(task='G6-A05', scope='local-control-session-candidate',
                           controlRuntimeQualified=False)
        output = self.run / 'map-service'
        coverage_file = self.run / 'coverage/live.json'
        coverage_file.parent.mkdir()
        with state.services.running([self.node, ROOT / 'scripts/g5_coverage/server.mjs',
                                     self.viewer_service, output, coverage_file], output) as service:
            segment = 0
            while True:
                segment += 1
                c.need(service.poll() is None, 'Control viewer service exited')
                self.operation_deadline = time.monotonic() + 8 * 3600
                result = self.case(f'segment-{segment:03d}', self.args.mode)
                c.need(result['status'] == 'passed', result.get('error', 'Control segment failed'))
                if result['exitReason'] == 'stop':
                    break
                c.need(result['exitReason'] == 'reset' and self.pending_reset,
                       'Reset segment lacks a pending operation')
        c.need(self.inputs() == self.record['inputs'], 'Control session sources changed')
        self.record.update(status='passed', normalExit=True, segments=segment,
                           controlRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    parser.add_argument('--mode', choices=('Headless', 'Gui'), default='Gui')
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    c.need(args.run_id.startswith('g6-control-') and
           all(char.isascii() and (char.isalnum() or char == '-') for char in args.run_id),
           'Invalid G6 control run ID')
    run = ROOT / 'out/runs' / args.run_id
    c.need(not run.exists(), 'G6 control run ID already exists')
    run.mkdir(parents=True)
    context_for(run, args.viewer_build)
    task = SessionRun(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(task.record['traceback'], flush=True)
        return 1
    finally:
        c.save(task.run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())

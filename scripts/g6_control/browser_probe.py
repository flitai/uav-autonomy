"""Candidate G6-A03 real Edge control interaction in both Windows modes."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import api_probe

c = api_probe.c
coverage = c.module('g6_control_coverage_collector', ROOT / 'scripts/g5_coverage/collector.py')
state = api_probe.probe.state


class BrowserRun(api_probe.ApiRun):
    def inputs(self):
        paths = [p for p in (self.root / 'apps/cesium_control').rglob('*') if p.is_file()]
        paths += [p for p in (self.root / 'tests/g6_control').rglob('*') if p.is_file()]
        return super().inputs() + c.base.inventory(self.root, paths)

    def prepare(self):
        super().prepare()
        build = self.root / 'out/runs' / self.args.viewer_build
        candidate = self.root / 'out/build/g6-control' / self.args.viewer_build
        receipt = c.load(build / 'result.json')
        c.need(receipt['status'] == 'passed' and receipt['task'] == 'G6-A03', 'Control viewer candidate unqualified')
        c.base.verify_files(self.root, receipt['inputs'])
        self.viewer_service = candidate / 'service.json'
        c.need(self.viewer_service.is_file() and (candidate / 'project/dist/index.html').is_file(),
               'Control viewer artifact missing')
        self.record.update(task='G6-A03', scope='real-browser-control-candidate',
                           viewerBuildRunId=self.args.viewer_build, viewerBuildSHA256=c.sha(build / 'result.json'),
                           controlViewerQualified=False)

    def files(self, mode, fault):
        self.collector = None
        super().files(mode, fault)

    def handshake(self):
        super().handshake()
        self.collector = coverage.Collector(self.directory / 'gateway-host/manifest.json',
                                            self.prepared, self.run / 'coverage/live.json')
        self.collector.start()

    def browser_exercise(self, session):
        output = self.directory / 'browser'
        with (self.directory / 'browser.stdout').open('wb') as stdout, (self.directory / 'browser.stderr').open('wb') as stderr:
            browser = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'tests/g6_control/browser.py'), '--output', str(output)],
                cwd=self.directory, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        self.browser = browser
        self.wait('real-browser-controls', lambda: browser.poll() is not None, 140)
        c.need(browser.returncode == 0, 'Real Edge controls failed')
        result = c.load(output / 'result.json')
        c.need(result['status'] == 'passed' and len(result['steps']) == 7 and
               result['steps'][-1]['state']['runId'] == session['backendRunId'],
               'Browser control receipt or G4 identity differs')
        code, operations = api_probe.http('GET', '/operations')
        c.need(code == 200 and operations['runId'] == session['runId'] and
               len(operations['items']) == 6 and all(row['status'] == 'confirmed' for row in operations['items']),
               'Browser operations did not receive authoritative confirmation')
        code, final = api_probe.http('GET', '/state')
        c.need(code == 200 and final['simulation']['state'] == 2 and
               final['simulation']['real_time_multiple'] == 0.5, 'Browser final backend status differs')
        self.item['browserEvidence'] = dict(browser=result, operations=operations['items'], finalState=final,
                                            screenshotSHA256=c.sha(output / 'controls.png'))
        degraded_dir = self.directory / 'browser-degraded'
        with (self.directory / 'browser-degraded.stdout').open('wb') as stdout, \
             (self.directory / 'browser-degraded.stderr').open('wb') as stderr:
            degraded = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'tests/g6_control/browser.py'), '--output', str(degraded_dir),
                '--scenario', 'degrade', '--stop-file', str(self.directory / 'control-request-stop')],
                cwd=self.directory, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        self.browser = degraded
        self.wait('control-api-disconnected-browser', lambda: degraded.poll() is not None, 75)
        degradation = c.load(degraded_dir / 'result.json')
        c.need(degraded.returncode == 0 and degradation['status'] == 'passed' and
               len(degradation['steps']) == 2, 'Browser did not disable controls after API disconnect')
        self.item['browserEvidence']['degradation'] = degradation

    def cleanup(self):
        if getattr(self, 'browser', None) is not None and self.browser.poll() is None:
            (self.directory / 'browser/request-stop').touch()
            try:
                self.browser.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.browser.kill()
                self.browser.wait()
                self.item.setdefault('cleanupErrors', []).append('Browser forced termination')
        if self.collector is not None:
            try:
                record = self.collector.stop()
                self.item['coverageCollector'] = record
                if record['status'] != 'passed':
                    self.item.setdefault('cleanupErrors', []).append('Coverage collector failed')
            except Exception as error:
                self.item.setdefault('cleanupErrors', []).append('Coverage collector: ' + str(error))
        super().cleanup()

    def audit(self):
        c.need(len(self.item.get('browserEvidence', {}).get('operations', [])) == 6,
               'Browser control and backend operations missing')
        c.need(self.item['browserEvidence']['finalState']['simulation']['state'] == 2,
               'Final browser pause missing')
        c.need(self.item['browserEvidence']['degradation']['status'] == 'passed',
               'Browser API disconnect not observed')
        c.base.verify_files(self.java_dir, self.item['runtimeInputs'])
        self.item.update(realBrowserControlObserved=True, controlViewerQualified=False)

    def execute(self):
        self.prepare()
        output = self.run / 'map-service'
        coverage_file = self.run / 'coverage/live.json'
        coverage_file.parent.mkdir()
        with state.services.running([self.node, ROOT / 'scripts/g5_coverage/server.mjs',
                                     self.viewer_service, output, coverage_file], output) as service:
            for mode in ('Headless', 'Gui'):
                c.need(service.poll() is None, 'Control viewer service exited')
                self.operation_deadline = time.monotonic() + 450
                result = self.case(mode.lower(), mode)
                c.need(result['status'] == 'passed', result.get('error', 'Browser control case failed'))
        c.need(self.inputs() == self.record['inputs'], 'Control viewer inputs changed')
        self.record.update(status='passed', browserControlObserved=True, controlViewerQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    args.mode = 'Headless'
    task = BrowserRun(args)
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

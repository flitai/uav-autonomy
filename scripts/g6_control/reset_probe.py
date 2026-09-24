"""G6-A04 candidate reset: stop the whole group and start a new run segment."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import api_probe

c = api_probe.c


class ResetRun(api_probe.ApiRun):
    def reset_exercise(self, session):
        code, initial = api_probe.http('GET', '/state')
        c.need(code == 200 and initial['backendRunId'] == session['backendRunId'] and not initial['ready'],
               'New segment was not initialized paused')
        c.need(not any(row['type'] == 'afrl.cmasi.AirVehicleState' for row in self.observer.rows),
               'New segment advanced before start')
        initialized = next(row for row in self.amase.events(self.java_dir)
                           if row['kind'] == 'initialized-paused')
        c.need(float(initialized['simTimeSeconds']) == 0, 'New segment did not return to scenario start')
        if self.item['name'].endswith('-first'):
            key = 'reset-' + self.mode.lower() + '-0001'
            code, started = api_probe.http('POST', '/operations', dict(runId=session['runId'],
                segmentId=session['segmentId'], expectedSequence=initial['controlSequence'],
                idempotencyKey='start-' + self.mode.lower() + '-0001',
                action='start', multiple=None))
            c.need(code in (200, 202), 'First segment start failed')
            self.wait('first-segment-started', lambda: api_probe.http('GET',
                '/operations/start-' + self.mode.lower() + '-0001')[1]['status'] == 'confirmed', 15)
            live = self.host.live()
            c.need(live['run_id'] == session['backendRunId'], 'First segment gateway differs')
            _, current = api_probe.http('GET', '/state')
            code, reset = api_probe.http('POST', '/operations', dict(runId=session['runId'],
                segmentId=session['segmentId'], expectedSequence=current['controlSequence'],
                idempotencyKey=key, action='reset', multiple=None))
            c.need(code == 202 and reset['status'] == 'pending' and
                   (self.directory / 'request-reset').exists(), 'Reset request was not handed to owner')
            self.old_segment = dict(session=session, streamId=live['stream_id'], resetKey=key,
                                    resetOperation=reset)
            self.item['resetRequested'] = self.old_segment
        else:
            old = self.old_segment
            c.need(session['segmentId'] != old['session']['segmentId'] and
                   session['backendRunId'] != old['session']['backendRunId'] and
                   session['amaseProcess'] != old['session']['amaseProcess'],
                   'Reset reused the old group identity')
            health = self.host.health()
            c.need(health['stream_id'] != old['streamId'], 'Reset reused the old G4 stream')
            receipts = self.run / 'control-reset-receipts'
            receipts.mkdir(exist_ok=True)
            receipt = dict(key=old['resetKey'], action='reset', status='confirmed',
                           fromRunId=old['session']['runId'], fromSegmentId=old['session']['segmentId'],
                           fromBackendRunId=old['session']['backendRunId'],
                           toSegmentId=session['segmentId'], toBackendRunId=session['backendRunId'],
                           toStreamId=health['stream_id'], newSimulationTimeMs='0')
            c.save(receipts / (old['resetKey'] + '.json'), receipt)
            code, queried = api_probe.http('GET', '/operations/' + old['resetKey'])
            c.need(code == 200 and queried == receipt, 'Reset result not queryable after restart')
            code, stale = api_probe.http('POST', '/operations', dict(runId=session['runId'],
                segmentId=old['session']['segmentId'], expectedSequence=initial['controlSequence'],
                idempotencyKey='stale-' + self.mode.lower() + '-0001',
                action='start', multiple=None))
            c.need(code == 409, 'Old segment command accepted after reset')
            self.item['resetConfirmed'] = receipt

    def audit(self):
        c.need(self.item.get('resetRequested') or self.item.get('resetConfirmed'),
               'Reset segment evidence missing')
        c.base.verify_files(self.java_dir, self.item['runtimeInputs'])
        self.item.update(groupResetObserved=True, controlRuntimeQualified=False)

    def execute(self):
        self.prepare()
        for mode in ('Headless', 'Gui'):
            for suffix in ('first', 'second'):
                self.operation_deadline = time.monotonic() + 450
                result = self.case(mode.lower() + '-' + suffix, mode)
                c.need(result['status'] == 'passed', result.get('error', 'Reset segment failed'))
        c.need(self.inputs() == self.record['inputs'], 'Reset sources changed')
        self.record.update(status='passed', groupResetObserved=True, controlRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    args.mode = 'Headless'
    task = ResetRun(args)
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

"""Exercise the candidate G6 control HTTP API against real AMASE, UxAS and G4."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import backend_probe as probe

sys.path.insert(0, str(ROOT / 'src'))
from sim_bridge.windows import process_identity

c = probe.c
URL = 'http://127.0.0.1:8001/api/control/v1'


def http(method, path, value=None, origin=True):
    headers = {'Origin': 'http://127.0.0.1:8080'} if origin else {}
    data = None
    if value is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(value).encode('utf-8')
    request = Request(URL + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


class ApiRun(probe.ControlRun):
    def inputs(self):
        return super().inputs() + c.base.inventory(self.root, [self.root / 'apps/g6_control/server.py'])

    def files(self, mode, fault):
        self.control_process = None
        super().files(mode, fault)

    def body(self, mode, fault, keep_gui):
        self.initial_started = time.monotonic()
        self.initial_deadline = self.initial_started + 30
        self.transition('initialization-started', timeoutSeconds=30)
        argv = [self.java, '-Dfile.encoding=UTF-8', '-Djava.awt.headless=true',
                '-Djava.io.tmpdir=' + str(self.java_dir / 'tmp'), '-Duser.home=' + str(self.java_dir / 'home'),
                '-Dg3.integration.directory=' + str(self.java_dir), '-cp', os.pathsep.join(map(str, self.cp)),
                'avtas.app.Application', '--config', self.java_dir / 'config', '--scenario', 'scenario.xml',
                '--sim_rate', '1']
        self.java_process = self.launch(self.java_dir, argv)
        self.wait('amase-paused', lambda: any(e['kind'] == 'initialized-paused'
                  for e in self.amase.events(self.java_dir)))
        startup = probe.backend.mixed.startup
        self.monitor = startup.Stream(startup.protocol.connect(self.ports['amasePort'], self.java_process, 20),
                                      self.directory, 'amase', self.factory)
        self.streams.append(self.monitor)
        self.cpp = self.launch(self.cpp_dir, [self.uxas / 'uxas.exe', '-cfgPath', self.cpp_dir / 'uxas.xml'])
        self.observer = startup.Stream(startup.protocol.connect(self.ports['observerPort'], self.cpp, 20),
                                       self.directory, 'observer', self.factory)
        self.streams.append(self.observer)
        self.handshake()
        c.need(not any(row['type'] == 'afrl.cmasi.AirVehicleState' for row in self.observer.rows),
               'Simulation advanced before start operation')
        session = dict(runId=self.args.run_id, segmentId=self.item['name'] + '-1',
                       backendRunId=self.host.manifest['run_id'], durationMs='1800000',
                       amaseProcess=process_identity(self.java_process.pid), javaDirectory=str(self.java_dir))
        c.save(self.directory / 'control-session.json', session)
        with (self.directory / 'control.stdout').open('wb') as out, (self.directory / 'control.stderr').open('wb') as err:
            self.control_process = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'apps/g6_control/server.py'), '--session', str(self.directory / 'control-session.json')],
                cwd=self.directory, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('control-api-ready', lambda: self.control_process.poll() is not None or self.is_ready(), 15)
        c.need(self.control_process.poll() is None, 'Control API process exited at startup')
        code, state = http('GET', '/state')
        c.need(code == 200 and state['runId'] == session['runId'] and
               state['segmentId'] == session['segmentId'] and state['backendRunId'] == session['backendRunId'],
               'Control state identity differs')
        if hasattr(self, 'browser_exercise'):
            return self.browser_exercise(session)
        if hasattr(self, 'reset_exercise'):
            return self.reset_exercise(session)
        if hasattr(self, 'fault_exercise'):
            return self.fault_exercise(session)
        if hasattr(self, 'session_exercise'):
            return self.session_exercise(session)

        requests = {}
        def body(key, action, multiple=None, run_id=None):
            if key in requests:
                return requests[key]
            status, current = http('GET', '/state')
            c.need(status == 200, 'Control state unavailable before request')
            request = dict(runId=run_id or session['runId'], segmentId=session['segmentId'],
                           expectedSequence=current['controlSequence'],
                           idempotencyKey=key, action=action, multiple=multiple)
            requests[key] = request
            return request

        c.need(http('POST', '/operations', body('without-origin-01', 'pause'), False)[0] == 403,
               'Cross-origin control was accepted')
        c.need(http('POST', '/operations', body('wrong-run-0001', 'pause', run_id='old-run'))[0] == 409,
               'Stale run accepted')
        c.need(http('POST', '/operations', body('invalid-rate-01', 'rate', '500'))[0] == 422,
               'Invalid multiple accepted')
        c.need(http('POST', '/operations', body('early-reset-0001', 'reset'))[0] == 503 and
               not (self.directory / 'request-reset').exists(),
               'Reset before an initialized snapshot was accepted')

        code, started = http('POST', '/operations', body('start-first-0001', 'start'))
        c.need(code in (200, 202) and started['key'] == 'start-first-0001',
               'Initial start request failed')
        def start_confirmed():
            status, result = http('GET', '/operations/start-first-0001')
            c.need(status == 200, 'Start result query failed')
            return result if result['status'] == 'confirmed' else None
        started = self.wait('confirmed-initial-start', start_confirmed, 15)
        snapshot = self.host.live()
        c.need(snapshot['run_id'] == session['backendRunId'], 'Started backend run identity differs')
        self.item['initialData'] = self.wait('all-real-initial-data',
            lambda: self.gate.inspect(list(self.observer.rows), list(self.monitor.rows)))

        evidence = [started]
        competing = body('second-client-0001', 'resume')
        for key, action, multiple in [('pause-first-0001', 'pause', None),
                                      ('rate-two-000001', 'rate', '2'),
                                      ('resume-first-001', 'resume', None),
                                      ('rate-half-00001', 'rate', '0.5'),
                                      ('pause-final-0001', 'pause', None)]:
            code, row = http('POST', '/operations', body(key, action, multiple))
            c.need(code in (200, 202) and row['key'] == key, 'Control POST failed: ' + str((code, row)))
            if key == 'rate-two-000001':
                c.need(row['status'] == 'applied', 'Paused rate should await status feedback')
                evidence.append(row)
                continue
            def confirmed():
                status, result = http('GET', '/operations/' + key)
                c.need(status == 200, 'Control result query failed')
                return result if result['status'] == 'confirmed' else None
            result = self.wait('confirmed-' + key, confirmed, 8)
            evidence.append(result)
            if key == 'pause-first-0001':
                c.need(http('POST', '/operations', competing)[0] == 409,
                       'Concurrent client used a stale control version')
            if key == 'resume-first-001':
                status, earlier_rate = http('GET', '/operations/rate-two-000001')
                c.need(status == 200 and earlier_rate['status'] == 'confirmed',
                       'Paused rate was not confirmed after resume')
                evidence[2] = earlier_rate
        code, duplicate = http('POST', '/operations', body('rate-half-00001', 'rate', '0.5'))
        c.need(code == 200 and duplicate['sequence'] == evidence[4]['sequence'],
               'Idempotent request did not return original result')
        c.need(http('POST', '/operations', dict(body('rate-half-00001', 'rate', '0.5'), action='pause'))[0] == 409,
               'Idempotency key conflict accepted')
        c.need(len(list((self.java_dir / 'results').glob('*.json'))) == 5,
               'API generated an extra AMASE control command')
        c.need(http('GET', '/operations/unknown-operation-0001')[0] == 404,
               'Unknown operation unexpectedly exists')
        code, final = http('GET', '/state')
        c.need(code == 200 and final['simulation']['state'] == 2 and
               final['simulation']['real_time_multiple'] == 0.5, 'Final backend state differs')
        self.item['apiEvidence'] = dict(session=session, operations=evidence, finalState=final,
                                        duplicateSequence=duplicate['sequence'], rawGatewayRunId=snapshot['run_id'])

    def is_ready(self):
        try:
            return http('GET', '/state')[0] == 200
        except Exception:
            return False

    def cleanup(self):
        if self.control_process is not None:
            (self.directory / 'control-request-stop').touch()
            try:
                self.control_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.control_process.kill()
                self.control_process.wait()
                self.item.setdefault('cleanupErrors', []).append('Control API forced termination')
            if self.control_process.returncode != 0:
                self.item.setdefault('cleanupErrors', []).append('Control API abnormal exit')
        super().cleanup()
        self.amase.check_port(8001)

    def audit(self):
        c.need(len(self.item.get('apiEvidence', {}).get('operations', [])) == 6,
               'Confirmed API operations missing')
        c.need(self.item['apiEvidence']['finalState']['simulation']['state'] == 2,
               'Final authoritative pause missing')
        c.base.verify_files(self.java_dir, self.item['runtimeInputs'])
        self.item.update(apiControlCandidateObserved=True, controlRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    args.mode = 'Headless'
    task = ApiRun(args)
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

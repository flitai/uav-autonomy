"""G6-A04 real control fault checks with owned Windows processes."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import api_probe

c = api_probe.c


def lost_reply(request):
    body = json.dumps(request).encode('utf-8')
    headers = (b'POST /api/control/v1/operations HTTP/1.1\r\n'
               b'Host: 127.0.0.1:8001\r\n'
               b'Origin: http://127.0.0.1:8080\r\n'
               b'Content-Type: application/json\r\n'
               + f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode('ascii'))
    with socket.create_connection(('127.0.0.1', 8001), timeout=5) as connection:
        connection.sendall(headers + body)
        # The caller loses the HTTP response after transmitting the complete request.


class FaultRun(api_probe.ApiRun):
    def fault_exercise(self, session):
        code, state = api_probe.http('GET', '/state')
        c.need(code == 200 and not state['ready'], 'Fault segment did not start paused')
        start = dict(runId=session['runId'], segmentId=session['segmentId'],
                     expectedSequence=state['controlSequence'], idempotencyKey='fault-start-0001',
                     action='start', multiple=None)
        c.need(api_probe.http('POST', '/operations', start)[0] in (200, 202), 'Fault segment start failed')
        self.wait('fault-start-confirmed', lambda: api_probe.http('GET',
                  '/operations/fault-start-0001')[1]['status'] == 'confirmed', 15)
        code, state = api_probe.http('GET', '/state')
        c.need(code == 200 and state['simulation']['state'] == 1, 'Fault segment never ran')
        pause = dict(runId=session['runId'], segmentId=session['segmentId'],
                     expectedSequence=state['controlSequence'], idempotencyKey='lost-reply-pause-0001',
                     action='pause', multiple=None)
        lost_reply(pause)
        receipt = self.wait('lost-reply-recovered', lambda: self.confirmed('lost-reply-pause-0001'), 15)
        code, duplicate = api_probe.http('POST', '/operations', pause)
        c.need(code == 200 and duplicate['sequence'] == receipt['sequence'],
               'Lost-reply retry generated another command')
        c.need(len(list((self.java_dir / 'results').glob('*.json'))) == 1,
               'Lost response generated duplicate AMASE command')
        (self.java_dir / 'request-shutdown').touch()
        self.java_process.wait(timeout=20)
        code, unavailable = api_probe.http('GET', '/state')
        c.need(code == 503, 'Exited AMASE still produced a writable control state')
        new = dict(pause, expectedSequence='2', idempotencyKey='after-exit-pause-0001', action='resume')
        c.need(api_probe.http('POST', '/operations', new)[0] == 503,
               'Controller accepted an operation after AMASE exited')
        self.item['faultEvidence'] = dict(lostResponseOperation=receipt, duplicateOperation=duplicate,
                                           postExitState=unavailable, amaseExitCode=self.java_process.returncode)

    def confirmed(self, key):
        try:
            code, result = api_probe.http('GET', '/operations/' + key)
            return result if code == 200 and result['status'] == 'confirmed' else None
        except Exception:
            return None

    def audit(self):
        c.need(self.item['faultEvidence']['amaseExitCode'] == 0, 'AMASE fault shutdown was abnormal')
        c.base.verify_files(self.java_dir, self.item['runtimeInputs'])
        self.item.update(faultMatrixObserved=True, controlRuntimeQualified=False)

    def execute(self):
        self.prepare()
        for mode in ('Headless', 'Gui'):
            self.operation_deadline = time.monotonic() + 450
            result = self.case(mode.lower(), mode)
            c.need(result.get('faultEvidence') and result['faultEvidence']['amaseExitCode'] == 0,
                   result.get('error', 'Expected fault evidence missing'))
            c.need(result['normalExit'] and result['portsReleased'] and
                   (result['status'] == 'passed' or result['status'] == 'failed' and
                    'Gateway shutdown failed:' in result['error'] and "'exit_code': 1" in result['error'] and
                    "'forced_termination': False" in result['error']),
                   'Expected backend-exit observer failure was not isolated')
            result['expectedBackendExit'] = True
        c.need(self.inputs() == self.record['inputs'], 'Fault probe inputs changed')
        self.record.update(status='passed', faultMatrixObserved=True, controlRuntimeQualified=False)


def port_conflict(directory, python):
    directory.mkdir()
    java = directory / 'java'
    (java / 'results').mkdir(parents=True)
    session = directory / 'control-session.json'
    c.save(session, dict(runId='port-conflict', segmentId='1', backendRunId='port-conflict',
                         durationMs='1800000', javaDirectory=str(java),
                         amaseProcess=dict(pid='0', created_filetime='0')))
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 8001))
        occupied.listen(1)
        result = subprocess.run([str(python), '-I', '-B', '-X', 'utf8',
            str(ROOT / 'apps/g6_control/server.py'), '--session', str(session)],
            cwd=directory, capture_output=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
    (directory / 'stdout.log').write_bytes(result.stdout)
    (directory / 'stderr.log').write_bytes(result.stderr)
    c.need(result.returncode != 0 and b'Errno 10048' in result.stderr,
           'Control server did not reject the occupied fixed port')
    return dict(exitCode=result.returncode, stderrSHA256=c.sha(directory / 'stderr.log'), port=8001)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    args.mode = 'Headless'
    task = FaultRun(args)
    try:
        task.execute()
        task.record['portConflict'] = port_conflict(task.run / 'port-conflict', task.web_python)
        return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(task.record['traceback'], flush=True)
        return 1
    finally:
        c.save(task.run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())

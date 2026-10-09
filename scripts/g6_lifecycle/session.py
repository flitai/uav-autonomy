"""Run the B07 task service and recover an owned service restart."""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('g6_b06_session', ROOT / 'scripts/g6_replanning/session.py')
b06 = module_from_spec(spec)
spec.loader.exec_module(b06)
c = b06.c


class LifecycleSession(b06.ReplanningSession):
    def inputs(self):
        paths = [path for directory in ('apps/g6_lifecycle', 'apps/cesium_lifecycle',
                                        'scripts/g6_lifecycle')
                 for path in (ROOT / directory).rglob('*')
                 if path.is_file() and '__pycache__' not in path.parts]
        return super().inputs() + c.base.inventory(ROOT, paths)

    def prepare(self):
        super().prepare()
        receipt_file = ROOT / 'out/runs' / self.args.lifecycle_build / 'result.json'
        receipt = c.load(receipt_file)
        c.need(receipt['status'] == 'passed' and receipt['task'] == 'G6-B07' and
               receipt['b06BuildRunId'] == self.args.replanning_build,
               'B07 viewer build is not qualified')
        c.base.verify_files(ROOT, receipt['inputs'])
        candidate = ROOT / 'out/build/g6-lifecycle' / self.args.lifecycle_build
        c.need((candidate / 'project/dist/index.html').is_file(),
               'B07 viewer artifact missing')
        self.viewer_service = candidate / 'service.json'
        self.record.update(b07ViewerBuildRunId=self.args.lifecycle_build,
                           b07ViewerBuildSHA256=c.sha(receipt_file))

    def spawn_lifecycle(self, session, restart=False):
        label = 'lifecycle-restart-' + str(self.lifecycle_restarts + 1) if restart else 'lifecycle'
        with (self.directory / (label + '.stdout')).open('wb') as out, \
             (self.directory / (label + '.stderr')).open('wb') as err:
            self.replanning_process = subprocess.Popen([
                str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'apps/g6_lifecycle/server.py'), '--session',
                str(self.directory / 'control-session.json'),
                '--planner-deadline-seconds', str(self.args.planner_deadline_seconds)],
                cwd=self.directory, stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW)

        def ready():
            c.need(self.replanning_process.poll() is None, 'B07 service exited at startup')
            try:
                with urlopen('http://127.0.0.1:8006/api/tasks/v4/state', timeout=2) as response:
                    state = json.load(response)
                if state['health']['readOnly']:
                    c.save(self.directory / 'lifecycle-health.json', state['health'])
                if all(state['identity'][key] == session[key]
                       for key in ('runId', 'segmentId', 'backendRunId')) and \
                       not state['health']['readOnly']:
                    return state
            except Exception:
                pass
            return None
        return self.wait('lifecycle-api-ready' if not restart else
                         'lifecycle-restart-ready', ready, 25)

    def session_exercise(self, session):
        self.lifecycle_directory = self.directory
        self.lifecycle_restarts = 0
        self.spawn_lifecycle(session)
        c.save(self.run / 'b07-session-ready.json', dict(
            runId=session['runId'], segmentId=session['segmentId'],
            backendRunId=session['backendRunId'], url='http://127.0.0.1:8080/',
            lifecycleUrl='http://127.0.0.1:8006/', mode=self.mode,
            stopFile=str(self.run / 'request-stop')))
        print('G6_B07_SESSION_READY=' + session['runId'], flush=True)
        return b06.assignment_session.AssignmentSession.session_exercise(self, session)

    def alive(self):
        # The B04 body calls wait() before session_exercise() on a reset.
        # Forget the prior segment's already closed B05/B07 services there.
        if getattr(self, 'lifecycle_directory', None) != self.directory:
            for name in ('assignment_process', 'replanning_process'):
                process = getattr(self, name, None)
                if process is not None:
                    c.need(process.poll() is not None,
                           'Previous task service still runs across reset: ' + name)
                    delattr(self, name)
        gateway_marker = self.directory / 'task-replanning/request-gateway-restart'
        if gateway_marker.is_file():
            gateway_marker.unlink()
            before = self.host.live()
            self.host.stop()
            with urlopen('http://127.0.0.1:8006/api/tasks/v4/state', timeout=3) as response:
                outage = json.load(response)
            c.need(outage['health']['readOnly'],
                   'B07 accepted writes while the gateway was stopped')
            self.host.start()
            after = self.host.live()
            with urlopen('http://127.0.0.1:8006/api/tasks/v4/state', timeout=3) as response:
                recovered = json.load(response)
            c.need(after['stream_id'] != before['stream_id'] and
                   not recovered['health']['readOnly'] and
                   recovered['identity']['streamId'] == after['stream_id'],
                   'B07 did not bind the restarted gateway stream')
            c.save(self.directory / 'task-replanning/gateway-restart.json',
                   dict(oldStreamId=before['stream_id'],
                        newStreamId=after['stream_id'],
                        outageReadOnly=outage['health']['readOnly'],
                        recoveredReadOnly=recovered['health']['readOnly']))
        backend_marker = self.directory / 'task-replanning/request-backend-exit'
        if backend_marker.is_file():
            backend_marker.unlink()
            with urlopen('http://127.0.0.1:8006/api/tasks/v4/state', timeout=3) as response:
                before = json.load(response)
            process = self.cpp
            c.need(process.poll() is None, 'Owned UxAS already exited before fault injection')
            process.terminate()
            process.wait(timeout=10)
            with urlopen('http://127.0.0.1:8006/api/tasks/v4/state', timeout=3) as response:
                outage = json.load(response)
            c.need(outage['health']['readOnly'],
                   'B07 remained writable after UxAS exit')
            body = dict(before['identity'],
                        idempotencyKey='g6-b07-backend-fault-write',
                        change=dict(action='add', draftId='0' * 32))
            request = Request('http://127.0.0.1:8006/api/tasks/v3/plans',
                              data=json.dumps(body).encode('utf-8'), method='POST',
                              headers={'Origin': 'http://127.0.0.1:8080',
                                       'Content-Type': 'application/json'})
            try:
                with urlopen(request, timeout=3) as response:
                    write_status = response.status
            except HTTPError as error:
                write_status = error.code
            c.need(write_status == 409, 'B07 accepted planning after UxAS exit')
            c.save(self.directory / 'task-replanning/backend-exit.json',
                   dict(ownedUxasPid=process.pid, exitCode=process.returncode,
                        readOnly=outage['health']['readOnly'],
                        planningHttpStatus=write_status))
        marker = self.directory / 'task-replanning/request-service-restart'
        if marker.is_file():
            process = self.replanning_process
            c.need(process.poll() is None, 'B07 service exited before controlled restart')
            old_pid = process.pid
            process.terminate()
            process.wait(timeout=10)
            marker.unlink()
            session = c.load(self.directory / 'control-session.json')
            self.spawn_lifecycle(session, restart=True)
            self.lifecycle_restarts += 1
            c.save(self.directory / 'task-replanning' /
                   ('restart-' + str(self.lifecycle_restarts) + '.json'),
                   dict(oldPid=old_pid, newPid=self.replanning_process.pid,
                        segmentId=session['segmentId'], recovered=True))
        super().alive()

    def execute(self):
        super().execute()
        self.record.update(task='G6-B07', scope='task-lifecycle-candidate',
                           lifecycleQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    parser.add_argument('--draft-build', required=True)
    parser.add_argument('--execution-build', required=True)
    parser.add_argument('--assignment-build', required=True)
    parser.add_argument('--replanning-build', required=True)
    parser.add_argument('--lifecycle-build', required=True)
    parser.add_argument('--planner-deadline-seconds', type=int, default=90)
    parser.add_argument('--mode', choices=('Headless', 'Gui'), default='Headless')
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    c.need(args.run_id.startswith('g6-b07-session-'), 'B07 session ID required')
    run = ROOT / 'out/runs' / args.run_id
    c.need(not run.exists(), 'B07 session ID exists')
    run.mkdir(parents=True)
    b06.assignment_session.execution_session.draft_session.control_session.context_for(
        run, args.viewer_build)
    task = LifecycleSession(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(task='G6-B07', status='failed', error=str(error),
                           traceback=traceback.format_exc())
        print(task.record['traceback'], file=sys.stderr)
        return 1
    finally:
        c.save(task.run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())

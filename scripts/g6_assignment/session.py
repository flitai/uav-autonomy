"""B05 viewer and planning service over the qualified B04 execution session."""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('g6_b04_session', ROOT / 'scripts/g6_execution/session.py')
execution_session = module_from_spec(spec)
spec.loader.exec_module(execution_session)

c = execution_session.c


class AssignmentSession(execution_session.ExecutionSession):
    def inputs(self):
        paths = [p for directory in ('apps/g6_assignment', 'apps/cesium_assignment',
                                     'scripts/g6_assignment')
                 for p in (self.root / directory).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        paths.append(self.root / 'config/g6-assignment-contract-v1.json')
        return super().inputs() + c.base.inventory(self.root, paths)

    def prepare(self):
        super().prepare()
        receipt_file = ROOT / 'out/runs' / self.args.assignment_build / 'result.json'
        receipt = c.load(receipt_file)
        c.need(receipt['status'] == 'passed' and receipt['task'] == 'G6-B05' and
               receipt['b04BuildRunId'] == self.args.execution_build,
               'B05 viewer build is not qualified')
        c.base.verify_files(self.root, receipt['inputs'])
        candidate = ROOT / 'out/build/g6-assignment' / self.args.assignment_build
        c.need((candidate / 'project/dist/index.html').is_file(),
               'B05 viewer artifact missing')
        self.viewer_service = candidate / 'service.json'
        self.record.update(b05ViewerBuildRunId=self.args.assignment_build,
                           b05ViewerBuildSHA256=c.sha(receipt_file))

    def session_exercise(self, session):
        with (self.directory / 'assignment.stdout').open('wb') as out, \
             (self.directory / 'assignment.stderr').open('wb') as err:
            self.assignment_process = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'apps/g6_assignment/server.py'), '--session',
                str(self.directory / 'control-session.json')], cwd=self.directory,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        def ready():
            c.need(self.assignment_process.poll() is None, 'B05 service exited at startup')
            try:
                with urlopen('http://127.0.0.1:8005/api/tasks/v2/state', timeout=2) as response:
                    state = json.load(response)
                if all(state['identity'][key] == session[key] for key in
                       ('runId', 'segmentId', 'backendRunId')):
                    return state
            except Exception:
                pass
            return None
        state = self.wait('assignment-api-ready', ready, 20)
        c.save(self.run / 'b05-session-ready.json', dict(
            runId=session['runId'], segmentId=session['segmentId'],
            backendRunId=session['backendRunId'], streamId=state['identity']['streamId'],
            url='http://127.0.0.1:8080/', assignmentUrl='http://127.0.0.1:8005/',
            mode=self.mode, stopFile=str(self.run / 'request-stop')))
        print('G6_B05_SESSION_READY=' + session['runId'], flush=True)
        return super().session_exercise(session)

    def alive(self):
        super().alive()
        if hasattr(self, 'assignment_process'):
            c.need(self.assignment_process.poll() is None, 'B05 assignment service exited')

    def cleanup(self):
        process = getattr(self, 'assignment_process', None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                self.item.setdefault('cleanupErrors', []).append('B05 service forced termination')
        super().cleanup()

    def execute(self):
        super().execute()
        self.record.update(task='G6-B05', scope='multi-task-assignment-candidate',
                           assignmentQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    parser.add_argument('--draft-build', required=True)
    parser.add_argument('--execution-build', required=True)
    parser.add_argument('--assignment-build', required=True)
    parser.add_argument('--mode', choices=('Headless', 'Gui'), default='Headless')
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    c.need(args.run_id.startswith('g6-b05-session-'), 'B05 session run ID required')
    run = ROOT / 'out/runs' / args.run_id
    c.need(not run.exists(), 'B05 session ID exists')
    run.mkdir(parents=True)
    execution_session.draft_session.control_session.context_for(run, args.viewer_build)
    task = AssignmentSession(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(task='G6-B05', status='failed', error=str(error),
                           traceback=traceback.format_exc())
        print(task.record['traceback'], file=sys.stderr)
        return 1
    finally:
        c.save(task.run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())

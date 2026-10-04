"""Run the B06 viewer and local replacement API with a B05 backend session."""
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
spec = spec_from_file_location('g6_b05_session', ROOT / 'scripts/g6_assignment/session.py')
assignment_session = module_from_spec(spec)
spec.loader.exec_module(assignment_session)
c = assignment_session.c


class ReplanningSession(assignment_session.AssignmentSession):
    def inputs(self):
        paths = [path for directory in ('apps/g6_replanning', 'apps/cesium_replanning',
                                        'scripts/g6_replanning')
                 for path in (self.root / directory).rglob('*')
                 if path.is_file() and '__pycache__' not in path.parts]
        return super().inputs() + c.base.inventory(self.root, paths)

    def prepare(self):
        super().prepare()
        receipt_file = ROOT / 'out/runs' / self.args.replanning_build / 'result.json'
        receipt = c.load(receipt_file)
        c.need(receipt['status'] == 'passed' and receipt['task'] == 'G6-B06' and
               receipt['b05BuildRunId'] == self.args.assignment_build,
               'B06 viewer build is not qualified')
        c.base.verify_files(self.root, receipt['inputs'])
        candidate = ROOT / 'out/build/g6-replanning' / self.args.replanning_build
        c.need((candidate / 'project/dist/index.html').is_file(),
               'B06 viewer artifact missing')
        self.viewer_service = candidate / 'service.json'
        self.record.update(b06ViewerBuildRunId=self.args.replanning_build,
                           b06ViewerBuildSHA256=c.sha(receipt_file))

    def session_exercise(self, session):
        with (self.directory / 'replanning.stdout').open('wb') as out, \
             (self.directory / 'replanning.stderr').open('wb') as err:
            self.replanning_process = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(ROOT / 'apps/g6_replanning/server.py'), '--session',
                str(self.directory / 'control-session.json')], cwd=self.directory,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        def ready():
            c.need(self.replanning_process.poll() is None, 'B06 service exited at startup')
            try:
                with urlopen('http://127.0.0.1:8006/api/tasks/v3/state', timeout=2) as response:
                    state = json.load(response)
                if all(state['identity'][key] == session[key] for key in
                       ('runId', 'segmentId', 'backendRunId')):
                    return state
            except Exception:
                pass
            return None
        self.wait('replanning-api-ready', ready, 20)
        c.save(self.run / 'b06-session-ready.json', dict(
            runId=session['runId'], segmentId=session['segmentId'],
            backendRunId=session['backendRunId'],
            url='http://127.0.0.1:8080/', replanningUrl='http://127.0.0.1:8006/',
            mode=self.mode, stopFile=str(self.run / 'request-stop')))
        print('G6_B06_SESSION_READY=' + session['runId'], flush=True)
        return super().session_exercise(session)

    def alive(self):
        super().alive()
        if hasattr(self, 'replanning_process'):
            c.need(self.replanning_process.poll() is None, 'B06 replanning service exited')

    def cleanup(self):
        process = getattr(self, 'replanning_process', None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                self.item.setdefault('cleanupErrors', []).append('B06 service forced termination')
        super().cleanup()

    def execute(self):
        super().execute()
        self.record.update(task='G6-B06', scope='controlled-replanning-candidate',
                           replanningQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    parser.add_argument('--draft-build', required=True)
    parser.add_argument('--execution-build', required=True)
    parser.add_argument('--assignment-build', required=True)
    parser.add_argument('--replanning-build', required=True)
    parser.add_argument('--mode', choices=('Headless', 'Gui'), default='Headless')
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    c.need(args.run_id.startswith('g6-b06-session-'), 'B06 session run ID required')
    run = ROOT / 'out/runs' / args.run_id
    c.need(not run.exists(), 'B06 session ID exists')
    run.mkdir(parents=True)
    assignment_session.execution_session.draft_session.control_session.context_for(
        run, args.viewer_build)
    task = ReplanningSession(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(task='G6-B06', status='failed', error=str(error),
                           traceback=traceback.format_exc())
        print(task.record['traceback'], file=sys.stderr)
        return 1
    finally:
        c.save(task.run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())

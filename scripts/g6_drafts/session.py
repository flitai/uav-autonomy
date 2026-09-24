"""B03 candidate session with the independent preview and draft services."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_control'))
import session as control_session

c = control_session.c


class DraftSession(control_session.SessionRun):
    def inputs(self):
        paths = [p for directory in ('apps/cesium_tasks', 'apps/g6_drafts',
                                    'scripts/g6_drafts') for p in (self.root / directory).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        return super().inputs() + c.base.inventory(self.root, paths)

    def prepare(self):
        super().prepare()
        candidate = self.root / 'out/build/g6-drafts' / self.args.draft_build
        receipt = c.load(self.root / 'out/runs' / self.args.draft_build / 'result.json')
        c.need(receipt['status'] == 'passed' and receipt['task'] == 'G6-B03',
               'B03 viewer build missing')
        c.base.verify_files(self.root, receipt['inputs'])
        b02 = self.root / 'out/runs/g6-b02-acceptance-20260924-2410/acceptance.json'
        c.need(c.sha(b02) == receipt['b02AcceptanceSHA256'],
               'B02 preview qualification changed')
        self.viewer_service = candidate / 'service.json'
        c.need(self.viewer_service.is_file() and (candidate / 'project/dist/index.html').is_file(),
               'B03 viewer artifact missing')
        self.record.update(b03ViewerBuildRunId=self.args.draft_build,
                           b03ViewerBuildSHA256=c.sha(self.root / 'out/runs' /
                                                     self.args.draft_build / 'result.json'))

    def session_exercise(self, session):
        self.task_services = []
        for label, script in [('preview', 'apps/g6_tasks/server.py'),
                              ('drafts', 'apps/g6_drafts/server.py')]:
            with (self.directory / (label + '.stdout')).open('wb') as out, \
                 (self.directory / (label + '.stderr')).open('wb') as err:
                process = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                    str(ROOT / script), '--session', str(self.directory / 'control-session.json')],
                    cwd=self.directory, stdout=out, stderr=err,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.task_services.append((label, process))
        from urllib.request import urlopen
        import json
        def ready():
            try:
                with urlopen('http://127.0.0.1:8002/api/tasks/v1/state', timeout=2) as response:
                    planner = json.load(response)
                with urlopen('http://127.0.0.1:8003/api/tasks/v1/catalog', timeout=2) as response:
                    catalog = json.load(response)
                if all(planner[key] == catalog['identity'][key] == session[key]
                       for key in ('runId', 'segmentId', 'backendRunId')) and planner['streamId']:
                    return dict(preview=planner, catalog=catalog)
            except Exception:
                pass
            return None
        state = self.wait('draft-and-preview-api-ready', ready, 20)
        c.save(self.run / 'b03-session-ready.json',
               dict(runId=session['runId'],segmentId=session['segmentId'],
                    backendRunId=session['backendRunId'],streamId=state['preview']['streamId'],
                    url='http://127.0.0.1:8080/', draftUrl='http://127.0.0.1:8003/',
                    previewUrl='http://127.0.0.1:8002/',mode=self.mode,
                    stopFile=str(self.run / 'request-stop')))
        print('G6_B03_SESSION_READY=' + session['runId'],flush=True)
        while not (self.run / 'request-stop').exists():
            self.alive()
            c.need(all(process.poll() is None for _, process in self.task_services),
                   'B03 task service exited')
            time.sleep(.1)
        self.item['exitReason'] = 'stop'

    def cleanup(self):
        for label, process in getattr(self, 'task_services', []):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
                    self.item.setdefault('cleanupErrors', []).append(label + ' service forced termination')
        super().cleanup()

    def execute(self):
        super().execute()
        self.record.update(task='G6-B03',scope='task-draft-session-candidate',
                           taskDraftQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--viewer-build', required=True)
    parser.add_argument('--draft-build', required=True)
    parser.add_argument('--mode', choices=('Headless', 'Gui'), default='Headless')
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    c.need(args.run_id.startswith('g6-b03-session-'), 'B03 session run ID required')
    run = ROOT / 'out/runs' / args.run_id
    c.need(not run.exists(), 'B03 session ID exists')
    run.mkdir(parents=True)
    control_session.context_for(run, args.viewer_build)
    task = DraftSession(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(task='G6-B03',status='failed',error=str(error),
                           traceback=traceback.format_exc())
        print(task.record['traceback'],file=sys.stderr)
        return 1
    finally:
        c.save(task.run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())

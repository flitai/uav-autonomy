"""B04 candidate: G6-A backend plus isolated preview, drafts and fixed plan activation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from importlib.util import spec_from_file_location, module_from_spec

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('g6_draft_session', ROOT / 'scripts/g6_drafts/session.py')
draft_session = module_from_spec(spec)
spec.loader.exec_module(draft_session)

c = draft_session.c
DISABLED = {'AutomationRequestValidatorService', 'RoutePlannerVisibilityService',
            'RouteAggregatorService', 'AssignmentTreeBranchBoundService',
            'PlanBuilderService', 'AutomationDiagramDataService'}


class ExecutionSession(draft_session.DraftSession):
    def inputs(self):
        paths = [p for directory in ('apps/g6_execution','scripts/g6_execution')
                 for p in (self.root / directory).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        return super().inputs() + c.base.inventory(self.root, paths)

    def prepare(self):
        super().prepare()
        if self.args.execution_build:
            candidate=self.root/'out/build/g6-execution'/self.args.execution_build
            receipt_file=self.root/'out/runs'/self.args.execution_build/'result.json'
            receipt=c.load(receipt_file)
            c.need(receipt['status']=='passed' and receipt['task']=='G6-B04',
                   'B04 viewer build missing')
            c.base.verify_files(self.root,receipt['inputs'])
            self.viewer_service=candidate/'service.json'
            c.need(self.viewer_service.is_file() and (candidate/'project/dist/index.html').is_file(),
                   'B04 viewer artifact missing')
            self.record.update(b04ViewerBuildRunId=self.args.execution_build,
                               b04ViewerBuildSHA256=c.sha(receipt_file))

    def files(self, mode, fault):
        super().files(mode, fault)
        config = self.cpp_dir / 'uxas.xml'
        tree = ET.parse(config)
        root = tree.getroot()
        removed = []
        for node in list(root):
            if node.tag == 'Service' and node.get('Type') in DISABLED:
                removed.append(node.get('Type'))
                root.remove(node)
        c.need(set(removed) == DISABLED and
               len(root.findall("Service[@Type='WaypointPlanManagerService']")) == 3 and
               root.find("Service[@Type='TaskManagerService']") is not None,
               'B04 execution-only UxAS configuration differs')
        tree.write(config, encoding='utf-8', xml_declaration=True)
        self.item['executionConfigSHA256'] = c.sha(config)
        self.item['disabledPlannerServices'] = sorted(removed)

    def session_exercise(self, session):
        self.task_services = []
        for label, script in [('preview','apps/g6_tasks/server.py'),
                              ('drafts','apps/g6_drafts/server.py'),
                              ('execution','apps/g6_execution/server.py')]:
            with (self.directory / (label + '.stdout')).open('wb') as out, \
                 (self.directory / (label + '.stderr')).open('wb') as err:
                process = subprocess.Popen([str(self.web_python), '-I','-B','-X','utf8',
                    str(ROOT / script), '--session', str(self.directory / 'control-session.json')],
                    cwd=self.directory, stdout=out, stderr=err,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.task_services.append((label, process))
        def ready():
            try:
                with urlopen('http://127.0.0.1:8002/api/tasks/v1/state',timeout=2) as response:
                    planner=json.load(response)
                with urlopen('http://127.0.0.1:8003/api/tasks/v1/catalog',timeout=2) as response:
                    catalog=json.load(response)
                with urlopen('http://127.0.0.1:8004/api/tasks/v1/confirmation-state',timeout=2) as response:
                    activation=json.load(response)
                if all(planner[key] == catalog['identity'][key] == activation[key] == session[key]
                       for key in ('runId','segmentId','backendRunId')) and planner['streamId']:
                    return dict(preview=planner,catalog=catalog,activation=activation)
            except Exception:
                pass
            return None
        state=self.wait('execution-api-ready',ready,20)
        c.save(self.run / 'b04-session-ready.json',dict(runId=session['runId'],
            segmentId=session['segmentId'],backendRunId=session['backendRunId'],
            streamId=state['preview']['streamId'],url='http://127.0.0.1:8080/',
            confirmationUrl='http://127.0.0.1:8004/',mode=self.mode,
            stopFile=str(self.run / 'request-stop')))
        print('G6_B04_SESSION_READY='+session['runId'],flush=True)
        while not (self.run / 'request-stop').exists():
            self.alive()
            c.need(all(process.poll() is None for _,process in self.task_services),
                   'B04 task service exited')
            time.sleep(.1)
        self.item['exitReason']='stop'

    def execute(self):
        super().execute()
        self.record.update(task='G6-B04',scope='fixed-plan-execution-candidate',
                           executionQualified=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--viewer-build',required=True)
    parser.add_argument('--draft-build',required=True)
    parser.add_argument('--execution-build')
    parser.add_argument('--mode',choices=('Headless','Gui'),default='Headless')
    args=parser.parse_args(); args.root=ROOT; args.verify=False;args.keep_gui=False
    c.need(args.run_id.startswith('g6-b04-session-'),'B04 session run ID required')
    run=ROOT/'out/runs'/args.run_id
    c.need(not run.exists(),'B04 session ID exists')
    run.mkdir(parents=True)
    draft_session.control_session.context_for(run,args.viewer_build)
    task=ExecutionSession(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(task='G6-B04',status='failed',error=str(error),
                           traceback=traceback.format_exc())
        print(task.record['traceback'],file=sys.stderr)
        return 1
    finally:
        c.save(task.run/'runtime-result.json',task.record)


if __name__=='__main__':
    sys.exit(main())

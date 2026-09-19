"""G4-T06 original two-entity full task, gateway, browser and recovery evidence."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


root = Path(__file__).resolve().parents[2]
recovery = module('g4_completion_recovery', root / 'scripts/g4_recovery/runtime.py')
from sim_bridge.codec import load_schema
save, sha, require = recovery.save, recovery.sha, recovery.require


class Qualification(recovery.Qualification):
    def __init__(self, args):
        super().__init__(args); self.record['task'] = 'G4-T06'

    def inputs(self):
        paths = [p for directory in ('scripts/g4_completion', 'tests/g4_completion')
                 for p in (self.root / directory).rglob('*.py')]
        paths += [self.root / p for p in ('config/g4-completion.json', 'scripts/windows/run-g4-completion.ps1',
                                          'tests/windows/g4-completion.tests.ps1', 'tests/g4_web/browser.py')]
        return super().inputs() + [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]

    def prepare(self):
        self.record['g4Provenance'] = recovery.environment.verify_handoff(self.root, self.context['baselineRunId'])
        self.web_python, environment = recovery.environment.environment(self.root)
        recovery.complete.Completion.prepare(self)
        self.schema = load_schema(self.root)
        policy = json.loads((self.root / 'config/g4-completion.json').read_text(encoding='utf-8-sig'))
        require(policy == dict(schemaVersion=1, scope='gateway-completion', recoveryRunId='g4-t05-test-20260920-004801-605',
            completionConfiguration='config/g3-completion.json', modes=['Headless','Gui'], simulationRate=1,
            gridResolutionMeters=20, minimumCoveragePercent=None, browserClients=3), 'G4 full-task policy changed')
        prior = self.root / 'out/runs' / policy['recoveryRunId']
        receipt = json.loads((prior / 'result.json').read_text(encoding='utf-8-sig'))
        entry = json.loads((prior / 'entry-result.json').read_text(encoding='utf-8-sig'))
        require(receipt['status'] == entry['status'] == 'passed' and receipt['gatewayRecoveryValidated'] and
                receipt['inputsUnchanged'] and receipt['realCompletionRecovered'], 'Unqualified T05 recovery')
        self.amase.verify_records(self.root, receipt['inputs'])
        for key in ('artifacts', 'formalUxas', 'amaseBuildRunId'):
            require(receipt[key] == self.record[key], 'Recovery backend provenance differs: ' + key)
        self.record['recoveryReference'] = dict(runId=policy['recoveryRunId'], resultSHA256=sha(prior/'result.json'),
                                               entrySHA256=sha(prior/'entry-result.json'))

    def files(self, mode, fault):
        self.host, self.proxies, self.relay, self.watcher = None, {}, None, None
        # Retain the original G3 whitelist and scene; T06 does not remove entities
        # or tasks after completion. Only the read-only probe modules are added.
        recovery.complete.Completion.files(self, mode, '')

    def start_clients(self):
        self.watch_directory = self.directory / 'continuous-clients'
        with (self.directory/'watch.stdout').open('wb') as stdout, (self.directory/'watch.stderr').open('wb') as stderr:
            self.watcher = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(self.root/'tests/g4_recovery/watch.py'), '--url', self.host.url, '--run-id', self.host.manifest['run_id'],
                '--output', str(self.watch_directory)], stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('three-continuous-clients', lambda: self.host.health()['metrics']['clients'] == 3)

    def body(self, mode, fault, keep_gui):
        recovery.startup.Startup.body(self, mode, '', False)
        for proxy in self.proxies.values(): proxy.restore()
        self.witness('initial-plan', self.host.live())
        self.start_clients()
        self.outage('observer-partial-frame', ['amase'], True)
        self.restart('gateway-restart-during-task')
        self.clients()
        self.full_completion()
        self.witness('completed-full-scene', self.host.live())
        result = subprocess.run([str(self.web_python), '-I', '-B', '-X', 'utf8', str(self.root/'tests/g4_web/browser.py'),
            '--url', self.host.url, '--output', str(self.directory/'edge-browser')],
            capture_output=True, timeout=100, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.directory/'browser.stdout').write_bytes(result.stdout); (self.directory/'browser.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'Completed diagnostic page failed in native Edge')

    def audit(self):
        recovery.complete.Completion.audit(self)
        require(self.host.records and all(r['status']=='passed' for r in self.host.records), 'Full-task gateway failed')
        snapshot = json.loads((self.directory/'completed-full-scene.json').read_text())
        require(set(snapshot['state']['entities']) == {'400','500'} and snapshot['state']['tasks']['1000']['backend_completed'],
                'Full scene or completion missing from gateway')
        require(snapshot['state']['tasks']['1000']['completed_time_ms'] == self.item['completion']['completion']['timeTaskCompletedMs'],
                'Gateway completion time differs from backend proof')
        require(json.loads((self.directory/'continuous-clients/result.json').read_text())['status']=='passed', 'Continuous clients failed')
        require(json.loads((self.directory/'edge-browser/result.json').read_text())['status']=='passed', 'Native page failed')
        require(any(p.stat().st_size for p in self.host.directory.rglob('tail.bin')), 'Partial raw gap evidence missing')
        self.item['gatewayCompletion'] = dict(status='passed', entityIds=['400','500'], taskId='1000',
            assignedEntityIds=['400'], browserClients=3, nativeDiagnosticPage=True, taskInjectionCount=1, requestInjectionCount=1,
            backendControlsFromGateway=0, wireGapsPreserved=True)

    def execute(self):
        self.prepare()
        for mode in (('Headless','Gui') if self.args.verify else (self.args.mode,)):
            item = self.case(mode.lower(),mode)
            require(item['status']=='passed', item.get('error','G4 full task failed'))
        require(self.inputs()==self.record['inputs'], 'G4 completion source changed')
        for key in ('configuration','executionConfiguration','completionConfiguration'):
            require(sha(Path(self.context[key]))==self.record[key+'SHA256'], 'Functional policy changed')
        self.amase.verify_records(self.root,self.baseline['frozenInputs'])
        self.record.update(status='passed', inputsUnchanged=True, gatewayCompletionValidated=True,
                           taskExecutionValidated=True, taskCompletionValidated=True, coverageValidated=True, manualGuiAcceptance=False)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--run-id',required=True)
    parser.add_argument('--mode',choices=['Headless','Gui'],default='Headless'); parser.add_argument('--verify',action='store_true')
    args=parser.parse_args(); args.keep_gui=False
    require(re.fullmatch(r'g4-t06-[A-Za-z0-9-]+',args.run_id),'Invalid G4 full-task identity')
    task=Qualification(args)
    try: task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed',error=str(error),traceback=traceback.format_exc()); print('FAILED: '+str(error),flush=True); return 1
    finally:
        task.record['finishedAt']=recovery.startup.stamp(); save(task.run/'result.json',task.record)
        print('G4_T06_EVIDENCE='+str(task.run),flush=True)


if __name__=='__main__': sys.exit(main())

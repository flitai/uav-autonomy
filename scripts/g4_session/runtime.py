"""Development session with backend lifetime independent of its observer process."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
entry = module('session_entry', ROOT / 'scripts/g4_stage/entry.py')
legacy = module('session_base', ROOT / 'scripts/g4_stage/session.py')
stage = legacy.stage
load, save, need = stage.load, stage.save, stage.need


class Independent:
    def inputs(self):
        paths = [Path(__file__), self.root / 'scripts/windows/start-g4-session.ps1']
        return super().inputs() + stage.package.files(self.root, paths)

    def observe_gateway(self):
        """Reap only owned exited observers; never stop a backend for their failure."""
        if self.host.current and self.host.current[2].poll() is not None:
            directory, output, process, item = self.host.current
            item['exit_code'] = process.returncode
            save(directory / 'process.json', item)
            result_path = output / 'result.json'
            result = load(result_path) if result_path.exists() else {
                'status': 'failed', 'error': 'Observer exited without final receipt'}
            self.host.records.append(result)
            self.item.setdefault('observerExits', []).append({
                'pid': str(process.pid), 'exitCode': process.returncode,
                'receiptStatus': result['status'], 'backendStopRequested': False})
            self.host.current = None
            self.next_restart = time.monotonic() + 1
        # An operator can leave the observer down while the simulation continues.
        if not self.host.current and not (self.run / 'gateway-offline').exists():
            if time.monotonic() >= getattr(self, 'next_restart', 0):
                self.next_restart = time.monotonic() + 10
                try:
                    self.host.start()
                except Exception as error:
                    # Backend health is checked separately, including during start.
                    self.alive()
                    self.item.setdefault('observerStartErrors', []).append(str(error))
        try:
            health = self.host.health() if self.host.current else None
        except (OSError, ValueError):
            health = None
        status = 'offline' if not health else health['status']
        error = None if not health else health['error']
        if (status, error) != getattr(self, 'observer_status', None):
            self.observer_status = (status, error)
            save(self.run / 'observer-status.json', {
                'status': status, 'error': error, 'backendRunId': self.args.run_id,
                'backendContinues': True, 'recordedAt': datetime.now().astimezone().isoformat()})
        return health

    def body(self, mode, fault, keep_gui):
        if self.args.scene == 'Original':
            stage.original.recovery.startup.Startup.body(self, mode, '', False)
            expected = {'1000': '400'}
        else:
            stage.scale.mixed.planning.Planning.body(self, mode, '', False)
            expected = {row['taskId']: row['entityId'] for row in self.scene['assignments']}
        self.host.live(); self.item['sessionReady'] = True
        self.record['status'] = 'demonstration-running'; save(self.run / 'result.json', self.record)
        print('G4_SESSION_READY=' + self.args.run_id + ' URL=http://127.0.0.1:8000', flush=True)
        latest = 0; completions = {}; cursor = 0; paused = False; finalized = False
        while not (self.run / 'request-stop').exists():
            self.alive()
            for row in self.observer.rows[cursor:]:
                cursor += 1
                if row['type'] in ('afrl.cmasi.SessionStatus', 'afrl.cmasi.AirVehicleState'):
                    latest = max(latest, int(row['timeMs']))
                if row['type'] == 'uxas.messages.task.TaskComplete':
                    node = stage.original.recovery.complete.completion.xml(row); task = node.findtext('TaskID')
                    need(task in expected and [n.text for n in node.findall('EntitiesInvolved/int64')] == [expected[task]],
                         'Unexpected completion identity')
                    need(task not in completions, 'Repeated completion')
                    completions[task] = node.findtext('TimeTaskCompleted')
            self.observer.rows.clear(); self.monitor.rows.clear(); cursor = 0
            health = self.observe_gateway()
            completed = len(completions) == len(expected)
            reached = (self.args.scene == 'Original' and completed and latest >= int(completions['1000']) + 3000) or latest >= 785000
            if reached and not paused:
                need(completed, 'Not all assigned tasks completed within the scene')
                (self.java_dir / 'request-pause').touch()
                self.wait('session-paused', lambda: any(r['type'] == 'afrl.cmasi.SessionStatus' and r['state'] == 2 for r in self.monitor.rows))
                (self.java_dir / 'request-analysis').touch()
                self.wait('session-analysis', lambda: (self.java_dir / 'analysis-done').exists(), 90)
                paused = True
                self.record['status'] = 'demonstration-paused'; save(self.run / 'result.json', self.record)
                remaining = self.operation_deadline - time.monotonic()
            if paused:
                self.operation_deadline = time.monotonic() + remaining
                if health and health['ready'] and not finalized:
                    snapshot = self.host.live()
                    for task, entity in expected.items():
                        observed = snapshot['state']['tasks'][task]
                        need(observed['backend_completed'] and observed['completed_entity_ids'] == [entity] and
                             observed['completed_time_ms'] == completions[task], 'Session completion differs from gateway')
                    save(self.directory / 'completed-scene.json', snapshot); finalized = True
            time.sleep(.1)
        self.item['observedCompletions'] = completions

    def audit(self):
        need(self.item.get('sessionReady'), 'Session did not initialize')
        self.item['demonstrationOnly'] = True
        self.item['observerLifetimeIndependent'] = True


class Original(Independent, legacy.Original):
    def handshake(self):
        stage.original.recovery.startup.Startup.handshake(self)
        self.host = stage.OriginalHost(self, self.web_python, self.schema,
            {'amase': self.ports['amasePort'], 'uxas': self.ports['observerPort']})
        self.host.start()


class Twenty(Independent, legacy.Twenty):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--baseline-run-id', required=True)
    parser.add_argument('--validate-entry', action='store_true')
    parser.add_argument('--scene', choices=['Original', 'Mixed20'], default='Mixed20')
    parser.add_argument('--mode', choices=['Headless', 'Gui'], default='Gui')
    args = parser.parse_args(); args.root = args.root.resolve()
    bundle, pointer, python = entry.resolve(args.root)
    if not args.validate_entry:
        binding = load(args.root / 'out/artifacts/gis-gateway/session.json')
        receipt = (args.root / binding['path']).resolve()
        need(receipt.is_relative_to(args.root / 'out/runs') and stage.sha(receipt) == binding['sha256'],
             'Session qualification changed')
        qualification = load(receipt)
        need(qualification['status'] == 'passed' and qualification['pointer'] == pointer,
             'Session is not qualified for the current gateway')
        stage.package.verify_files(args.root, qualification['sources'])
    if Path(sys.executable).resolve() != python.resolve():
        return subprocess.call([str(python), '-I', '-B', '-X', 'utf8', str(Path(__file__).resolve()), *sys.argv[1:]])
    args.bundle = bundle; args.run_id = 'g4-t09-demo-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    args.purpose = 'Demonstration'; args.keep_gui = False; args.verify = False; args.seconds = 785
    directory = args.root / 'out/runs' / args.run_id; directory.mkdir()
    context = {'baselineRunId': args.baseline_run_id, 'javaHome': str(args.java_home.resolve())}
    for key, name in [('configuration', 'startup'), ('executionConfiguration', 'execution'), ('completionConfiguration', 'completion')]:
        context[key] = str(args.root / ('config/g3-' + name + '.json'))
    save(directory / 'context.json', context)
    print('G4_SESSION_RUN_ID=' + args.run_id, flush=True)
    task = (Original if args.scene == 'Original' else Twenty)(args)
    try:
        task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(task.record['traceback'], flush=True); return 1
    finally:
        save(directory / 'result.json', task.record)


if __name__ == '__main__': sys.exit(main())

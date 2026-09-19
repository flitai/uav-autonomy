"""G3-T04 execution entry; reuse the qualified T03 startup and shutdown contract."""
import argparse
import difflib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import time
import traceback
import xml.etree.ElementTree as ET


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


startup = module('execution_startup', Path(__file__).parents[1] / 'g3_integration/runtime.py')
correlator = module('execution_correlator', Path(__file__).with_name('correlator.py'))
load, save, sha, require = startup.load, startup.save, startup.sha, startup.require


class Execution(startup.Startup):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G3-T04'

    def inputs(self):
        paths = [p for d in ('scripts/g3_execution', 'tests/g3_execution') for p in (self.root / d).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        paths += [self.root / p for p in ('scripts/windows/run-g3-execution.ps1', 'tests/windows/g3-execution.tests.ps1')]
        return super().inputs() + [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]

    def prepare(self):
        self.policy = load(Path(self.context['executionConfiguration']))
        expected = dict(schemaVersion=1, scope='execution', startupConfiguration='config/g3-startup.json',
                        executionTimeoutSeconds=600, minimumTaskWaypoints=4, minimumCompletedTaskLegs=2,
                        minimumLegProgressMeters=10, maximumRouteDeviationMeters=300, minimumSegmentCommands=2)
        require(self.policy == expected, 'T04 uses fixed execution evidence policy; no silent relaxation')
        require(Path(self.context['configuration']).resolve() == (self.root / self.policy['startupConfiguration']).resolve(), 'Wrong startup policy')
        super().prepare()
        self.record['executionConfigurationSHA256'] = sha(Path(self.context['executionConfiguration']))
        save(self.run / 'execution-configuration.json', self.policy)
        build = self.root / 'out/build/g3-execution' / self.args.run_id
        classes = build / 'classes'; classes.mkdir(parents=True)
        result = subprocess.run([str(Path(self.context['javaHome']) / 'bin/javac.exe'), '-encoding', 'UTF-8', '--release', '11',
            '-cp', os.pathsep.join(map(str, self.cp)), '-d', str(classes), str(Path(__file__).with_name('ExecutionProbe.java'))],
            capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run / 'execution-javac.stdout').write_bytes(result.stdout)
        (self.run / 'execution-javac.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'Execution module compile failed')
        self.cp.append(classes)
        self.record['executionPluginClasses'] = [dict(path=p.relative_to(build).as_posix(), sha256=sha(p)) for p in classes.rglob('*.class')]
        save(self.run / 'result.json', self.record)

    def files(self, mode, fault):
        super().files(mode, fault)
        path = self.java_dir / 'config/EntityControl.xml'
        before = path.read_text(encoding='utf-8')
        tree = ET.parse(path)
        ET.SubElement(tree.find('DefaultAircraft'), 'Module', Class='validation.g3.ExecutionProbe')
        tree.write(path, encoding='utf-8', xml_declaration=True)
        with (self.directory / 'configuration.diff').open('a', encoding='utf-8') as output:
            output.writelines(difflib.unified_diff(before.splitlines(True), path.read_text(encoding='utf-8').splitlines(True),
                                                  'T03-copy/EntityControl.xml', 'T04-copy/EntityControl.xml'))

    def navigation(self):
        return [json.loads(line) for path in sorted(self.java_dir.glob('execution-*.jsonl'))
                for line in path.read_text(encoding='utf-8').splitlines()]

    def body(self, mode, fault, keep_gui):
        super().body(mode, fault, False)
        # Incremental live progress is only a stopping condition. Passing requires
        # the full independent post-exit correlation below.
        seen, targets = 0, {}
        self.transition('execution-started', timeoutSeconds=self.policy['executionTimeoutSeconds'])
        next_log = time.monotonic()

        def progressed():
            nonlocal seen, next_log
            for row in list(self.observer.rows)[seen:]:
                seen += 1
                if row['type'] != 'afrl.cmasi.AirVehicleState': continue
                s = correlator.state(correlator.xml(row))
                if '1000' in s['tasks']:
                    targets.setdefault(s['entityId'], set()).add(s['waypoint'])
            assigned = [c['vehicleId'] for c in self.item['planningReceipt']['commands']]
            if time.monotonic() >= next_log:
                print(self.item['name'] + ' execution: ' + str({e: sorted(targets.get(e, set()), key=int) for e in assigned}), flush=True)
                next_log = time.monotonic() + 25
            return all(len(targets.get(e, set())) >= self.policy['minimumTaskWaypoints'] for e in assigned)

        self.wait('execution-observed', progressed, self.policy['executionTimeoutSeconds'])

    def audit(self):
        super().audit()
        result = correlator.assess(self.observer.rows, self.monitor.rows, self.amase.events(self.java_dir),
                                  self.policy, ET.fromstring(self.input_message('request').toXMLStr('')), self.navigation())
        # Keep detailed state sequences in their own evidence artifact.
        save(self.directory / 'execution.json', result)
        self.item['execution'] = {k: v for k, v in result.items() if k != 'entities'}
        self.item['execution']['entities'] = [{k: v for k, v in e.items() if k != 'trajectory'} for e in result['entities']]
        self.item['planningReceipt']['actualExecutionValidated'] = True

    def execute(self):
        self.prepare()
        modes = ('Headless', 'Gui') if self.args.verify else (self.args.mode,)
        for mode in modes:
            item = self.case(mode.lower(), mode)
            require(item['status'] == 'passed', item.get('error', 'Execution failed'))
        if self.args.verify:
            checks = module('execution_checks', self.root / 'tests/g3_execution/checks.py')
            self.record['counterexamples'] = checks.verify(self, correlator)
        require(self.record['inputs'] == self.inputs(), 'Runtime inputs changed')
        require(sha(Path(self.context['configuration'])) == self.record['configurationSHA256'] and
                sha(Path(self.context['executionConfiguration'])) == self.record['executionConfigurationSHA256'], 'Configuration changed')
        self.amase.verify_records(self.root, self.baseline['frozenInputs'])
        self.record.update(status='passed', inputsUnchanged=True, taskExecutionValidated=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui', 'Headless'], default='Headless')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    args.keep_gui = False
    require(re.fullmatch(r'g3-t04-[A-Za-z0-9-]+', args.run_id), 'Invalid execution run identity')
    task = Execution(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True)
        return 1
    finally:
        task.record['finishedAt'] = startup.stamp()
        save(task.run / 'result.json', task.record)
        print('G3 execution evidence: ' + str(task.run), flush=True)


if __name__ == '__main__':
    sys.exit(main())

"""Candidate G6-A02 real AMASE control probe; no browser write API or release."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g5_backend'))
import runtime as backend
state = backend.c.module('g6_control_state_runtime', ROOT / 'scripts/g5_state/runtime.py')

c = backend.c


class ControlRun(state.StateRun):
    def inputs(self):
        paths = list((self.root / 'scripts/g6_control').glob('*.py'))
        paths += list((self.root / 'scripts/g6_control').glob('*.java'))
        return super().inputs() + c.base.inventory(self.root, paths)

    def prepare(self):
        super().prepare()
        self.record.update(task='G6-A02', scope='real-backend-control-candidate', controlRuntimeQualified=False)
        classes = self.root / 'out/build/g6-control' / self.args.run_id / 'classes'
        classes.mkdir(parents=True)
        source = Path(__file__).with_name('ControlProbe.java')
        c.invoke([Path(self.context['javaHome']) / 'bin/javac.exe', '-encoding', 'UTF-8', '--release', '11',
                  '-cp', os.pathsep.join(map(str, self.cp)), '-d', classes, source], self.run,
                 'control-javac', timeout=60)
        self.cp.append(classes)
        self.record['controlClassSHA256'] = c.sha(classes / 'validation/g6/ControlProbe.class')

    def files(self, mode, fault):
        super().files(mode, fault)
        config = self.java_dir / 'config/Plugins.xml'
        plugins = ET.parse(config)
        # The legacy AMASE toolbar calls SimTimer directly. Its Play/Reset buttons
        # bypass the run-bound G6 controller and can invalidate the active segment.
        for plugin in list(plugins.getroot()):
            if plugin.get('Class') == 'avtas.amase.ui.SimControls':
                plugins.getroot().remove(plugin)
        ET.SubElement(plugins.getroot(), 'Plugin', Class='validation.g6.ControlProbe')
        plugins.write(config, encoding='utf-8', xml_declaration=True)
        layout = self.java_dir / 'config/WindowService.xml'
        if layout.is_file():
            windows = ET.parse(layout)
            for parent in windows.getroot().iter():
                for child in list(parent):
                    if (child.tag == 'DockingPortNode' and len(child) == 1 and
                            child[0].tag == 'DockableNode' and
                            child[0].get('dockableId') == 'avtas.amase.ui.SimControls'):
                        parent.remove(child)
            windows.write(layout, encoding='utf-8', xml_declaration=True)
        self.item['runtimeInputs'] = c.base.inventory(self.java_dir, [self.java_dir / 'scenario.xml',
            *sorted((self.java_dir / 'config').glob('*.xml')),
            *sorted((self.java_dir / 'data/g5-dted').rglob('*.dt1'))])
        (self.java_dir / 'requests').mkdir()
        (self.java_dir / 'results').mkdir()

    def launch(self, directory, argv):
        if directory == self.java_dir:
            argv = [argv[0], '-Dg6.control.directory=' + str(self.java_dir), *argv[1:]]
        return super().launch(directory, argv)

    def statuses(self):
        return [row for row in self.observer.rows if row['type'] == 'afrl.cmasi.SessionStatus']

    def operation(self, number, action, value=''):
        identity = f'{number:012d}'
        path = self.java_dir / 'requests' / (identity + '.request')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(action + '\n' + value + '\n', encoding='ascii')
        os.replace(temporary, path)
        receipt = self.java_dir / 'results' / (identity + '.json')
        self.wait('control-' + identity + '-' + action, lambda: receipt.exists(), 10)
        result = c.load(receipt)
        c.need(result['id'] == identity and result['action'] == action, 'Control receipt identity differs')
        self.item.setdefault('controls', []).append(result)
        return result

    def body(self, mode, fault, keep_gui):
        backend.mixed.Planning.body(self, mode, '', False)
        c.need(c.load(self.java_dir / 'terrain-loaded.json')['status'] == 'passed', 'Qualified terrain did not load')
        snapshot = self.host.live()
        c.need(isinstance(snapshot['run_id'], str) and snapshot['run_id'] and
               isinstance(snapshot['stream_id'], str) and snapshot['stream_id'],
               'Gateway run or stream identity missing')
        self.item['gatewayRunId'] = snapshot['run_id']
        self.item['gatewayStreamId'] = snapshot['stream_id']
        initial = self.statuses()
        c.need(any(row['state'] == 1 for row in initial), 'AMASE never entered Running state')
        start = len(initial)
        c.need(self.operation(1, 'pause')['outcome'] == 'applied', 'Pause rejected')
        paused = self.wait('authoritative-pause', lambda: next((r for r in self.statuses()[start:] if r['state'] == 2), None))
        paused_time = int(paused['timeMs'])
        time.sleep(1.2)
        c.need(all(int(row['timeMs']) == paused_time for row in self.statuses()[start:] if row['state'] == 2),
               'Simulation advanced while paused')
        c.need(self.operation(2, 'rate', '2')['outcome'] == 'applied', '2x rate rejected')
        c.need(self.operation(3, 'resume')['outcome'] == 'applied', 'Resume rejected')
        resumed = self.wait('authoritative-resume-2x', lambda: next((r for r in self.statuses()[start:]
            if r['state'] == 1 and r['realTimeMultiple'] == 2 and int(r['timeMs']) > paused_time), None))
        resumed_time = int(resumed['timeMs'])
        c.need(self.operation(4, 'rate', '0.5')['outcome'] == 'applied', '0.5x rate rejected')
        slower = self.wait('authoritative-rate-0.5x', lambda: next((r for r in self.statuses()[start:]
            if r['state'] == 1 and r['realTimeMultiple'] == 0.5 and int(r['timeMs']) > resumed_time), None))
        c.need(int(slower['timeMs']) >= resumed_time, 'Simulation time regressed after rate change')
        c.need(self.operation(5, 'rate', '500')['outcome'] == 'invalid', 'Invalid rate accepted')
        c.need(self.operation(6, 'reset')['outcome'] == 'invalid', 'Direct reset unexpectedly accepted')
        c.need(self.operation(7, 'pause')['outcome'] == 'applied', 'Final pause rejected')
        self.wait('final-authoritative-pause', lambda: next((r for r in self.statuses()[start:]
            if r['state'] == 2 and int(r['timeMs']) >= int(slower['timeMs'])), None))
        self.item['controlEvidence'] = dict(initialTimeMs=initial[-1]['timeMs'], pausedTimeMs=str(paused_time),
            resumedTimeMs=str(resumed_time), slowerTimeMs=slower['timeMs'], statuses=len(self.statuses()),
            source='AMASE SessionStatus over real TCP')

    def audit(self):
        c.need(len(self.item.get('controls', [])) == 7, 'Seven control receipts missing')
        c.need(self.item['controlEvidence']['statuses'] >= 4, 'Authoritative status evidence missing')
        c.base.verify_files(self.java_dir, self.item['runtimeInputs'])
        c.need(not (self.java_dir / 'terrain-error').exists(), 'Qualified terrain failed')
        self.item.update(realBackendControlObserved=True, controlRuntimeQualified=False)

    def execute(self):
        self.prepare()
        for mode in ('Headless', 'Gui'):
            self.operation_deadline = time.monotonic() + 450
            result = self.case(mode.lower(), mode)
            c.need(result['status'] == 'passed', result.get('error', 'G6 control case failed'))
        c.need(self.inputs() == self.record['inputs'], 'Control sources changed')
        self.record.update(status='passed', backendControlObserved=True, controlRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    args.mode = 'Headless'
    task = ControlRun(args)
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

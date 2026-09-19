"""Independent G4-T02 real ingress qualification using the unchanged G3 startup host."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import traceback


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from sim_bridge.codec import load_schema
from sim_bridge.transport import TcpCapture

startup = module('g4_ingress_startup', root / 'scripts/g3_integration/runtime.py')
environment = module('g4_ingress_environment', root / 'scripts/g4_environment/manage.py')
load, save, sha, require = startup.load, startup.save, startup.sha, startup.require


class Qualification(startup.Startup):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G4-T02'
        self.captures = []

    def inputs(self):
        paths = [p for directory in ('src/sim_bridge', 'scripts/g4_protocol', 'tests/g4_protocol')
                 for p in (self.root / directory).rglob('*.py')]
        paths += [self.root / p for p in ('scripts/windows/run-g4-protocol.ps1', 'tests/windows/g4-protocol.tests.ps1')]
        return super().inputs() + [{'path': p.relative_to(self.root).as_posix(), 'sha256': sha(p)} for p in sorted(paths)]

    def prepare(self):
        self.record['g4Provenance'] = environment.verify_handoff(self.root, self.context['baselineRunId'])
        python, manifest = environment.environment(self.root)
        self.record['webEnvironment'] = {'runId': manifest['runId'], 'lockSHA256': manifest['lockSHA256']}
        super().prepare()
        self.schema = load_schema(self.root)
        checks = module('g4_protocol_checks', self.root / 'tests/g4_protocol/checks.py')
        self.record['protocolChecks'] = checks.verify(self.root, self.run / 'protocol-checks')
        transport_checks = module('g4_transport_checks', self.root / 'tests/g4_protocol/transport_checks.py')
        self.record['transportChecks'] = transport_checks.verify(self.root, self.run / 'transport-checks')

    def handshake(self):
        self.captures = []
        for channel, port in (('amase', self.ports['amasePort']), ('uxas', self.ports['observerPort'])):
            self.captures.append(TcpCapture('127.0.0.1', port, channel, self.directory / ('g4-' + channel),
                                            self.schema, {'400', '500'}))
        super().handshake()

    def alive(self):
        super().alive()
        for capture in self.captures:
            require(capture.error is None and not capture.disconnected, 'G4 ingress failed: ' + str(capture.error))

    def body(self, mode, fault, keep_gui):
        super().body(mode, fault, False)
        self.wait('g4-real-samples', lambda: all(c.counts['afrl.cmasi.AirVehicleState'] >= 40 for c in self.captures), 30)

    def cleanup(self):
        try:
            super().cleanup()
        finally:
            for capture in self.captures:
                capture.close()

    def audit(self):
        super().audit()
        evidence = []
        for capture in self.captures:
            require(capture.error is None and not capture.reader.buffer, 'G4 stream failed or ended with a partial frame')
            rows = [json.loads(line) for line in (capture.folder / 'messages.jsonl').read_text(encoding='utf-8').splitlines()]
            reference = self.monitor.rows if capture.channel == 'amase' else self.observer.rows
            reference_hashes = {r['rawSHA256'].lower() for r in reference}
            require(all(r['rawSHA256'] in reference_hashes for r in rows), 'G4 messages differ from independent real observer')
            for entity in ('400', '500'):
                states = [r['fields'] for r in rows if r['type'] == 'afrl.cmasi.AirVehicleState' and r['fields']['ID'] == entity]
                require(len(states) >= 10 and len({s['Time'] for s in states}) >= 10, 'Insufficient real dynamic states')
                require(len({(s['Location']['Latitude'], s['Location']['Longitude']) for s in states}) > 1, 'Static state sample')
                times = [int(s['Time']) for s in states]
                require(times == sorted(times), 'State time regressed')
            require(capture.counts['afrl.cmasi.SessionStatus'] > 0 and capture.counts['afrl.cmasi.MissionCommand'] > 0,
                    'Missing session or real command')
            if capture.channel == 'uxas':
                require(capture.counts['afrl.cmasi.AutomationResponse'] > 0, 'Missing real planning response')
            evidence.append(capture.summary())
        self.item['gatewayIngress'] = {'status': 'passed', 'sources': evidence, 'sentBusinessFrames': 0}
        save(self.directory / 'gateway-ingress.json', self.item['gatewayIngress'])
        self.captures = []

    def execute(self):
        self.prepare()
        for mode in (('Headless', 'Gui') if self.args.verify else (self.args.mode,)):
            self.captures = []
            result = self.case(mode.lower(), mode)
            require(result['status'] == 'passed', result.get('error', 'G4 ingress failed'))
        require(self.record['inputs'] == self.inputs(), 'G4 inputs changed during validation')
        self.record.update(status='passed', realIngressValidated=True, taskCompletionValidated=False,
                           gatewayRecoveryValidated=False, inputsUnchanged=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui', 'Headless'], default='Headless')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(); args.keep_gui = False
    require(re.fullmatch(r'g4-t02-[A-Za-z0-9-]+', args.run_id), 'Invalid G4 ingress run identity')
    task = Qualification(args)
    try:
        task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True); return 1
    finally:
        task.record['finishedAt'] = startup.stamp()
        save(task.run / 'result.json', task.record)
        print('G4_T02_EVIDENCE=' + str(task.run), flush=True)


if __name__ == '__main__':
    sys.exit(main())

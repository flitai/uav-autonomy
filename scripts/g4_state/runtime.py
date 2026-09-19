"""G4-T03 live state/journal qualification, independent of backend binaries."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import traceback


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from sim_bridge.journal import EventStore, Journal
from sim_bridge.state import State

ingress = module('g4_state_ingress', root / 'scripts/g4_protocol/runtime.py')
load, save, sha, require = ingress.load, ingress.save, ingress.sha, ingress.require


class Qualification(ingress.Qualification):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G4-T03'
        self.journal = None
        self.event_store = None

    def inputs(self):
        paths = [p for directory in ('scripts/g4_state', 'tests/g4_state') for p in (self.root / directory).rglob('*.py')]
        paths += [self.root / p for p in ('scripts/windows/run-g4-state.ps1', 'tests/windows/g4-state.tests.ps1',
                                          'scripts/g4_environment/manage.py', 'config/g4-baseline.json')]
        return super().inputs() + [{'path': p.relative_to(self.root).as_posix(), 'sha256': sha(p)} for p in sorted(paths)]

    def prepare(self):
        super().prepare()
        checks = module('g4_state_checks', self.root / 'tests/g4_state/checks.py')
        self.record['stateChecks'] = checks.verify(self.root, self.run / 'state-checks')
        logging_checks = module('g4_logging_checks', self.root / 'tests/g4_state/logging_checks.py')
        self.record['loggingChecks'] = logging_checks.verify(self.run / 'logging-checks')
        provenance_checks = module('g4_revision_checks', self.root / 'tests/g4_state/provenance_checks.py')
        self.record['revisionChecks'] = provenance_checks.verify(ingress.environment, self.root, self.context['baselineRunId'])

    def handshake(self):
        super().handshake()
        self.binding = {'run_id': self.args.run_id + '/' + self.item['name'],
                        'log_directory': str(self.cpp_dir / 'datawork/SavedMessages'),
                        'uxas_pid': str(self.cpp.pid), 'amase_pid': str(self.java_process.pid),
                        'configuration_sha256': sha(self.cpp_dir / 'uxas.xml'),
                        'baseline_run_id': self.context['baselineRunId']}
        binding_path = self.directory / 'journal-binding.json'; save(binding_path, self.binding)
        self.journal = Journal(binding_path, self.binding['run_id'], self.schema, {'400', '500'})
        self.state = State(self.binding['run_id'], {'400', '500'})
        self.event_store = EventStore(self.directory / 'normalized-events.db3', self.binding)
        self.boundaries, self.next_poll = [], 0

    def pump(self):
        boundary = self.journal.boundary()
        count = 0
        for event in self.journal.read(boundary, self.state.cursor):
            self.event_store.append(event)
            self.state.apply(event)
            count += 1
        self.boundaries.append({'boundary': boundary, 'new_records': count, 'monotonic_seconds': time.monotonic()})

    def alive(self):
        super().alive()
        if self.journal is not None and time.monotonic() >= self.next_poll:
            self.pump()
            self.next_poll = time.monotonic() + 0.2

    def audit(self):
        output = (self.cpp_dir / 'stdout.log').read_text(encoding='utf-8', errors='replace')
        require('insert failed' not in output and 'database is locked' not in output, 'UxAS journal dropped a message')
        super().audit()
        self.pump()
        require(sum(b['new_records'] > 0 for b in self.boundaries) >= 5, 'No meaningful concurrent journal read evidence')
        require(set(self.state.data['entities']) == {'400', '500'} and self.state.data['tasks']['1000']['initialized'],
                'Missing live entity/task state')
        require(self.state.data['routes'] and self.state.data['commands'] and self.state.data['simulation'], 'Incomplete live state')
        rebuilt = State(self.binding['run_id'], {'400', '500'})
        journal_hashes = set()
        critical = {'afrl.cmasi.MissionCommand', 'afrl.cmasi.AutomationResponse', 'uxas.messages.task.TaskInitialized'}
        for event in self.event_store.records():
            rebuilt.apply(event)
            if event['message']['type'] in critical:
                journal_hashes.add(event['message']['rawSHA256'])
        require(rebuilt.fingerprint() == self.state.fingerprint(), 'Live durable rebuild differs')
        for line in (self.directory / 'g4-uxas/messages.jsonl').read_text(encoding='utf-8').splitlines():
            message = json.loads(line)
            if message['type'] in critical:
                require(message['rawSHA256'] in journal_hashes, 'TCP critical event absent/different in committed journal')
        self.item['gatewayState'] = {'status': 'passed', 'cursor': list(map(str, self.state.cursor)),
                                     'stateSHA256': self.state.fingerprint(), 'onlineReadBatches': len(self.boundaries),
                                     'criticalSemanticHashesMatched': len(journal_hashes), 'journalReadOnly': True}
        save(self.directory / 'state-evidence.json', self.item['gatewayState'])
        save(self.directory / 'journal-boundaries.json', self.boundaries)
        save(self.directory / 'snapshot.json', self.state.snapshot())
        self.event_store.close(); self.event_store = None; self.journal = None

    def execute(self):
        super().execute()
        self.record.update(stateRebuildValidated=True, onlineCommittedJournalReadValidated=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui', 'Headless'], default='Headless')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(); args.keep_gui = False
    require(re.fullmatch(r'g4-t03-[A-Za-z0-9-]+', args.run_id), 'Invalid G4 state run identity')
    task = Qualification(args)
    try:
        task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True); return 1
    finally:
        if task.event_store is not None:
            task.event_store.close()
        task.record['finishedAt'] = ingress.startup.stamp()
        save(task.run / 'result.json', task.record)
        print('G4_T03_EVIDENCE=' + str(task.run), flush=True)


if __name__ == '__main__':
    sys.exit(main())

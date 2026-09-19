"""G3-T06 isolated stability runs, reusing qualified startup/execution semantics."""
import argparse
import difflib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import importlib.util


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


execution = module('stability_execution', Path(__file__).parents[1] / 'g3_execution/runtime.py')
startup = execution.startup
load, save, sha, require = startup.load, startup.save, startup.sha, startup.require
relay_module = module('stability_relay', Path(__file__).with_name('relay.py'))
isolation = module('stability_isolation', Path(__file__).with_name('isolation.py'))


class Stability(execution.Execution):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G3-T06'
        self.relay = None
        if 'operationDeadline' in self.context:
            self.operation_deadline = min(self.operation_deadline, self.context['operationDeadline'])

    def inputs(self):
        paths = [p for d in ('scripts/g3_stability', 'tests/g3_stability') for p in (self.root / d).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        paths += [self.root / p for p in ('scripts/windows/run-g3-stability.ps1', 'tests/windows/g3-stability.tests.ps1',
                  'config/g3-stability.json', 'config/g3-startup.json', 'config/g3-execution.json', 'config/g3-completion.json')]
        return super().inputs() + [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]

    def prepare(self):
        self.stability = load(Path(self.context['stabilityConfiguration']))
        require(self.stability == dict(schemaVersion=1, scope='stability', startupConfiguration='config/g3-startup.json',
            executionConfiguration='config/g3-execution.json', completionConfiguration='config/g3-completion.json',
            simulationRate=1, consecutiveExecutions=3, disconnectRelayPort=5557,
            disconnectTimeoutSeconds=10, wholeRunSeconds=2700), 'Unexpected stability policy')
        super().prepare()
        save(self.run / 'stability-configuration.json', self.stability)
        self.record['stabilityConfigurationSHA256'] = sha(Path(self.context['stabilityConfiguration']))
        prior = self.root / 'out/runs' / self.context['completionRunId']
        receipt, entry = load(prior / 'result.json'), load(prior / 'entry-result.json')
        require(receipt['task'] == 'G3-T05' and receipt['runId'] == self.context['completionRunId'] and
                receipt['status'] == entry['status'] == 'passed' and receipt['taskCompletionValidated'] and
                receipt['coverageValidated'] and receipt['inputsUnchanged'], 'Unqualified T05 completion')
        for key in ('artifacts', 'amaseBuildRunId', 'formalUxas', 'configurationSHA256', 'executionConfigurationSHA256'):
            require(receipt[key] == self.record[key], 'T05 frozen identity differs: ' + key)
        require(receipt['completionConfigurationSHA256'] == sha(self.root / 'config/g3-completion.json'), 'T05 policy changed')
        self.amase.verify_records(self.root, receipt['inputs'])
        require({c['mode'] for c in receipt['cases']} == {'Gui', 'Headless'} and
                all(c['status'] == 'passed' and c['normalExit'] and c['portsReleased'] for c in receipt['cases']),
                'T05 both modes required')
        for case in receipt['cases']:
            require(load(prior / case['name'] / 'case-result.json') == case, 'T05 case receipt differs')
            self.amase.verify_records(prior / case['name'], case['evidence'])
        self.record['completionReference'] = dict(runId=self.context['completionRunId'],
            resultSHA256=sha(prior / 'result.json'), entrySHA256=sha(prior / 'entry-result.json'),
            scope='Prior full-task/coverage evidence; T06 independently requires actual rate 1')
        self.protected = self.protected_files()
        save(self.run / 'preservation-before.json', self.protected)

    def protected_files(self):
        paths = [p for folder in (self.folder, self.uxas) for p in folder.rglob('*') if p.is_file()]
        paths += [self.root / 'out/artifacts/uxas/current.json', self.lmcp_jar,
                  self.root / 'out/runs' / self.context['completionRunId'] / 'result.json',
                  self.root / 'out/runs' / self.context['completionRunId'] / 'entry-result.json']
        paths += [self.root / r['path'] for r in self.baseline['frozenInputs']]
        return [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(set(paths))]

    def files(self, mode, fault):
        super().files(mode, fault)
        if fault == 'disconnect-partial':
            port = self.stability['disconnectRelayPort']
            self.amase.check_port(port)
            self.port_values.append(port)
            path = self.cpp_dir / 'uxas.xml'
            before = path.read_text(encoding='utf-8')
            tree = ET.parse(path)
            tree.find("Bridge[@Server='false']").set('TcpAddress', 'tcp://127.0.0.1:' + str(port))
            tree.write(path, encoding='utf-8', xml_declaration=True)
            with (self.directory / 'configuration.diff').open('a', encoding='utf-8') as output:
                output.writelines(difflib.unified_diff(before.splitlines(True), path.read_text(encoding='utf-8').splitlines(True),
                                                       'direct/uxas.xml', 'fault-relay/uxas.xml'))

    def launch(self, directory, argv):
        # AMASE is already listening when Startup launches UxAS.
        if directory == self.cpp_dir and self.args.fault == 'disconnect-partial':
            self.relay = relay_module.DisconnectRelay(startup.protocol, self.directory,
                self.stability['disconnectRelayPort'], self.ports['amasePort'])
        return super().launch(directory, argv)

    def port_snapshot(self, expected, connected=False):
        if self.relay is None: return super().port_snapshot(expected, connected)
        expected = dict(expected); expected[self.stability['disconnectRelayPort']] = os.getpid()
        super().port_snapshot(expected, False)
        if connected:
            rows = self.item['portSnapshots'][-1]['connections']
            for owner, remote in ((self.cpp.pid, self.stability['disconnectRelayPort']), (os.getpid(), self.ports['amasePort'])):
                require(any(r['OwningProcess'] == owner and r['RemotePort'] == remote and r['State'] in (5, 'Established')
                            for r in rows), 'Fault relay connection/owner absent')

    def alive(self):
        super().alive()
        require(not (self.run / 'request-abort').exists(), 'timeout:parent-budget')
        if self.relay:
            require(self.relay.error is None, 'relay-error:' + str(self.relay.error))
            require(not self.relay.cut.is_set(), 'disconnect:main-link-partial-frame')
        for stream in self.streams:
            if stream.name == 'amase':
                rows = list(stream.rows)
                for row in rows[self.rate_seen:]:
                    if row['type'] == 'afrl.cmasi.SessionStatus' and row['state'] == 1:
                        require(row['realTimeMultiple'] == 1, 'simulation-rate-changed:' + str(row['realTimeMultiple']))
                self.rate_seen = len(rows)

    def body(self, mode, fault, keep_gui):
        self.rate_seen = 0
        if not fault:
            return super().body(mode, fault, False)
        startup.Startup.body(self, mode, fault, False)
        if fault in ('amase-early-exit', 'uxas-early-exit'):
            if fault == 'amase-early-exit':
                process = self.java_process
                (self.java_dir / 'request-shutdown').touch()
            else:
                from uxas.messages.uxnative.KillService import KillService
                process = self.cpp
                stop = KillService(); stop.ServiceID = -1; self.send(stop, 'injected-early-stop')
            self.transition('early-exit-injected', ownedPid=process.pid, method='normal shutdown before execution')
            process.wait(timeout=10)
            self.item['injectedEarlyExit'] = dict(pid=process.pid, exitCode=process.returncode)
            self.alive()  # Even exit 0 here must fail the unfinished run.
            raise RuntimeError('Early child exit was accepted')
        if fault == 'disconnect-partial':
            self.transition('disconnect-armed')
            self.relay.armed.set()
            self.wait('disconnect-must-fail', lambda: False, self.stability['disconnectTimeoutSeconds'])

    def cleanup(self):
        try:
            if self.relay:
                self.relay.close()
                require(self.relay.error is None, 'Relay error: ' + str(self.relay.error))
                self.item['disconnect'] = self.relay.receipt
                save(self.directory / 'disconnect.json', dict(receipt=self.relay.receipt, threadsReaped=True,
                                                             error=self.relay.error))
        finally:
            super().cleanup()

    def audit(self):
        super().audit()
        self.item.update(isolation.assess(self.args.run_id, self.item['name'], self.item,
            self.observer.rows, self.monitor.rows, self.amase.events(self.java_dir)))

    def execute(self):
        self.prepare()
        if self.args.verify:
            checks = module('stability_checks', self.root / 'tests/g3_stability/checks.py')
            checks.verify(self)
        else:
            name = '中文 空格运行' if self.args.chinese_path else 'execution'
            item = self.case(name, self.args.mode, self.args.fault)
            require(item['status'] == 'passed', item.get('error', 'Execution failed'))
        require(self.inputs() == self.record['inputs'], 'Stability inputs changed')
        require(self.protected_files() == self.protected, 'Qualified files changed')
        require(sha(Path(self.context['stabilityConfiguration'])) == self.record['stabilityConfigurationSHA256'], 'Stability configuration changed')
        save(self.run / 'preservation-after.json', self.protected_files())
        self.record.update(status='passed', inputsUnchanged=True, qualifiedPackagesUnchanged=True,
                           taskExecutionValidated=True, stabilityValidated=self.args.verify)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Headless', 'Gui'], default='Headless')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--chinese-path', action='store_true')
    parser.add_argument('--fault', choices=['', 'amase-early-exit', 'uxas-early-exit', 'planning-timeout',
                        'shutdown-timeout', 'disconnect-partial'], default='')
    args = parser.parse_args(); args.keep_gui = False
    require(re.fullmatch(r'g3-t06-[A-Za-z0-9-]{1,100}', args.run_id), 'Invalid stability run identity')
    require(not args.verify or not args.fault, 'Matrix cannot combine a single fault')
    task = Stability(args)
    try:
        task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True)
        return 1
    finally:
        task.record['finishedAt'] = startup.stamp()
        save(task.run / 'result.json', task.record)
        print('G3 stability evidence: ' + str(task.run), flush=True)


if __name__ == '__main__':
    sys.exit(main())

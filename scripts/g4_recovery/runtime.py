"""G4-T05 isolated observer recovery and real completion across a wire gap."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from sim_bridge.codec import load_schema
from sim_bridge.journal import EventStore, Journal
from sim_bridge.state import State
from sim_bridge.windows import main_connection

complete = module('g4_recovery_completion', root / 'scripts/g3_completion/runtime.py')
startup = complete.execution.startup
environment = module('g4_recovery_environment', root / 'scripts/g4_environment/manage.py')
hosts = module('g4_recovery_host', Path(__file__).with_name('host.py'))
proxies = module('g4_recovery_proxy', root / 'tests/g4_recovery/proxy.py')
relays = module('g4_recovery_main_fault', root / 'scripts/g3_stability/relay.py')
navigation_evidence = module('g4_navigation_evidence', Path(__file__).with_name('navigation.py'))
save, sha, require = complete.save, complete.sha, complete.require


class Qualification(complete.Completion):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G4-T05'
        self.host, self.proxies, self.relay = None, {}, None
        self.watcher = None

    def inputs(self):
        paths = [p for directory in ('src/sim_bridge', 'apps/gis_gateway', 'scripts/g4_recovery', 'tests/g4_recovery')
                 for p in (self.root / directory).rglob('*') if p.is_file() and p.suffix in ('.py', '.html')]
        paths += [self.root / p for p in ('scripts/windows/run-g4-recovery.ps1', 'tests/windows/g4-recovery.tests.ps1',
                  'scripts/g4_environment/manage.py', 'config/g4-baseline.json', 'config/g4-gateway.json',
                  'tests/g4_web/clients.py', 'scripts/g3_stability/relay.py')]
        return super().inputs() + [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]

    def prepare(self):
        self.record['g4Provenance'] = environment.verify_handoff(self.root, self.context['baselineRunId'])
        self.web_python, manifest = environment.environment(self.root)
        super().prepare()
        self.schema = load_schema(self.root)
        checks = module('g4_recovery_checks', self.root / 'tests/g4_recovery/checks.py')
        self.record['recoveryChecks'] = checks.verify(self.root, self.run / 'recovery-checks', self.schema)
        navigation_checks = module('g4_navigation_checks', self.root / 'tests/g4_recovery/navigation_checks.py')
        self.record['navigationChecks'] = navigation_checks.verify(self.root, self.run / 'navigation-checks.json',
            navigation_evidence.execution_view, complete.completion, self.policy)

    def navigation(self):
        raw = super().navigation()
        view, receipts = navigation_evidence.execution_view(raw, self.observer.rows)
        save(self.directory / 'navigation-receipt-transitions.json', {'rawSamples':len(raw), 'executionSamples':len(view),
                                                                    'receiptOnlyTransitions':receipts})
        return view

    def files(self, mode, fault):
        self.host, self.proxies, self.relay = None, {}, None
        self.watcher = None
        super().files(mode, '')
        path = self.cpp_dir / 'uxas.xml'; tree = ET.parse(path)
        main = tree.find("Bridge[@Server='false']")
        for name in ('RemoveEntities', 'RemoveTasks', 'RemoveZones'):
            ET.SubElement(main, 'SubscribeToMessage', MessageType='afrl.cmasi.' + name)
        if fault == 'main-link':
            self.amase.check_port(15556)
            main.set('TcpAddress', 'tcp://127.0.0.1:15556')
        tree.write(path, encoding='utf-8', xml_declaration=True)

    def launch(self, directory, argv):
        if directory == self.cpp_dir and self.item['fault'] == 'main-link':
            self.relay = relays.DisconnectRelay(startup.protocol, self.directory, 15556, self.ports['amasePort'])
        return super().launch(directory, argv)

    def port_snapshot(self, expected, connected=False):
        if self.relay is None: return super().port_snapshot(expected, connected)
        super().port_snapshot({**expected, 15556: os.getpid()}, False)
        if connected: main_connection(self.cpp.pid, 15556)

    def handshake(self):
        super().handshake()
        for channel, port in [('amase', 15555), ('uxas', 19999)]:
            self.amase.check_port(port)
            upstream = self.ports['amasePort' if channel == 'amase' else 'observerPort']
            proxy = proxies.ObserverProxy(port, upstream); proxy.cut()
            self.proxies[channel] = proxy
        self.host = hosts.GatewayHost(self, self.web_python, self.schema, {'amase':15555, 'uxas':19999},
                                      15556 if self.relay else None)
        self.host.start()

    def alive(self):
        super().alive()
        for proxy in self.proxies.values(): require(proxy.error is None, 'Observer proxy failed: ' + str(proxy.error))

    def witness(self, name, snapshot):
        # Re-read precisely the durable boundary represented by the snapshot;
        # live simulation may continue after this HTTP response.
        manifest = self.host.manifest
        output = self.host.current[1]
        journal = Journal(output / 'journal-binding.json', manifest['run_id'], self.schema, manifest['entity_ids'])
        expected = State(manifest['run_id'], manifest['entity_ids'])
        for event in journal.read(journal.boundary()):
            expected.apply(event)
            if expected.sequence == int(snapshot['sequence']): break
        require(expected.snapshot() == snapshot['state'], 'Recovered browser state differs from committed journal: ' + name)
        save(self.directory / (name + '.json'), snapshot)
        self.item.setdefault('recoverySnapshots', []).append(dict(name=name, streamId=snapshot['stream_id'],
                                                                  sequence=snapshot['sequence'], stateSHA256=expected.fingerprint()))

    def outage(self, name, channels, partial=False):
        before = self.host.live()
        for channel in channels: self.proxies[channel].cut(partial)
        self.host.wait(lambda: not self.host.health()['ready'], name + ' suspended')
        require(self.host.request('/api/v1/snapshot')[0] == 503, 'Incomplete snapshot was published')
        began = time.monotonic()
        self.wait(name + '-gap', lambda: time.monotonic() - began >= 2, 5)
        for channel in channels: self.proxies[channel].restore()
        after = self.host.live()
        require(before['stream_id'] != after['stream_id'], 'Recovery did not replace stream identity')
        self.witness(name, after)

    def restart(self, name):
        before = self.host.live()
        self.host.stop()
        began = time.monotonic()
        self.wait(name + '-process-gap', lambda: time.monotonic() - began >= 3, 6)
        self.host.start()
        after = self.host.live()
        require(before['run_id'] == after['run_id'] and before['stream_id'] != after['stream_id'], 'Restart identity differs')
        self.witness(name, after)

    def clients(self):
        result = subprocess.run([str(self.web_python), '-I', '-B', '-X', 'utf8', str(self.root / 'tests/g4_web/clients.py'),
                                 '--url', self.host.url, '--output', str(self.directory / 'browser-clients.json')],
                                capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.directory / 'clients.stdout').write_bytes(result.stdout); (self.directory / 'clients.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'Recovered browser clients differ')

    def body(self, mode, fault, keep_gui):
        startup.Startup.body(self, mode, '', False)
        require(not self.host.health()['ready'] and self.host.request('/api/v1/snapshot')[0] == 503,
                'Gateway published live state with blocked observer connections')
        for proxy in self.proxies.values(): proxy.restore()
        self.witness('missed-initial-configuration-and-plan', self.host.live())
        if fault:
            return self.backend_fault(fault)
        self.watch_directory = self.directory / 'continuous-clients'
        with (self.directory / 'watch.stdout').open('wb') as stdout, (self.directory / 'watch.stderr').open('wb') as stderr:
            self.watcher = subprocess.Popen([str(self.web_python), '-I', '-B', '-X', 'utf8',
                str(self.root / 'tests/g4_recovery/watch.py'), '--url', self.host.url, '--run-id', self.host.manifest['run_id'],
                '--output', str(self.watch_directory)], stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        self.wait('continuous-clients-connected', lambda: self.host.health()['metrics']['clients'] == 3)
        self.outage('amase-partial-frame', ['amase'], True)
        self.outage('uxas-observer-only', ['uxas'])
        self.outage('both-observers', ['amase', 'uxas'])
        self.restart('gateway-process-restart')
        self.clients()
        if mode == 'Headless': self.full_completion()
        # Explicit deletion is tested after the completed run's analysis export,
        # or at the end of the GUI startup/recovery case.
        for proxy in self.proxies.values(): proxy.cut()
        self.host.wait(lambda: not self.host.health()['ready'], 'deletion gap')
        from afrl.cmasi.RemoveTasks import RemoveTasks
        from afrl.cmasi.RemoveEntities import RemoveEntities
        remove = RemoveTasks(); remove.TaskList = [1000]; self.send(remove, 'remove-completed-task')
        remove = RemoveEntities(); remove.EntityList = [500]; self.send(remove, 'remove-unused-entity')
        self.wait('deletion-recorded', lambda: any(r['type'] == 'afrl.cmasi.RemoveTasks' for r in self.monitor.rows))
        for proxy in self.proxies.values(): proxy.restore()
        snapshot = self.host.live()
        require('1000' not in snapshot['state']['tasks'] and '500' not in snapshot['state']['entities'], 'Deletion was lost')
        self.witness('delete-during-disconnect', snapshot)
        self.restart('restart-after-deletion')

    def full_completion(self):
        cursor, latest, complete_ms, next_print, armed = 0, {}, None, 0, False
        def finished():
            nonlocal cursor, complete_ms, next_print, armed
            for row in list(self.observer.rows)[cursor:]:
                cursor += 1
                if row['type'] == 'afrl.cmasi.AirVehicleState':
                    state = complete.completion.execution.state(complete.completion.xml(row)); latest[state['entityId']] = state
                elif row['type'] == 'uxas.messages.task.TaskComplete':
                    require(complete_ms is None, 'Repeated TaskComplete')
                    complete_ms = int(complete.completion.xml(row).findtext('TimeTaskCompleted'))
            sim_ms = max((int(s['timeMs']) for s in latest.values()), default=0)
            if sim_ms >= 700000 and not armed:
                for proxy in self.proxies.values(): proxy.cut()
                armed = True; self.transition('completion-observation-gap-started', simulationTimeMs=str(sim_ms))
            if time.monotonic() >= next_print:
                health = self.host.health()
                require(health['error'] is None, 'Gateway failed during full run: ' + str(health['error']))
                print('G4 recovery full task: sim=' + str(sim_ms) + ' gateway=' + health['status'], flush=True)
                next_print = time.monotonic() + 30
            require(sim_ms < 785000, 'Task did not complete within original duration')
            return complete_ms is not None and sim_ms >= complete_ms + 3000
        self.wait('completion-observed', finished, 830)
        require(armed and not self.host.health()['ready'], 'Task completion did not cross observer gap')
        (self.java_dir / 'request-pause').touch()
        self.wait('completion-paused', lambda: any(e['kind'] == 'paused' for e in self.amase.events(self.java_dir)))
        (self.java_dir / 'request-analysis').touch()
        self.wait('analysis-exported', lambda: (self.java_dir / 'analysis-done').exists())
        for proxy in self.proxies.values(): proxy.restore()
        snapshot = self.host.live()
        task = snapshot['state']['tasks']['1000']
        require(task['backend_completed'] and task['completed_entity_ids'] == ['400'] and
                task['completed_time_ms'] == str(complete_ms), 'Completion catch-up identity/time differs')
        self.witness('real-completion-during-disconnect', snapshot)
        self.item['realCompletionRecovered'] = dict(taskId='1000', entityIds=['400'], completedTimeMs=str(complete_ms))

    def backend_fault(self, fault):
        if fault == 'main-link':
            self.relay.armed.set()
        elif fault == 'uxas-exit':
            from uxas.messages.uxnative.KillService import KillService
            message = KillService(); message.ServiceID = -1; self.send(message, 'injected-backend-stop')
        else:
            (self.java_dir / 'request-shutdown').touch()
        health = self.host.wait(lambda: (value if (value := self.host.health()) and value['error'] else None),
                                'backend/main-link failure refusal', 15, backend_alive=False)
        require(health['status'] == 'degraded' and not health['ready'] and self.host.request('/api/v1/snapshot')[0] == 503,
                'Backend failure accepted as live')
        self.item['expectedRefusal'] = health
        self.item['backendRunStatus'] = 'failed-new-whole-run-required'
        self.host.stop(expected=1)

    def cleanup(self):
        try:
            if self.watcher:
                if self.watch_directory.is_dir(): (self.watch_directory / 'request-stop').touch()
                try: self.watcher.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.watcher.kill(); self.watcher.wait(timeout=10)
                    self.item.setdefault('cleanupErrors', []).append('Continuous clients required forced termination')
                self.item['continuousClientProcess'] = {'pid': str(self.watcher.pid), 'exitCode': self.watcher.returncode}
                if self.watcher.returncode != 0:
                    self.item.setdefault('cleanupErrors', []).append('Continuous clients failed: see watch.stderr')
            if self.host and self.host.current:
                self.host.stop(expected=1 if self.host.health() and self.host.health().get('error') else 0)
        finally:
            for proxy in self.proxies.values(): proxy.close()
            if self.relay: self.relay.close()
            super().cleanup()
            for port in (8000,15555,19999,15556): self.amase.check_port(port)
        if self.host: self.item['gatewayInstances'] = self.host.records
        self.item['observerProxies'] = {name: proxy.summary() for name, proxy in self.proxies.items()}

    def audit(self):
        if self.item['fault']:
            require(self.item.get('expectedRefusal'), 'Expected failure was not observed')
            return
        if self.item['mode'] == 'Headless': super().audit()
        else: startup.Startup.audit(self)
        require(all(r['status'] == 'passed' for r in self.host.records), 'Recovery instance failed')
        tails = [p.stat().st_size for p in self.host.directory.rglob('tail.bin')]
        require(any(tails), 'No preserved partial-frame gap evidence')
        require(len(self.item['recoverySnapshots']) >= 7, 'Recovery matrix incomplete')
        self.item['gatewayRecovery'] = dict(status='passed', wireGapBytesPreserved=sum(tails), semanticRecovery=True)

    def execute(self):
        self.prepare()
        for name, mode, fault in [('headless','Headless',''), ('gui','Gui',''),
                                 ('main-link-fault','Headless','main-link'), ('uxas-exit','Headless','uxas-exit'),
                                 ('amase-exit','Headless','amase-exit'), ('fresh-whole-restart','Gui','')]:
            if not self.args.verify and (fault or name not in (self.args.mode.lower(),)): continue
            item = self.case(name, mode, fault)
            require(item['status'] == 'passed', item.get('error', 'G4 recovery failed'))
        require(self.inputs() == self.record['inputs'], 'Recovery runtime inputs changed')
        self.amase.verify_records(self.root, self.baseline['frozenInputs'])
        self.record.update(status='passed', gatewayRecoveryValidated=True,
                           realCompletionRecovered=any(c.get('realCompletionRecovered') for c in self.record['cases']),
                           inputsUnchanged=True, manualGuiAcceptance=False)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True); parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui','Headless'], default='Headless'); parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(); args.keep_gui = False
    require(re.fullmatch(r'g4-t05-[A-Za-z0-9-]+', args.run_id), 'Invalid recovery run identity')
    task = Qualification(args)
    try: task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True); return 1
    finally:
        task.record['finishedAt'] = startup.stamp(); save(task.run / 'result.json', task.record)
        print('G4_T05_EVIDENCE=' + str(task.run), flush=True)


if __name__ == '__main__': sys.exit(main())

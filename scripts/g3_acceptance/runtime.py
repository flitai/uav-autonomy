"""G3-T07: final full missions, current GUI confirmation, and G4 handoff."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
import importlib.util


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


full = module('stage_completion', Path(__file__).parents[1] / 'g3_completion/runtime.py')
receipts = module('stage_receipts', Path(__file__).with_name('receipts.py'))
startup = full.execution.startup
load, save, sha, require = full.load, full.save, full.sha, full.require


class Acceptance(full.Completion):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G3-T07'
        self.manual_wait = 0
        self.rate_seen = 0
        self.paused_time = None

    def inputs(self):
        files = [p for d in ('scripts/g3_acceptance', 'tests/g3_acceptance') for p in (self.root / d).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        files += [self.root / p for p in ('scripts/windows/run-g3-acceptance.ps1', 'scripts/windows/finish-g3-acceptance.ps1',
                  'tests/windows/g3-acceptance.tests.ps1', 'config/g3-acceptance.json')]
        return super().inputs() + [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(files)]

    def prepare(self):
        self.stage_policy = load(Path(self.context['acceptanceConfiguration']))
        require(self.stage_policy == dict(schemaVersion=1, scope='stage-acceptance',
            connectionConfiguration='config/g3-startup.json', executionConfiguration='config/g3-execution.json',
            completionConfiguration='config/g3-completion.json', simulationRate=1, gridResolutionMeters=20,
            minimumCoveragePercent=None, automaticWallTimeLimitSeconds=2700, manualGuiConfirmationRequired=True,
            historicalRuns={'G3-T02':'g3-t02-verify-20260919-104721-817', 'G3-T03':'g3-t03-test-20260919-113944-818',
                            'G3-T04':'g3-t04-test-20260919-121531-644'}), 'Unexpected final acceptance policy')
        super().prepare()
        self.record['acceptanceConfigurationSHA256'] = sha(Path(self.context['acceptanceConfiguration']))
        save(self.run / 'acceptance-configuration.json', self.stage_policy)
        self.record['priorReceipts'] = receipts.verify(self)
        save(self.run / 'prior-receipts.json', self.record['priorReceipts'])
        self.protected = self.protected_files()
        save(self.run / 'preservation-before.json', self.protected)
        checks = module('stage_checks', self.root / 'tests/g3_acceptance/checks.py')
        self.record['confirmationChecks'] = checks.verify(receipts)
        save(self.run / 'confirmation-checks.json', self.record['confirmationChecks'])
        save(self.run / 'result.json', self.record)

    def protected_files(self):
        files = [p for folder in (self.folder, self.uxas) for p in folder.rglob('*') if p.is_file()]
        files += [self.root / 'out/artifacts/uxas/current.json', self.lmcp_jar]
        files += [self.root / row['path'] for row in self.baseline['frozenInputs']]
        return [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(set(files))]

    def alive(self):
        super().alive()
        for stream in self.streams:
            if stream.name != 'amase': continue
            rows = list(stream.rows)
            for row in rows[self.rate_seen:]:
                if row['type'] != 'afrl.cmasi.SessionStatus': continue
                if row['state'] == 1:
                    require(row['realTimeMultiple'] == 1, 'simulation-rate-changed:' + str(row['realTimeMultiple']))
                if self.paused_time is not None:
                    require(row['state'] != 1 and int(row['timeMs']) == self.paused_time, 'GUI was resumed/reset after review')
            self.rate_seen = len(rows)

    def body(self, mode, fault, keep_gui):
        self.rate_seen, self.paused_time = 0, None
        super().body(mode, fault, False)
        if mode == 'Gui':
            def paused_on_wire():
                sessions = [r for r in self.monitor.rows if r['type'] == 'afrl.cmasi.SessionStatus']
                return sessions and sessions[-1]['state'] == 2
            self.wait('gui-pause-observed', paused_on_wire)
            self.review_gui()
            self.await_confirmation()

    def review_gui(self):
        folder = self.directory / 'review'; folder.mkdir()
        bus, monitor, events, navigation = list(self.observer.rows), list(self.monitor.rows), self.amase.events(self.java_dir), self.navigation()
        # Snapshots are immutable while live observer heartbeats continue to arrive.
        for name, rows in [('observer', bus), ('amase', monitor), ('events', events), ('navigation', navigation)]:
            (folder / (name + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
        result = full.completion.assess(bus, monitor, events, self.policy,
            ET.fromstring(self.input_message('request').toXMLStr('')), navigation)
        save(folder / 'completion.json', result)
        coverage = full.coverage.assess(self.directory, ET.parse(self.root / self.config['task']).getroot())
        original = ET.parse(self.java_dir / 'analysis.xml').find('SearchTaskAnalysis')
        pixels = []
        for mode in ('Headless', 'Gui'):
            replay = folder / ('replay-' + mode.lower()); replay.mkdir()
            self.java_check('avtas.amase.analysis.AnalysisReplay',
                [self.java_dir / 'analysis-events.tsv', self.java_dir / 'config/Plugins.xml', replay], replay, mode == 'Headless')
            for filename in ('analysis.xml', 'incremental.xml', 'reset-replay.xml'):
                require(full.completion.execution.equivalent(original, ET.parse(replay / filename).find('SearchTaskAnalysis')),
                        'Pre-close replay report differs')
            pixels.append((replay / 'pixels.csv').read_bytes())
        require(pixels[0] == pixels[1], 'Pre-close GUI/headless cells differ')
        coverage['sameEventsBothModesMatched'] = True
        save(folder / 'coverage.json', coverage)
        sessions = [r for r in monitor if r['type'] == 'afrl.cmasi.SessionStatus']
        running = [r for r in sessions if r['state'] == 1]
        require(running and all(r['realTimeMultiple'] == 1 for r in running), 'GUI actual rate differs from 1')
        self.paused_time = int(sessions[-1]['timeMs'])
        self.rate_seen = len(monitor)
        self.item['review'] = dict(status='passed', taskCompletionValidated=True, coverage=coverage,
            completion=result['completion'], entities=result['assignedEntities'], simulationRate=1,
            pausedSimulationTimeMs=str(self.paused_time), normalExitValidated=False, manualGuiAcceptance=False,
            files=[dict(path=p.relative_to(folder).as_posix(), sha256=sha(p)) for p in sorted(folder.rglob('*')) if p.is_file()])
        save(folder / 'review.json', self.item['review'])
        self.transition('gui-review-ready', taskId='1000', coverageSeen=coverage['seen'], coverageTotal=coverage['total'])

    def await_confirmation(self):
        ready = dict(runId=self.args.run_id, phase='awaiting-confirmation', nonce=uuid.uuid4().hex,
            controllerPid=os.getpid(), javaPid=self.java_process.pid, uxasPid=self.cpp.pid,
            readyAtEpochSeconds=time.time(), wallTime=startup.stamp(), reviewSHA256=sha(self.directory / 'review/review.json'))
        save(self.run / 'gui-ready.json', ready)
        self.record['status'] = 'awaiting-gui'
        save(self.run / 'result.json', self.record)
        print('G3_T07_GUI_READY=' + self.args.run_id, flush=True)
        print('GUI is paused after verified completion/coverage; current human confirmation and normal exit are pending.', flush=True)
        began, remaining = time.monotonic(), self.operation_deadline - time.monotonic()
        require(remaining > 0, 'timeout:whole-run')
        try:
            while True:
                # The published G3 plan excludes this separate human wait from
                # automatic execution. Processes, streams, pause and rate stay monitored.
                self.operation_deadline = time.monotonic() + remaining
                self.alive()
                request = self.run / 'request-gui-acceptance.json'
                if request.exists():
                    confirmation = load(request)
                    receipts.validate_confirmation(ready, confirmation, sha(self.run / 'gui-ready.json'),
                                                   sha(self.directory / 'review/review.json'))
                    self.record['manualGuiAcceptance'] = confirmation
                    self.item['manualGuiAcceptance'] = confirmation
                    self.transition('gui-confirmed', confirmationSHA256=sha(request))
                    break
                time.sleep(0.1)
        finally:
            duration = time.monotonic() - began
            self.manual_wait += duration
            self.record['manualWaitSeconds'] = self.manual_wait
            self.operation_deadline = time.monotonic() + remaining
        self.record['status'] = 'running'
        save(self.run / 'result.json', self.record)

    def audit(self):
        super().audit()
        sessions = [r for r in self.monitor.rows if r['type'] == 'afrl.cmasi.SessionStatus' and r['state'] == 1]
        require(sessions and all(r['realTimeMultiple'] == 1 for r in sessions), 'Actual running rate differs from 1')
        self.item['simulationRate'] = dict(configured=1, observed=dict(Counter(str(r['realTimeMultiple']) for r in sessions)), status='passed')
        if self.item['mode'] == 'Gui':
            require(bool(self.item.get('manualGuiAcceptance')), 'Current GUI confirmation missing')
            require(self.item['coverage'] == self.item['review']['coverage'] and
                    self.item['completion']['completion'] == self.item['review']['completion'], 'Post-close result differs from reviewed result')
            self.amase.verify_records(self.directory / 'review', self.item['review']['files'])
        self.paused_time = None

    def execute(self):
        self.prepare()
        for mode in ('Headless', 'Gui'):
            item = self.case(mode.lower(), mode)
            require(item['status'] == 'passed', item.get('error', 'Final full mission failed'))
        checks = module('stage_completion_checks', self.root / 'tests/g3_completion/checks.py')
        self.record['counterexamples'] = checks.verify(self, full.completion, full.coverage)
        require(self.record['inputs'] == self.inputs(), 'Stage runtime inputs changed')
        for key in ('configuration', 'executionConfiguration', 'completionConfiguration', 'acceptanceConfiguration'):
            require(sha(Path(self.context[key])) == self.record[key + 'SHA256'], 'Configuration changed: ' + key)
        require(receipts.verify(self) == self.record['priorReceipts'], 'Prior receipts changed during acceptance')
        require(self.protected_files() == self.protected, 'Qualified inputs changed')
        save(self.run / 'preservation-after.json', self.protected_files())
        automatic = time.monotonic() - self.started - self.manual_wait
        require(automatic < 2700, 'timeout:whole-run')
        self.record.update(status='passed', taskExecutionValidated=True, taskCompletionValidated=True, coverageValidated=True,
            inputsUnchanged=True, stageAccepted=True, qualifiedPackagesUnchanged=True,
            automaticWallSeconds=automatic, manualWaitSeconds=self.manual_wait)
        self.handoff()
        save(self.run / 'acceptance.json', dict(task='G3-T07', runId=self.args.run_id, status='passed',
            cases=[dict(name=c['name'], sha256=sha(self.run / c['name'] / 'case-result.json')) for c in self.record['cases']],
            handoffSHA256=sha(self.run / 'handoff.json'), priorReceipts=self.record['priorReceipts'],
            manualGuiAcceptance=self.record['manualGuiAcceptance'], inputs=self.record['inputs'],
            automaticWallSeconds=automatic, manualWaitSeconds=self.manual_wait))
        self.record['acceptanceSHA256'] = sha(self.run / 'acceptance.json')

    def handoff(self):
        configurations = [dict(path=p, sha256=sha(self.root / p)) for p in
            ('config/g3-startup.json', 'config/g3-execution.json', 'config/g3-completion.json', 'config/g3-acceptance.json')]
        save(self.run / 'handoff.json', dict(schemaVersion=1, task='G3-T07', runId=self.args.run_id, status='passed',
            artifacts=self.record['artifacts'], amaseBuildRunId=self.record['amaseBuildRunId'], formalUxas=self.record['formalUxas'],
            lmcpGenerationRunId=load(self.root / 'out/generated/lmcp/generation-info.json')['runId'],
            configurations=configurations, modes=self.config['modes'], topology='AMASE TCP server <-> UxAS TCP client; separate observer/controller TCP server',
            mainBridge=dict(ConsiderSelfGenerated=False, ExportOnlyLocalMessages=True,
                exports=['afrl.cmasi.MissionCommand','afrl.cmasi.LineSearchTask','afrl.cmasi.VehicleActionCommand','afrl.cmasi.KeyValuePair']),
            observerBridge=dict(ConsiderSelfGenerated=True, ExportOnlyLocalMessages=False, subscriptions=['afrl.','uxas.'],
                injectedSource='900/1', importedSource='100/TcpBridge', receivedMessagesForwarded=False),
            stateSource='AMASE source entity/service 0/0; vehicle IDs 400 and 500 are payload IDs',
            startup=['qualified inputs and ports', 'AMASE paused', 'UxAS and both TCP paths parseable', 'single start',
                     'both vehicle configurations and dynamic states', 'single task 1000', 'TaskInitialized', 'single original AutomationRequest'],
            time=dict(entityTime='simulation milliseconds, not UTC', taskTimes='UxAS Test_SimulationTime discrete simulation milliseconds',
                rate=1, scenarioSeconds=785, automaticWallLimitSeconds=2700, manualWaitExcluded=True, int64Encoding='decimal strings'),
            coverage=dict(gridResolutionMeters=20, waterwayPoints=90, minimumCoveragePercent=None, terrain='zero elevation fallback'),
            runs=[dict(mode=c['mode'], directory=c['name'], caseSHA256=sha(self.run / c['name'] / 'case-result.json'),
                completion=c['completion']['completion'], coverage=c['coverage'], simulationRate=c['simulationRate'],
                normalExit=c['normalExit'], portsReleased=c['portsReleased'],
                runtimeUxasConfigurationSHA256=sha(self.run / c['name'] / 'uxas/uxas.xml')) for c in self.record['cases']],
            priorReceipts=self.record['priorReceipts'], gatewayImplemented=False,
            deferred=['G4 online reconnect, snapshots and full recovery matrix', 'G6 reset/scenario time segmentation',
                      'Unicode business string generator fixes before such payloads', 'real terrain/calibrated coverage',
                      'G8 second machine/offline deployment', 'later algorithm and parameter optimization']))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(); args.keep_gui=False; args.verify=True; args.mode='Headless'
    require(re.fullmatch(r'g3-t07-[A-Za-z0-9-]{1,80}', args.run_id), 'Invalid stage run identity')
    task = Acceptance(args)
    try:
        task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True); return 1
    finally:
        task.record['finishedAt'] = startup.stamp()
        save(task.run / 'result.json', task.record)
        print('G3 stage evidence: ' + str(task.run), flush=True)


if __name__ == '__main__': sys.exit(main())

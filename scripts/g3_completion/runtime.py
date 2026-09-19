"""G3-T05 full task and native coverage, using qualified T03/T04 components."""
import argparse
import difflib
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import importlib.util


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


execution = module('completion_runtime_execution', Path(__file__).parents[1]/'g3_execution/runtime.py')
completion = module('completion_evidence', Path(__file__).with_name('completion.py'))
coverage = module('completion_coverage', Path(__file__).with_name('coverage.py'))
load, save, sha, require = execution.load, execution.save, execution.sha, execution.require


class Completion(execution.Execution):
    def __init__(self, args):
        super().__init__(args)
        self.record['task'] = 'G3-T05'

    def inputs(self):
        paths = [p for d in ('scripts/g3_completion', 'tests/g3_completion') for p in (self.root/d).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        paths += [self.root/p for p in ('scripts/windows/run-g3-completion.ps1', 'tests/windows/g3-completion.tests.ps1')]
        return super().inputs() + [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]

    def java_check(self, name, arguments, directory, headless=True):
        result = subprocess.run([str(self.java), '-Dfile.encoding=UTF-8', '-Djava.awt.headless='+str(headless).lower(),
            '-cp', os.pathsep.join(map(str, self.cp)), name, *map(str, arguments)],
            cwd=directory, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        (directory/'java.stdout').write_bytes(result.stdout); (directory/'java.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'Coverage Java check failed: '+str(directory))
        return dict(exitCode=result.returncode, headless=headless)

    def prepare(self):
        self.completion_policy = load(Path(self.context['completionConfiguration']))
        require(self.completion_policy == dict(schemaVersion=1, scope='completion', startupConfiguration='config/g3-startup.json',
            executionConfiguration='config/g3-execution.json', scenarioDurationSeconds=785, simulationRate=1,
            gridResolutionMeters=20, minimumCoveragePercent=None), 'T05 requires the frozen functional policy')
        super().prepare()
        self.record['completionConfigurationSHA256'] = sha(Path(self.context['completionConfiguration']))
        save(self.run/'completion-configuration.json', self.completion_policy)
        build = self.root/'out/build/g3-completion'/self.args.run_id
        classes = build/'classes'; classes.mkdir(parents=True)
        sources = [Path(__file__).with_name('CompletionProbe.java'),
                   self.root/'tests/g3_completion/CoverageChecks.java', self.root/'tests/g3_completion/AnalysisReplay.java',
                   self.root/'tests/g3_completion/TerminalChecks.java']
        result = subprocess.run([str(Path(self.context['javaHome'])/'bin/javac.exe'), '-encoding', 'UTF-8', '--release', '11',
            '-cp', os.pathsep.join(map(str, self.cp)), '-d', str(classes), *map(str, sources)],
            capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run/'completion-javac.stdout').write_bytes(result.stdout); (self.run/'completion-javac.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'Completion analysis plugin compile failed')
        self.cp.append(classes)
        self.record['completionPluginClasses'] = [dict(path=p.relative_to(build).as_posix(), sha256=sha(p)) for p in classes.rglob('*.class')]
        fixture_dir = self.run/'coverage-fixtures'; fixture_dir.mkdir()
        self.record['coverageFixtures'] = self.java_check('avtas.amase.analysis.CoverageChecks', [fixture_dir/'checks.xml'], fixture_dir)
        terminal_dir = self.run/'terminal-fixtures'; terminal_dir.mkdir()
        self.record['terminalFixtures'] = self.java_check('avtas.amase.entity.modules.TerminalChecks', [terminal_dir/'checks.xml'], terminal_dir)
        save(self.run/'result.json', self.record)

    def files(self, mode, fault):
        super().files(mode, fault)
        path = self.java_dir/'config/Plugins.xml'
        before = path.read_text(encoding='utf-8')
        tree = ET.parse(path)
        ET.SubElement(tree.getroot(), 'Plugin', Class='validation.g3.CompletionProbe')
        tree.write(path, encoding='utf-8', xml_declaration=True)
        with (self.directory/'configuration.diff').open('a', encoding='utf-8') as output:
            output.writelines(difflib.unified_diff(before.splitlines(True), path.read_text(encoding='utf-8').splitlines(True),
                                                   'T04-copy/Plugins.xml', 'T05-copy/Plugins.xml'))

    def body(self, mode, fault, keep_gui):
        execution.startup.Startup.body(self, mode, fault, False)
        self.transition('completion-started', originalDurationSeconds=785, simulationRate=1)
        cursor, latest, complete_ms, next_print = 0, {}, None, 0
        def finished():
            nonlocal cursor, complete_ms, next_print
            for row in list(self.observer.rows)[cursor:]:
                cursor += 1
                if row['type'] == 'afrl.cmasi.AirVehicleState':
                    state = completion.execution.state(completion.xml(row)); latest[state['entityId']] = state
                elif row['type'] == 'uxas.messages.task.TaskComplete':
                    require(complete_ms is None, 'Repeated TaskComplete')
                    complete_ms = int(completion.xml(row).findtext('TimeTaskCompleted'))
            sim_ms = max((int(s['timeMs']) for s in latest.values()), default=0)
            if time.monotonic() >= next_print:
                print(self.item['name']+' full task: '+str({e:dict(timeMs=s['timeMs'], waypoint=s['waypoint'], tasks=s['tasks'])
                                                         for e,s in latest.items()}), flush=True)
                next_print = time.monotonic()+30
            require(sim_ms < self.completion_policy['scenarioDurationSeconds']*1000,
                    'task-not-complete-within-frozen-duration')
            return complete_ms is not None and sim_ms >= complete_ms+3000
        self.wait('completion-observed', finished, self.completion_policy['scenarioDurationSeconds']+45)
        (self.java_dir/'request-pause').touch()
        self.wait('completion-paused', lambda: any(e['kind'] == 'paused' for e in self.amase.events(self.java_dir)))
        (self.java_dir/'request-analysis').touch()
        def exported():
            require(not (self.java_dir/'analysis-error').exists(), 'AMASE analysis export failed: '+
                    ((self.java_dir/'analysis-error').read_text(encoding='utf-8') if (self.java_dir/'analysis-error').exists() else ''))
            return (self.java_dir/'analysis-done').exists()
        self.wait('analysis-exported', exported)

    def audit(self):
        execution.startup.Startup.audit(self)
        result = completion.assess(self.observer.rows, self.monitor.rows, self.amase.events(self.java_dir), self.policy,
                                   ET.fromstring(self.input_message('request').toXMLStr('')), self.navigation())
        save(self.directory/'completion.json', result)
        self.item['completion'] = {k:v for k,v in result.items() if k != 'execution'}
        self.item['coverage'] = coverage.assess(self.directory, ET.parse(self.root/self.config['task']).getroot())
        original = ET.parse(self.java_dir/'analysis.xml').find('SearchTaskAnalysis')
        pixel_contents = []
        for mode in ('Headless', 'Gui'):
            folder = self.directory/('replay-'+mode.lower()); folder.mkdir()
            self.java_check('avtas.amase.analysis.AnalysisReplay',
                [self.java_dir/'analysis-events.tsv', self.java_dir/'config/Plugins.xml', folder], folder, mode=='Headless')
            for name in ('analysis.xml', 'incremental.xml', 'reset-replay.xml'):
                require(completion.execution.equivalent(original, ET.parse(folder/name).find('SearchTaskAnalysis')),
                        'Replay report differs: '+mode+'/'+name)
            pixel_contents.append((folder/'pixels.csv').read_bytes())
        require(pixel_contents[0] == pixel_contents[1], 'Same events yield different GUI/headless pixels')
        self.item['coverage']['sameEventsBothModesMatched'] = True
        save(self.directory/'coverage.json', self.item['coverage'])
        self.item['planningReceipt']['actualExecutionValidated'] = True

    def execute(self):
        self.prepare()
        for mode in (('Headless','Gui') if self.args.verify else (self.args.mode,)):
            item = self.case(mode.lower(), mode)
            require(item['status'] == 'passed', item.get('error', 'Completion failed'))
        if self.args.verify:
            checks = module('completion_checks', self.root/'tests/g3_completion/checks.py')
            self.record['counterexamples'] = checks.verify(self, completion, coverage)
        require(self.record['inputs'] == self.inputs(), 'Runtime inputs changed')
        for key in ('configuration', 'executionConfiguration', 'completionConfiguration'):
            require(sha(Path(self.context[key])) == self.record[key+'SHA256'], 'Configuration changed: '+key)
        self.amase.verify_records(self.root, self.baseline['frozenInputs'])
        self.record.update(status='passed', taskExecutionValidated=True, taskCompletionValidated=True, coverageValidated=True,
                           inputsUnchanged=True, manualGuiAcceptance=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui','Headless'], default='Headless')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(); args.keep_gui = False
    require(re.fullmatch(r'g3-t05-[A-Za-z0-9-]+', args.run_id), 'Invalid completion run identity')
    task = Completion(args)
    try:
        task.execute(); return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: '+str(error), flush=True); return 1
    finally:
        task.record['finishedAt'] = execution.startup.stamp()
        save(task.run/'result.json', task.record)
        print('G3 completion evidence: '+str(task.run), flush=True)


if __name__ == '__main__': sys.exit(main())

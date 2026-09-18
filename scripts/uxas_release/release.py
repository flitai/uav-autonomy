"""T07 qualification, two-phase publication, and qualified HelloWorld consumption."""
import argparse
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import traceback

spec = importlib.util.spec_from_file_location('release_package', Path(__file__).with_name('package.py'))
package = importlib.util.module_from_spec(spec); spec.loader.exec_module(package)
runtime, lmcp = package.runtime, package.lmcp
require, load, save, sha, child = package.require, package.load, package.save, package.sha, package.child


def entry_check(directory):
    runtime.build.entry_check(directory)
    entry = load(directory / 'entry-result.json')
    require(entry['locationRestored'] and entry['encodingRestored'], 'Release entry restoration differs')


def release_receipt(root, run_id, provenance):
    require(re.fullmatch(r'g2-t07-test-[\d-]+', run_id), 'Invalid T07 validation ID')
    directory = child(root / 'out/runs', run_id)
    entry_check(directory)
    result, receipt = load(directory / 'result.json'), load(directory / 'acceptance.json')
    require(result['status'] == receipt['status'] == 'passed' and result['sourcesUnchanged'] and
            result['provenance'] == receipt['provenance'] == provenance and
            receipt['runId'] == result['runId'] == run_id and
            result['acceptanceSHA256'] == sha(directory / 'acceptance.json') and
            result['releaseInputs'] == receipt['releaseInputs'] == package.inputs(root), 'T07 receipt differs')
    require(package.hello_receipt(root, receipt['helloWorld']['runId'], provenance) == receipt['helloWorld'],
            'T06 receipt changed')
    for case, sealed in zip(result['cases'], receipt['cases'], strict=True):
        location = child(directory, case['name'])
        require(case['name'] == sealed['name'] and sha(location / 'case-result.json') == sealed['sha256'],
                'T07 case receipt differs')
        package.check_case(location, case)
    require(sha(directory / 'fault-checks.json') == receipt['faultChecksSHA256'] and
            sha(directory / 'preservation.json') == receipt['preservationSHA256'], 'T07 auxiliary evidence differs')
    faults = load(directory / 'fault-checks.json')
    require(faults['status'] == 'passed' and faults['previousPointerPreserved'] and faults['previousPackagePreserved'],
            'Publication failure checks did not pass')
    lmcp.check_records(directory / 'isolated-faults', faults['files'])
    staging = child(root / 'out/build/uxas', run_id) / 'release-candidate'
    info = package.check(staging, receipt['packageInfoSHA256'], provenance)
    require(info['releaseInputs'] == receipt['releaseInputs'] and info['helloWorld'] == receipt['helloWorld'] and
            info['releaseRunId'] == run_id, 'Staged release source identity differs')
    return receipt, staging


def resolve(root, provenance):
    store = root / 'out/artifacts/uxas'
    pointer = load(store / 'current.json')
    require(pointer['status'] == 'passed' and pointer['buildRunId'] == provenance['buildRunId'] and
            pointer['validationRunId'] == provenance['validationRunId'] and
            re.fullmatch(r'g2-t07-publish-[\d-]+', pointer['publishRunId']), 'Formal pointer identity differs')
    expected = '/'.join((pointer['buildRunId'], pointer['releaseRunId'], pointer['publishRunId']))
    require(pointer['path'] == expected, 'Formal package path differs')
    receipt, staging = release_receipt(root, pointer['releaseRunId'], provenance)
    published = child(root / 'out/runs', pointer['publishRunId'])
    entry_check(published)
    result = load(published / 'result.json')
    require(result['status'] == 'passed' and result['published'] and result['pointer'] == pointer and
            result['releaseAcceptanceSHA256'] == sha(child(root / 'out/runs', pointer['releaseRunId']) / 'acceptance.json') and
            pointer['buildInfoSHA256'] == receipt['packageInfoSHA256'], 'Formal publication not qualified')
    destination = child(store, pointer['path'])
    info = package.check(destination, pointer['buildInfoSHA256'], provenance)
    require(info['releaseInputs'] == package.inputs(root), 'Formal runtime inputs changed')
    package.runtime_files(destination)
    return destination, pointer


def preservation(root):
    paths = ['out/artifacts/deps/current.json', 'out/artifacts/lmcp/cpp/current.json',
             'out/artifacts/lmcp/build-info.json', 'out/generated/lmcp/generation-info.json',
             'out/artifacts/amase/build-info.json', 'out/artifacts/amase/OpenAMASE.jar']
    paths += [p.relative_to(root).as_posix() for p in (root / 'out/build/uxas').glob('*/candidate/*') if p.is_file()]
    paths += [p.relative_to(root).as_posix() for p in (root / 'out/artifacts/uxas').rglob('*') if p.is_file()]
    return [dict(path=p, sha256=sha(root / p)) for p in sorted(paths)]


class Task:
    def __init__(self, args):
        self.args, self.root = args, args.root
        mode = 'publish' if args.mode == 'commit' else args.mode
        require(re.fullmatch(r'g2-t07-' + mode + r'-[\d-]+', args.run_id), 'Invalid T07 run ID')
        self.run = child(self.root / 'out/runs', args.run_id)
        self.run.mkdir(parents=True, exist_ok=True)
        self.record = dict(schemaVersion=1, task='G2-T07', runId=args.run_id, mode=mode,
                           status='running', startedAt=lmcp.stamp(), cases=[], published=False)
        self.original = self.root / 'OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml'

    def case(self, name, executable, original=None, fault=None):
        directory = child(self.run, name); directory.mkdir()
        config = directory / 'cfg_HelloWorld.xml'
        original = original or self.original
        if fault != 'missing':
            data = original.read_bytes()
            if fault == 'malformed':
                data = b'<UxAS><Service'
            elif fault == 'timeout':
                require(b'RunDuration_s="10.0"' in data, 'Unexpected timeout source')
                data = data.replace(b'RunDuration_s="10.0"', b'RunDuration_s="60.0"')
            elif fault:
                data = data.replace(b'</UxAS>', ('<Bridge Type="' + fault + '"/></UxAS>').encode())
            config.write_bytes(data)
            if not fault:
                require(sha(config) == sha(original) == sha(self.original), 'Original config differs')
        item = dict(name=name, status='running', executable=str(executable), executableSHA256=sha(executable),
                    configSHA256=sha(config) if config.exists() else None)
        self.record['cases'].append(item)
        save(self.run / 'result.json', self.record)
        try:
            execution = runtime.process(directory, [executable, '-cfgPath', config])
            item['process'] = execution
            application, logs = runtime.application_logs(directory)
            stdout = (directory / 'stdout.log').read_bytes()
            item['applicationLogs'] = logs
            if not fault:
                evidence = runtime.analysis.analyze(stdout, application, execution, config, self.services)
                save(directory / 'messages.json', evidence)
                require(evidence['status'] == 'passed', '; '.join(evidence['errors']))
                item.update(status='passed', directions=evidence['directions'])
            elif fault == 'timeout':
                require(execution['timedOut'] and execution['forcedTermination'] and execution['reaped'] and
                        execution['exitCode'] != 0 and 30 <= execution['elapsedSeconds'] < 40 and
                        b'RECEIVED' in stdout and 'set run duration seconds 60' in application,
                        'Real UxAS timeout/cleanup evidence differs')
                item.update(status='failed', expectedFailureVerified=True, usesUxas=True)
            else:
                expected = 100 if fault in ('missing', 'malformed') else 300
                diagnostics = application + stdout.decode('utf-8') + (directory / 'stderr.log').read_text(encoding='utf-8')
                require(execution['exitCode'] == expected and execution['reaped'] and
                        not execution['forcedTermination'] and not execution['timedOut'], 'Configuration rejection differs')
                if expected == 100:
                    require('failed to load base XML configuration from [' + str(config) + ']' in diagnostics,
                            'Configuration diagnostic missing')
                else:
                    switch = 'UXAS_ENABLE_SERIAL' if 'Serial' in fault else 'UXAS_ENABLE_ZYRE'
                    require(fault + ' is unavailable (' + switch + '=OFF)' in diagnostics, 'Bridge diagnostic missing')
                require('UxAS_Main created networkServer' not in application and
                        'successfully created HelloWorld service ID' not in application and b'RECEIVED' not in stdout,
                        'Rejected configuration started network/services')
                item.update(status='failed', expectedFailureVerified=True, expectedExitCode=expected)
            require(sha(executable) == item['executableSHA256'] and
                    (sha(config) if config.exists() else None) == item['configSHA256'], 'Runtime input changed')
            print(name + ': ' + ('expected failure verified' if fault else 'passed'), flush=True)
        except BaseException as error:
            item.update(status='failed', error=str(error))
            raise
        finally:
            item['files'] = lmcp.files(directory)
            save(directory / 'case-result.json', item)
            save(self.run / 'result.json', self.record)

    def test(self):
        hello = package.hello_receipt(self.root, self.args.hello_world_run_id, self.provenance)
        self.record['helloWorld'] = hello
        before = preservation(self.root)
        executable = self.candidate / 'uxas.exe'
        for index in range(1, 4):
            self.case('repeat-' + str(index), executable)
        validation = child(self.root / 'out/runs', self.provenance['validationRunId'])
        modules = load(validation / 'unicode-loaded-modules.json')['modules']
        compiled = [(Path(p), digest) for p, digest in modules.items() if Path(p).name.lower() == 'uxas.exe']
        require(len(compiled) == 1, 'Unicode build executable identity missing')
        unicode_exe, digest = compiled[0]
        require(unicode_exe.is_relative_to(self.root / 'out/build/uxas' / self.provenance['validationRunId']) and
                sha(unicode_exe) == digest, 'Unicode compiled candidate differs')
        self.case('中文 空格运行', unicode_exe)
        require(sha(unicode_exe) == digest, 'Unicode executable changed')
        for name, fault in [('missing-configuration', 'missing'), ('malformed-configuration', 'malformed'),
                            ('disabled-serial', 'LmcpObjectNetworkSerialBridge'),
                            ('disabled-zyre', 'LmcpObjectNetworkZeroMqZyreBridge'), ('uxas-timeout', 'timeout')]:
            self.case(name, executable, fault=fault)
        staging = child(self.root / 'out/build/uxas', self.args.run_id) / 'release-candidate'
        info = package.create(self.root, staging, self.provenance, hello, self.args.run_id)
        self.record['crtFiles'] = package.runtime_files(staging)
        self.case('staged-package', staging / 'uxas.exe', staging / 'cfg_HelloWorld.xml')
        checks = runtime.module('release_checks', self.root / 'tests/uxas_release/checks.py')
        checks.run(package, self.root, self.run, staging, self.provenance)
        require(preservation(self.root) == before, 'Existing candidate/artifact changed')
        save(self.run / 'preservation.json', dict(status='passed', before=before, after=preservation(self.root)))
        self.unchanged()
        info['status'] = 'passed'
        save(staging / 'build-info.json', info)
        package.check(staging, sha(staging / 'build-info.json'), self.provenance)
        receipt = dict(schemaVersion=1, task='G2-T07', status='passed', runId=self.args.run_id,
                       provenance=self.provenance, helloWorld=hello, releaseInputs=self.record['releaseInputs'],
                       packageInfoSHA256=sha(staging / 'build-info.json'),
                       cases=[dict(name=c['name'], sha256=sha(child(self.run, c['name']) / 'case-result.json'))
                              for c in self.record['cases']], faultChecksSHA256=sha(self.run / 'fault-checks.json'),
                       preservationSHA256=sha(self.run / 'preservation.json'))
        save(self.run / 'acceptance.json', receipt)
        self.record['acceptanceSHA256'] = sha(self.run / 'acceptance.json')

    def publish(self):
        receipt, staging = release_receipt(self.root, self.args.release_run_id, self.provenance)
        store = self.root / 'out/artifacts/uxas'
        relative = '/'.join((self.provenance['buildRunId'], self.args.release_run_id, self.args.run_id))
        destination = child(store, relative)
        require(not destination.exists(), 'Publication output must be new')
        previous = sha(store / 'current.json') if (store / 'current.json').exists() else None
        shutil.copytree(staging, destination)
        package.check(destination, receipt['packageInfoSHA256'], self.provenance)
        package.runtime_files(destination)
        self.case('published-location', destination / 'uxas.exe', destination / 'cfg_HelloWorld.xml')
        self.unchanged()
        pointer = dict(schemaVersion=1, status='passed', path=relative, buildRunId=self.provenance['buildRunId'],
                       validationRunId=self.provenance['validationRunId'], releaseRunId=self.args.release_run_id,
                       publishRunId=self.args.run_id, buildInfoSHA256=receipt['packageInfoSHA256'])
        self.record.update(status='prepared', pointer=pointer, previousPointerSHA256=previous,
                           releaseAcceptanceSHA256=sha(child(self.root / 'out/runs', self.args.release_run_id) / 'acceptance.json'))
        print('Package prepared; pointer commit follows successful environment restoration.', flush=True)

    def commit(self):
        entry_check(self.run)
        self.record = load(self.run / 'result.json')
        require(self.record['status'] == 'prepared' and not self.record['published'], 'Publication not prepared')
        self.provenance = self.record['provenance']
        self.candidate = package.candidate_args(self.root, self.provenance).candidate
        self.unchanged()
        pointer = self.record['pointer']
        receipt, staging = release_receipt(self.root, pointer['releaseRunId'], self.provenance)
        require(receipt['packageInfoSHA256'] == pointer['buildInfoSHA256'], 'Prepared metadata differs')
        store = self.root / 'out/artifacts/uxas'
        package.check(child(store, pointer['path']), pointer['buildInfoSHA256'], self.provenance)
        package.runtime_files(child(store, pointer['path']))
        for case in self.record['cases']:
            package.check_case(child(self.run, case['name']), case)
        current = sha(store / 'current.json') if (store / 'current.json').exists() else None
        require(current == self.record['previousPointerSHA256'], 'Concurrent formal pointer change')
        def finish():
            self.record.update(status='passed', published=True, finishedAt=lmcp.stamp())
            save(self.run / 'result.json', self.record)
        package.switch_pointer(store, pointer, self.args.run_id, finish)
        print('Formal UxAS published: ' + str(child(store, pointer['path'])), flush=True)

    def unchanged(self):
        require(runtime.qualified(package.candidate_args(self.root, self.provenance)) == self.provenance and
                package.inputs(self.root) == self.record['releaseInputs'], 'Release source changed')
        self.record['sourcesUnchanged'] = True

    def execute(self):
        try:
            require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.flags.isolated,
                    'Expected isolated Python 3.14.7 x64')
            with ExitStack() as locks:
                for path in ('out/build/uxas/task.lock', 'out/build/lmcp/generate.lock', 'out/build/lmcp-cpp/task.lock'):
                    locks.enter_context(lmcp.lock(self.root / path))
                if self.args.mode == 'commit':
                    self.commit()
                else:
                    selected = dict(buildRunId=self.args.build_run_id, validationRunId=self.args.validation_run_id)
                    self.candidate = package.candidate_args(self.root, selected).candidate
                    self.provenance = runtime.qualified(package.candidate_args(self.root, selected))
                    self.services = runtime.analysis.configuration(self.original.read_bytes())
                    self.record.update(provenance=self.provenance, releaseInputs=package.inputs(self.root),
                                       gitHead=subprocess.check_output(['git', '-C', self.root, 'rev-parse', 'HEAD'], encoding='utf-8').strip(),
                                       gitStatus=subprocess.check_output(['git', '-C', self.root, 'status', '--short'], encoding='utf-8'),
                                       pythonVersion=sys.version, pythonExecutable=sys.executable)
                    if self.args.mode == 'test':
                        self.test()
                    elif self.args.mode == 'publish':
                        self.publish()
                    else:
                        destination, pointer = resolve(self.root, self.provenance)
                        self.record['pointer'] = pointer
                        if self.args.mode == 'run':
                            self.case('HelloWorld', destination / 'uxas.exe', destination / 'cfg_HelloWorld.xml')
                        resolve(self.root, self.provenance)
                    self.unchanged()
                    if self.args.mode != 'publish':
                        self.record['status'] = 'passed'
            return 0
        except BaseException as error:
            self.record.update(status='failed', published=False, error=str(error), traceback=traceback.format_exc())
            print('FAILED: ' + str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = lmcp.stamp()
            # A committed result was persisted inside the rollback boundary already.
            if not (self.args.mode == 'commit' and self.record.get('published') and self.record['status'] == 'passed'):
                save(self.run / 'result.json', self.record)
            print('T07 evidence: ' + str(self.run), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('test', 'publish', 'commit', 'run', 'resolve'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    for name in ('build-run-id', 'validation-run-id', 'hello-world-run-id', 'release-run-id'):
        parser.add_argument('--' + name)
    args = parser.parse_args(); args.root = args.root.resolve()
    return Task(args).execute()


if __name__ == '__main__':
    sys.exit(main())

"""G2-T06 qualified HelloWorld execution. Standard library, no external bridge."""
import argparse
import importlib.util
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


build = module('uxas_build', Path(__file__).parents[1] / 'uxas/build.py')
analysis = module('hello_analysis', Path(__file__).with_name('analyze.py'))
lmcp = build.lmcp
require, load, save, sha, child = build.require, build.load, build.save, build.sha, build.child


def runtime_inputs(root):
    paths = ['scripts/windows/run-uxas.ps1', 'scripts/windows/uxas-runtime-common.ps1',
             'tests/windows/uxas-helloworld.tests.ps1', 'scripts/windows/uxas-build-common.ps1',
             'scripts/windows/lmcp-cpp-common.ps1', 'scripts/windows/deps-common.ps1',
             'scripts/windows/cpp-common.ps1', 'scripts/lmcp_cpp/manage.py']
    for directory in ('scripts/uxas_runtime', 'tests/uxas_runtime'):
        paths.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob('*') if p.is_file())
    return [dict(path=p, sha256=sha(root / p)) for p in sorted(paths)]


def qualified(args):
    root = args.root
    require(re.fullmatch(r'g2-t05-build-[\d-]+', args.build_run_id) and
            re.fullmatch(r'g2-t05-test-[\d-]+', args.validation_run_id), 'Invalid T05 run identities')
    previous = child(root / 'out/runs', args.build_run_id)
    validation = child(root / 'out/runs', args.validation_run_id)
    candidate = child(root / 'out/build/uxas', args.build_run_id) / 'candidate'
    require(args.candidate.resolve() == candidate, 'Candidate path does not match build identity')
    build.entry_check(previous); build.entry_check(validation)
    source, checked = load(previous / 'result.json'), load(validation / 'result.json')
    context, receipt = load(previous / 'context.json'), load(validation / 'acceptance.json')
    require(source['status'] == 'candidate' and source['runId'] == args.build_run_id, 'Build was not qualified')
    info = build.candidate_check(root, candidate, context, source['candidateInfoSHA256'])
    require(info['runId'] == args.build_run_id and checked['status'] == receipt['status'] == 'passed' and
            checked['buildRunId'] == receipt['buildRunId'] == args.build_run_id and
            receipt['validationRunId'] == args.validation_run_id and
            sha(validation / 'acceptance.json') == checked['acceptanceSHA256'] and
            receipt['candidateInfoSHA256'] == checked['candidateInfoSHA256'] == source['candidateInfoSHA256'] and
            receipt['files'] == info['files'] and receipt['inputs'] == context['inputs'] and
            receipt['packages'] == context['packages'], 'Candidate acceptance receipt differs')
    return dict(buildRunId=args.build_run_id, validationRunId=args.validation_run_id,
                candidateInfoSHA256=source['candidateInfoSHA256'], executableSHA256=sha(candidate / 'uxas.exe'),
                acceptanceSHA256=sha(validation / 'acceptance.json'), packages=context['packages'])


def process(directory, arguments, timeout=30):
    """Own and reap the exact child handle, including timeout/exception cleanup."""
    argv = [str(a) for a in arguments]
    record = dict(status='running', arguments=argv, workingDirectory=str(directory),
                  startedAt=lmcp.stamp(), timeoutSeconds=timeout, timedOut=False,
                  forcedTermination=False, reaped=False, exitCode=None)
    started = time.monotonic()
    try:
        with (directory / 'stdout.log').open('wb') as out, (directory / 'stderr.log').open('wb') as err:
            child_process = subprocess.Popen(argv, cwd=directory, stdout=out, stderr=err,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
            record['pid'] = child_process.pid
            try:
                save(directory / 'process.json', record)
                child_process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record['timedOut'] = True
            finally:
                if child_process.poll() is None:
                    record['forcedTermination'] = True
                    child_process.kill()
                child_process.wait(timeout=10)
                record.update(exitCode=child_process.returncode, reaped=child_process.poll() is not None)
        record['status'] = 'exited' if record['exitCode'] == 0 and not record['forcedTermination'] else 'failed'
    except BaseException as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        record.update(finishedAt=lmcp.stamp(), elapsedSeconds=time.monotonic() - started)
        save(directory / 'process.json', record)
    return record


def application_logs(directory):
    paths = sorted((directory / 'log').glob('log_*'), key=lambda p: int(p.name.split('_')[1]))
    require(paths, 'No application logs in owned working directory')
    return ''.join(p.read_text(encoding='utf-8') for p in paths), [dict(path=p.relative_to(directory).as_posix(), sha256=sha(p)) for p in paths]


class Task:
    def __init__(self, args):
        self.args = args
        self.root = args.root
        require(re.fullmatch(r'g2-t06-' + args.mode + r'-[\d-]+', args.run_id), 'Invalid T06 run ID')
        self.run = child(self.root / 'out/runs', args.run_id)
        self.record = dict(schemaVersion=1, task='G2-T06', runId=args.run_id, mode=args.mode,
                           startedAt=lmcp.stamp(), status='running', cases=[], formalRelease=False)
        self.original = self.root / 'OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml'

    def case(self, name, fault=None):
        directory = child(self.run, name)
        directory.mkdir()
        config = directory / 'cfg_HelloWorld.xml'
        if fault != 'missing':
            shutil.copyfile(self.original, config)
            if fault:
                data = config.read_bytes().replace(b'</UxAS>', ('<Bridge Type="' + fault + '"/></UxAS>').encode())
                config.write_bytes(data)
            else:
                require(sha(config) == self.config_hash, 'Configuration copy hash mismatch')
                analysis.configuration(config.read_bytes())
        entry = dict(name=name, directory=str(directory), status='running',
                     configPath=str(config), configSHA256=sha(config) if config.exists() else None)
        self.record['cases'].append(entry)
        save(self.run / 'result.json', self.record)
        require(qualified(self.args) == self.provenance, 'Candidate provenance changed before launch')
        try:
            execution = process(directory, [self.args.candidate / 'uxas.exe', '-cfgPath', config])
            entry['process'] = execution
            stdout = (directory / 'stdout.log').read_bytes()
            application, files = application_logs(directory)
            entry['applicationLogs'] = files
            if not fault:
                evidence = analysis.analyze(stdout, application, execution, config, self.services)
                save(directory / 'messages.json', evidence)
                entry.update(status=evidence['status'], messageEvidenceSHA256=sha(directory / 'messages.json'),
                             directions=evidence['directions'], selfReceivedCount=evidence['selfReceivedCount'])
                require(evidence['status'] == 'passed', '; '.join(evidence['errors']))
            else:
                # The process failure remains failed; only its expected rejection is verified.
                entry['status'] = 'failed'
                expected = 100 if fault == 'missing' else 300
                require(execution['exitCode'] == expected and not execution['timedOut'] and
                        not execution['forcedTermination'] and execution['reaped'], 'Wrong configuration failure behavior')
                diagnostics = application + stdout.decode('utf-8') + (directory / 'stderr.log').read_text(encoding='utf-8')
                if fault == 'missing':
                    require('failed to load base XML configuration from [' + str(config) + ']' in diagnostics,
                            'Missing configuration was not diagnosed')
                else:
                    switch = 'UXAS_ENABLE_SERIAL' if 'Serial' in fault else 'UXAS_ENABLE_ZYRE'
                    require(fault + ' is unavailable (' + switch + '=OFF)' in diagnostics, 'Disabled bridge diagnostic differs')
                require('UxAS_Main created networkServer' not in application and
                        'successfully created HelloWorld service ID' not in application and b'RECEIVED' not in stdout,
                        'Rejected configuration unexpectedly started network/services')
                entry.update(expectedFailureVerified=True, expectedExitCode=expected)
            if config.exists():
                require(sha(config) == entry['configSHA256'], 'Run configuration changed')
            print(name + ': ' + ('expected failure verified' if fault else 'passed') +
                  ', exit ' + str(execution['exitCode']), flush=True)
            return directory, stdout, application, execution
        except BaseException as error:
            entry.update(status='failed', error=str(error))
            raise
        finally:
            entry['files'] = lmcp.files(directory)
            save(directory / 'case-result.json', entry)
            save(self.run / 'result.json', self.record)

    def test(self):
        ordinary = self.case('ordinary')
        self.case('\u4e2d\u6587 HelloWorld run')
        self.case('missing-configuration', 'missing')
        self.case('disabled-serial', 'LmcpObjectNetworkSerialBridge')
        self.case('disabled-zyre', 'LmcpObjectNetworkZeroMqZyreBridge')
        tests = module('hello_tests', self.root / 'tests/uxas_runtime/checks.py')
        checks = tests.check_parser(analysis, ordinary, self.services)
        self.record['parserChecks'] = checks
        timeout_dir = self.run / 'owned-timeout'
        timeout_dir.mkdir()
        execution = process(timeout_dir, [sys.executable, '-I', '-B', '-c', 'import time; time.sleep(60)'], timeout=0.2)
        require(execution['status'] == 'failed' and execution['timedOut'] and execution['forcedTermination'] and
                execution['reaped'] and execution['exitCode'] != 0, 'Timeout cleanup was not an owned process failure')
        self.record['timeoutCheck'] = dict(expectedFailureVerified=True, process=execution,
                                           processSHA256=sha(timeout_dir / 'process.json'), usesUxas=False)
        print('parser counterexamples and owned timeout: passed', flush=True)

    def execute(self):
        try:
            require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.flags.isolated,
                    'Expected isolated Python 3.14.7 x64')
            with lmcp.lock(self.root / 'out/build/uxas/task.lock'), lmcp.lock(self.root / 'out/build/lmcp/generate.lock'), \
                    lmcp.lock(self.root / 'out/build/lmcp-cpp/task.lock'):
                self.provenance = qualified(self.args)
                inputs = runtime_inputs(self.root)
                self.config_hash = sha(self.original)
                self.services = analysis.configuration(self.original.read_bytes())
                git_head = subprocess.check_output(['git', '-C', self.root, 'rev-parse', 'HEAD'], encoding='utf-8').strip()
                git_status = subprocess.check_output(['git', '-C', self.root, 'status', '--short'], encoding='utf-8')
                self.record.update(provenance=self.provenance, runtimeInputs=inputs, configSHA256=self.config_hash,
                                   gitHead=git_head, gitStatus=git_status, pythonVersion=sys.version, pythonExecutable=sys.executable)
                save(self.run / 'result.json', self.record)
                if self.args.mode == 'run':
                    self.case('HelloWorld')
                else:
                    self.test()
                require(qualified(self.args) == self.provenance and sha(self.original) == self.config_hash and
                        runtime_inputs(self.root) == inputs, 'Source changed during HelloWorld execution')
                self.record.update(status='passed', sourcesUnchanged=True)
                if self.args.mode == 'test':
                    receipt = dict(schemaVersion=1, task='G2-T06', status='passed', runId=self.args.run_id,
                                   provenance=self.provenance, runtimeInputs=inputs, formalRelease=False,
                                   cases=[dict(name=c['name'], sha256=sha(Path(c['directory']) / 'case-result.json'))
                                          for c in self.record['cases']],
                                   parserChecks=sha(self.run / 'parser-checks.json'),
                                   timeoutCheck=self.record['timeoutCheck'])
                    save(self.run / 'acceptance.json', receipt)
                    self.record['acceptanceSHA256'] = sha(self.run / 'acceptance.json')
            return 0
        except BaseException as error:
            self.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
            print('FAILED: ' + str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = lmcp.stamp()
            save(self.run / 'result.json', self.record)
            print('HelloWorld evidence: ' + str(self.run), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('run', 'test'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--build-run-id', required=True)
    parser.add_argument('--validation-run-id', required=True)
    args = parser.parse_args()
    args.root = args.root.resolve()
    return Task(args).execute()


if __name__ == '__main__':
    sys.exit(main())

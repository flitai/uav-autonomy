"""G2-T03 native LMCP build/acceptance. Python standard library; no downloads."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import traceback


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    require(path.is_file(), 'Required file missing: ' + str(path))
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def stamp():
    return datetime.now().astimezone().isoformat()


def child(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()) and path != root.resolve(), 'Path escapes owned root')
    return path


def check_records(root, records):
    require(records, 'Empty provenance inventory')
    for item in records:
        require(sha(child(root, item['path'])) == item['sha256'], 'Input hash mismatch: ' + item['path'])


def files(root):
    return [dict(path=p.relative_to(root).as_posix(), sha256=sha(p))
            for p in sorted(root.rglob('*')) if p.is_file() and p != root / 'build-info.json']


def check_model_set(directory, models):
    actual = {p.name for p in directory.iterdir() if p.suffix.lower() in ('.xml', '.mdm')}
    require(actual == {m['file'] for m in models}, 'MDM file set differs from the seven locked models')


def generation(root):
    generated = root / 'out/generated/lmcp'
    g = load(generated / 'generation-info.json')
    parent = load(root / 'out/artifacts/lmcp/build-info.json')
    generator = load(root / 'out/artifacts/lmcpgen/build-info.json')
    require(parent['status'] == generator['status'] == 'passed', 'G1 parent status differs')
    require(g['runId'] == parent['runId'] and g['files'] == parent['generatedFiles'] and
            g['models'] == parent['models'] and g['artifact'] == parent['artifact'] and
            g['generator'] == parent['generator'], 'G1 parent/generation identity differs')
    check_records(root, parent['inputs'])
    check_records(root, generator['inputs'])
    require(sha(root / g['artifact']['path']) == g['artifact']['sha256'], 'Java artifact hash differs')
    require(g['generator']['t02RunId'] == generator['runId'] and
            g['generator']['sha256'] == sha(root / 'out/artifacts/lmcpgen/LmcpGen.jar'), 'Generator identity differs')
    check_records(generated, g['files'])
    actual = {p.relative_to(generated).as_posix() for p in generated.rglob('*') if p.is_file()}
    require(actual == {f['path'] for f in g['files']} | {'generation-info.json'}, 'G1 generated file inventory differs')
    config = load(root / 'config/lmcp-models.json')
    check_model_set(child(root, config['source']), config['models'])
    require(len(g['models']) == 7 and all(any(all(m[k] == locked[k] for k in locked) for m in g['models'])
            for locked in config['models']), 'Seven model identities differ')
    cpp = [f for f in g['files'] if f['path'].startswith('cpp/')]
    require(len(cpp) == 588, 'Expected 588 generated C++ files')
    return g


def input_records(root, deps):
    paths = ['CMakeLists.txt', 'scripts/windows/build-lmcp-cpp.ps1', 'scripts/windows/lmcp-cpp-common.ps1',
             'tests/windows/lmcp-cpp.tests.ps1', 'config/windows-cpp-toolchain.json', 'scripts/windows/cpp-common.ps1',
             'scripts/windows/deps-common.ps1', 'out/artifacts/lmcp/build-info.json',
             'out/generated/lmcp/generation-info.json', 'out/artifacts/deps/current.json',
             (deps / 'build-info.json').relative_to(root).as_posix()]
    for directory in ('cmake', 'scripts/lmcp_cpp', 'tests/lmcp_cpp'):
        paths.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob('*') if p.is_file())
    return [dict(path=p, sha256=sha(root / p)) for p in sorted(paths)]


def check_package(root, prefix, info, expected_inputs, generation_id):
    require(info['status'] in ('candidate', 'passed') and info['generationRunId'] == generation_id and
            info['configuration'] == 'Release-x64-v143-MD-cxx14', 'LMCP metadata identity differs')
    require(info['inputs'] == expected_inputs, 'LMCP build inputs differ; rebuild the candidate')
    check_records(root, info['inputs'])
    check_records(prefix, info['files'])
    require(files(prefix) == info['files'], 'LMCP package inventory differs')


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class Task:
    def __init__(self, args):
        self.args = args
        self.root = args.root.resolve()
        self.run = child(self.root / 'out/runs', args.run_id)
        self.context = load(args.context)
        self.tools = self.context['tools']
        self.cmake = self.tools['cmake']
        self.deps = Path(self.context['dependencies'])
        self.record = dict(schemaVersion=1, task='G2-T03', runId=args.run_id, status='running',
                           startedAt=stamp(), commands=[], checks=[], context=self.context)
        self.cwd = self.run / 'other working directory'
        self.cwd.mkdir()

    def command(self, name, arguments, cwd=None, expect=0, timeout=600):
        argv = [str(a) for a in arguments]
        entry = dict(label=name, arguments=argv, workingDirectory=str(cwd or self.cwd), startedAt=stamp())
        self.record['commands'].append(entry)
        stdout, stderr = self.run / (name + '.stdout.log'), self.run / (name + '.stderr.log')
        try:
            with stdout.open('wb') as out, stderr.open('wb') as err:
                with subprocess.Popen(argv, cwd=cwd or self.cwd, stdout=out, stderr=err) as result:
                    entry['pid'] = result.pid
                    try:
                        result.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        # Only the still-owned child and its build descendants are stopped.
                        if result.poll() is None:
                            subprocess.run(['taskkill.exe', '/PID', str(result.pid), '/T', '/F'],
                                           stdout=err, stderr=err, timeout=30)
                        raise
            entry['exitCode'] = result.returncode
        except subprocess.TimeoutExpired:
            entry.update(exitCode=None, timedOut=True)
            raise RuntimeError(name + ' timed out')
        finally:
            entry.update(finishedAt=stamp(), stdout=str(stdout), stderr=str(stderr))
            save(self.run / 'result.json', self.record)
        require(result.returncode == expect, name + ': unexpected exit ' + str(result.returncode) + '; see ' + str(self.run))
        print(name + ': exit ' + str(result.returncode), flush=True)
        return stdout.read_text(encoding='utf-8', errors='replace') + stderr.read_text(encoding='utf-8', errors='replace')

    def mark(self, name, **detail):
        self.record['checks'].append(dict(name=name, status='passed', **detail))

    def preflight(self):
        require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.flags.isolated,
                'Expected isolated Python 3.14.7 x64')
        self.g = generation(self.root)
        self.inputs = input_records(self.root, self.deps)
        self.record.update(inputs=self.inputs, generationRunId=self.g['runId'], models=self.g['models'],
                           python=dict(executable=sys.executable, version=sys.version),
                           dependencyBuildInfoSHA256=sha(self.deps / 'build-info.json'))
        self.record['gitHead'] = self.command('git-head', ['git', '-C', self.root, 'rev-parse', 'HEAD']).strip()
        self.mark('g1-generation-and-t02-dependencies', generatedFiles=len(self.g['files']), cppFiles=588)

    def configure(self, name, source, build, options, ninja=False, expect=0):
        arguments = [self.cmake, '-S', source, '-B', build, '-G', 'Ninja' if ninja else 'Visual Studio 17 2022']
        if ninja:
            arguments += ['-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_MAKE_PROGRAM=' + self.tools['ninja'],
                          '-DCMAKE_CXX_COMPILER=' + str(Path(self.tools['system']['vcDirectory']) / 'bin/Hostx64/x64/cl.exe')]
        else:
            arguments += ['-A', 'x64', '-T', 'v143,host=x64,version=' + self.tools['system']['vcVersion'],
                          '-DCMAKE_GENERATOR_INSTANCE=' + self.tools['system']['instance']['installationPath']]
        arguments += ['-DCMAKE_SYSTEM_VERSION=10.0.26100.0', '-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF',
                      '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF'] + options
        return self.command(name, arguments, expect=expect)

    def compile(self, name, build, targets=None):
        arguments = [self.cmake, '--build', build, '--config', 'Release', '--parallel', '8', '--verbose']
        if targets:
            arguments += ['--target', *targets]
        self.command(name, arguments)

    def build(self):
        build = child(self.root / 'out/build/lmcp-cpp', self.args.run_id) / '\u6d88\u606f build'
        snapshot = build / 'generated'
        snapshot.mkdir(parents=True)
        shutil.copytree(self.root / 'out/generated/lmcp/cpp', snapshot / 'cpp')
        shutil.copyfile(self.root / 'out/generated/lmcp/generation-info.json', snapshot / 'generation-info.json')
        binary, candidate = build / 'vs', build / 'candidate'
        self.configure('configure-library', self.root, binary,
                       ['-DUXAS_LMCP_GENERATED_DIR=' + (snapshot / 'cpp').as_posix(),
                        '-DUXAS_LMCP_PROVENANCE=' + (snapshot / 'generation-info.json').as_posix()])
        self.compile('build-library', binary, targets=['uxas_lmcp', 'lmcp_probe'])
        self.command('install-library', [self.cmake, '--install', binary, '--config', 'Release', '--component', 'Lmcp', '--prefix', candidate])
        self.verify_build(binary, candidate / 'lib/lmcp.lib')
        check_records(snapshot, [f for f in self.g['files'] if f['path'].startswith('cpp/')])
        generation(self.root); check_records(self.root, self.inputs)
        info = dict(schemaVersion=1, runId=self.args.run_id, status='candidate', generationRunId=self.g['runId'],
                    configuration='Release-x64-v143-MD-cxx14', inputs=self.inputs, files=files(candidate),
                    dependencyBuildInfoSHA256=self.record['dependencyBuildInfoSHA256'], models=self.g['models'],
                    sourceCount=183, generatedFileCount=588, buildDirectory=str(binary),
                    probe=str(binary / 'Release/lmcp_probe.exe'), probeSHA256=sha(binary / 'Release/lmcp_probe.exe'), context=self.context)
        save(candidate / 'build-info.json', info)
        self.record.update(status='candidate', candidate=str(candidate), buildDirectory=str(build), sourceCount=183)
        print('Candidate ready: ' + self.args.run_id, flush=True)

    def verify_build(self, binary, library):
        ns = (binary / 'lmcp-sources.txt').read_text(encoding='utf-8').strip().split(';')
        require(len(ns) == 183 and len(set(ns)) == 183, 'Incomplete C++ source list')
        project = (binary / 'uxas_lmcp.vcxproj').read_text(encoding='utf-8-sig')
        require('<LanguageStandard>stdcpp14</LanguageStandard>' in project and
                '<RuntimeLibrary>MultiThreadedDLL</RuntimeLibrary>' in project and
                'MultiThreadedDebug' not in project and '<PlatformToolset>v143</PlatformToolset>' in project,
                'Compiler flags differ from the plan')
        dump = Path(self.tools['system']['vcDirectory']) / 'bin/Hostx64/x64/dumpbin.exe'
        output = self.command('library-headers', [dump, '/headers', library])
        require('8664 machine (x64)' in output and '14C machine (x86)' not in output, 'Library architecture differs')
        output = self.command('library-directives', [dump, '/directives', library])
        require('MSVCRT' in output.upper() and not re.search(r'LIBCMT|MSVCRTD|LIBCPMT', output, re.I), 'Wrong library CRT')
        self.runtime('built-probe', binary / 'Release/lmcp_probe.exe')
        self.mark('all-seven-models-native-build', translationUnits=183, configuration='Release-x64-v143-MD-cxx14')

    def runtime(self, name, exe):
        dump = Path(self.tools['system']['vcDirectory']) / 'bin/Hostx64/x64/dumpbin.exe'
        output = self.command(name + '-imports', [dump, '/dependents', exe])
        imports = re.findall(r'^\s+([\w.-]+\.dll)\s*$', output, re.I | re.M)
        require(imports and all(re.match(r'^(?:KERNEL32|MSVCP140|VCRUNTIME140(?:_1)?|api-ms-win-crt-[\w-]+)\.dll$',
                                        item, re.I) for item in imports), 'Unexpected runtime DLL: ' + str(imports))
        self.record.setdefault('runtimeImports', {})[name] = imports

    def java(self, name, jar, *args):
        home = Path(self.context['javaHome'])
        return self.command(name, [home / 'bin/java.exe', '-Dfile.encoding=UTF-8', '-Duser.language=en',
                '-Duser.country=US', '-Djava.awt.headless=true', '-cp', str(self.classes) + os.pathsep + str(jar),
                'JavaProbe', *args], timeout=60)

    def python_probe(self, name, java_new, output):
        self.command(name, [sys.executable, '-I', '-B', '-X', 'utf8', self.root / 'tests/lmcp/python_probe.py',
                     '--generated', self.root / 'out/generated/lmcp/py', '--models', self.run / 'models.json',
                     '--fixture', self.fixture, '--java-new', java_new, '--java-old', self.run / 'java-old',
                     '--inventory', self.run / 'java-inventory.json', '--output', output], timeout=60)

    def samples(self, probe):
        self.fixture = self.root / 'tests/lmcp/samples.properties'
        self.jar = self.root / self.g['artifact']['path']
        old_jar = self.root / 'OpenAMASE/OpenAMASE/lib/lmcplib.jar'
        self.classes = self.run / 'java-classes'; self.classes.mkdir()
        self.command('compile-java-probe', [Path(self.context['javaHome']) / 'bin/javac.exe', '-encoding', 'UTF-8',
                     '-cp', self.jar, '-d', self.classes, self.root / 'tests/lmcp/JavaProbe.java'])
        names = [m['namespace'].replace('/', '.') + '.' + n for m in self.g['models'] for n in m['structs'] + m['enums'] + ['SeriesEnum']]
        types = self.run / 'types.txt'; types.write_text('\n'.join(names) + '\n', encoding='utf-8')
        save(self.run / 'models.json', self.g['models'])
        self.java('java-inventory', self.jar, 'inventory', types, self.run / 'java-inventory.json')
        inventory = load(self.run / 'java-inventory.json')
        self.inventory = self.run / 'cpp-inventory.txt'
        self.inventory.write_text(''.join(f"{n} {e['seriesId']} {e['typeId']} {e['version']}\n"
                                  for n,e in sorted(inventory.items()) if e['kind'] == 'struct'), encoding='ascii')
        for name, jar in (('new', self.jar), ('old', old_jar)):
            directory = self.run / ('java-' + name)
            self.java('java-' + name + '-emit', jar, 'emit', self.fixture, directory, directory / 'fields.json')
        self.python_probe('python-receives-java', self.run / 'java-new', self.run / 'python')
        self.command('cpp-inventory', [probe, 'inventory', self.inventory], timeout=30)
        for origin in ('java-new', 'python'):
            self.command('cpp-receives-' + origin, [probe, 'verify', self.fixture, self.run / origin], timeout=30)
        emitted = self.run / 'cpp'; emitted.mkdir()
        self.command('cpp-emit', [probe, 'emit', self.fixture, emitted], timeout=30)
        archived = child(self.root / 'out/runs', self.g['runId'])
        comparisons = []
        for sample in sorted(emitted.glob('*.bin')):
            for origin in ('java-new', 'python'):
                prior = archived / origin / sample.name
                require(sha(prior) == sha(sample), 'C++ differs from archived G1 sample: ' + sample.name)
                comparisons.append(dict(path=prior.relative_to(self.root).as_posix(), sha256=sha(prior)))
        self.record['g1SampleComparisons'] = comparisons
        self.java('java-receives-cpp', self.jar, 'verify', self.fixture, emitted, self.run / 'java-received-cpp.json')
        self.python_probe('python-receives-cpp', emitted, self.run / 'python-received-cpp')
        self.mark('three-language-bidirectional-samples', structures=164, samples=3, checksumModes=2)
        corrupt = bytearray((emitted / 'wide-checksum.bin').read_bytes()); corrupt[30] ^= 1
        invalid = {
            'checksum': (corrupt, 'Invalid LMCP checksum'),
            'truncated-checksum': ((emitted / 'wide-checksum.bin').read_bytes()[:-1], 'Invalid LMCP length'),
            'truncated-zero': ((emitted / 'wide-zero.bin').read_bytes()[:-1], 'Invalid LMCP length'),
            'short-header': (b'LMCP', 'Invalid LMCP header'),
            'sentinel-instead-of-raw': ((self.run / 'java-new/basic-sentinel.bin').read_bytes(), 'Invalid LMCP header'),
            'uxtask7': ((self.run / 'java-old/task-checksum.bin').read_bytes(), 'Unsupported LMCP type or version'),
        }
        for name, (data, diagnostic) in invalid.items():
            path = self.run / (name + '.bin'); path.write_bytes(data)
            output = self.command('reject-' + name, [probe, 'decode', path], expect=2, timeout=15)
            require(diagnostic in output, 'Missing rejection diagnostic: ' + name)
        self.mark('malformed-and-old-version-rejections', cases=list(invalid))

    def consumer(self, name, prefix, ninja=False):
        build = self.run / ('\u4e2d\u6587 space ' + name)
        self.configure(name + '-configure', self.root / 'tests/lmcp_cpp', build,
                       ['-DUXAS_LMCP_PREFIX=' + prefix.as_posix(), '-DUXAS_LMCP_VALIDATE_CANDIDATE=ON'], ninja=ninja)
        self.compile(name + '-build', build)
        build_log = (self.run / (name + '-build.stdout.log')).read_text(encoding='utf-8', errors='replace')
        expected_library = (prefix / 'lib/lmcp.lib').as_posix().lower()
        require(expected_library in build_log.replace('\\', '/').lower(), 'Consumer link source differs')
        if ninja:
            headers = self.command(name + '-headers', [self.tools['ninja'], '-C', build, '-t', 'deps'])
            header_paths = [line.strip() for line in headers.splitlines() if line.strip().endswith('.h')]
        else:
            header_paths = re.findall(r'including file:\s+([^\r\n]+\.h)', build_log)
        lmcp_headers = []
        for value in header_paths:
            if re.search(r'(?:^|[/\\])(?:afrl|avtas|uxas)[/\\]', value):
                header = (build / value).resolve()
                require(header.is_relative_to(prefix / 'include'), 'Consumer selected unrelated LMCP header: ' + value)
                lmcp_headers.append(dict(path=header.relative_to(prefix).as_posix(), sha256=sha(header)))
        require(any(item['path'] == 'include/avtas/lmcp/Factory.h' for item in lmcp_headers), 'No compiler header evidence')
        self.record.setdefault('consumerSources', {})[name] = dict(library=str(prefix / 'lib/lmcp.lib'),
                    librarySHA256=sha(prefix / 'lib/lmcp.lib'), headers=lmcp_headers)
        probe = build / ('lmcp_probe.exe' if ninja else 'Release/lmcp_probe.exe')
        self.runtime(name, probe)
        for iteration in range(2):
            self.command(name + '-verify-' + str(iteration), [probe, 'verify', self.fixture, self.run / 'cpp'], timeout=30)
        self.command(name + '-inventory', [probe, 'inventory', self.inventory], timeout=30)
        self.mark(name, generator='Ninja' if ninja else 'Visual Studio 17 2022', relocatedPrefix=str(prefix))

    def faults(self, candidate, info):
        before = sha(self.pointer) if self.pointer.exists() else None
        for mode in ('missing-library', 'corrupt-library', 'wrong-generation', 'changed-input'):
            copy = self.run / ('fault-' + mode); shutil.copytree(candidate, copy)
            changed = load(copy / 'build-info.json')
            if mode == 'missing-library':
                (copy / 'lib/lmcp.lib').unlink()
            elif mode == 'corrupt-library':
                with (copy / 'lib/lmcp.lib').open('ab') as stream:
                    stream.write(b'corrupt')
            elif mode == 'wrong-generation':
                changed['generationRunId'] = 'unrelated-generation'
            else:
                changed['inputs'][0]['sha256'] = '0' * 64
            save(copy / 'build-info.json', changed)
            try:
                check_package(self.root, copy, changed, self.inputs, self.g['runId'])
            except RuntimeError as error:
                save(copy / 'expected-failure.json', dict(status='rejected', error=str(error)))
            else:
                raise RuntimeError('Fault was accepted: ' + mode)
        # Exercise the independent CMake hash guard with an altered generated snapshot.
        generated = self.run / 'fault-generated'; generated.mkdir()
        shutil.copytree(self.root / 'out/generated/lmcp/cpp', generated / 'cpp')
        shutil.copyfile(self.root / 'out/generated/lmcp/generation-info.json', generated / 'generation-info.json')
        with (generated / 'cpp/avtas/lmcp/Factory.cpp').open('ab') as stream:
            stream.write(b'\n// isolated fault\n')
        output = self.configure('reject-generated-hash', self.root, generated / 'build',
                               ['-DUXAS_LMCP_GENERATED_DIR=' + (generated / 'cpp').as_posix(),
                                '-DUXAS_LMCP_PROVENANCE=' + (generated / 'generation-info.json').as_posix()], expect=1)
        require('Generated input hash mismatch' in output, 'CMake did not reject stale generation')
        models = self.run / 'fault-extra-model'
        shutil.copytree(self.root / 'OpenUxAS/mdms', models)
        (models / 'Unexpected.xml').write_text('<MDM/>', encoding='utf-8')
        try:
            check_model_set(models, self.g['models'])
        except RuntimeError as error:
            save(models / 'expected-failure.json', dict(status='rejected', error=str(error)))
        else:
            raise RuntimeError('Extra MDM file was accepted')
        require((sha(self.pointer) if self.pointer.exists() else None) == before, 'Failure changed qualified pointer')
        self.mark('isolated-provenance-faults-and-rollback', cases=6, previousPointerUnchanged=True)

    def test(self):
        require(self.args.build_run_id and re.fullmatch(r'g2-t03-build-[\d-]+', self.args.build_run_id), 'Invalid build run ID')
        built = load(child(self.root / 'out/runs', self.args.build_run_id) / 'result.json')
        require(built['status'] == 'candidate', 'Build did not produce a candidate')
        candidate = Path(built['candidate']).resolve()
        require(candidate.is_relative_to(self.root / 'out/build/lmcp-cpp' / self.args.build_run_id), 'Candidate escaped build directory')
        info = load(candidate / 'build-info.json')
        require(info['runId'] == self.args.build_run_id, 'Candidate build identity differs')
        check_package(self.root, candidate, info, self.inputs, self.g['runId'])
        require(sha(Path(info['probe'])) == info['probeSHA256'], 'Build probe hash differs')
        entry = load(child(self.root / 'out/runs', self.args.build_run_id) / 'entry-result.json')
        require(entry['status'] == 'passed' and entry['environmentRestored'] and entry['persistentPathUnchanged'],
                'Build entry environment checks did not pass')
        self.record.update(buildRunId=self.args.build_run_id, candidateBuildInfoSHA256=sha(candidate / 'build-info.json'))
        self.samples(Path(info['probe']))
        self.consumer('installed-vs', candidate)
        self.pointer = self.root / 'out/artifacts/lmcp/cpp/current.json'
        self.faults(candidate, info)
        prefix = child(self.pointer.parent, self.args.build_run_id + '/' + self.args.run_id)
        shutil.copytree(candidate, prefix)
        self.consumer('relocated-ninja', prefix, ninja=True)
        generation(self.root); check_records(self.root, self.inputs)
        check_package(self.root, prefix, info, self.inputs, self.g['runId'])
        info.update(status='passed', validationRunId=self.args.run_id)
        save(prefix / 'build-info.json', info)
        self.record.update(status='passed', publishedPrefix=str(prefix), finishedAt=stamp())
        save(self.run / 'result.json', self.record)
        pointer = dict(schemaVersion=1, buildRunId=self.args.build_run_id, validationRunId=self.args.run_id,
                       path=prefix.relative_to(self.pointer.parent).as_posix(), buildInfoSHA256=sha(prefix / 'build-info.json'))
        temporary = self.pointer.with_name('next-' + self.args.run_id + '.json'); save(temporary, pointer)
        if self.pointer.exists():
            shutil.copyfile(self.pointer, self.pointer.with_name('previous-' + self.args.run_id + '.json'))
        os.replace(temporary, self.pointer)
        print('LMCP C++ published: ' + str(prefix), flush=True)

    def resolve(self):
        pointer = load(self.root / 'out/artifacts/lmcp/cpp/current.json')
        prefix = child(self.root / 'out/artifacts/lmcp/cpp', pointer['path'])
        require(sha(prefix / 'build-info.json') == pointer['buildInfoSHA256'], 'LMCP pointer hash differs')
        info = load(prefix / 'build-info.json')
        validation = load(child(self.root / 'out/runs', pointer['validationRunId']) / 'result.json')
        entry = load(child(self.root / 'out/runs', pointer['validationRunId']) / 'entry-result.json')
        require(info['status'] == validation['status'] == 'passed' and info['runId'] == pointer['buildRunId'] == validation['buildRunId']
                and info['validationRunId'] == pointer['validationRunId'], 'LMCP validation identity differs')
        require(entry['status'] == 'passed' and entry['environmentRestored'] and entry['persistentPathUnchanged'],
                'Validation entry environment checks did not pass')
        check_package(self.root, prefix, info, self.inputs, self.g['runId'])
        self.record.update(status='passed', prefix=str(prefix))
        print('Qualified LMCP C++: ' + str(prefix), flush=True)

    def execute(self):
        try:
            with lock(self.root / 'out/build/lmcp/generate.lock'), lock(self.root / 'out/build/lmcp-cpp/task.lock'):
                self.preflight()
                getattr(self, self.args.mode)()
            return 0
        except Exception as error:
            self.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
            print('FAILED: ' + str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = stamp()
            save(self.run / 'result.json', self.record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('build', 'test', 'resolve'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--build-run-id')
    return Task(parser.parse_args()).execute()


if __name__ == '__main__':
    sys.exit(main())

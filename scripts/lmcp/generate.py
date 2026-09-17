"""G1-T03 implementation behind the Windows entry; Python standard library only."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
import zipfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def stamp():
    return datetime.now().astimezone().isoformat()


class Generation:
    def __init__(self, root):
        self.root = root.resolve()
        self.run_id = 'g1-t03-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.run = self.out('runs/' + self.run_id)
        self.build = self.out('build/lmcp/' + self.run_id)
        self.generated = self.build / 'generated'
        self.artifacts = self.build / 'artifacts'
        self.java = Path(os.environ['JAVA_HOME']) / 'bin/java.exe'
        self.javac = Path(os.environ['JAVA_HOME']) / 'bin/javac.exe'
        self.jvm = [str(self.java), '-Dfile.encoding=UTF-8', '-Duser.language=en', '-Duser.country=US', '-Djava.awt.headless=true']
        self.ant = self.jvm + ['-Dant.home=' + os.environ['ANT_HOME'], '-cp', str(Path(os.environ['ANT_HOME']) / 'lib/ant-launcher.jar'),
                               'org.apache.tools.ant.launch.Launcher', '-nouserlib', '-noinput']
        self.record = dict(schemaVersion=1, task='G1-T03', runId=self.run_id, status='running', step='preflight',
                           startedAt=stamp(), finishedAt=None, projectRoot=str(self.root), runDirectory=str(self.run),
                           commands=[], inputs=[], error=None)

    def out(self, relative):
        path = (self.root / 'out' / relative).resolve()
        require(path.is_relative_to((self.root / 'out').resolve()) and path != self.root / 'out', 'Output path escaped out/')
        return path

    def command(self, label, argv, cwd=None):
        entry = dict(label=label, arguments=[str(x) for x in argv], workingDirectory=str(cwd or self.root), startedAt=stamp())
        self.record['commands'].append(entry)
        try:
            result = subprocess.run(entry['arguments'], cwd=entry['workingDirectory'], encoding='utf-8', errors='strict',
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            entry.update(exitCode=result.returncode, stdout=result.stdout, stderr=result.stderr, finishedAt=stamp())
        except Exception as error:
            entry.update(exitCode=None, error=str(error), finishedAt=stamp())
            raise
        (self.run / (label + '.stdout.log')).write_text(result.stdout, encoding='utf-8')
        (self.run / (label + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
        print(label + ': exit ' + str(result.returncode), flush=True)
        require(result.returncode == 0, label + ' failed; see ' + str(self.run))
        return result.stdout + result.stderr

    def remember(self, path):
        self.record['inputs'].append(dict(path=path.relative_to(self.root).as_posix(), sha256=sha(path)))

    def preflight(self):
        require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8, 'Expected verified Python 3.14.7 x64')
        self.record['python'] = dict(version=sys.version, executable=sys.executable, isolated=bool(sys.flags.isolated))
        self.generator = self.root / 'out/artifacts/lmcpgen/LmcpGen.jar'
        info_path = self.generator.with_name('build-info.json')
        info = load(info_path)
        require(info['status'] == 'passed' and sha(self.generator) == info['artifact']['sha256'], 'Generator hash or T02 status mismatch')
        for item in info['inputs']:
            path = self.root / item['path']
            require(path.is_file() and sha(path) == item['sha256'], 'T02 input mismatch: ' + item['path'])
        self.record['generator'] = dict(sha256=sha(self.generator), t02RunId=info['runId'], source=info['git'], provenanceSha256=sha(info_path))
        self.remember(self.generator)
        self.remember(info_path)
        model_config = self.root / 'config/lmcp-models.json'
        config = load(model_config)
        require(config['schemaVersion'] == 1 and config['source'] == 'OpenUxAS/mdms', 'Unsupported MDM manifest')
        model_dir = self.root / config['source']
        expected_files = {m['file'] for m in config['models']}
        require(len(expected_files) == 7 and {p.name for p in model_dir.iterdir() if p.suffix.lower() in ('.xml', '.mdm')} == expected_files,
                'MDM file set mismatch: exactly seven locked models are required')
        self.models = []
        for model in config['models']:
            path = model_dir / model['file']
            require(sha(path) == model['sha256'], 'MDM hash mismatch: ' + model['file'])
            doc = ET.parse(path).getroot()
            require((doc.findtext('SeriesName'), doc.findtext('Namespace'), int(doc.findtext('Version'))) ==
                    (model['series'], model['namespace'], model['version']), 'MDM identity mismatch: ' + model['file'])
            item = dict(model, structs=[s.attrib['Name'] for s in doc.findall('./StructList/Struct')],
                        enums=[e.attrib['Name'] for e in doc.findall('./EnumList/Enum')])
            self.models.append(item)
            self.remember(path)
        require(sum(len(m['structs']) for m in self.models) == 164 and sum(len(m['enums']) for m in self.models) == 19, 'Model type count differs')
        self.record['models'] = self.models
        self.old_jar = self.root / 'OpenAMASE/OpenAMASE/lib/lmcplib.jar'
        self.remember(self.old_jar)
        for relative in ('config/lmcp-models.json', 'config/windows-java-toolchain.json', 'scripts/windows/generate-lmcp.ps1',
                         'scripts/windows/use-java.ps1', 'scripts/windows/java-common.ps1', 'scripts/lmcp/generate.py',
                         'tests/lmcp/JavaProbe.java', 'tests/lmcp/python_probe.py', 'tests/lmcp/samples.properties'):
            self.remember(self.root / relative)
        self.record['oldJarSha256'] = sha(self.old_jar)
        head = subprocess.run(['git', '-C', str(self.root), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
        self.record['git'] = dict(kind='isolated copy; see actual file hashes')
        if head.returncode == 0 and Path(head.stdout.strip()).resolve() == self.root:
            self.record['git'] = dict(head=subprocess.check_output(['git','rev-parse','HEAD'], cwd=self.root, text=True).strip(),
                                      status=subprocess.check_output(['git','status','--porcelain'], cwd=self.root, text=True),
                                      kind='local root; upstream commit unknown')
        versions = dict(java=self.command('java-version', self.jvm + ['-version']),
                        javac=self.command('javac-version', [self.javac, '-version']),
                        ant=self.command('ant-version', self.ant + ['-version']))
        require('11.0.32.1+1' in versions['java'] and 'javac 11.0.32.1' in versions['javac'] and 'version 1.10.18' in versions['ant'], 'Tool version mismatch')
        self.record['tools'] = versions
        self.record['step'] = 'snapshot'
        snapshot = self.build / 'inputs/mdms'
        snapshot.mkdir(parents=True)
        for model in self.models:
            shutil.copyfile(model_dir / model['file'], snapshot / model['file'])
            require(sha(snapshot / model['file']) == model['sha256'], 'Snapshot differs')
        self.snapshot = snapshot
        save(self.run / 'models.json', self.models)

    def generate(self):
        self.record['step'] = 'generate'
        for language in ('java', 'cpp', 'py'):
            directory = self.generated / language
            directory.mkdir(parents=True)
            output = self.command('generate-' + language, self.jvm + ['-jar', str(self.generator), '-mdmdir', str(self.snapshot),
                                                                       '-' + language, '-dir', str(directory)])
            require(not re.search(r'(?im)^\s*(?:error|fatal|exception)|can.t find|unrecognized', output), 'Generation diagnostics: ' + language)
        self.check_generated()
        self.record['step'] = 'java-build'
        self.new_jar = self.artifacts / 'java/lmcplib.jar'
        self.new_jar.parent.mkdir(parents=True)
        self.command('ant-java', self.ant + ['-f', str(self.generated / 'java/build.xml'),
                     '-Dbuild.dir=' + str(self.build / 'java-build'), '-Ddist.dir=' + str(self.new_jar.parent),
                     '-Ddist.jar=' + str(self.new_jar), '-Dmkdist.disabled=true', '-Djavac.source=1.8', '-Djavac.target=1.8', 'jar'])
        names = ['avtas.lmcp.' + x for x in ('LMCPObject','LMCPFactory','LMCPEnum','LMCPUtil','LMCPXMLReader','XMLUtil')]
        for model in self.models:
            names.extend(model['namespace'].replace('/', '.') + '.' + name for name in model['structs'] + model['enums'] + ['SeriesEnum'])
        self.names_file = self.run / 'types.txt'
        self.names_file.write_text('\n'.join(sorted(names)) + '\n', encoding='utf-8')
        with zipfile.ZipFile(self.new_jar) as jar:
            for name in names:
                content = jar.read(name.replace('.', '/') + '.class')
                require(content[:4] == b'\xca\xfe\xba\xbe' and int.from_bytes(content[6:8]) == 52, 'Wrong class bytecode: ' + name)
        self.record['javaClassesChecked'] = len(names)

    def check_generated(self):
        expected = {'java': ['build.xml','nbproject/project.properties','nbproject/build-impl.xml','src/avtas/lmcp/LMCPFactory.java'],
                    'cpp': ['avtas/lmcp/Factory.cpp','avtas/lmcp/Factory.h','avtas/lmcp/ByteBuffer.cpp','CMakeLists.txt'],
                    'py': ['lmcp/LMCPFactory.py','lmcp/LMCPObject.py','lmcp/__init__.py']}
        for model in self.models:
            ns = model['namespace']
            for name in model['structs'] + model['enums']:
                expected['java'].append('src/' + ns + '/' + name + '.java')
                expected['cpp'].append(ns + '/' + name + '.h')
                expected['py'].append(ns + '/' + name + '.py')
            expected['java'].append('src/' + ns + '/SeriesEnum.java')
            expected['py'].extend([ns + '/SeriesEnum.py', ns + '/__init__.py'])
            expected['cpp'].extend(ns + '/' + model['series'] + suffix for suffix in ('Enum.h','Factory.cpp','Factory.h','XMLReader.cpp','XMLReader.h','.h'))
            for name in model['structs']:
                expected['cpp'].extend([ns + '/' + ns.replace('/', '') + name + '.cpp', ns + '/' + name + 'Descendants.h'])
        for language, files in expected.items():
            for relative in files:
                path = self.generated / language / relative
                require(path.is_file() and path.stat().st_size > 0, 'Missing generated file: ' + language + '/' + relative)
        for path in self.generated.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.java','.py','.h','.cpp'):
                require(not re.search(r'-<[A-Za-z_]\w*>-', path.read_text(encoding='utf-8-sig')), 'Unreplaced template token: ' + str(path))
        self.record['requiredGeneratedFiles'] = {key: len(value) for key, value in expected.items()}

    def probe(self, label, jar, mode, *arguments):
        return self.command(label, self.jvm + ['-cp', os.pathsep.join([str(self.probe_classes), str(jar)]), 'JavaProbe', mode, *map(str, arguments)])

    def validate(self):
        self.record['step'] = 'probe-compile'
        self.probe_classes = self.build / 'probe-classes'
        self.probe_classes.mkdir()
        self.command('compile-probe', [self.javac, '-J-Dfile.encoding=UTF-8', '-J-Duser.language=en', '-J-Duser.country=US',
                                      '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-cp', self.new_jar,
                                      '-d', self.probe_classes, self.root / 'tests/lmcp/JavaProbe.java'])
        self.record['step'] = 'inventories'
        for label, jar in (('new', self.new_jar), ('old', self.old_jar)):
            self.probe(label + '-inventory', jar, 'inventory', self.names_file, self.run / (label + '-inventory.json'))
        self.compare_libraries()
        self.record['step'] = 'samples'
        fixture = self.root / 'tests/lmcp/samples.properties'
        for label, jar in (('new', self.new_jar), ('old', self.old_jar)):
            directory = self.run / ('java-' + label)
            self.probe(label + '-emit', jar, 'emit', fixture, directory, directory / 'fields.json')
        py_output = self.run / 'python'
        self.command('python-probe', [sys.executable, '-I', '-B', '-X', 'utf8', self.root / 'tests/lmcp/python_probe.py',
                     '--generated', self.generated / 'py', '--models', self.run / 'models.json', '--fixture', fixture,
                     '--java-new', self.run / 'java-new', '--java-old', self.run / 'java-old',
                     '--inventory', self.run / 'new-inventory.json', '--output', py_output])
        self.probe('java-receives-python', self.new_jar, 'verify', fixture, py_output, self.run / 'java-received.json')
        self.probe('old-java-receives-cmasi', self.old_jar, 'verify-cmasi', fixture, py_output, self.run / 'old-java-received.json')
        self.probe('old-java-rejects-uxtask8', self.old_jar, 'unsupported', py_output / 'task-checksum.bin')
        self.probe('java-rejects-corrupt', self.new_jar, 'reject-corrupt', py_output / 'corrupt.bin')
        self.record['validation'] = load(py_output / 'result.json')
        require(self.record['validation']['status'] == 'passed' and self.record['validation']['instantiatedStructs'] == 164, 'Incomplete Python verification')

    def compare_libraries(self):
        new, old = load(self.run / 'new-inventory.json'), load(self.run / 'old-inventory.json')
        require(set(new) == set(old), 'Old/new class names differ')
        require(sum(x['kind'] == 'struct' for x in new.values()) == 164, 'Java struct count differs')
        differences = []
        required = set()
        for path in (self.root / 'OpenAMASE/OpenAMASE/src').rglob('*.java'):
            content = path.read_text(encoding='utf-8-sig', errors='replace')
            for imported in re.findall(r'(?m)^\s*import\s+(?:static\s+)?([\w.*]+)\s*;', content):
                if imported.endswith('.*'):
                    required.update(name for name in old if name.rpartition('.')[0] == imported[:-2])
                elif imported in old:
                    required.add(imported)
            required.update(name for name in old if name in content)
        for name in sorted(old):
            a, b = old[name], new[name]
            removed, added = sorted(set(a['api']) - set(b['api'])), sorted(set(b['api']) - set(a['api']))
            fields = {key: {'old': a.get(key), 'new': b.get(key)} for key in ('typeId','seriesId','version','constants') if a.get(key) != b.get(key)}
            if removed or added or fields:
                differences.append(dict(type=name, removedApi=removed, addedApi=added, metadata=fields, referencedByAmase=name in required))
        comparison = dict(oldJarSha256=sha(self.old_jar), newJarSha256=sha(self.new_jar), comparedClasses=len(old),
                          amaseReferencedClasses=sorted(required), differences=differences, fullAmaseBuildVerified=False,
                          framing='Both Java libraries use Sentinel when checksum=true; Python emits raw LMCP')
        save(self.run / 'library-comparison.json', comparison)
        self.record['libraryComparison'] = comparison
        for item in differences:
            require(not (item['removedApi'] and item['referencedByAmase']), 'AMASE-referenced public API removed: ' + item['type'])
            require('typeId' not in item['metadata'] and 'seriesId' not in item['metadata'], 'Message identity changed: ' + item['type'])
        expected_versions = {m['series']: m['version'] for m in self.models}
        for item in new.values():
            if item['kind'] in ('series','struct'):
                require(item['version'] == expected_versions[item['series']], 'Generated series version differs')
        for item in old.values():
            if item['kind'] in ('series','struct'):
                require(item['version'] == (7 if item['series'] == 'UXTASK' else expected_versions[item['series']]), 'Unexpected old series version')

    def publish(self):
        self.record['step'] = 'input-stability'
        for item in self.record['inputs']:
            require(sha(self.root / item['path']) == item['sha256'], 'Input changed during generation: ' + item['path'])
        for model in self.models:
            require(sha(self.snapshot / model['file']) == model['sha256'], 'Snapshot changed during generation')
        self.record['generatedFiles'] = [dict(path=p.relative_to(self.generated).as_posix(), sha256=sha(p), sizeBytes=p.stat().st_size)
                                         for p in sorted(self.generated.rglob('*')) if p.is_file()]
        self.record['artifact'] = dict(path='out/artifacts/lmcp/java/lmcplib.jar', sha256=sha(self.new_jar), sizeBytes=self.new_jar.stat().st_size)
        self.record['status'] = 'passed'
        self.record['step'] = 'publish'
        self.record['finishedAt'] = stamp()
        save(self.generated / 'generation-info.json', dict(schemaVersion=1, runId=self.run_id, generator=self.record['generator'],
             artifact=self.record['artifact'], models=self.models, files=self.record['generatedFiles']))
        save(self.artifacts / 'build-info.json', self.record)
        moves = [(self.generated, self.out('generated/lmcp')), (self.artifacts, self.out('artifacts/lmcp'))]
        backed_up, installed = [], []
        try:
            for source, destination in moves:
                # Every directory move is resolved and constrained to this project's out/ tree.
                self.out(source.relative_to(self.root / 'out').as_posix())
                destination.parent.mkdir(parents=True, exist_ok=True)
                backup = self.out('build/lmcp/' + self.run_id + '/previous-' + destination.parent.name)
                if destination.exists():
                    require((destination / ('generation-info.json' if destination.parent.name == 'generated' else 'build-info.json')).is_file(), 'Refusing unrecognized existing output')
                    destination.rename(backup)
                    backed_up.append((backup, destination))
                source.rename(destination)
                installed.append((destination, source))
        except Exception:
            for destination, source in reversed(installed):
                destination.rename(source)
            for backup, destination in reversed(backed_up):
                backup.rename(destination)
            raise
        self.record['step'] = 'complete'
        print('PASS:', self.record['artifact']['path'], self.record['artifact']['sha256'], flush=True)

    def execute(self):
        # Existing run directories are never reused or rewritten.
        self.run.mkdir(parents=True, exist_ok=False)
        lock_file = None
        locked = False
        try:
            self.build.mkdir(parents=True, exist_ok=False)
            import msvcrt
            lock_file = self.out('build/lmcp/generate.lock').open('a+b')
            if lock_file.tell() == 0:
                lock_file.write(b'0'); lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
            self.preflight()
            self.generate()
            self.validate()
            self.publish()
            return 0
        except Exception as error:
            self.record.update(status='failed', error=str(error))
            (self.run / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
            print('FAIL [' + self.record['step'] + ']: ' + str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = stamp()
            save(self.run / 'result.json', self.record)
            if lock_file:
                if locked:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                lock_file.close()
            print('Run records:', self.run, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    sys.exit(Generation(parser.parse_args().root).execute())

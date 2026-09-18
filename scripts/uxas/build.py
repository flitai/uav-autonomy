"""T05 clean native builds, candidate qualification and read-only T06 resolution."""
import argparse
import copy
import importlib.util
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import traceback

spec = importlib.util.spec_from_file_location('uxas_graph', Path(__file__).with_name('graph.py'))
graph = importlib.util.module_from_spec(spec); spec.loader.exec_module(graph)
lmcp = graph.lmcp
require, load, save, sha, child = graph.require, graph.load, graph.save, graph.sha, graph.child


def candidate_check(root, directory, context, expected_hash):
    graph.validate(root, context)
    require(sha(directory / 'build-info.json') == expected_hash, 'Candidate metadata hash mismatch')
    info = load(directory / 'build-info.json')
    require(info['status'] == 'candidate' and info['configuration'] == 'Release-x64-v143-MD-cxx14', 'Candidate configuration differs')
    require(info['inputs'] == context['inputs'] and info['packages'] == context['packages'] and
            info['toolFiles'] == context['toolFiles'], 'Candidate source context differs')
    require(info['sourceCount'] == 122 and info['serviceCount'] == 40 and info['resourceCount'] == 5,
            'Candidate inventory differs')
    require({p.name for p in directory.iterdir()} == {'uxas.exe', 'build-info.json'}, 'Candidate file inventory differs')
    lmcp.check_records(directory, info['files'])
    require([f['path'] for f in info['files']] == ['uxas.exe'], 'Unexpected candidate files')
    executable = directory / 'uxas.exe'
    data = executable.read_bytes()
    require(data[:2] == b'MZ', 'Candidate DOS signature differs')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    require(data[offset:offset+4] == b'PE\0\0' and struct.unpack_from('<H', data, offset+4)[0] == 0x8664 and
            struct.unpack_from('<H', data, offset+24)[0] == 0x20b,
            'Candidate is not x64 PE')
    return info


def entry_check(run):
    entry = load(run / 'entry-result.json')
    require(entry['status'] == 'passed' and entry['environmentRestored'] and entry['persistentPathUnchanged'],
            'Entry/environment qualification failed')


class Task(graph.Task):
    def prepare(self):
        super().prepare()
        self.record['task'] = 'G2-T05'

    def selected_candidate(self):
        require(self.args.build_run_id and re.fullmatch(r'g2-t05-build-[\d-]+', self.args.build_run_id), 'Invalid build run ID')
        run = child(self.root / 'out/runs', self.args.build_run_id)
        result = load(run / 'result.json'); entry_check(run)
        require(result['status'] == 'candidate' and result['runId'] == self.args.build_run_id, 'Build did not produce candidate')
        directory = child(self.root / 'out/build/uxas', self.args.build_run_id) / 'candidate'
        info = candidate_check(self.root, directory, self.context, result['candidateInfoSHA256'])
        require(info['runId'] == self.args.build_run_id, 'Candidate build identity differs')
        return directory, info, result['candidateInfoSHA256']

    def full_build(self, label, build):
        require(not build.exists(), 'Build output must be clean')
        self.configure_graph(label + '-configure', build)
        self.audit_graph(build)
        self.compile(label + '-compile', build, ['uxas', 'uxas_platform_probe'])
        self.audit_build(label, build)
        graph.validate(self.root, self.context)

    def runtime(self, name, exe):
        dump = Path(self.tools['system']['vcDirectory']) / 'bin/Hostx64/x64/dumpbin.exe'
        output = self.command(name + '-imports', [dump, '/dependents', exe])
        imports = re.findall(r'^\s+([\w.-]+\.dll)\s*$', output, re.I | re.M)
        require(imports and all(re.fullmatch(r'(?:WS2_32|IPHLPAPI|KERNEL32|USER32|ADVAPI32|MSVCP140|'
                r'VCRUNTIME140(?:_1)?|api-ms-win-crt-[\w-]+)\.dll', item, re.I) for item in imports),
                'Unexpected runtime DLL: ' + str(imports))
        self.record.setdefault('runtimeImports', {})[name] = imports

    def audit_build(self, label, build):
        self.audit_graph(build)
        objects = sorted((build / 'uxas.dir/Release').glob('*.obj'))
        manifest = graph.inventory(self.root)
        expected = {Path(p).stem.lower() + '.obj' for p in manifest['sources'] if p not in manifest['excludedSources']}
        require(len(objects) == 122 and {p.name.lower() for p in objects} == expected, 'Actual compiled objects differ')
        tlogs = build / 'uxas.dir/Release/uxas.tlog'
        commands = (tlogs / 'CL.command.1.tlog').read_text(encoding='utf-16')
        require(all(flag in commands.upper() for flag in ('/MD', '/EHSC', '/STD:C++14', 'DPSS_STATIC', 'NOMINMAX')),
                'Actual compiler flags differ')
        require(not re.search(r'/(?:MTD?|MDD)(?:\s|$)', commands, re.I), 'Unqualified CRT compilation')
        includes = (tlogs / 'CL.read.1.tlog').read_text(encoding='utf-16').splitlines()
        headers = sorted({str(Path(line).resolve()) for line in includes if line.lower().endswith(('.h', '.hpp', '.hxx', '.inl', '.code'))})
        allowed = [self.root / 'OpenUxAS', self.deps, Path(self.context['lmcp']),
                   Path(self.tools['system']['vcDirectory']), Path(self.tools['system']['sdkDirectory'])]
        for header in headers:
            require(any(Path(header).is_relative_to(p) for p in allowed), 'Unexpected header source: ' + header)
        require(any(Path(h).is_relative_to(self.deps) for h in headers) and
                any(Path(h).is_relative_to(Path(self.context['lmcp'])) for h in headers), 'Missing dependency/LMCP header evidence')
        link = (tlogs / 'link.command.1.tlog').read_text(encoding='utf-16')
        require('/MACHINE:X64' in link.upper() and '/DLL' not in link.upper(), 'Link target differs')
        library_reads = (tlogs / 'link.read.1.tlog').read_text(encoding='utf-16').splitlines()
        libraries = sorted({Path(line).resolve() for line in library_reads if line.lower().endswith('.lib')})
        for library in libraries:
            require(any(library.is_relative_to(p) for p in allowed[1:]), 'Unexpected actual library source: ' + str(library))
        required_libraries = {p.resolve() for p in (self.deps / 'lib').glob('*.lib')} | {
                             Path(self.context['lmcp']) / 'lib/lmcp.lib'}
        require(required_libraries <= set(libraries), 'Actual linker input library inventory differs')
        mapfile = build / 'uxas.map'
        mapping = mapfile.read_text(encoding='utf-8', errors='replace')
        services = graph.inventory(self.root)['services']
        require(all(name.split('::')[-1] in mapping for name in services), 'Service registration missing from link map')
        dump = Path(self.tools['system']['vcDirectory']) / 'bin/Hostx64/x64/dumpbin.exe'
        directives = self.command(label + '-object-directives', [dump, '/directives', *objects])
        require('MSVCRT' in directives.upper() and not re.search(r'DEFAULTLIB:.*?(?:LIBCMT|MSVCRTD|LIBCPMT)', directives, re.I),
                'Object runtime directives differ')
        self.runtime(label, build / 'Release/uxas.exe')
        # Extract the actual embedded manifest rather than trusting source text.
        mt = Path(self.tools['system']['sdkDirectory']) / 'bin/10.0.26100.0/x64/mt.exe'
        manifest = self.run / (label + '-embedded.manifest')
        self.command(label + '-manifest', [mt, '-nologo', '-inputresource:' + str(build / 'Release/uxas.exe') + ';#1', '-out:' + str(manifest)])
        require(re.search(r'<activeCodePage[^>]*>UTF-8</activeCodePage>', manifest.read_text(encoding='utf-8-sig')), 'UTF-8 manifest missing')
        diagnostics = (self.run / (label + '-compile.stdout.log')).read_text(encoding='utf-8', errors='replace')
        warnings = {}
        for code in re.findall(r'warning ([CD]\d+)', diagnostics): warnings[code] = warnings.get(code, 0) + 1
        require(not any(code in warnings for code in ('C4003', 'C4530', 'D9030')), 'Macro/exception/compiler option warnings returned')
        evidence = dict(objects=[dict(path=str(p), sha256=sha(p)) for p in objects], headerSources=headers,
                        linkMap=dict(path=str(mapfile), sha256=sha(mapfile)), serviceNames=services,
                        compilerCommandsSHA256=sha(tlogs / 'CL.command.1.tlog'),
                        linkCommandsSHA256=sha(tlogs / 'link.command.1.tlog'), warningOccurrences=warnings,
                        linkedLibraries=[dict(path=str(p), sha256=sha(p)) for p in libraries],
                        warningCountIncludesMsbuildSummary=True)
        save(self.run / (label + '-build-audit.json'), evidence)
        self.mark(label + '-full-build', objects=122, services=40, embeddedResources=5, x64=True, runtime='MD')

    def build_candidate(self):
        base = child(self.root / 'out/build/uxas', self.args.run_id)
        binary = base / 'vs'
        self.full_build('ordinary', binary)
        candidate = base / 'candidate'; candidate.mkdir()
        shutil.copy2(binary / 'Release/uxas.exe', candidate / 'uxas.exe')
        info = dict(schemaVersion=1, runId=self.args.run_id, status='candidate',
                    configuration='Release-x64-v143-MD-cxx14', inputs=self.context['inputs'],
                    packages=self.context['packages'], toolFiles=self.context['toolFiles'],
                    sourceCount=122, serviceCount=40, resourceCount=5,
                    files=lmcp.files(candidate), buildDirectory=str(binary),
                    platformProbeSHA256=sha(binary / 'Release/uxas_platform_probe.exe'),
                    context=self.context, gitHead=self.record['gitHead'])
        save(candidate / 'build-info.json', info)
        digest = sha(candidate / 'build-info.json')
        candidate_check(self.root, candidate, self.context, digest)
        self.record.update(status='candidate', candidate=str(candidate), candidateInfoSHA256=digest,
                           buildDirectory=str(binary))
        print('Candidate ready (not released): ' + self.args.run_id, flush=True)

    def smoke(self, label, executable):
        report = self.run / (label + '-loaded-modules.json')
        text = self.command(label + '-early-cli', [sys.executable, '-I', '-B', '-X', 'utf8',
                            self.root / 'scripts/uxas/loader.py', executable, report], timeout=30)
        require('Unrecognized argument -t05-unknown-中文' in text, 'Early CLI diagnostic/UTF-8 argv differs')
        observed = load(report)
        modules = {Path(p).name.lower(): p for p in observed['modules']}
        required = {'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'}
        require(required <= set(modules), 'Missing actual CRT load evidence')
        system = Path(os.environ['SystemRoot']) / 'System32'
        for name, path in modules.items():
            require(Path(path) == executable or Path(path).is_relative_to(system), 'Unexpected loaded module: ' + path)
            require(sha(Path(path)) == observed['modules'][path], 'Loaded runtime changed')
            require(not re.search(r'(?:msvcp\d+d|vcruntime\d+(?:_\d+)?d|ucrtbased)\.dll', name), 'Debug CRT loaded')
        require(not any(self.cwd.glob('**/*')), 'Early CLI unexpectedly wrote service files')
        self.mark(label + '-pre-service-smoke', exitCode=observed['exitCode'], actualCrtPaths={n: modules[n] for n in sorted(required)})

    def platform(self, label, build):
        probe = build / 'Release/uxas_platform_probe.exe'
        probe_hash = sha(probe)
        previous = os.environ.get('TZ')
        try:
            for timezone in ('UTC0', 'PST8PDT'):
                os.environ['TZ'] = timezone
                output = self.command(label + '-platform-' + timezone, [probe,
                                      self.run / (label + ' 中文 文件 ' + timezone), '中文 参数'], timeout=20)
                require('PLATFORM_OK ACP=65001 UTC=1577934245678 TZ=' + timezone in output, 'Platform acceptance missing')
        finally:
            if previous is None: os.environ.pop('TZ', None)
            else: os.environ['TZ'] = previous
        require(sha(probe) == probe_hash, 'Platform probe changed while running')
        self.mark(label + '-platform-files-logging-time-exceptions', timezones=['UTC0', 'PST8PDT'],
                  probe=str(probe), probeSHA256=probe_hash)

    def reject(self, label, arguments, diagnostic):
        output = self.command(label, arguments, expect=1, timeout=120)
        require(diagnostic in output, 'Unexpected failure diagnostic for ' + label)
        self.mark(label)

    def failures(self, candidate, digest, base):
        base.mkdir(parents=True)
        common = [sys.executable, '-I', '-B', '-X', 'utf8', self.root / 'scripts/uxas/build.py', 'check-candidate',
                  '--root', self.root, '--context', self.args.context, '--expected-hash', digest]
        for fault in ('missing-exe', 'corrupt-exe', 'metadata'):
            clone = base / fault; shutil.copytree(candidate, clone)
            if fault == 'missing-exe': (clone / 'uxas.exe').unlink()
            elif fault == 'corrupt-exe': (clone / 'uxas.exe').write_bytes(b'broken PE')
            else:
                info = load(clone / 'build-info.json'); info['sourceCount'] = 121; save(clone / 'build-info.json', info)
            expected = {'missing-exe': 'Candidate file inventory differs', 'corrupt-exe': 'Input hash mismatch',
                        'metadata': 'Candidate metadata hash mismatch'}[fault]
            self.reject('reject-' + fault, [*common, '--candidate', clone], expected)
        for kind in ('dependencies', 'lmcp', 'tool', 'stale-input'):
            context = copy.deepcopy(self.context)
            if kind in ('dependencies', 'lmcp'): context[kind] = str(base / kind)
            elif kind == 'tool': context['toolFiles'][0]['sha256'] = '0' * 64
            else: context['inputs'][0]['sha256'] = '0' * 64
            path = base / (kind + '.json'); save(path, context)
            arguments = [*common, '--candidate', candidate, '--context', path]
            expected = 'source context differs' if kind in ('dependencies', 'lmcp') else (
                'Tool source hash differs' if kind == 'tool' else 'configuration inputs changed')
            self.reject('reject-' + kind, arguments, expected)
        # A corrupted generated model input is rejected by the production G1
        # hash checker, using only an isolated input copy (never edit the model).
        generated = base / 'generated'; generated.mkdir()
        model = 'OpenUxAS/mdms/CMASI.xml'
        (generated / 'CMASI.xml').write_bytes((self.root / model).read_bytes() + b'corrupt')
        records = base / 'generation-records.json'
        save(records, [dict(path='CMASI.xml', sha256=sha(self.root / model))])
        self.reject('reject-stale-generation', [sys.executable, '-I', '-B', '-X', 'utf8',
                    self.root / 'scripts/uxas/graph.py', 'check-records', '--root', generated, '--context', records], 'Input hash mismatch')
        for package in ('UxasDependencies', 'UxasLmcp'):
            output = self.configure_graph('reject-cached-' + package, base / package,
                extra=['-D' + package + '_DIR=' + str(base / 'unqualified-package')], expect=1)
            require('differs from the qualified package source' in output, 'Package override accepted')
            self.mark('reject-cached-' + package)
        try:
            self.command('reject-owned-timeout', [sys.executable, '-I', '-B', '-c', 'import time; time.sleep(60)'], timeout=1)
        except RuntimeError as error:
            require('timed out' in str(error), 'Unexpected timeout error')
            self.mark('reject-owned-timeout', onlyOwnedProcessTerminated=True)
        else: raise RuntimeError('Timeout was accepted')

    def test_candidate(self):
        candidate, info, digest = self.selected_candidate()
        original = Path(info['buildDirectory'])
        require(sha(original / 'Release/uxas_platform_probe.exe') == info['platformProbeSHA256'],
                'Platform probe differs from the selected build')
        snapshots = {str(p): sha(p) for directory in ('out/artifacts/deps', 'out/artifacts/lmcp/cpp', 'out/artifacts/uxas')
                     for p in (self.root / directory).rglob('*') if p.is_file()}
        self.platform('ordinary', original); self.smoke('ordinary', candidate / 'uxas.exe')
        second = child(self.root / 'out/build/uxas', self.args.run_id) / '中文 空格 build'
        self.full_build('unicode', second)
        self.platform('unicode', second); self.smoke('unicode', second / 'Release/uxas.exe')
        self.smoke('repeat', candidate / 'uxas.exe')
        self.failures(candidate, digest, second.parent / 'faults')
        candidate_check(self.root, candidate, self.context, digest)
        require(all(sha(Path(p)) == value for p, value in snapshots.items()), 'Qualified artifact changed')
        self.mark('qualified-artifacts-preserved', files=len(snapshots))
        receipt = dict(schemaVersion=1, status='passed', buildRunId=self.args.build_run_id,
                       validationRunId=self.args.run_id, candidateInfoSHA256=digest, files=info['files'],
                       inputs=self.context['inputs'], packages=self.context['packages'], formalRelease=False)
        save(self.run / 'acceptance.json', receipt)
        self.record.update(status='passed', buildRunId=self.args.build_run_id, candidateInfoSHA256=digest,
                           acceptanceSHA256=sha(self.run / 'acceptance.json'), formalRelease=False)
        print('Candidate accepted: ' + self.args.build_run_id + ' / ' + self.args.run_id, flush=True)

    def resolve(self):
        candidate, info, digest = self.selected_candidate()
        require(self.args.validation_run_id and re.fullmatch(r'g2-t05-test-[\d-]+', self.args.validation_run_id), 'Invalid validation run ID')
        run = child(self.root / 'out/runs', self.args.validation_run_id)
        entry_check(run); result = load(run / 'result.json'); receipt = load(run / 'acceptance.json')
        require(result['status'] == receipt['status'] == 'passed' and
                result['buildRunId'] == receipt['buildRunId'] == self.args.build_run_id and
                receipt['validationRunId'] == self.args.validation_run_id and
                sha(run / 'acceptance.json') == result['acceptanceSHA256'] and
                receipt['candidateInfoSHA256'] == digest == result['candidateInfoSHA256'] and
                receipt['files'] == info['files'] and receipt['inputs'] == self.context['inputs'] and
                receipt['packages'] == self.context['packages'], 'Candidate acceptance receipt differs')
        self.record.update(status='passed', candidate=str(candidate), buildRunId=self.args.build_run_id,
                           validationRunId=self.args.validation_run_id)
        print('Qualified candidate: ' + str(candidate), flush=True)

    def execute(self):
        try:
            with lmcp.lock(self.root / 'out/build/uxas/task.lock'), lmcp.lock(self.root / 'out/build/lmcp/generate.lock'), \
                    lmcp.lock(self.root / 'out/build/lmcp-cpp/task.lock'):
                self.prepare()
                {'build': self.build_candidate, 'test': self.test_candidate, 'resolve': self.resolve}[self.args.mode]()
            return 0
        except Exception as error:
            self.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
            print('FAILED: ' + str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = lmcp.stamp(); save(self.run / 'result.json', self.record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('build', 'test', 'resolve', 'check-candidate'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--run-id'); parser.add_argument('--build-run-id'); parser.add_argument('--validation-run-id')
    parser.add_argument('--candidate', type=Path); parser.add_argument('--expected-hash')
    args = parser.parse_args(); args.root = args.root.resolve()
    if args.mode == 'check-candidate':
        try:
            candidate_check(args.root, args.candidate, load(args.context), args.expected_hash)
            return 0
        except Exception as error:
            print(str(error), file=sys.stderr); return 1
    return Task(args).execute()


if __name__ == '__main__':
    sys.exit(main())

"""G2-T04 configure-only entry and acceptance; no dependency installation."""
import argparse
import copy
import importlib.util
from pathlib import Path
import re
import shutil
import struct
import sys
import traceback

spec = importlib.util.spec_from_file_location('lmcp_tools', Path(__file__).parents[1] / 'lmcp_cpp/manage.py')
lmcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lmcp)
require, sha, load, save, child = lmcp.require, lmcp.sha, lmcp.load, lmcp.save, lmcp.child


def inventory(root):
    manifest = load(root / 'config/uxas-sources.json')
    upstream = root / 'OpenUxAS'
    make = (upstream / 'Makefile').read_text(encoding='utf-8')
    block = re.search(r'^SOURCE_DIRS:=(.*?)(?:\n\s*\n)', make, re.M | re.S)
    require(block, 'Makefile SOURCE_DIRS not found')
    directories = block[1].replace('\\\n', ' ').replace('$(SOURCE_DIR)', 'src/cpp').split()
    require(directories == manifest['sourceDirectories'], 'Makefile source directories changed')
    require('$(wildcard $(source_dir)/*.cpp)' in make and '$(SOURCE_DIR)/UxAS_Main.cpp' in make,
            'Makefile source selection changed')
    actual = sorted(['src/cpp/UxAS_Main.cpp'] + [p.relative_to(upstream).as_posix()
                    for d in directories for p in (upstream / d).glob('*.cpp')])
    sources = manifest['sources']
    require(len(sources) == len(set(sources)) == 125 and actual == sorted(sources),
            'Source inventory differs (missing, additional or duplicate compilation unit)')
    excluded = manifest['excludedSources']
    require(excluded == {
        'src/cpp/Communications/LmcpObjectNetworkSerialBridge.cpp': 'UXAS_ENABLE_SERIAL',
        'src/cpp/Communications/LmcpObjectNetworkZeroMqZyreBridge.cpp': 'UXAS_ENABLE_ZYRE',
        'src/cpp/Communications/ZeroMqZyreBridge.cpp': 'UXAS_ENABLE_ZYRE'}, 'Optional source exclusions changed')
    for name in sources:
        require(child(upstream, name).is_file(), 'Missing source: ' + name)
    service_file = upstream / 'src/cpp/Services/00_ServiceList.h'
    services = re.findall(r'make_unique<([^>]+)>', service_file.read_text(encoding='utf-8'))
    require(len(services) == len(set(services)) == 40 and services == manifest['services'], 'Service registry differs')
    resource_dir = upstream / 'resources/AutomationDiagramDataService'
    actual_resources = sorted(p.relative_to(upstream).as_posix() for p in resource_dir.glob('*.code'))
    require(len(actual_resources) == 5 and actual_resources == manifest['embeddedResources'], 'Embedded resource inventory differs')
    diagram = (upstream / 'src/cpp/Services/AutomationDiagramDataService.cpp').read_text(encoding='utf-8')
    require(sorted(re.findall(r'#include\s+"([^"\n]+\.code)"', diagram)) ==
            sorted(Path(p).name for p in actual_resources), 'Automation diagram resource includes differ')
    return manifest


def inputs(root):
    paths = ['CMakeLists.txt', 'CMakePresets.json', 'config/uxas-sources.json', 'OpenUxAS/Makefile',
             'config/windows-cpp-toolchain.json', 'scripts/windows/uxas-cmake-common.ps1',
             'scripts/windows/configure-uxas.ps1', 'tests/windows/uxas-cmake.tests.ps1',
             'scripts/windows/uxas-build-common.ps1', 'scripts/windows/build-uxas.ps1',
             'tests/windows/uxas-build.tests.ps1',
             'OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml']
    for directory in ('cmake', 'scripts/uxas', 'tests/uxas_cmake', 'tests/uxas_build', 'OpenUxAS/src/cpp',
                      'OpenUxAS/resources/AutomationDiagramDataService'):
        paths.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob('*') if p.is_file())
    return [dict(path=p, sha256=sha(root / p)) for p in sorted(paths)]


def qualified_packages(root, context):
    dp = load(root / 'out/artifacts/deps/current.json')
    deps = child(root / 'out/artifacts/deps', dp['buildRunId'] + '/' + dp['validationRunId'])
    require(deps == Path(context['dependencies']).resolve(), 'Dependency source context differs')
    require(sha(deps / 'build-info.json') == dp['buildInfoSHA256'], 'Dependency pointer hash differs')
    di = load(deps / 'build-info.json')
    dv = load(child(root / 'out/runs', dp['validationRunId']) / 'result.json')
    require(di['status'] == dv['status'] == 'passed' and di['triplet'] == 'x64-windows-uxas' and
            di['runId'] == dp['buildRunId'] == dv['buildRunId'] and di['validationRunId'] == dp['validationRunId'],
            'Dependency publication identity differs')
    lmcp.check_records(root, di['inputs']); lmcp.check_records(root, dv['inputs'])
    expected = {'vcpkg.json', 'vcpkg-configuration.json', 'config/windows-dependencies.json',
                'config/windows-cpp-toolchain.json', 'scripts/windows/cpp-common.ps1',
                'scripts/windows/deps-common.ps1', 'scripts/windows/build-deps.ps1'}
    expected.update(p.relative_to(root).as_posix() for p in (root / 'config/vcpkg').rglob('*') if p.is_file())
    require(expected == {f['path'] for f in di['inputs']}, 'Dependency input inventory changed')
    lmcp.check_records(deps, di['files'])
    require({p.relative_to(deps).as_posix() for p in deps.rglob('*') if p.is_file()} ==
            {f['path'] for f in di['files']} | {'build-info.json'}, 'Dependency installed inventory differs')
    generated = lmcp.generation(root)
    lp = load(root / 'out/artifacts/lmcp/cpp/current.json')
    prefix = child(root / 'out/artifacts/lmcp/cpp', lp['path'])
    require(prefix == Path(context['lmcp']).resolve(), 'LMCP source context differs')
    require(sha(prefix / 'build-info.json') == lp['buildInfoSHA256'], 'LMCP pointer hash differs')
    info = load(prefix / 'build-info.json')
    validation = load(child(root / 'out/runs', lp['validationRunId']) / 'result.json')
    entry = load(child(root / 'out/runs', lp['validationRunId']) / 'entry-result.json')
    require(info['status'] == validation['status'] == entry['status'] == 'passed' and
            info['runId'] == lp['buildRunId'] == validation['buildRunId'] and
            info['validationRunId'] == lp['validationRunId'] and entry['environmentRestored'] and entry['persistentPathUnchanged'],
            'LMCP validation identity differs')
    lmcp.check_package(root, prefix, info, lmcp.input_records(root, deps), generated['runId'])
    return dict(dependencies=dp, lmcp=lp, generationRunId=generated['runId'])


def validate(root, context, output=None):
    manifest = inventory(root)
    require(context.get('root') == str(root), 'Qualified source root differs')
    require(context['inputs'] == inputs(root), 'UxAS configuration inputs changed; configure a fresh run')
    for tool in context['toolFiles']:
        require(sha(Path(tool['path'])) == tool['sha256'], 'Tool source hash differs: ' + tool['path'])
    packages = qualified_packages(root, context)
    require(packages == context['packages'], 'Qualified package context changed')
    result = dict(schemaVersion=1, status='validated', sources=[p for p in manifest['sources']
                  if p not in manifest['excludedSources']], excludedSources=manifest['excludedSources'],
                  services=manifest['services'], includeDirectories=manifest['sourceDirectories'],
                  embeddedResources=manifest['embeddedResources'], inputs=context['inputs'], packages=packages)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        save(output, result)
        def quote(value):
            value = str(value).replace('\\', '/')
            require(not any(c in value for c in (';', '"', '\n', '$')), 'Unsupported CMake path character')
            return '"' + value + '"'
        lines = ['# Generated only after live provenance validation.']
        for name, paths in (
            ('UXAS_QUALIFIED_CMAKE_COMMAND', [context['tools']['cmake']]),
            ('UXAS_QUALIFIED_CMAKE_CXX_COMPILER', [Path(context['tools']['system']['vcDirectory']) / 'bin/Hostx64/x64/cl.exe']),
            ('UXAS_QUALIFIED_CMAKE_LINKER', [Path(context['tools']['system']['vcDirectory']) / 'bin/Hostx64/x64/link.exe']),
            ('UXAS_DEPENDENCIES_PREFIX', [context['dependencies']]), ('UXAS_LMCP_PREFIX', [context['lmcp']]),
            ('UXAS_SOURCES', [root / 'OpenUxAS' / p for p in result['sources']]),
            ('UXAS_INCLUDE_DIRS', [root / 'OpenUxAS' / p for p in result['includeDirectories']]),
            ('UXAS_EMBEDDED_RESOURCES', [root / 'OpenUxAS' / p for p in result['embeddedResources']])):
            lines.append('set(' + name + '\n  ' + '\n  '.join(map(quote, paths)) + '\n)')
        output.with_name('uxas-inputs.cmake').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


class Task(lmcp.Task):
    def prepare(self):
        require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.flags.isolated,
                'Expected isolated Python 3.14.7 x64')
        self.record['task'] = 'G2-T04'
        inventory(self.root)
        self.context.update(root=str(self.root), inputs=inputs(self.root))
        self.context['toolFiles'] = self.tools['system']['files'] + [dict(path=self.tools[t], sha256=sha(Path(self.tools[t])))
                                                                   for t in ('cmake', 'ninja')]
        self.context['packages'] = qualified_packages(self.root, self.context)
        save(self.args.context, self.context)
        self.record.update(inputs=self.context['inputs'], packages=self.context['packages'],
                           gitHead=self.command('git-head', ['git', '-C', self.root, 'rev-parse', 'HEAD']).strip())

    def configure_graph(self, name, build, root=None, context=None, extra=(), expect=0):
        source = root or self.root
        query = build / '.cmake/api/v1/query'
        query.mkdir(parents=True, exist_ok=True)
        (query / 'codemodel-v2').touch()
        options = ['-DUXAS_VALIDATION_PYTHON=' + sys.executable,
                   '-DCMAKE_GENERATOR_INSTANCE=' + self.tools['system']['instance']['installationPath']]
        if context is not False:
            options.append('-DUXAS_VALIDATION_CONTEXT=' + str(context or self.args.context))
        output = self.command(name, [self.cmake, '--preset', 'windows-uxas-release', '-S', source, '-B', build,
                                     *options, *extra], expect=expect)
        # CMake wraps diagnostics to terminal width; retain raw logs, normalize
        # only the text used by assertions.
        return ' '.join(output.split())

    def audit_graph(self, build):
        graph = load(build / 'uxas-graph.json')
        reply = build / '.cmake/api/v1/reply'
        index = load(sorted(reply.glob('index-*.json'))[-1])
        model = load(reply / index['reply']['codemodel-v2']['jsonFile'])
        require([c['name'] for c in model['configurations']] == ['Release'], 'Unexpected build configurations')
        targets = model['configurations'][0]['targets']
        require(not any(t['name'] in ('uxas_lmcp', 'lmcp_probe') for t in targets), 'Generated LMCP compiled twice')
        uxas = load(reply / next(t['jsonFile'] for t in targets if t['name'] == 'uxas'))
        sources = [(self.root / p['path']).resolve() for p in uxas['sources'] if p['path'].endswith('.cpp')]
        require(len(sources) == 122 and set(sources) == {self.root / 'OpenUxAS' / p for p in graph['sources']},
                'Actual File API UxAS sources differ')
        resources = {(self.root / p['path']).resolve() for p in uxas['sources'] if p['path'].endswith('.code')}
        require(resources == {self.root / 'OpenUxAS' / p for p in graph['embeddedResources']}, 'File API resources differ')
        groups = uxas['compileGroups']
        for group in groups:
            definitions = {d['define'] for d in group['defines']}
            require({'UXAS_ENABLE_ZYRE=0', 'UXAS_ENABLE_SERIAL=0', 'BOOST_ALL_NO_LIB', 'ZMQ_STATIC', 'CZMQ_STATIC', 'WIN32'} <= definitions,
                    'Compile definitions differ')
            includes = {Path(p['path']).resolve() for p in group['includes']}
            require({self.root / 'OpenUxAS' / p for p in graph['includeDirectories']} |
                    {self.deps / 'include', Path(self.context['lmcp']) / 'include'} <= includes, 'Include sources differ')
            require(group['languageStandard']['standard'] == '14', 'Expected C++14')
        fragments = uxas['link']['commandFragments']
        linked = [f['fragment'].strip('"').replace('\\', '/') for f in fragments if f['role'] == 'libraries']
        expected = {p.as_posix() for p in (self.deps / 'lib').glob('*.lib')} | {
                    (Path(self.context['lmcp']) / 'lib/lmcp.lib').as_posix()}
        require(expected <= set(linked), 'Actual link graph misses qualified libraries')
        require(not any('zyre' in p.lower() or 'serial.lib' in p.lower() or p in ('dl', 'pthread', '-ldl', '-lpthread')
                        for p in linked), 'Disabled/Linux dependency leaked into link graph')
        require({'ws2_32.lib', 'iphlpapi.lib', 'rpcrt4.lib'} <= set(linked), 'Windows transitive libraries missing')
        for p in linked:
            if '/' in p and p.lower().endswith('.lib'):
                require(p in expected, 'Unexpected external link source: ' + p)
        project = (build / 'uxas.vcxproj').read_text(encoding='utf-8-sig')
        require('<RuntimeLibrary>MultiThreadedDLL</RuntimeLibrary>' in project and
                '<LanguageStandard>stdcpp14</LanguageStandard>' in project and
                '<PlatformToolset>v143</PlatformToolset>' in project, 'Generated MSBuild options differ')
        receipt = dict(status='passed', sourceCount=len(sources), serviceCount=len(graph['services']),
                       resourceCount=len(resources), libraries=linked, compileGroups=groups,
                       codemodel=str(reply / index['reply']['codemodel-v2']['jsonFile']),
                       targetSHA256=sha(reply / next(t['jsonFile'] for t in targets if t['name'] == 'uxas')))
        save(build / 'graph-audit.json', receipt)
        self.mark('file-api-build-graph', buildDirectory=str(build), sources=122, services=40, resources=5)

    def configure_only(self):
        build = child(self.root / 'out/build/uxas', self.args.run_id)
        require(not build.exists(), 'Configure output must be clean')
        self.configure_graph('configure-vs', build)
        self.audit_graph(build)
        validate(self.root, self.context)
        self.record.update(status='configured', buildDirectory=str(build), compiledUxas=False)
        print('UxAS configured (not compiled): ' + str(build), flush=True)

    def probes(self, build):
        self.compile('compile-policy-probes', build, ['bridge_configuration_probe', 'bridge_legacy_defaults_probe'])
        probe = build / 'Release/bridge_configuration_probe.exe'
        legacy = build / 'Release/bridge_legacy_defaults_probe.exe'
        self.command('hello-world-config', [probe, self.root / 'OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml'])
        fixtures = self.run / 'bridge fixtures'; fixtures.mkdir()
        retained = ['LmcpObjectNetworkTcpBridge', 'LmcpObjectNetworkSubscribePushBridge',
                    'LmcpObjectNetworkPublishPullBridge', 'ImpactSubscribePushBridge']
        def xml(types):
            return '<UxAS>' + ''.join('<Bridge Type="' + t + '"/>' for t in types) + '</UxAS>'
        serial, zyre = 'LmcpObjectNetworkSerialBridge', 'LmcpObjectNetworkZeroMqZyreBridge'
        cases = [(t, xml([t]), 0, []) for t in retained] + [
            ('serial', xml([serial]), 300, ['UXAS_ENABLE_SERIAL=OFF', serial]),
            ('zyre', xml([zyre]), 300, ['UXAS_ENABLE_ZYRE=OFF', zyre]),
            ('mixed', xml(retained + [serial, zyre]), 300, ['UXAS_ENABLE_SERIAL=OFF', 'UXAS_ENABLE_ZYRE=OFF']),
            ('malformed', '<UxAS><Bridge', 100, ['Invalid UxAS XML'])]
        for name, value, code, messages in cases:
            file = fixtures / (name + '.xml'); file.write_text(value, encoding='utf-8')
            output = self.command('policy-' + name, [probe, file], expect=code, timeout=10)
            require(all(m in output for m in messages), 'Missing bridge diagnostic')
        output = self.command('legacy-defaults', [legacy, fixtures / 'mixed.xml'], timeout=10)
        require('serial=1 zyre=1' in output, 'Legacy feature defaults differ')
        self.record['probes'] = [dict(path=str(p), sha256=sha(p)) for p in (probe, legacy)]
        self.mark('compiled-bridge-policy', cases=10, closedBridgeExit=300, malformedXmlExit=100, noNetwork=True)

    def failures(self, base):
        # All altered files/contexts are private copies. Qualified packages are read-only.
        for flag in ('ZYRE', 'SERIAL'):
            output = self.configure_graph('reject-' + flag, base / flag, extra=['-DUXAS_ENABLE_' + flag + '=ON'], expect=1)
            require('no qualified optional bridge dependencies' in output, 'Missing optional dependency diagnostic')
        output = self.configure_graph('reject-no-context', base / 'no-context', context=False, expect=1)
        require('Missing qualified source context' in output, 'Unqualified manual configuration accepted')
        for key in ('dependencies', 'lmcp'):
            altered = copy.deepcopy(self.context); altered[key] = str(base / ('wrong-' + key))
            context = self.run / ('bad-' + key + '.json'); save(context, altered)
            output = self.configure_graph('reject-' + key, base / key, context=context, expect=1)
            require('source context differs' in output, 'Wrong package source was not diagnosed')
        altered = copy.deepcopy(self.context); altered['toolFiles'][0]['sha256'] = '0' * 64
        context = self.run / 'bad-tool-source.json'; save(context, altered)
        output = self.configure_graph('reject-tool-source', base / 'tool-source', context=context, expect=1)
        require('Tool source hash differs' in output, 'Changed tool source was not diagnosed')
        snapshot = base / 'source copy'; snapshot.mkdir(parents=True)
        for name in ('CMakeLists.txt', 'CMakePresets.json', 'config/uxas-sources.json', 'OpenUxAS/Makefile',
                     'scripts/lmcp_cpp/manage.py', 'scripts/uxas/graph.py'):
            destination = snapshot / name; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / name, destination)
        for name in ('cmake', 'OpenUxAS/src/cpp', 'OpenUxAS/resources/AutomationDiagramDataService'):
            shutil.copytree(self.root / name, snapshot / name)
        manifest = inventory(self.root)
        for name, relative, diagnostic in (
            ('source', 'OpenUxAS/' + manifest['sources'][0], 'Source inventory differs'),
            ('resource', 'OpenUxAS/' + manifest['embeddedResources'][0], 'Embedded resource inventory differs')):
            file = snapshot / relative; content = file.read_bytes(); file.unlink()
            try:
                output = self.configure_graph('reject-missing-' + name, base / ('missing-' + name), root=snapshot, expect=1)
                require(diagnostic in output, 'Missing file diagnostic differs')
            finally:
                file.write_bytes(content)
        extra = snapshot / 'OpenUxAS/src/cpp/Services/Unregistered.cpp'; extra.write_text('// isolated extra source\n')
        try:
            output = self.configure_graph('reject-extra-source', base / 'extra-source', root=snapshot, expect=1)
            require('Source inventory differs' in output, 'Additional source accepted')
        finally:
            extra.unlink()
        manifest_file = snapshot / 'config/uxas-sources.json'
        duplicate = copy.deepcopy(manifest); duplicate['sources'][0] = duplicate['sources'][1]
        save(manifest_file, duplicate)
        try:
            output = self.configure_graph('reject-duplicate-source', base / 'duplicate-source', root=snapshot, expect=1)
            require('Source inventory differs' in output, 'Duplicate source accepted')
        finally:
            save(manifest_file, manifest)
        # Exercise the same hash checker used for T02, T03 and G1 on isolated copies.
        cases = [self.deps / 'lib/czmq.lib', Path(self.context['lmcp']) / 'lib/lmcp.lib',
                 self.root / 'out/generated/lmcp/cpp/avtas/lmcp/Factory.cpp',
                 self.root / 'OpenUxAS' / manifest['embeddedResources'][0],
                 self.root / 'OpenUxAS/mdms/CMASI.xml']
        for i, original in enumerate(cases):
            directory = base / ('hash-fault-' + str(i)); directory.mkdir()
            file = directory / original.name; shutil.copy2(original, file)
            records = [dict(path=file.name, sha256=sha(original))]
            metadata = directory / 'records.json'; save(metadata, records)
            file.write_bytes(file.read_bytes() + b'corruption')
            output = self.command('reject-hash-' + str(i), [sys.executable, '-I', '-B', '-X', 'utf8',
                                  self.root / 'scripts/uxas/graph.py', 'check-records', '--root', directory,
                                  '--context', metadata], expect=1)
            require('Input hash mismatch' in output, 'Corrupted file was not diagnosed')
        self.mark('isolated-failure-rejection', cases=15, noQualifiedFilesModified=True)

    def test(self):
        require(self.args.configure_run_id and re.fullmatch(r'g2-t04-configure-[\d-]+', self.args.configure_run_id), 'Invalid configure run ID')
        previous = child(self.root / 'out/runs', self.args.configure_run_id)
        configured = load(previous / 'result.json'); entry = load(previous / 'entry-result.json')
        require(configured['status'] == 'configured' and entry['status'] == 'passed' and
                entry['environmentRestored'] and entry['persistentPathUnchanged'], 'Configure entry did not pass')
        validate(self.root, load(previous / 'context.json'))
        build = Path(configured['buildDirectory'])
        require(build == self.root / 'out/build/uxas' / self.args.configure_run_id, 'Unexpected configure output')
        self.audit_graph(build)
        pointers = [self.root / 'out/artifacts/deps/current.json', self.root / 'out/artifacts/lmcp/cpp/current.json']
        before = [sha(p) for p in pointers]
        second = child(self.root / 'out/build/uxas', self.args.run_id) / '\u4e2d\u6587 configure build'
        self.configure_graph('configure-unicode', second); self.audit_graph(second)
        self.configure_graph('repeat-configure', second); self.audit_graph(second)
        self.probes(second)
        self.failures(second.parent / 'faults')
        validate(self.root, self.context)
        require([sha(p) for p in pointers] == before, 'Failure tests changed qualified pointers')
        require(not list(build.rglob('uxas.exe')) and not list(second.rglob('uxas.exe')), 'T04 unexpectedly built UxAS')
        self.mark('repeat-path-environment-and-rollback', unicodePath=str(second), otherWorkingDirectory=str(self.cwd), pointersUnchanged=True)
        self.record.update(status='passed', configureRunId=self.args.configure_run_id, compiledUxas=False)

    def execute(self):
        try:
            with lmcp.lock(self.root / 'out/build/uxas/task.lock'), lmcp.lock(self.root / 'out/build/lmcp/generate.lock'), \
                    lmcp.lock(self.root / 'out/build/lmcp-cpp/task.lock'):
                self.prepare()
                if self.args.mode == 'configure':
                    self.configure_only()
                else:
                    self.test()
            return 0
        except Exception as error:
            self.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
            print('FAILED: ' + str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = lmcp.stamp()
            save(self.run / 'result.json', self.record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('configure', 'test', 'validate', 'check-records'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--configure-run-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); args.root = args.root.resolve()
    if args.mode in ('validate', 'check-records'):
        try:
            if args.mode == 'validate':
                validate(args.root, load(args.context), args.output)
            else:
                lmcp.check_records(args.root, load(args.context))
            return 0
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 1
    return Task(args).execute()


if __name__ == '__main__':
    sys.exit(main())

"""Windows AMASE build/run/acceptance driver. Standard library; no downloads."""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import traceback
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
import zipfile

PROJECT = Path('OpenAMASE/OpenAMASE')
SCENARIO = Path('OpenUxAS/examples/02_Example_WaterwaySearch/Scenario_WaterwaySearch.xml')
LIBRARIES = ['lib/Flexdock/flexdock-1.2.3.jar', 'lib/SwingX/swingx-all-1.6.4.jar',
             'lib/GRAL/gral-core-0.10.jar', 'lib/worldwind.jar']


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


def inside(parent, relative):
    path = (parent / relative).resolve()
    require(path.is_relative_to(parent.resolve()) and path != parent.resolve(), 'Path escaped output root')
    return path


def inputs(root):
    project = root / PROJECT
    files = [p for folder in ('src', 'config', 'data', 'nbproject') for p in (project / folder).rglob('*')
             if p.is_file() and 'private' not in p.relative_to(project).parts]
    files += [project / n for n in LIBRARIES + ['build.xml', 'manifest.mf', 'buildinfo.xml', 'lib/nblibraries.properties']]
    files += [root / n for n in ['scripts/amase/amase.py', 'scripts/windows/amase-common.ps1',
              'scripts/windows/build-amase.ps1', 'scripts/windows/run-amase.ps1', 'tests/amase/RuntimeProbe.java',
              'scripts/windows/use-java.ps1', 'scripts/windows/java-common.ps1', 'config/windows-java-toolchain.json',
              'tests/amase/acceptance.py', 'tests/windows/amase.tests.ps1']]
    return [dict(path=p.relative_to(root).as_posix(), sha256=sha(p)) for p in sorted(set(files))]


def verify_records(root, records):
    for item in records:
        path = inside(root, item['path'])
        require(path.is_file() and sha(path) == item['sha256'], 'Input missing or hash mismatch: ' + item['path'])


def lmcp(root):
    info = load(root / 'out/artifacts/lmcp/build-info.json')
    marker = load(root / 'out/generated/lmcp/generation-info.json')
    require(info['status'] == 'passed' and info['runId'] == marker['runId'], 'T03 batch mismatch')
    require(info['generatedFiles'] == marker['files'], 'T03 generated manifest mismatch')
    verify_records(root, info['inputs'])
    verify_records(root / 'out/generated/lmcp', marker['files'])
    jar = inside(root, info['artifact']['path'])
    require(sha(jar) == info['artifact']['sha256'], 'T03 JAR hash mismatch')
    return jar, dict(runId=info['runId'], sha256=sha(jar), path=jar.relative_to(root).as_posix(),
                     provenanceSha256=sha(root / 'out/artifacts/lmcp/build-info.json'))


class Operation:
    def __init__(self, root, kind):
        self.root = root.resolve()
        self.id = 'g1-t04-' + kind + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.run = inside(root / 'out/runs', self.id)
        self.run.mkdir(parents=True)
        self.record = dict(schemaVersion=1, task='G1-T04', runId=self.id, status='running', startedAt=stamp(),
                           invocationDirectory=str(Path.cwd()), commands=[])
        self.java = Path(os.environ['JAVA_HOME']) / 'bin/java.exe'
        self.jvm = [str(self.java), '-Dfile.encoding=UTF-8', '-Duser.language=en', '-Duser.country=US']
        print('RUN_DIRECTORY=' + str(self.run), flush=True)

    def command(self, label, argv, cwd=None, timeout=180):
        item = dict(label=label, arguments=[str(a) for a in argv], workingDirectory=str(cwd or self.root), startedAt=stamp())
        self.record['commands'].append(item)
        with (self.run / (label + '.stdout.log')).open('w', encoding='utf-8') as stdout, \
             (self.run / (label + '.stderr.log')).open('w', encoding='utf-8') as stderr:
            result = subprocess.run(item['arguments'], cwd=cwd or self.root, stdout=stdout, stderr=stderr,
                                    timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        item.update(exitCode=result.returncode, finishedAt=stamp())
        print(label + ': exit ' + str(result.returncode), flush=True)
        require(result.returncode == 0, label + ' failed; see logs')
        return (self.run / (label + '.stdout.log')).read_text(encoding='utf-8') + (self.run / (label + '.stderr.log')).read_text(encoding='utf-8')

    def finish(self, status='passed', error=None):
        self.record.update(status=status, finishedAt=stamp())
        if error:
            self.record['error'] = str(error)
        save(self.run / 'result.json', self.record)


def build(op):
    root = op.root
    jar, provenance = lmcp(root)
    op.record.update(inputs=inputs(root), lmcp=provenance)
    project = root / PROJECT
    build_dir = inside(root / 'out/build/amase', op.id)
    candidate = build_dir / 'candidate'
    candidate.mkdir(parents=True)
    target = candidate / 'OpenAMASE.jar'
    version = op.command('java-version', op.jvm + ['-version'])
    ant = op.jvm + ['-Djava.awt.headless=true', '-Dant.home=' + os.environ['ANT_HOME'], '-cp',
                   str(Path(os.environ['ANT_HOME']) / 'lib/ant-launcher.jar'), 'org.apache.tools.ant.launch.Launcher', '-nouserlib', '-noinput']
    ant_version = op.command('ant-version', ant + ['-version'])
    require('11.0.32.1' in version and '1.10.18' in ant_version, 'Tool version mismatch')
    cp = [jar] + [project / n for n in LIBRARIES]
    op.command('ant-jar', ant + ['-f', str(project / 'build.xml'), '-Dbuild.dir=' + str(build_dir / 'classes-build'),
               '-Ddist.dir=' + str(candidate), '-Ddist.jar=' + str(target), '-Dfile.reference.lmcplib.jar=' + str(jar),
               '-Djavac.source=11', '-Djavac.target=11', '-Dmkdist.disabled=true', '-Dnative.bundling.enabled=false',
               '-Djavac.classpath=' + os.pathsep.join(map(str, cp)), 'jar'])
    with zipfile.ZipFile(target) as archive:
        require(b'Main-Class: avtas.app.Application' in archive.read('META-INF/MANIFEST.MF'), 'Wrong main class')
        classes = [n for n in archive.namelist() if n.endswith('.class')]
        require(classes and all(int.from_bytes(archive.read(n)[6:8]) == 55 for n in classes), 'AMASE bytecode must be 55')
        require(not any(n.startswith(('afrl/', 'uxas/messages/', 'avtas/lmcp/')) for n in classes), 'Embedded duplicate LMCP classes')
        resources = [p for d in ('Core', 'Amase', 'SetupTool', 'example') for p in (project / 'src' / d).rglob('*')
                     if p.is_file() and p.suffix not in ('.java', '.form')]
        for resource in resources:
            entry = '/'.join(resource.relative_to(project / 'src').parts[1:])
            require(archive.read(entry) == resource.read_bytes(), 'Missing/changed packaged resource: ' + entry)
    probe_classes = build_dir / 'probe-classes'
    probe_classes.mkdir()
    javac = Path(os.environ['JAVA_HOME']) / 'bin/javac.exe'
    op.command('compile-probe', [str(javac), '-J-Dfile.encoding=UTF-8', '-encoding', 'UTF-8', '--release', '11',
               '-cp', os.pathsep.join(map(str, [target] + cp)), '-d', str(probe_classes), str(root / 'tests/amase/RuntimeProbe.java')])
    validation = candidate / 'validation'
    validation.mkdir()
    probe = validation / 'amase-probe.jar'
    op.command('jar-probe', [str(Path(os.environ['JAVA_HOME']) / 'bin/jar.exe'), '--create', '--file', str(probe), '-C', str(probe_classes), '.'])
    verify_records(root, op.record['inputs'])
    top = Path(subprocess.check_output(['git','-C',str(root),'rev-parse','--show-toplevel'], text=True).strip()).resolve()
    head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip() if top == root else None
    op.record.update(buildDirectory=str(build_dir), candidateDirectory=str(candidate), gitHead=head,
                     toolchain=dict(java=version.strip(), ant=ant_version.strip()), compileClasspath=list(map(str, cp)),
                     classCount=len(classes), resourceCount=len(resources), artifact=dict(sha256=sha(target), file='OpenAMASE.jar'),
                     probe=dict(sha256=sha(probe), file='validation/amase-probe.jar'))
    op.finish('built')
    save(candidate / 'build-info.json', op.record)
    print('BUILD_RUN_ID=' + op.id, flush=True)


def candidate(root, build_id):
    if build_id:
        require(re.fullmatch(r'g1-t04-build-\d{8}-\d{6}-\d{6}', build_id), 'Invalid BuildRunId')
        folder = inside(root / 'out/build/amase', build_id + '/candidate')
    else:
        folder = root / 'out/artifacts/amase'
    info = load(folder / 'build-info.json')
    require(info['status'] == ('built' if build_id else 'passed'), 'AMASE build is not eligible')
    verify_records(root, info['inputs'])
    jar, provenance = lmcp(root)
    require(provenance == info['lmcp'], 'AMASE references a different T03 batch')
    for key in ('artifact', 'probe'):
        require(sha(folder / info[key]['file']) == info[key]['sha256'], 'AMASE artifact hash mismatch')
    return folder, info, jar


def check_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(('0.0.0.0', port))
        except OSError as error:
            raise RuntimeError('Port unavailable: ' + str(port)) from error


def listener_pid(port):
    command = ['powershell.exe','-NoProfile','-Command',
               f'Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess']
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    return {int(line) for line in result.stdout.splitlines() if line.strip().isdigit()}


def events(directory):
    path = directory / 'events.jsonl'
    if not path.exists():
        return []
    lines = path.read_text(encoding='utf-8').splitlines()
    # A concurrent writer may have a final incomplete line.
    return [json.loads(line) for line in lines if line.endswith('}')]


def evidence(directory, mode, lmcp_jar, require_end=False):
    rows = events(directory)
    initialized = [r for r in rows if r['kind'] == 'initialized']
    require(len(initialized) == 1, 'Missing/duplicate initialization evidence')
    start = initialized[0]
    source = unquote(urlparse(start['lmcpSource']).path).lstrip('/')
    require(Path(source).resolve() == lmcp_jar.resolve() and start['uxtaskVersion'] == 8, 'Wrong runtime LMCP source/version')
    runtime = load(directory / 'result.json')
    amase_source = Path(unquote(urlparse(start['amaseSource']).path).lstrip('/')).resolve()
    require(amase_source == Path(runtime['classpath'][0]['path']).resolve(), 'Wrong runtime AMASE source')
    required = {'avtas.amase.scenario.ScenarioManager', 'avtas.amase.util.SimTimer', 'avtas.amase.entity.EntityControl',
                'avtas.amase.analysis.AnalysisManager', 'avtas.amase.network.TcpServer', 'avtas.terrain.TerrainConfigurator'}
    require(required.issubset(start['plugins']), 'Required runtime plugin missing')
    if mode == 'gui':
        require(not start['headless'] and start['visibleWindows'] > 0, 'GUI not visible')
        require(any(r['kind'] == 'gui-ready' and r['simTime'] >= 20 for r in rows), 'GUI observation incomplete')
    else:
        require(start['headless'] and start['visibleWindows'] == 0, 'Headless runtime has windows')
        require('avtas.amase.scenario.ConstructiveControl' in start['plugins'], 'Missing automatic simulation controller')
    result = {}
    for entity in ('400', '500'):
        states = [r for r in rows if r['kind'] == 'entity' and r['id'] == entity]
        require(len(states) >= 10, 'Insufficient real states for ' + entity)
        require(all(int(a['timeMs']) <= int(b['timeMs']) for a,b in zip(states, states[1:])), 'Entity time regressed')
        require(int(states[-1]['timeMs']) > int(states[0]['timeMs']), 'Entity time did not advance')
        require(len({(r['latitude'],r['longitude']) for r in states}) > 1, 'Entity did not move')
        require(all(math.isfinite(r[k]) for r in states for k in ('latitude','longitude','altitude')), 'Non-finite entity state')
        result[entity] = dict(count=len(states), first=states[0], last=states[-1])
    sessions = [r for r in rows if r['kind'] == 'session']
    require(len(sessions) >= 10 and max(int(r['timeMs']) for r in sessions) >= 20000, 'Simulation time did not advance')
    if require_end:
        require(any(r['state'] == 'Stopped' and int(r['timeMs']) >= 785000 for r in sessions), 'Full scenario did not finish')
    return dict(entities=result, sessionCount=len(sessions), initialized=start, lastSession=sessions[-1])


def run(op, args):
    root = op.root
    folder, info, lmcp_jar = candidate(root, args.build_run_id)
    scenario = Path(args.scenario).resolve() if args.scenario else root / SCENARIO
    require(scenario.is_file(), 'Missing scenario: ' + str(scenario))
    tree = ET.parse(scenario)
    require(tree.getroot().tag == 'AMASE' and tree.find('ScenarioData/ScenarioDuration') is not None, 'Invalid AMASE scenario')
    duration = float(tree.findtext('ScenarioData/ScenarioDuration'))
    if args.validate_run:
        require(duration == 785 and {e.findtext('ID') for e in tree.findall('.//AirVehicleState')} >= {'400','500'}, 'Expected original WaterwaySearch')
    check_port(args.port)
    configuration = root / PROJECT / 'config' / ('amase' if args.mode == 'gui' else 'amase_headless')
    entity_config = ET.parse(configuration / 'EntityControl.xml')
    active_ids = {e.findtext('ID') for e in tree.findall('.//AirVehicleState')}
    entity_ports = {}
    for connection in entity_config.findall('.//TcpConnection'):
        if connection.get('Id') in active_ids:
            port = int(connection.get('Port')) + args.entity_port_offset
            require(1 <= port <= 65535, 'Invalid effective entity port')
            entity_ports[connection.get('Id')] = port
            connection.set('Port', str(port))
    ports = [args.port] + list(entity_ports.values())
    require(len(set(ports)) == len(ports), 'Runtime ports overlap')
    for port in entity_ports.values():
        check_port(port)
    runtime = op.run / 'runtime'
    runtime.mkdir()
    settings = runtime / 'config'
    shutil.copytree(configuration, settings)
    entity_config.write(settings / 'EntityControl.xml', encoding='utf-8', xml_declaration=True)
    shutil.copytree(root / PROJECT / 'data', runtime / 'data')
    # Optional overlays are empty in this source distribution.
    (runtime / 'data/overlay').mkdir(exist_ok=True)
    shutil.copy2(root / PROJECT / 'buildinfo.xml', runtime / 'buildinfo.xml')
    scenario_copy = runtime / 'scenario.xml'
    shutil.copy2(scenario, scenario_copy)
    require(sha(scenario_copy) == sha(scenario), 'Scenario copy differs')
    (runtime / 'tmp').mkdir()
    (runtime / 'home').mkdir()
    plugins = ET.parse(settings / 'Plugins.xml')
    server = plugins.find(".//Plugin[@Class='avtas.amase.network.TcpServer']/TCPServer")
    require(server is not None, 'Missing TCP plugin configuration')
    server.set('Port', str(args.port))
    plugins.getroot().insert(0, ET.Element('Plugin', Class='validation.RuntimeProbe'))
    plugins.write(settings / 'Plugins.xml', encoding='utf-8', xml_declaration=True)
    classpath = [folder / 'OpenAMASE.jar', lmcp_jar] + [root / PROJECT / p for p in LIBRARIES] + [folder / 'validation/amase-probe.jar']
    argv = op.jvm + ['-Xmx1024m', '-Djava.awt.headless=' + str(args.mode == 'headless').lower(),
                    '-Djava.io.tmpdir=' + str(runtime / 'tmp'), '-Duser.home=' + str(runtime / 'home'),
                    '-Damase.probe.directory=' + str(op.run), '-Damase.probe.validate=' + str(args.validate_run).lower(),
                    '-Damase.probe.simRate=' + str(args.sim_rate), '-cp', os.pathsep.join(map(str, classpath)),
                    'avtas.app.Application', '--config', str(settings), '--scenario', str(scenario_copy),
                    '--sim_rate', str(args.sim_rate)]
    op.record.update(buildRunId=info['runId'], mode=args.mode, port=args.port, entityPorts=entity_ports,
                     entityPortOffset=args.entity_port_offset, scenarioSource=str(scenario),
                     scenarioSha256=sha(scenario), durationSeconds=duration, arguments=argv, workingDirectory=str(runtime),
                     classpath=[dict(path=str(p),sha256=sha(p)) for p in classpath],
                     runtimeInputs=[dict(path=p.relative_to(runtime).as_posix(),sha256=sha(p)) for p in sorted(runtime.rglob('*')) if p.is_file()])
    with (op.run / 'stdout.log').open('w', encoding='utf-8') as stdout, (op.run / 'stderr.log').open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(argv, cwd=runtime, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        op.record['pid'] = process.pid
        save(op.run / 'result.json', op.record)
        started = time.monotonic()
        ready = False
        listening = False
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if not listening and elapsed >= 1:
                    listening = all(process.pid in listener_pid(port) for port in ports)
                    if listening:
                        op.record['listenerPidVerified'] = process.pid
                        save(op.run / 'result.json', op.record)
                    elif elapsed > 15:
                        raise RuntimeError('AMASE did not own the requested listening port')
                if args.mode == 'headless' and elapsed > 120:
                    raise RuntimeError('Headless run exceeded 120 seconds')
                if args.mode == 'gui' and args.validate_run and not ready:
                    if any(r['kind'] == 'gui-ready' for r in events(op.run)):
                        op.record['validation'] = evidence(op.run, args.mode, lmcp_jar)
                        op.record['status'] = 'awaiting-manual-confirmation'
                        save(op.run / 'result.json', op.record)
                        print('GUI_READY=' + op.id, flush=True)
                        ready = True
                    elif elapsed > 60:
                        raise RuntimeError('GUI initialization/observation exceeded 60 seconds')
                time.sleep(0.25)
        except BaseException:
            # Request normal shutdown first, then only terminate our own child.
            (op.run / 'request-shutdown').touch()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                op.record['forcedTermination'] = True
            op.record['exitCode'] = process.returncode
            raise
    op.record['exitCode'] = process.returncode
    require(process.returncode == 0, 'AMASE process failed')
    require(listening, 'Missing AMASE port ownership evidence')
    output = (op.run / 'stdout.log').read_text(encoding='utf-8') + (op.run / 'stderr.log').read_text(encoding='utf-8')
    require(not re.search(r'Exception|SEVERE|Could not create object|Cannot load application', output), 'AMASE runtime diagnostics indicate failure')
    if args.validate_run:
        op.record['validation'] = evidence(op.run, args.mode, lmcp_jar, require_end=args.mode == 'headless')
    for port in ports:
        check_port(port)
    op.record['portReleased'] = True
    op.finish('automatic-passed' if args.validate_run else 'exited')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('action', choices=['build','run','automatic','finalize'])
    parser.add_argument('--build-run-id')
    parser.add_argument('--gui-run-id')
    parser.add_argument('--validation-run-id')
    parser.add_argument('--manual-confirmation')
    parser.add_argument('--mode', choices=['gui','headless'], default='gui')
    parser.add_argument('--scenario')
    parser.add_argument('--port', type=int, default=5555)
    parser.add_argument('--entity-port-offset', type=int, default=0)
    parser.add_argument('--sim-rate', type=float, default=1)
    parser.add_argument('--validate-run', action='store_true')
    args = parser.parse_args()
    require(sys.version_info >= (3,11) and struct.calcsize('P') == 8, 'Python 3.11+ x64 required; validated with 3.14.7')
    op = Operation(args.root.resolve(), args.action)
    try:
        if args.action == 'build':
            build(op)
        elif args.action == 'run':
            run(op,args)
        else:
            sys.path.insert(0, str(op.root / 'tests/amase'))
            from acceptance import automatic, finalize
            (automatic if args.action == 'automatic' else finalize)(op,args)
    except BaseException as error:
        op.finish('failed', error)
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

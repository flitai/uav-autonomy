"""Real AMASE/UxAS TCP protocol probes. No search completion or coverage claim."""
import argparse
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
from types import SimpleNamespace
from collections import Counter
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


wire = module('g3_wire', Path(__file__).with_name('wire.py'))
baseline_driver = module('g3_baseline', Path(__file__).parents[1] / 'g3_baseline/check.py')
release = baseline_driver.release
load, save, sha, require = release.load, release.save, release.sha, release.require


def connect(port, process=None, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process is not None:
            require(process.poll() is None, 'Process exited before TCP readiness')
        try:
            sock = socket.create_connection(('127.0.0.1', port), timeout=0.5)
            sock.settimeout(0.2)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        except OSError:
            time.sleep(0.05)
    raise RuntimeError('Connection timeout: ' + str(port))


class Capture:
    def __init__(self, sock, path):
        self.sock, self.path, self.stop = sock, path, threading.Event()
        self.error, self.disconnected = None, False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            with self.path.open('wb', buffering=0) as output:
                while not self.stop.is_set():
                    try:
                        data = self.sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        self.disconnected = True
                        break
                    output.write(data)
        except OSError as error:
            if not self.stop.is_set():
                self.error = repr(error)

    def close(self):
        self.stop.set()
        self.sock.close()
        self.thread.join(3)
        require(not self.thread.is_alive(), 'Capture thread did not stop')


class WireTap:
    """Transport-only recorder; forwards the exact bytes between the two real ends."""
    def __init__(self, directory, port, amase_port, split):
        self.directory, self.amase_port, self.split = directory, amase_port, split
        self.stop, self.ready = threading.Event(), threading.Event()
        self.error, self.sockets, self.chunks = None, [], []
        self.disconnected = threading.Event()
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.server.bind(('127.0.0.1', port)); self.server.listen(1); self.server.settimeout(0.2)
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()

    def pump(self, source, destination, name):
        reader = wire.sentinel.SentinelReader()
        try:
            with (self.directory / (name + '.bin')).open('wb', buffering=0) as output:
                while not self.stop.is_set():
                    try:
                        data = source.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        self.disconnected.set()
                        break
                    output.write(data)
                    for frame in reader.feed(data):
                        packet = frame['wire']
                        pieces = [packet]
                        if self.split:
                            at = packet.index(wire.sentinel.BODY) + 1
                            pieces = [packet[:at], packet[at:at+1], packet[at+1:]]
                        for i, piece in enumerate(pieces):
                            destination.sendall(piece)
                            self.chunks.append(dict(direction=name, frameOffset=frame['offset'], part=i,
                                                    length=len(piece), wallTime=time.time()))
                            if self.split and i < len(pieces)-1:
                                time.sleep(0.04)
        except (OSError, ValueError) as error:
            if not self.stop.is_set():
                self.error = repr(error)
                self.disconnected.set()
        finally:
            (self.directory / (name + '-tail.bin')).write_bytes(reader.buffer)

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    uxas, _ = self.server.accept(); break
                except socket.timeout:
                    continue
            else:
                return
            amase = connect(self.amase_port)
            for s in (uxas, amase):
                s.settimeout(0.2); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sockets = [uxas, amase]
            tasks = [threading.Thread(target=self.pump, args=(amase, uxas, 'java-to-cpp'), daemon=True),
                     threading.Thread(target=self.pump, args=(uxas, amase, 'cpp-to-java'), daemon=True)]
            for t in tasks: t.start()
            self.ready.set()
            for t in tasks: t.join()
        except Exception as error:
            self.error = repr(error)

    def close(self):
        self.stop.set(); self.server.close()
        for sock in self.sockets: sock.close()
        self.thread.join(5)
        save(self.directory / 'forwarded-chunks.json', self.chunks)
        require(not self.thread.is_alive(), 'Wire recorder did not stop')


class Task:
    def __init__(self, args):
        self.args, self.root = args, args.root.resolve()
        require(re.fullmatch(r'g3-t02-(reproduce|verify)-[\d-]+', args.run_id), 'Invalid run identity')
        self.run = self.root / 'out/runs' / args.run_id
        self.context = load(self.run / 'context.json')
        self.amase = module('amase_runtime', self.root / 'scripts/amase/amase.py')
        self.record = dict(task='G3-T02', runId=args.run_id, status='running', cases=[], startedAt=release.lmcp.stamp(),
                           taskExecutionValidated=False, coverageValidated=False)

    def command(self, name, argv, cwd=None):
        result = subprocess.run([str(a) for a in argv], cwd=cwd or self.root, capture_output=True, timeout=180,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run / (name + '.stdout')).write_bytes(result.stdout)
        (self.run / (name + '.stderr')).write_bytes(result.stderr)
        require(result.returncode == 0, name + ' failed; see command output')

    def prepare(self):
        require(sys.version_info[:3] == (3,14,7) and struct.calcsize('P') == 8 and sys.flags.isolated,
                'Expected isolated Python 3.14.7 x64')
        self.record.update(pythonVersion=sys.version, pythonExecutable=sys.executable)
        prior = self.root / 'out/runs' / self.context['baselineRunId']
        require(load(prior / 'result.json')['status'] == load(prior / 'entry-result.json')['status'] == 'passed', 'Baseline not qualified')
        source = load(prior / 'baseline.json')
        require(load(prior / 'result.json')['baselineSHA256'] == sha(prior / 'baseline.json'), 'Baseline receipt differs')
        candidates = all(self.context.get(key) for key in ('amaseBuildRunId','uxasBuildRunId','uxasValidationRunId'))
        require(candidates or not any(self.context.get(key) for key in ('amaseBuildRunId','uxasBuildRunId','uxasValidationRunId')), 'All candidate identities required')
        changed = []
        repairs = {'OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java',
                   'OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.cpp',
                   'OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.h',
                   'OpenUxAS/src/cpp/Communications/ZeroMq/ZmqAttributedMsgSenderReceiver.cpp'}
        for row in source['frozenInputs']:
            current = sha(self.root/row['path'])
            if current != row['sha256']:
                require(candidates and row['path'] in repairs, 'Unexpected baseline change: '+row['path'])
                changed.append(dict(path=row['path'], before=row['sha256'], after=current))
        if candidates:
            self.uxas = self.root/'out/build/uxas'/self.context['uxasBuildRunId']/'candidate'
            provenance = release.runtime.qualified(SimpleNamespace(root=self.root, candidate=self.uxas,
                build_run_id=self.context['uxasBuildRunId'], validation_run_id=self.context['uxasValidationRunId']))
            self.pointer = dict(status='qualified-candidate', provenance=provenance)
        else:
            self.uxas, self.pointer = release.resolve(self.root, source['provenance'])
        self.folder, self.info, self.lmcp_jar = self.amase.candidate(self.root, self.context.get('amaseBuildRunId') or None)
        self.record.update(candidateMode=candidates, baselineRepairs=changed)
        self.record['baselineRunId'] = self.context['baselineRunId']
        self.record['formalUxas'] = self.pointer
        self.record['amaseBuildRunId'] = self.info['runId']
        self.record['artifacts'] = dict(amase=self.info['artifact'], amaseBuildInfoSHA256=sha(self.folder/'build-info.json'),
            lmcpSHA256=sha(self.lmcp_jar), uxasSHA256=sha(self.uxas/'uxas.exe'), baselineSHA256=sha(prior/'baseline.json'))
        paths = [p for folder in ['scripts/g3_protocol', 'tests/g3_protocol'] for p in (self.root / folder).rglob('*') if p.is_file()]
        paths += [self.root / 'tests/windows/g3-protocol.tests.ps1', self.root / 'scripts/validation/sentinel.py']
        self.inputs = [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]
        self.record['inputs'] = self.inputs
        sys.path.insert(0, str(self.root / 'out/generated/lmcp/py'))
        from lmcp import LMCPFactory
        self.factory = LMCPFactory
        self.build = self.root / 'out/build/g3-protocol' / self.args.run_id
        self.build.mkdir(parents=True)
        self.cp = [self.folder / 'OpenAMASE.jar', self.lmcp_jar] + [self.root / self.amase.PROJECT / p for p in self.amase.LIBRARIES]
        self.java = Path(self.context['javaHome']) / 'bin/java.exe'
        classes = self.build / 'classes'; classes.mkdir()
        self.command('javac', [Path(self.context['javaHome']) / 'bin/javac.exe', '-encoding', 'UTF-8', '--release', '11',
            '-cp', os.pathsep.join(map(str, self.cp)), '-d', classes, self.root / 'tests/g3_protocol/ProtocolProbe.java'] +
            ([self.root/'tests/g3_protocol/SentinelReaderChecks.java'] if self.args.action != 'reproduce' else []))
        self.cp.append(classes)
        native = self.build / 'native'
        self.command('cmake-configure', [self.context['cmake'], '-S', self.root / 'tests/g3_protocol', '-B', native, '-G', 'Ninja',
            '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_MAKE_PROGRAM='+self.context['ninja'], '-DUXAS_DEPENDENCIES_PREFIX='+self.context['dependenciesPrefix']])
        self.command('cmake-build', [self.context['cmake'], '--build', native])
        self.subscriber = native / 'pub_capture.exe'
        self.record['observerSHA256'] = sha(self.subscriber)

    def start(self, folder, argv):
        stdout, stderr = (folder / 'stdout.log').open('wb'), (folder / 'stderr.log').open('wb')
        try:
            process = subprocess.Popen([str(x) for x in argv], cwd=folder, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            stdout.close(); stderr.close()
        record = dict(pid=process.pid, arguments=list(map(str, argv)), workingDirectory=str(folder),
                      startedAt=release.lmcp.stamp(), forcedTermination=False, exitCode=None)
        save(folder / 'process.json', record)
        return process, record

    def finish_process(self, folder, process, record):
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            record['forcedTermination'] = True; process.kill(); process.wait(timeout=10)
        record.update(exitCode=process.returncode, reaped=True, finishedAt=release.lmcp.stamp())
        save(folder / 'process.json', record)

    def scenario(self, directory):
        runtime = directory / 'amase'; runtime.mkdir()
        settings = runtime / 'config'
        shutil.copytree(self.root / self.amase.PROJECT / 'config/amase_headless', settings)
        shutil.copytree(self.root / self.amase.PROJECT / 'data', runtime / 'data')
        (runtime / 'data/overlay').mkdir(exist_ok=True)
        shutil.copy2(self.root / self.amase.PROJECT / 'buildinfo.xml', runtime / 'buildinfo.xml')
        for name in ('tmp', 'home'): (runtime / name).mkdir()
        shutil.copy2(self.root / self.amase.SCENARIO, runtime / 'scenario.xml')
        plugins = ET.parse(settings / 'Plugins.xml')
        if self.args.action != 'reproduce':
            for node in plugins.findall("Plugin[@Class='avtas.amase.scenario.ConstructiveControl']"):
                plugins.getroot().remove(node)
        plugins.find(".//Plugin[@Class='avtas.amase.network.TcpServer']/TCPServer").set('Port', '5556')
        plugins.getroot().insert(0, ET.Element('Plugin', Class='validation.g3.ProtocolProbe'))
        plugins.write(settings / 'Plugins.xml', encoding='utf-8', xml_declaration=True)
        entities = ET.parse(settings / 'EntityControl.xml')
        for conn in entities.findall('.//TcpConnection'):
            conn.set('Port', str(int(conn.get('Port')) + 10000))
        entities.write(settings / 'EntityControl.xml', encoding='utf-8', xml_declaration=True)
        return runtime

    def configuration(self, directory, self_generated, direct=False):
        node = ET.Element('UxAS', EntityID='100', FormatVersion='1.0', EntityType='None', RunDuration_s='60.0')
        for port, server, names in [(5556 if direct else 5557, 'false', ['afrl.cmasi.MissionCommand', 'afrl.cmasi.LineSearchTask', 'afrl.cmasi.VehicleActionCommand']),
                                    (9999, 'true', ['afrl.', 'uxas.'])]:
            bridge = ET.SubElement(node, 'Bridge', Type='LmcpObjectNetworkTcpBridge', TcpAddress='tcp://127.0.0.1:'+str(port),
                                   Server=server, ConsiderSelfGenerated=str(self_generated if not server == 'true' else False).lower())
            if self.args.action != 'reproduce' and server == 'false':
                bridge.set('ExportOnlyLocalMessages', 'true')
            for name in names: ET.SubElement(bridge, 'SubscribeToMessage', MessageType=name)
        bridge = ET.SubElement(node, 'Bridge', Type='LmcpObjectNetworkPublishPullBridge', AddressPUB='tcp://127.0.0.1:5560',
                               AddressPULL='tcp://127.0.0.1:5561', ConsiderSelfGenerated='false')
        for name in ('afrl.', 'uxas.'): ET.SubElement(bridge, 'SubscribeToMessage', MessageType=name)
        ET.SubElement(node, 'Service', Type='HelloWorld', StringToSend='G3-T02 local PUB positive control', SendPeriod_ms='500')
        send = ET.SubElement(node, 'Service', Type='SendMessagesService', PathToMessageFiles=str(directory)+os.sep)
        scenario = ET.parse(self.root / self.amase.SCENARIO)
        mission = scenario.find('ScenarioEventList/MissionCommand')
        for index in range(2):
            command = copy.deepcopy(mission); command.attrib.pop('Time', None)
            command.find('CommandID').text = str(97001+index)
            name = 'mission-'+str(index)+'.xml'
            ET.ElementTree(command).write(directory / name, encoding='utf-8', xml_declaration=True)
            ET.SubElement(send, 'Message', MessageFileName=name, SendTime_ms=str(6000+500*index))
        if self.args.action != 'reproduce':
            shutil.copy2(self.root/baseline_driver.TASK, directory/'task.xml')
            ET.SubElement(send, 'Message', MessageFileName='task.xml', SendTime_ms='7000')
        ET.ElementTree(node).write(directory / 'uxas.xml', encoding='utf-8', xml_declaration=True)

    def case(self, name, self_generated=False, split=False, expected_missing=False, disconnect=False, direct=False):
        directory = self.run / name; directory.mkdir()
        ports = [5556, 5557, 19400, 19500, 9999, 5560, 5561]
        if direct: ports.remove(5557)
        for port in ports: self.amase.check_port(port)
        java_dir = self.scenario(directory)
        cpp_dir = directory / 'uxas'; cpp_dir.mkdir()
        pub_dir = directory / 'pub'; pub_dir.mkdir()
        self.configuration(cpp_dir, self_generated, direct)
        item = dict(name=name, status='running', selfGenerated=self_generated, split=split, ports=ports,
                    topology='direct TCP with passive monitors' if direct else 'byte-preserving TCP impairment recorder')
        self.record['cases'].append(item); save(self.run / 'result.json', self.record)
        children, tap, observer, monitor = [], None, None, None
        try:
            argv = [self.java, '-Dfile.encoding=UTF-8', '-Djava.awt.headless=true', '-Djava.io.tmpdir='+str(java_dir/'tmp'),
                    '-Duser.home='+str(java_dir/'home'), '-Dg3.protocol.directory='+str(java_dir),
                    '-cp', os.pathsep.join(map(str, self.cp)), 'avtas.app.Application', '--config', str(java_dir/'config'),
                    '--scenario', str(java_dir/'scenario.xml'), '--sim_rate', '1']
            java, jr = self.start(java_dir, argv); children.append((java_dir, java, jr))
            deadline = time.monotonic()+20
            while not any(x['kind'] == 'initialized' for x in self.amase.events(java_dir)):
                require(java.poll() is None and time.monotonic() < deadline, 'AMASE initialization failed')
                time.sleep(0.05)
            if direct:
                monitor = Capture(connect(5556, java), directory/'amase-monitor.bin')
            else:
                tap = WireTap(directory, 5557, 5556, split)
            pub, pr = self.start(pub_dir, [self.subscriber, 'tcp://127.0.0.1:5560', pub_dir/'frames.bin', pub_dir/'stop'])
            children.append((pub_dir, pub, pr))
            cpp, cr = self.start(cpp_dir, [self.uxas/'uxas.exe', '-cfgPath', cpp_dir/'uxas.xml'])
            children.append((cpp_dir, cpp, cr))
            observer = Capture(connect(9999, cpp), directory/'observer.bin')
            if tap: require(tap.ready.wait(15), 'Main TCP connection not ready')
            if direct:
                query = 'Get-NetTCPConnection -State Established -OwningProcess '+str(cpp.pid)+' | Where-Object { $_.RemotePort -eq 5556 } | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,OwningProcess | ConvertTo-Json -Compress'
                result = subprocess.run(['powershell.exe','-NoProfile','-Command',query], capture_output=True, timeout=15,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                require(result.returncode == 0 and result.stdout.strip(), 'Direct C++ to Java connection absent')
                item['directConnection'] = json.loads(result.stdout)
            if self.args.action != 'reproduce':
                deadline = time.monotonic()+15
                while True:
                    rows, _ = wire.decode((directory/'observer.bin').read_bytes(), self.factory)
                    if any(r['type'] == 'afrl.cmasi.KeyValuePair' and r['sourceEntity'] == '100' for r in rows):
                        break
                    require(time.monotonic() < deadline and cpp.poll() is None, 'Observer bus readiness missing')
                    time.sleep(0.05)
                item['transportReadyBeforeStart'] = True
                (java_dir/'request-start').touch()
            query = 'Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in '+','.join(map(str, ports))+' } | Select-Object LocalPort,OwningProcess | ConvertTo-Json -Compress'
            wanted = {5556:java.pid, 19400:java.pid, 19500:java.pid, 5557:os.getpid(), 9999:cpp.pid, 5560:cpp.pid, 5561:cpp.pid}
            if direct: wanted.pop(5557)
            deadline = time.monotonic()+15
            while True:
                result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', query], capture_output=True, timeout=15,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                require(result.returncode == 0, 'Port ownership query failed')
                owners = {x['LocalPort']: x['OwningProcess'] for x in json.loads(result.stdout)}
                if owners == wanted or time.monotonic() >= deadline:
                    break
                require(all(wanted.get(p) == pid for p, pid in owners.items()), 'Foreign port owner')
                time.sleep(0.1)
            require(owners == wanted, 'Unexpected port owner: '+str(owners)); item['portOwners'] = owners
            deadline = time.monotonic()+10
            while time.monotonic() < deadline:
                require(java.poll() is None and cpp.poll() is None and pub.poll() is None, 'Protocol process exited early')
                require((tap is None or tap.error is None) and observer.error is None and (monitor is None or monitor.error is None), 'Capture transport failed')
                require((tap is None or not tap.disconnected.is_set()) and not observer.disconnected and (monitor is None or not monitor.disconnected), 'Unexpected TCP disconnect')
                time.sleep(0.1)
            if self.args.action != 'reproduce' and name == 'preserved-source':
                item['socketChecks'] = self.socket_checks(directory, java_dir, observer)
            if disconnect:
                packet = self.key_value('discard-'+self.args.run_id)
                prefix = packet[:len(packet)//2]
                (directory/'injected-partial.bin').write_bytes(prefix)
                reader = wire.sentinel.SentinelReader(); require(not reader.feed(prefix), 'Partial input decoded')
                try:
                    reader.eof()
                    raise RuntimeError('Partial input not rejected at disconnect')
                except wire.sentinel.ProtocolError:
                    pass
                tap.sockets[0].sendall(prefix)
                tap.sockets[0].shutdown(socket.SHUT_RDWR)
                require(tap.disconnected.wait(3), 'TCP disconnect not detected')
                item['disconnect'] = dict(detected=True, partialBytes=len(prefix), discarded=True,
                                          recovery='stop entire group; next case uses new processes and readers')
        finally:
            if observer:
                try:
                    from uxas.messages.uxnative.KillService import KillService
                    stop = KillService(); stop.ServiceID = -1
                    packet = wire.frame(self.factory.packMessage(stop, True), stop.FULL_LMCP_TYPE_NAME)
                    (directory/'stop-request.bin').write_bytes(packet); observer.sock.sendall(packet)
                except Exception as error:
                    item['stopRequestError'] = repr(error)
            (java_dir/'request-shutdown').touch(); (pub_dir/'stop').touch()
            for folder, process, record in reversed(children): self.finish_process(folder, process, record)
            if observer: observer.close()
            if monitor: monitor.close()
            if tap: tap.close()
            item['processes'] = [record for _, _, record in children]
            save(directory/'case-result.json', item)
        for port in ports: self.amase.check_port(port)
        lifecycle_ok = all(r['exitCode'] == 0 and not r['forcedTermination'] for _, _, r in children)
        if self.args.action != 'reproduce':
            require(lifecycle_ok, 'Processes did not close normally')
        decoded = {}
        for stream in (('amase-monitor', 'observer') if direct else ('java-to-cpp', 'cpp-to-java', 'observer')):
            decoded[stream], tail = wire.decode((directory/(stream+'.bin')).read_bytes(), self.factory)
            (directory/(stream+'-unconsumed.bin')).write_bytes(tail)
            require(not tail, 'Incomplete captured stream: '+stream)
        pub_raw, tail = wire.pub_messages((pub_dir/'frames.bin').read_bytes()); require(not tail, 'Incomplete PUB record')
        decoded['pub'] = []
        for message in pub_raw:
            rows, tail = wire.decode(wire.envelope(message), self.factory)
            require(not tail, 'Incomplete PUB message'); decoded['pub'].extend(rows)
        save(directory/'decoded.json', decoded)
        java_stream = decoded['amase-monitor' if direct else 'java-to-cpp']
        command_stream = decoded['observer' if direct else 'cpp-to-java']
        java_states = [r for r in java_stream if r['type'] == 'afrl.cmasi.AirVehicleState']
        require({r['id'] for r in java_states} == {'400','500'}, 'Missing real Java states')
        require(all(r['sourceEntity'] == r['sourceService'] == '0' for r in java_states), 'Java source attributes differ')
        configs = [r for r in decoded['observer'] if r['type'] == 'afrl.cmasi.AirVehicleConfiguration']
        require({r['id'] for r in configs} == {'400','500'} and all(r['rawSHA256'] in {j['rawSHA256'] for j in java_stream} for r in configs), 'Real configurations did not reach UxAS')
        bus_states = [r for r in decoded['observer'] if r['type'] == 'afrl.cmasi.AirVehicleState']
        require(bus_states and all(r['sourceEntity'] == ('100' if self_generated else '0') for r in bus_states), 'TCP source rewriting differs')
        require(all(r['rawSHA256'] in {s['rawSHA256'] for s in java_states} for r in bus_states), 'Bus state absent from actual Java stream')
        require(not (Counter(r['rawSHA256'] for r in bus_states)-Counter(r['rawSHA256'] for r in java_states)), 'State duplicated by bridge')
        for entity in ('400','500'):
            states = [r for r in bus_states if r['id'] == entity]
            require(len(states) >= 10 and int(states[-1]['timeMs']) > int(states[0]['timeMs']) and
                    len({(r['latitude'],r['longitude']) for r in states}) > 1, 'Real dynamic states missing: '+entity)
        require({r.get('id') for r in java_states} == {'400','500'}, 'Entity set differs')
        pub_states = [r for r in decoded['pub'] if r['type'] == 'afrl.cmasi.AirVehicleState']
        require(bool(pub_states) == self_generated, 'PUB source filtering differs')
        require(any(r['type'] == 'afrl.cmasi.KeyValuePair' and r['sourceEntity'] == '100' for r in decoded['pub']), 'PUB positive control absent')
        echoed = [] if direct else [r for r in command_stream if r['type'] == 'afrl.cmasi.MissionCommand' and r['commandId'] == '100']
        item['scenarioCommandEchoCount'] = len(echoed)
        if self.args.action != 'reproduce':
            require(not echoed, 'Scenario command echoed back to AMASE')
        emitted = [r for r in command_stream if r['type'] == 'afrl.cmasi.MissionCommand' and r['commandId'] in ('97001','97002')]
        require({r['commandId'] for r in emitted} == {'97001','97002'} and len(emitted) == 2, 'Missing/duplicate actual C++ commands')
        received = []
        for event in self.amase.events(java_dir):
            if event['kind'] == 'message' and event['type'] == 'afrl.cmasi.MissionCommand':
                xml = ET.fromstring(base64.b64decode(event['xmlBase64']))
                if xml.findtext('CommandID') in ('97001','97002'): received.append(xml.findtext('CommandID'))
        require((not received) if expected_missing else sorted(received) == ['97001','97002'], 'Unexpected AMASE command receipt: '+str(received))
        if not direct:
            require(not [r for r in command_stream if r['type'].endswith('AirVehicleState')], 'State forwarded back to simulator')
            require(not [r for r in java_stream if r.get('commandId') in ('97001','97002')], 'Command forwarded back to UxAS')
        if self.args.action != 'reproduce':
            self.event_checks(java_dir, item)
            require(not any(r.get('value','').startswith('discard-') for rows in decoded.values() for r in rows), 'Partial frame entered a run')
        if name == 'fresh-group-after-disconnect':
            previous = self.record['cases'][-2]
            require(previous['name'] == 'disconnect-partial' and previous['expectedFailureVerified'], 'Missing failed prior run')
            require(not ({r['pid'] for r in previous['processes']} & {r['pid'] for _,_,r in children}), 'Prior process reused')
            item['priorFailedCase'] = previous['name']
        item.update(status='failed' if expected_missing or not lifecycle_ok or disconnect else 'passed', expectedFailureVerified=expected_missing or disconnect,
                    javaCommandIds=received, javaStateCount=len(java_states), busStateCount=len(bus_states), pubStateCount=len(pub_states),
                    portReleased=True, lifecyclePassed=lifecycle_ok,
                    failure='controlled disconnect with partial frame' if disconnect else ('fragmented marker dropped by Java receiver' if expected_missing else ('TCP shutdown blocked' if not lifecycle_ok else None)))
        item['files'] = [dict(path=p.relative_to(directory).as_posix(), sha256=sha(p)) for p in sorted(directory.rglob('*'))
                         if p.is_file() and p.name != 'case-result.json']
        save(directory/'case-result.json', item)
        print(name+': '+item['status']+(' (reproduced)' if expected_missing else ''), flush=True)

    def execute(self):
        try:
            self.prepare()
            if self.args.action == 'reproduce':
                self.case('original-normal')
                self.case('original-fragmented', split=True, expected_missing=True)
                self.record['status'] = 'reproduced'
            else:
                self.case('preserved-source')
                self.case('rewritten-source', self_generated=True)
                self.case('fragmented', split=True)
                self.case('disconnect-partial', disconnect=True)
                self.case('fresh-group-after-disconnect')
                self.case('direct-connection', direct=True)
                self.parser_checks()
                self.record['status'] = 'passed'
            self.amase.verify_records(self.root, self.inputs)
            return 0
        except BaseException as error:
            for item in self.record['cases']:
                if item['status'] == 'running':
                    item.update(status='failed', error=str(error))
                    save(self.run/item['name']/'case-result.json', item)
            self.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
            print('FAILED: '+str(error), flush=True)
            return 1
        finally:
            self.record['finishedAt'] = release.lmcp.stamp()
            save(self.run/'result.json', self.record)

    def parser_checks(self):
        directory = self.run/'malformed'; directory.mkdir()
        samples = {}
        for direction in ('java-to-cpp','cpp-to-java'):
            reader = wire.sentinel.SentinelReader()
            frames = reader.feed((self.run/'preserved-source'/(direction+'.bin')).read_bytes())
            samples[direction] = frames[0]['wire']
        checks = module('g3_checks', self.root/'tests/g3_protocol/checks.py')
        self.record['strictParserChecks'] = checks.run(wire, self.factory, samples, directory)
        self.command('java-reader-checks', [self.java, '-cp', os.pathsep.join(map(str, self.cp)),
            'validation.g3.SentinelReaderChecks', directory])

    def key_value(self, value):
        from afrl.cmasi.KeyValuePair import KeyValuePair
        item = KeyValuePair(); item.Key = 'G3-T02'; item.Value = value
        return wire.frame(self.factory.packMessage(item, True), item.FULL_LMCP_TYPE_NAME)

    def event_checks(self, java_dir, item):
        events = self.amase.events(java_dir)
        initialized = [e for e in events if e['kind'] == 'initialized']
        require(len(initialized) == 1, 'Initialization evidence differs')
        for field, path in [('amaseSource',self.folder/'OpenAMASE.jar'),('lmcpSource',self.lmcp_jar)]:
            require(Path(unquote(urlparse(initialized[0][field]).path).lstrip('/')).resolve() == path.resolve(), 'Loaded Java source differs')
        objects = [ET.fromstring(base64.b64decode(e['xmlBase64'])) for e in events if e['kind'] == 'message']
        original = [x for x in objects if x.tag == 'MissionCommand' and x.findtext('CommandID') == '100']
        require(sorted(x.findtext('VehicleID') for x in original) == ['400','500'], 'Original commands executed more than once')
        configs = [x for x in objects if x.tag == 'AirVehicleConfiguration']
        require({x.findtext('ID') for x in configs} == {'400','500'}, 'Real configurations absent')
        tasks = [x for x in objects if x.tag == 'LineSearchTask' and x.findtext('TaskID') == '1000']
        require(len(tasks) == 1 and len(tasks[0].findall('PointList/Location3D')) == 90, 'Original task payload differs')
        item['effectiveFields'] = dict(cameraBands={x.findtext('ID'):[c.findtext('SupportedWavelengthBand') for c in x.findall('.//CameraConfiguration')] for x in configs},
            viewAngles=[{y.tag:y.text for y in x} for x in tasks[0].findall('ViewAngleList/Wedge')],
            desiredBands=[x.text for x in tasks[0].findall('DesiredWavelengthBands/WavelengthBand')])
        angles = item['effectiveFields']['viewAngles']
        require(len(angles) == 1 and float(angles[0]['AzimuthCenterline']) == 35 and float(angles[0]['VerticalCenterline']) == -60,
                'Effective C++ view angle differs')

    def socket_checks(self, directory, java_dir, observer):
        checks = module('g3_socket_checks', self.root/'tests/g3_protocol/checks.py')
        java_packet = self.key_value('java-coalesced')
        bad = checks.malformed(wire, self.key_value('java-rejected'))['outer-checksum']
        with connect(5556) as client:
            client.sendall(java_packet+java_packet+bad)
            deadline = time.monotonic()+5
            closed = False
            while time.monotonic() < deadline:
                try:
                    if not client.recv(65536):
                        closed = True; break
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    closed = True; break
            require(closed, 'AMASE did not close malformed connection')
        partial = self.key_value('java-discarded')
        with connect(5556) as client:
            client.sendall(partial[:len(partial)//2])
        with connect(5556) as client:
            client.sendall(self.key_value('java-fresh-connection'))
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                if any('java-fresh-connection' in base64.b64decode(e.get('xmlBase64','')).decode('utf-8') for e in self.amase.events(java_dir)):
                    break
                time.sleep(0.05)
        xml = [base64.b64decode(e['xmlBase64']).decode('utf-8') for e in self.amase.events(java_dir) if e.get('type') == 'afrl.cmasi.KeyValuePair']
        require(sum('java-coalesced' in x for x in xml) == 2 and sum('java-fresh-connection' in x for x in xml) == 1,
                'AMASE coalesced/fresh connection evidence missing')
        require(not any('java-rejected' in x or 'java-discarded' in x for x in xml), 'AMASE accepted malformed or partial input')
        bad = checks.malformed(wire, self.key_value('cpp-rejected'))
        packet = bad['outer-checksum']+bad['outer-length']+self.key_value('cpp-coalesced-1')+self.key_value('cpp-coalesced-2')
        (directory/'injected-coalesced.bin').write_bytes(packet)
        observer.sock.sendall(packet)
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            rows, _ = wire.decode((directory/'observer.bin').read_bytes(), self.factory)
            values = [r.get('value') for r in rows if r.get('key') == 'G3-T02']
            if 'cpp-coalesced-1' in values and 'cpp-coalesced-2' in values:
                break
            time.sleep(0.05)
        require(values.count('cpp-coalesced-1') == values.count('cpp-coalesced-2') == 1 and 'cpp-rejected' not in values,
                'C++ coalesced/invalid envelope evidence differs')
        return dict(javaCoalesced=2, javaMalformedClosed=True, javaPartialDiscarded=True, javaFreshConnection=True,
                    cppCoalesced=2, cppOuterLengthAndChecksumRejected=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--action', choices=['reproduce','verify'], required=True)
    sys.exit(Task(parser.parse_args()).execute())

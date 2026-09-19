"""Windows G3-T03 controlled startup. Task execution/coverage belong to later cards."""
import argparse
import base64
from collections import Counter
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import unquote, urlparse
import xml.dom.minidom
import xml.etree.ElementTree as ET


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


protocol = module('startup_protocol', Path(__file__).parents[1] / 'g3_protocol/run.py')
gates = module('startup_gates', Path(__file__).with_name('gates.py'))
wire, release = protocol.wire, protocol.release
load, save, sha, require = release.load, release.save, release.sha, release.require
stamp = release.lmcp.stamp


def digest(data):
    return hashlib.sha256(data).hexdigest().upper()


class Stream:
    """Independent incremental receiver; never sends its received messages back."""
    def __init__(self, sock, folder, name, factory):
        self.sock, self.folder, self.name, self.factory = sock, folder, name, factory
        self.rows, self.error, self.disconnected = [], None, False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.receive, daemon=True)
        self.thread.start()

    def receive(self):
        reader, decoder = wire.sentinel.SentinelReader(), wire.sentinel.Decoder(self.factory)
        try:
            with (self.folder / (self.name + '.bin')).open('wb', buffering=0) as raw_file, \
                    (self.folder / (self.name + '.jsonl')).open('w', encoding='utf-8') as decoded:
                while not self.stop.is_set():
                    try:
                        data = self.sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        self.disconnected = True
                        reader.eof()
                        break
                    raw_file.write(data)
                    for frame in reader.feed(data):
                        row, raw = decoder.decode(frame)
                        obj = self.factory.LMCPFactory().getObject(bytearray(raw))
                        row.update(offset=frame['offset'], length=frame['length'], rawSHA256=digest(raw),
                                   wallTime=stamp(), monotonicSeconds=time.monotonic(),
                                   xmlBase64=base64.b64encode(obj.toXMLStr('').encode('utf-8')).decode('ascii'))
                        for field, key in [('ID', 'id'), ('TaskID', 'taskId'), ('CommandID', 'commandId'),
                                           ('VehicleID', 'vehicleId'), ('RequestID', 'requestId'), ('ResponseID', 'responseId')]:
                            if hasattr(obj, field): row[key] = str(getattr(obj, field))
                        if hasattr(obj, 'Key'): row.update(key=obj.Key, value=obj.Value)
                        decoded.write(json.dumps(row, ensure_ascii=False) + '\n'); decoded.flush()
                        self.rows.append(row)
        except Exception as error:
            if not self.stop.is_set(): self.error = repr(error)
        finally:
            (self.folder / (self.name + '-tail.bin')).write_bytes(reader.buffer)

    def close(self):
        self.stop.set()
        self.sock.close()
        self.thread.join(3)
        require(not self.thread.is_alive(), 'Receiver thread did not stop')


class Startup:
    def __init__(self, args):
        self.args, self.root = args, args.root.resolve()
        self.run = self.root / 'out/runs' / args.run_id
        self.context = load(self.run / 'context.json')
        self.amase = module('startup_amase', self.root / 'scripts/amase/amase.py')
        self.record = dict(schemaVersion=1, task='G3-T03', runId=args.run_id, status='running', startedAt=stamp(),
                           taskExecutionValidated=False, taskCompletionValidated=False, coverageValidated=False, cases=[])
        self.started = time.monotonic()
        # Reserve the 30 s shutdown wait, 10 s forced-reap fallback and receiver
        # joins/evidence writes inside the 2700 s automatic-run budget.
        self.operation_deadline = self.started + 2650

    def inputs(self):
        paths = [p for d in ('scripts/g3_integration', 'tests/g3_integration') for p in (self.root / d).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
        paths += [self.root / p for p in ('scripts/windows/run-g3.ps1', 'scripts/windows/finish-g3-gui.ps1',
                  'tests/windows/g3-startup.tests.ps1', 'scripts/g3_protocol/run.py', 'scripts/g3_protocol/wire.py',
                  'scripts/validation/sentinel.py', 'scripts/g3_baseline/check.py')]
        return [dict(path=p.relative_to(self.root).as_posix(), sha256=sha(p)) for p in sorted(paths)]

    def prepare(self):
        require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.flags.isolated,
                'Expected isolated Python 3.14.7 x64')
        self.config = load(Path(self.context['configuration']))
        require(self.config['schemaVersion'] == 1 and self.config['scope'] == 'startup', 'Unsupported configuration')
        require(self.config['simulationRate'] == 1 and self.config['minimumDynamicStates'] >= 5, 'Invalid initialization policy')
        require(self.config['timeoutsSeconds'] == dict(initialization=30, taskInitialization=30, planning=30,
                                                      shutdown=30, wholeRun=2700), 'Expected fixed G3 timeouts')
        for key, expected in [('scenario', protocol.baseline_driver.SCENARIO), ('task', protocol.baseline_driver.TASK),
                              ('request', protocol.baseline_driver.REQUEST),
                              ('uxasConfiguration', protocol.baseline_driver.EXAMPLE + 'cfg_WaterwaySearch.xml')]:
            require(self.config[key] == expected, 'T03 preserves original input: ' + key)
        for mode in ('Gui', 'Headless'):
            ports = self.config['modes'][mode]
            require(set(ports['entityPorts']) == {'400', '500'}, 'Both entity ports required')
            values = [ports['amasePort'], ports['observerPort'], *ports['entityPorts'].values()]
            require(len(set(values)) == 4 and all(type(p) is int and 1024 <= p <= 65535 for p in values), 'Invalid ports')
        prior = self.root / 'out/runs' / self.context['baselineRunId']
        require(load(prior / 'result.json')['status'] == load(prior / 'entry-result.json')['status'] == 'passed', 'Unqualified baseline')
        require(sha(prior / 'baseline.json') == load(prior / 'result.json')['baselineSHA256'], 'Baseline receipt mismatch')
        self.baseline = load(prior / 'baseline.json')
        self.amase.verify_records(self.root, self.baseline['frozenInputs'])
        self.uxas, pointer = release.resolve(self.root, self.baseline['provenance'])
        self.folder, info, self.lmcp_jar = self.amase.candidate(self.root, None)
        require(info['runId'] == self.baseline['amase']['buildRunId'], 'AMASE differs from baseline')
        self.record.update(baselineRunId=self.context['baselineRunId'], baselineSHA256=sha(prior / 'baseline.json'),
            formalUxas=pointer, amaseBuildRunId=info['runId'], pythonVersion=sys.version,
            configurationSHA256=sha(Path(self.context['configuration'])), inputs=self.inputs(),
            artifacts=dict(amaseSHA256=sha(self.folder / 'OpenAMASE.jar'), lmcpSHA256=sha(self.lmcp_jar),
                           uxasSHA256=sha(self.uxas / 'uxas.exe')))
        save(self.run / 'configuration.json', self.config)
        sys.path.insert(0, str(self.root / 'out/generated/lmcp/py'))
        from lmcp import LMCPFactory
        self.factory = LMCPFactory
        build = self.root / 'out/build/g3-integration' / self.args.run_id
        classes = build / 'classes'; classes.mkdir(parents=True)
        self.cp = [self.folder / 'OpenAMASE.jar', self.lmcp_jar] + [self.root / self.amase.PROJECT / p for p in self.amase.LIBRARIES]
        self.java = Path(self.context['javaHome']) / 'bin/java.exe'
        result = subprocess.run([str(Path(self.context['javaHome']) / 'bin/javac.exe'), '-encoding', 'UTF-8', '--release', '11',
            '-cp', os.pathsep.join(map(str, self.cp)), '-d', str(classes), str(Path(__file__).with_name('StartupProbe.java'))],
            capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.run / 'javac.stdout').write_bytes(result.stdout); (self.run / 'javac.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'G3 plugin compile failed')
        self.cp.append(classes)
        self.record['pluginClasses'] = [dict(path=p.relative_to(build).as_posix(), sha256=sha(p)) for p in classes.rglob('*.class')]
        save(self.run / 'result.json', self.record)

    def transition(self, phase, **evidence):
        row = dict(phase=phase, wallTime=stamp(), monotonicSeconds=time.monotonic(), **evidence)
        self.item['transitions'].append(row)
        save(self.directory / 'case-result.json', self.item)

    def alive(self):
        require(time.monotonic() < self.operation_deadline, 'timeout:whole-run')
        for _, child, record in self.children:
            require(child.poll() is None, 'process-exited:' + str(record['pid']))
        for stream in self.streams:
            require(stream.error is None and not stream.disconnected, 'stream-failed:' + stream.name + ':' + str(stream.error))
        require(not any(e['kind'] == 'unexpected-start' for e in self.amase.events(self.java_dir)), 'AMASE started before barrier')

    def wait(self, phase, predicate, seconds=30):
        begin = time.monotonic()
        initial_phases = {'amase-paused', 'connections-parseable', 'initial-data'}
        deadline = self.initial_deadline if phase in initial_phases else begin + seconds
        while True:
            self.alive()
            if time.monotonic() >= deadline:
                self.transition(phase + '-timeout', elapsedSeconds=time.monotonic() - begin, timeoutSeconds=seconds,
                                initializationElapsedSeconds=time.monotonic() - self.initial_started if phase in initial_phases else None)
                raise RuntimeError('timeout:' + phase)
            value = predicate()
            if value:
                self.transition(phase, elapsedSeconds=time.monotonic() - begin)
                return value
            time.sleep(0.05)  # Polling interval, never a readiness assumption.

    def launch(self, directory, argv):
        child, row = protocol.Task.start(self, directory, argv)
        self.children.append((directory, child, row))
        return child

    def files(self, mode, fault):
        self.java_dir = self.directory / 'amase'; self.java_dir.mkdir()
        self.cpp_dir = self.directory / 'uxas'; self.cpp_dir.mkdir()
        runtime = self.java_dir
        source = self.root / self.amase.PROJECT
        shutil.copytree(source / 'config' / ('amase' if mode == 'Gui' else 'amase_headless'), runtime / 'config')
        shutil.copytree(source / 'data', runtime / 'data')
        (runtime / 'data/overlay').mkdir(exist_ok=True)
        shutil.copy2(source / 'buildinfo.xml', runtime / 'buildinfo.xml')
        for name in ('tmp', 'home'): (runtime / name).mkdir()
        shutil.copy2(self.root / self.config['scenario'], runtime / 'scenario.xml')
        if fault == 'missing-configuration':
            tree = ET.parse(runtime / 'scenario.xml'); events = tree.find('ScenarioEventList')
            for node in list(events):
                if node.tag == 'AirVehicleConfiguration' and node.findtext('ID') == '500': events.remove(node)
            tree.write(runtime / 'scenario.xml', encoding='utf-8', xml_declaration=True)
        plugins = ET.parse(runtime / 'config/Plugins.xml')
        for node in plugins.findall("Plugin[@Class='avtas.amase.scenario.ConstructiveControl']"): plugins.getroot().remove(node)
        plugins.find(".//Plugin[@Class='avtas.amase.network.TcpServer']/TCPServer").set('Port', str(self.ports['amasePort']))
        plugins.getroot().insert(0, ET.Element('Plugin', Class='validation.g3.StartupProbe'))
        plugins.write(runtime / 'config/Plugins.xml', encoding='utf-8', xml_declaration=True)
        entities = ET.parse(runtime / 'config/EntityControl.xml')
        for parent in entities.iter():
            for node in list(parent):
                if node.tag != 'TcpConnection': continue
                if node.get('Id') not in self.ports['entityPorts']:
                    parent.remove(node)
                else:
                    node.set('Port', str(self.ports['entityPorts'][node.get('Id')]))
        entities.write(runtime / 'config/EntityControl.xml', encoding='utf-8', xml_declaration=True)
        original = self.root / self.config['uxasConfiguration']
        tree = ET.parse(original); uxas = tree.getroot()
        for node in list(uxas):
            if node.tag == 'Bridge' or node.get('Type') == 'SendMessagesService': uxas.remove(node)
            elif fault == 'task-initialization-timeout' and node.get('Type') == 'TaskManagerService': uxas.remove(node)
            elif fault in ('planning-timeout', 'empty-planning-response') and node.get('Type') == 'PlanBuilderService': uxas.remove(node)
            elif fault == 'planning-timeout' and node.get('Type') == 'AutomationRequestValidatorService':
                node.set('MaxResponseTime_ms', '60000')  # Test only: let the controller's 30 s bound fire first.
        for port, server, own, names in [
            (self.ports['amasePort'], 'false', 'false', ['afrl.cmasi.MissionCommand', 'afrl.cmasi.LineSearchTask',
                                                       'afrl.cmasi.VehicleActionCommand', 'afrl.cmasi.KeyValuePair']),
            (self.ports['observerPort'], 'true', 'true', ['afrl.', 'uxas.'])]:
            bridge = ET.SubElement(uxas, 'Bridge', Type='LmcpObjectNetworkTcpBridge',
                TcpAddress='tcp://127.0.0.1:' + str(port), Server=server, ConsiderSelfGenerated=own,
                ExportOnlyLocalMessages='true' if server == 'false' else 'false')
            for name in names: ET.SubElement(bridge, 'SubscribeToMessage', MessageType=name)
        tree.write(self.cpp_dir / 'uxas.xml', encoding='utf-8', xml_declaration=True)
        pairs = [(original, self.cpp_dir / 'uxas.xml'), (self.root / self.config['scenario'], runtime / 'scenario.xml'),
                 (source / 'config' / ('amase' if mode == 'Gui' else 'amase_headless') / 'Plugins.xml', runtime / 'config/Plugins.xml'),
                 (source / 'config' / ('amase' if mode == 'Gui' else 'amase_headless') / 'EntityControl.xml', runtime / 'config/EntityControl.xml')]
        with (self.directory / 'configuration.diff').open('w', encoding='utf-8') as output:
            for before, after in pairs:
                output.writelines(difflib.unified_diff(before.read_text(encoding='utf-8-sig').splitlines(True),
                    after.read_text(encoding='utf-8-sig').splitlines(True), before.relative_to(self.root).as_posix(), after.relative_to(self.root).as_posix()))

    def port_snapshot(self, expected, connected=False):
        ports = ','.join(map(str, expected))
        command = "@(Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(" + ports + ") -or $_.RemotePort -in @(" + ports + ") } | Select-Object LocalPort,RemotePort,State,OwningProcess) | ConvertTo-Json -Compress"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, 'Port inspection failed')
        rows = json.loads(result.stdout or b'[]')
        if isinstance(rows, dict): rows = [rows]
        # MSFT_NetTCPConnection State enum: Listen=2, Established=5.
        owners = {int(r['LocalPort']): int(r['OwningProcess']) for r in rows if r['State'] in (2, 'Listen')}
        require(owners == expected, 'port-owner-mismatch:' + str(owners))
        if connected:
            require(any(r['RemotePort'] == self.ports['amasePort'] and r['OwningProcess'] == self.cpp.pid
                        and r['State'] in (5, 'Established') for r in rows), 'Main TCP connection absent')
        self.item.setdefault('portSnapshots', []).append(dict(wallTime=stamp(), connections=rows))

    def send(self, obj, purpose):
        if purpose == 'task': self.gate.before_task()
        elif purpose == 'automation-request': self.gate.before_request()
        raw = self.factory.packMessage(obj, True)
        packet = wire.frame(raw, obj.FULL_LMCP_TYPE_NAME, source='900', service='1', group='G3Controller')
        index = len(self.item['injections'])
        filename = f'injection-{index:03d}-{purpose}.bin'
        (self.directory / filename).write_bytes(packet)
        row = dict(purpose=purpose, file=filename, type=obj.FULL_LMCP_TYPE_NAME, wallTime=stamp(),
                   monotonicSeconds=time.monotonic(), rawSHA256=digest(raw), inputSourceEntity='900', inputSourceService='1',
                   status='attempted')
        self.item['injections'].append(row)
        save(self.directory / 'case-result.json', self.item)
        self.observer.sock.sendall(packet)
        row['status'] = 'sent'
        return row

    def input_message(self, key):
        node = xml.dom.minidom.parse(str(self.root / self.config[key])).documentElement
        factory = self.factory.LMCPFactory()
        obj = factory.createObjectByName(node.getAttribute('Series'), node.localName)
        require(obj is not None, 'Expected one original ' + key + ' message')
        obj.unpackFromXMLNode(node, factory)
        return obj

    def handshake(self):
        from afrl.cmasi.KeyValuePair import KeyValuePair
        token = self.args.run_id + '/' + digest(self.item['name'].encode('utf-8'))[:16]
        last = [0.0]
        def ready():
            bus = any(r['type'] == 'uxas.messages.uxnative.OnboardStatusReport' and r['sourceEntity'] == '100' for r in self.observer.rows)
            java = any(r.get('key') == 'G3Ready' and r.get('value') == token for r in self.monitor.rows)
            if bus and java: return True
            if time.monotonic() - last[0] > 0.5:
                obj = KeyValuePair(); obj.Key = 'G3Ready'; obj.Value = token
                self.send(obj, 'readiness'); last[0] = time.monotonic()
            return False
        self.wait('connections-parseable', ready)

    def body(self, mode, fault, keep_gui):
        self.initial_started = time.monotonic()
        self.initial_deadline = self.initial_started + 30
        self.transition('initialization-started', timeoutSeconds=30)
        argv = [self.java, '-Dfile.encoding=UTF-8', '-Djava.awt.headless=' + str(mode == 'Headless').lower(),
                '-Djava.io.tmpdir=' + str(self.java_dir / 'tmp'), '-Duser.home=' + str(self.java_dir / 'home'),
                '-Dg3.integration.directory=' + str(self.java_dir), '-Dg3.integration.testFault=' + fault,
                '-cp', os.pathsep.join(map(str, self.cp)), 'avtas.app.Application', '--config', str(self.java_dir / 'config'),
                '--scenario', 'scenario.xml', '--sim_rate', '1']
        self.java_process = self.launch(self.java_dir, argv)
        self.wait('amase-paused', lambda: any(e['kind'] == 'initialized-paused' for e in self.amase.events(self.java_dir)))
        self.monitor = Stream(protocol.connect(self.ports['amasePort'], self.java_process,
            max(0, self.initial_deadline - time.monotonic())), self.directory, 'amase', self.factory)
        self.streams.append(self.monitor)
        self.cpp = self.launch(self.cpp_dir, [self.uxas / 'uxas.exe', '-cfgPath', self.cpp_dir / 'uxas.xml'])
        self.observer = Stream(protocol.connect(self.ports['observerPort'], self.cpp,
            max(0, self.initial_deadline - time.monotonic())), self.directory, 'observer', self.factory)
        self.streams.append(self.observer)
        self.transition('listeners-connected')
        self.handshake()
        self.port_snapshot({self.ports['amasePort']: self.java_process.pid, self.ports['observerPort']: self.cpp.pid}, True)
        require(not any(r['type'] == 'afrl.cmasi.AirVehicleState' for r in self.observer.rows), 'State appeared before start')
        self.transition('start-authorized')
        (self.java_dir / 'request-start').touch()
        if fault == 'early-request':
            self.send(self.input_message('request'), 'automation-request')
            raise RuntimeError('Early request unexpectedly sent')
        initial = self.wait('initial-data', lambda: self.gate.inspect(list(self.observer.rows), list(self.monitor.rows)))
        self.item['initialData'] = initial
        self.port_snapshot({self.ports['amasePort']: self.java_process.pid, self.ports['observerPort']: self.cpp.pid,
                            **{p: self.java_process.pid for p in self.ports['entityPorts'].values()}}, True)
        task = self.input_message('task')
        self.send(task, 'task'); self.transition('task-sent', taskId='1000')
        def initialized():
            for row in self.observer.rows: self.gate.observe_task(row)
            return self.gate.task_initialized and any(r.get('taskId') == '1000' and r['type'] == 'afrl.cmasi.LineSearchTask' for r in self.monitor.rows)
        self.wait('task-initialized', initialized)
        request = self.input_message('request')
        self.send(request, 'automation-request'); self.transition('request-sent')
        def planned():
            responses = [r for r in self.observer.rows if r['type'] == 'afrl.cmasi.AutomationResponse']
            if not responses: return False
            response = ET.fromstring(base64.b64decode(responses[0]['xmlBase64']))
            commands = response.findall('MissionCommandList/MissionCommand')
            require(commands and all(c.findall('WaypointList/Waypoint') for c in commands), 'Planning response has no mission waypoints')
            self.item['planningReceipt'] = dict(commands=[dict(commandId=c.findtext('CommandID'), vehicleId=c.findtext('VehicleID'),
                waypointCount=len(c.findall('WaypointList/Waypoint'))) for c in commands], actualExecutionValidated=False)
            return True
        self.wait('planning-response', planned)
        self.transition('startup-complete')
        if keep_gui:
            (self.java_dir / 'request-pause').touch()
            self.wait('gui-paused', lambda: any(e['kind'] == 'paused' for e in self.amase.events(self.java_dir)))
            save(self.run / 'gui-ready.json', dict(runId=self.args.run_id, case=self.item['name'], controllerPid=os.getpid(),
                javaPid=self.java_process.pid, uxasPid=self.cpp.pid, phase='awaiting-close', wallTime=stamp()))
            print('G3 GUI paused; close using finish-g3-gui.ps1 -RunId ' + self.args.run_id, flush=True)
            self.wait('gui-close-request', lambda: (self.run / 'request-gui-close.json').exists(),
                      max(0, self.operation_deadline - time.monotonic()))

    def cleanup(self):
        self.transition('shutdown-requested')
        if getattr(self, 'observer', None) and getattr(self, 'cpp', None) and self.cpp.poll() is None:
            try:
                from uxas.messages.uxnative.KillService import KillService
                stop = KillService(); stop.ServiceID = -1
                self.send(stop, 'normal-stop')
            except Exception as error:
                self.item.setdefault('cleanupErrors', []).append(str(error))
        if self.java_dir and self.java_dir.is_dir(): (self.java_dir / 'request-shutdown').touch()
        deadline = time.monotonic() + 30
        for folder, child, row in reversed(self.children):
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                row['forcedTermination'] = True
                self.item.setdefault('cleanupErrors', []).append('timeout:shutdown')
                child.kill(); child.wait(timeout=10)
            row.update(exitCode=child.returncode, reaped=True, finishedAt=stamp())
            save(folder / 'process.json', row)
        for stream in self.streams:
            stream.close()
            if stream.error: self.item.setdefault('cleanupErrors', []).append(stream.name + ':' + stream.error)
        self.item['processes'] = [row for _, _, row in self.children]
        for port in self.port_values: self.amase.check_port(port)
        self.item['portsReleased'] = True
        self.item['normalExit'] = bool(self.children) and all(r['exitCode'] == 0 and not r['forcedTermination'] for r in self.item['processes'])
        self.transition('shutdown-finished', normalExit=self.item['normalExit'])

    def audit(self):
        rows, java = self.observer.rows, self.monitor.rows
        logged = []
        for path in sorted(self.cpp_dir.rglob('*.db3')):
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
                for entry in database.execute('SELECT id,time_ms,descriptor,groupID,entityID,serviceID,xml FROM msg'):
                    logged.append(dict(sequence=str(entry[0]), sourceTimeMs=str(entry[1]), type=entry[2],
                        sourceGroup=entry[3], sourceEntity=str(entry[4]), sourceService=str(entry[5]), xml=entry[6]))
        for stream in self.streams:
            require(not (self.directory / (stream.name + '-tail.bin')).read_bytes(), 'Incomplete stream at close')
        for purpose, kind in [('task', 'afrl.cmasi.LineSearchTask'), ('automation-request', 'afrl.cmasi.AutomationRequest')]:
            injections = [r for r in self.item['injections'] if r['purpose'] == purpose]
            require(len(injections) == 1 and injections[0]['status'] == 'sent', 'Injection not single: ' + purpose)
            # The observer bridge excludes its own imported messages. The original
            # UxAS logger is the independent witness to their rewritten attributes.
            matches = [r for r in logged if r['type'] == kind]
            require(len(matches) == 1 and matches[0]['sourceEntity'] == '100' and matches[0]['sourceGroup'] == 'TcpBridge',
                    'Controller import/loop mismatch: ' + purpose)
            self.item.setdefault('controllerImports', []).extend(matches)
            if purpose == 'task':
                require(len([r for r in java if r['type'] == kind and r['rawSHA256'] == injections[0]['rawSHA256']]) == 1,
                        'Original task bytes missing or duplicated in AMASE')
        dynamic = [r for r in rows if r['type'] in ('afrl.cmasi.AirVehicleState', 'afrl.cmasi.AirVehicleConfiguration')]
        require(not (Counter(r['rawSHA256'] for r in dynamic) - Counter(r['rawSHA256'] for r in java)), 'Duplicated or non-Java data')
        require(self.gate.inspect(rows, java), 'Real initialization no longer valid')
        events = self.amase.events(self.java_dir)
        init = next(e for e in events if e['kind'] == 'initialized-paused')
        for key, expected in [('amaseSource', self.folder / 'OpenAMASE.jar'), ('lmcpSource', self.lmcp_jar)]:
            actual = Path(unquote(urlparse(init[key]).path.lstrip('/')))
            require(actual.resolve() == expected.resolve(), 'Class loading mismatch: ' + key)
        require(len([e for e in events if e['kind'] == 'start-request']) == 1, 'Start not single')
        require(any(e['kind'] == 'shutdown-request' for e in events) and any(e['kind'] == 'shutdown' for e in events), 'Missing normal shutdown events')
        task_events = [e for e in events if e.get('type') == 'afrl.cmasi.LineSearchTask']
        require(len(task_events) == 1, 'Task missing or duplicated inside AMASE')
        initial_commands = [ET.fromstring(base64.b64decode(e['xmlBase64'])) for e in events if e.get('type') == 'afrl.cmasi.MissionCommand']
        require(sorted(c.findtext('VehicleID') for c in initial_commands if c.findtext('CommandID') == '100') == ['400', '500'],
                'Original cruise commands were duplicated')
        requests = [r for r in rows if r['type'] == 'uxas.messages.task.UniqueAutomationRequest']
        responses = [r for r in rows if r['type'] == 'uxas.messages.task.UniqueAutomationResponse']
        require(len(requests) == len(responses) == 1 and requests[0]['requestId'] == responses[0]['responseId'], 'Planning identity mismatch')
        self.item['planningReceipt'].update(uniqueRequestId=requests[0]['requestId'], uniqueResponseId=responses[0]['responseId'])
        phases = {r['phase']: r['monotonicSeconds'] for r in self.item['transitions']}
        require(phases['initial-data'] < phases['task-sent'] < phases['task-initialized'] < phases['request-sent'] < phases['planning-response'], 'Initialization ordering differs')
        require(len([r for r in rows if r['type'] == 'uxas.messages.task.TaskInitialized' and r.get('taskId') == '1000']) == 1, 'Task initialization not single')
        self.item['messageCounts'] = dict(Counter(r['type'] for r in rows))
        self.item['actualSimulationSeconds'] = events[-1]['simTimeSeconds']

    def case(self, name, mode, fault='', keep_gui=False):
        self.directory = self.run / name; self.directory.mkdir()
        self.ports = self.config['modes'][mode]
        self.port_values = [self.ports['amasePort'], self.ports['observerPort'], *self.ports['entityPorts'].values()]
        self.item = dict(name=name, mode=mode, fault=fault, status='running', ports=self.ports, startedAt=stamp(), transitions=[], injections=[])
        self.record['cases'].append(self.item)
        self.children, self.streams = [], []
        self.observer, self.cpp = None, None
        self.java_dir = None
        self.gate = gates.StartupGate(self.config['minimumDynamicStates'])
        try:
            for port in self.port_values: self.amase.check_port(port)
            self.transition('ports-available')
            self.files(mode, fault)
            self.body(mode, fault, keep_gui)
        except Exception as error:
            self.item.update(status='failed', error=str(error), traceback=traceback.format_exc())
        finally:
            try: self.cleanup()
            except Exception as error: self.item.setdefault('cleanupErrors', []).append(str(error))
        if self.item.get('cleanupErrors'):
            self.item.update(status='failed', error=self.item.get('error', '; '.join(self.item['cleanupErrors'])))
        if self.item['status'] != 'failed':
            try:
                require(self.item['normalExit'], 'Processes did not close normally')
                self.audit(); self.item['status'] = 'passed'
            except Exception as error:
                self.item.update(status='failed', error=str(error), traceback=traceback.format_exc())
        self.item['finishedAt'] = stamp()
        self.item['evidence'] = [dict(path=p.relative_to(self.directory).as_posix(), sha256=sha(p))
                                 for p in sorted(self.directory.rglob('*')) if p.is_file() and p.name != 'case-result.json']
        save(self.directory / 'case-result.json', self.item)
        save(self.run / 'result.json', self.record)
        print(name + ': ' + self.item['status'] + (' / ' + self.item['error'] if self.item.get('error') else ''), flush=True)
        return self.item

    def execute(self):
        self.prepare()
        if self.args.verify:
            checks = module('startup_checks', self.root / 'tests/g3_integration/checks.py')
            checks.verify(self)
        else:
            result = self.case(self.args.mode.lower(), self.args.mode, keep_gui=self.args.keep_gui)
            require(result['status'] == 'passed', result.get('error', 'Startup failed'))
        require(self.record['inputs'] == self.inputs() and sha(Path(self.context['configuration'])) == self.record['configurationSHA256'], 'Runtime inputs changed')
        self.amase.verify_records(self.root, self.baseline['frozenInputs'])
        self.record.update(status='passed', inputsUnchanged=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui', 'Headless'], default='Headless')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--keep-gui', action='store_true')
    args = parser.parse_args()
    require(re.fullmatch(r'g3-t03-[A-Za-z0-9-]+', args.run_id), 'Invalid run identity')
    require(not args.keep_gui or args.mode == 'Gui' and not args.verify, 'KeepGui requires a single GUI run')
    task = Startup(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True)
        return 1
    finally:
        task.record['finishedAt'] = stamp()
        save(task.run / 'result.json', task.record)
        print('G3 startup evidence: ' + str(task.run), flush=True)


if __name__ == '__main__':
    sys.exit(main())

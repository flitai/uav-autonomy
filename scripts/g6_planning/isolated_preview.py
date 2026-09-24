"""G6-B02 candidate: request sandbox plans from a physically isolated UxAS process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import xml.dom.minidom
import xml.etree.ElementTree as ET
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release
sys.path.insert(0, str(ROOT / 'scripts/g3_integration'))
import runtime as startup
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import task_input

PORT = 10031


def need(value, message):
    if not value:
        raise RuntimeError(message)


def save(path, value):
    release.save(path, value)


def wait(label, predicate, process, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        need(process.poll() is None, label + ': isolated UxAS exited')
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    raise TimeoutError(label + ': timed out')


def make_config(source, output, fault=None):
    tree = ET.parse(source)
    root = tree.getroot()
    for node in list(root):
        if node.tag == 'Bridge' or node.get('Type') in ('WaypointPlanManagerService',
                                                       'MessageLoggerDataService') or \
                (fault == 'planning-timeout' and node.get('Type') == 'AutomationRequestValidatorService'):
            root.remove(node)
    bridge = ET.SubElement(root, 'Bridge', Type='LmcpObjectNetworkTcpBridge',
                           TcpAddress='tcp://127.0.0.1:' + str(PORT), Server='true',
                           ConsiderSelfGenerated='true', ExportOnlyLocalMessages='false')
    for name in ('afrl.', 'uxas.'):
        ET.SubElement(bridge, 'SubscribeToMessage', MessageType=name)
    tree.write(output, encoding='utf-8', xml_declaration=True)
    written = output.read_text(encoding='utf-8')
    need('5555' not in written and '9999' not in written and
         'WaypointPlanManagerService' not in written, 'Planner configuration reaches active execution')


def xml_message(path, tag=None):
    document = xml.dom.minidom.parse(str(path))
    node = document.documentElement
    if tag:
        node = document.getElementsByTagName(tag)[0]
    from lmcp import LMCPFactory
    factory = LMCPFactory.LMCPFactory()
    obj = factory.createObjectByName(node.getAttribute('Series'), node.localName)
    need(obj is not None, 'Unknown LMCP scene message: ' + node.localName)
    obj.unpackFromXMLNode(node, factory)
    return obj


def send(sock, obj, folder, label):
    from lmcp import LMCPFactory
    raw = LMCPFactory.packMessage(obj, True)
    packet = startup.wire.frame(raw, obj.FULL_LMCP_TYPE_NAME,
                                source='900', service='1', group='G6IsolatedPlanner')
    (folder / (label + '.bin')).write_bytes(packet)
    sock.sendall(packet)
    return dict(label=label, type=obj.FULL_LMCP_TYPE_NAME,
                rawSHA256=hashlib.sha256(raw).hexdigest(), bytes=len(packet))


def inspect_response(row, expected_vehicle, expected_task):
    import base64
    root = ET.fromstring(base64.b64decode(row['xmlBase64']))
    original = root.find('OriginalResponse/AutomationResponse')
    need(original is not None, 'Preview lacks AutomationResponse')
    failures = [item.findtext('Value', '') for item in original.findall('Info/KeyValuePair')]
    need(not failures, 'Preview returned failure: ' + '; '.join(failures))
    commands = original.findall('MissionCommandList/MissionCommand')
    need(len(commands) == 1, 'Preview must have one mission command')
    command = commands[0]
    need(command.findtext('VehicleID') == expected_vehicle, 'Preview assigned wrong vehicle')
    waypoints = command.findall('WaypointList/Waypoint')
    need(len(waypoints) >= 2, 'Preview lacks a usable route')
    linked = {item.text for item in command.findall('.//AssociatedTaskList/int64')}
    need(expected_task in linked, 'Preview route lacks task association')
    route = []
    for waypoint in waypoints:
        route.append(dict(number=waypoint.findtext('Number'),
                          nextWaypoint=waypoint.findtext('NextWaypoint'),
                          longitude=float(waypoint.findtext('Longitude')),
                          latitude=float(waypoint.findtext('Latitude')),
                          altitudeMeters=float(waypoint.findtext('Altitude')),
                          altitudeType=waypoint.findtext('AltitudeType'),
                          speedMetersPerSecond=float(waypoint.findtext('Speed'))))
    return dict(vehicleId=expected_vehicle, waypointCount=len(waypoints),
                commandId=command.findtext('CommandID'), taskId=expected_task,
                waypoints=route)


ACTIVE_FORBIDDEN = {'afrl.cmasi.AutomationRequest', 'afrl.cmasi.AutomationResponse',
                    'afrl.cmasi.MissionCommand', 'afrl.cmasi.VehicleActionCommand',
                    'uxas.messages.task.TaskAutomationRequest',
                    'uxas.messages.task.TaskAutomationResponse'}


def active_evidence(session_file):
    session = release.load(session_file)
    from sim_bridge.windows import process_identity
    need(process_identity(session['amaseProcess']['pid']) == session['amaseProcess'],
         'Active AMASE identity changed')
    uxas_record = release.load(session_file.parent / 'uxas/process.json')
    uxas_identity = process_identity(uxas_record['pid'])
    need(uxas_identity is not None and uxas_record['arguments'][0].lower().endswith('uxas.exe'),
         'Active UxAS is unavailable')
    with urlopen('http://127.0.0.1:8001/api/control/v1/state', timeout=3) as response:
        state = json.load(response)
    for key in ('runId', 'segmentId', 'backendRunId'):
        need(state[key] == session[key], 'Active ' + key + ' changed')
    need(not state['started'] and
         (state['simulation'] is None or state['simulation']['state'] in (0, 2)),
         'B02 preview requires frozen pre-start simulation state: ' +
         repr({key: state.get(key) for key in ('ready', 'started', 'simulation')}))
    observer = session_file.parent / 'observer.jsonl'
    rows = []
    moving_state_count = 0
    if observer.exists():
        with observer.open(encoding='utf-8') as source:
            for line in source:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # The active writer may be appending this line.
                if row['type'] in ACTIVE_FORBIDDEN:
                    rows.append((row['type'], row['rawSHA256']))
                if row['type'] == 'afrl.cmasi.AirVehicleState':
                    moving_state_count += 1
    need(moving_state_count == 0, 'Active entities advanced before preview')
    return dict(runId=state['runId'], segmentId=state['segmentId'],
                backendRunId=state['backendRunId'], streamId=state['streamId'],
                simulation=state['simulation'], forbiddenRows=rows,
                observerBytes=observer.stat().st_size if observer.exists() else 0,
                movingStateCount=moving_state_count, uxasProcess=uxas_identity)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--draft', type=Path)
    parser.add_argument('--active-session', type=Path)
    parser.add_argument('--fault', choices=('wrong-response-id', 'planning-timeout'))
    args = parser.parse_args()
    need(args.run_id.startswith('g6-b02-') and all(char.isascii() and
         (char.isalnum() or char == '-') for char in args.run_id), 'Invalid B02 run ID')
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B02 run ID already exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B02', runId=args.run_id, status='running',
                  previewIsolationQualified=False, executionQualified=False, messages=[])
    process = None
    stream = None
    sock = None
    try:
        active_before = None
        if args.active_session:
            sys.path.insert(0, str(ROOT / 'src'))
            active_before = active_evidence(args.active_session.resolve())
            record['activeBefore'] = active_before
        pointer, manifest = release.resolve()
        baseline = release.load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/acceptance.json')
        need(baseline['status'] == 'passed' and baseline['g6PointerSHA256'] ==
             release.digest(ROOT / 'out/artifacts/g6-control/current.json'), 'B01 source differs')
        scene_run = baseline['sourceSceneRunId']
        scene = ROOT / 'out/runs' / scene_run / 'segment-001' / 'scene'
        source_uxas = ROOT / 'out/runs' / scene_run / 'segment-001' / 'uxas' / 'uxas.xml'
        uxas_pointer = release.load(ROOT / 'out/artifacts/uxas/current.json')
        executable = ROOT / 'out/artifacts/uxas' / uxas_pointer['path'] / 'uxas.exe'
        production = release.load(ROOT / 'out/runs' / scene_run / 'runtime-result.json')
        need(release.digest(executable).lower() == production['artifacts']['uxasSHA256'].lower(),
             'Isolated planner UxAS executable differs from G6-A')
        contract = release.load(ROOT / 'config/g6-task-contract-v1.json')
        draft = release.load(args.draft.resolve()) if args.draft else None
        if draft:
            task_input.baseline.validate_draft(draft, contract)
            need(draft['runId'] == baseline['sourceSceneRunId'] or
                 (active_before and draft['runId'] == active_before['runId']),
                 'Draft run identity differs')
            if active_before:
                need(draft['segmentId'] == active_before['segmentId'],
                     'Draft segment identity differs')
            else:
                need(draft['segmentId'] == contract['sourceSegment'] + '-1',
                     'Draft baseline segment differs')
            context = release.load(ROOT / 'out/runs' / scene_run / 'context.json')
            terrain = Path(context['terrainCandidate']).resolve()
            need(release.digest(terrain / 'candidate.json') == context['terrainCandidateSHA256'],
                 'Terrain candidate changed')
            candidate = release.load(terrain / 'candidate.json')
            grid = next(row for row in candidate['files'] if row['path'] == 'orthometric.f32')
            need(release.digest(terrain / grid['path']).lower() == grid['sha256'].lower(),
                 'Canonical ground grid changed')
            task_input.build(draft, contract, scene, terrain, run / 'candidate-task.xml')
            record['draftSHA256'] = release.digest(args.draft.resolve())
            record['candidateTaskSHA256'] = release.digest(run / 'candidate-task.xml')
        work = run / 'uxas'
        work.mkdir()
        make_config(source_uxas, work / 'uxas.xml', args.fault)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', PORT))
        sys.path.insert(0, str(ROOT / 'out/generated/lmcp/py'))
        from lmcp import LMCPFactory
        stdout = (work / 'stdout.log').open('wb')
        stderr = (work / 'stderr.log').open('wb')
        try:
            process = subprocess.Popen([str(executable), '-cfgPath', str(work / 'uxas.xml')],
                                       cwd=work, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            stdout.close()
            stderr.close()
        deadline = time.monotonic() + 15
        while True:
            need(process.poll() is None, 'Isolated UxAS exited at startup')
            try:
                sock = socket.create_connection(('127.0.0.1', PORT), timeout=.5)
                break
            except OSError:
                need(time.monotonic() < deadline, 'Isolated planner port not ready')
                time.sleep(.1)
        sock.settimeout(.2)
        stream = startup.Stream(sock, run, 'planner', LMCPFactory)
        scenario = xml.dom.minidom.parse(str(scene / 'scenario.xml'))
        for kind in ('AirVehicleConfiguration', 'AirVehicleState'):
            for node in scenario.getElementsByTagName(kind):
                factory = LMCPFactory.LMCPFactory()
                obj = factory.createObjectByName(node.getAttribute('Series'), node.localName)
                obj.unpackFromXMLNode(node, factory)
                record['messages'].append(send(sock, obj, run, kind + '-' + str(obj.ID)))
        task_ids = (draft['taskId'],) if draft else ('3000', '3001', '3002')
        for task_id in task_ids:
            task_path = run / 'candidate-task.xml' if draft else scene / ('task-' + task_id + '.xml')
            record['messages'].append(send(sock, xml_message(task_path), run, 'task-' + task_id))
        wait('task initialization', lambda: {row.get('taskId') for row in stream.rows
             if row['type'] == 'uxas.messages.task.TaskInitialized'} >= set(task_ids), process, 35)
        from uxas.messages.task.TaskAutomationRequest import TaskAutomationRequest
        previews = []
        for index, task_id in enumerate(task_ids, start=1):
            request = xml_message(scene / ('request-' + task_id + '.xml'))
            plan = TaskAutomationRequest()
            plan.RequestID = 910000 + index
            plan.OriginalRequest = request
            plan.SandBoxRequest = True
            record['messages'].append(send(sock, plan, run, 'preview-' + task_id))
            expected_response_id = str(plan.RequestID + 1) if args.fault == 'wrong-response-id' else str(plan.RequestID)
            response = wait('preview ' + task_id, lambda: next((row for row in stream.rows
                if row['type'] == 'uxas.messages.task.TaskAutomationResponse' and
                row.get('responseId') == expected_response_id), None), process,
                3 if args.fault == 'wrong-response-id' else 30)
            entity = contract['taskTypes'][draft['kind']]['baselineEntityIds'][0] if draft else \
                {'3000': '400', '3001': '500', '3002': '600'}[task_id]
            route = inspect_response(response, entity, task_id)
            import base64
            response_xml = base64.b64decode(response['xmlBase64'])
            response_file = run / ('plan-' + task_id + '.xml')
            response_file.write_bytes(response_xml)
            previews.append(dict(taskId=task_id, requestId=str(plan.RequestID),
                                 responseId=response['responseId'], responseSHA256=response['rawSHA256'],
                                 responseXmlSHA256=release.digest(response_file),
                                 responseFile=response_file.name, route=route))
        forbidden = [row for row in stream.rows if row['type'] in
                     ('afrl.cmasi.AutomationResponse', 'afrl.cmasi.MissionCommand',
                      'afrl.cmasi.VehicleActionCommand') or
                     row['type'].endswith(('ActionCommand', 'GimbalAngleAction',
                                           'GimbalStareAction', 'VideoStreamAction'))]
        need(not forbidden, 'Preview emitted an executable command on isolated bus')
        if active_before:
            time.sleep(.5)
            active_after = active_evidence(args.active_session.resolve())
            need(active_before['streamId'] == active_after['streamId'],
                 'Active gateway stream changed during preview')
            need(active_before['uxasProcess'] == active_after['uxasProcess'],
                 'Active UxAS process changed during preview')
            need(active_before['forbiddenRows'] == active_after['forbiddenRows'],
                 'Preview coincided with active execution command or planning request')
            record['activeAfter'] = active_after
        record.update(status='passed', isolatedPlannerObserved=True,
                      previewIsolationQualified=bool(active_before), executionQualified=False,
                      previews=previews, forbiddenMessageCount=0,
                      uxasSHA256=release.digest(executable),
                      configSHA256=release.digest(work / 'uxas.xml'),
                      g6ManifestSHA256=pointer['manifestSHA256'])
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr, flush=True)
        return 1
    finally:
        if process is not None and process.poll() is None and sock is not None:
            try:
                from uxas.messages.uxnative.KillService import KillService
                stop = KillService()
                stop.ServiceID = -1
                record['messages'].append(send(sock, stop, run, 'normal-stop'))
                process.wait(timeout=20)
            except Exception as error:
                record.setdefault('cleanupErrors', []).append(str(error))
        if stream is not None:
            try:
                stream.close()
            except Exception as error:
                record.setdefault('cleanupErrors', []).append(str(error))
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
            record['forcedTermination'] = True
        if process is not None:
            record['exitCode'] = process.returncode
        save(run / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())

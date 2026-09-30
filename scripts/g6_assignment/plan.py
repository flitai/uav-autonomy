"""Plan several saved search drafts in a physically isolated UxAS instance."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import xml.dom.minidom
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core
preview = core.isolated_preview
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import task_input
from lmcp import LMCPFactory
from uxas.messages.task.TaskAutomationRequest import TaskAutomationRequest
from uxas.messages.uxnative.KillService import KillService


def object_from_scene(node):
    return core.lmcp_node(node)


def message_xml(row):
    return ET.fromstring(base64.b64decode(row['xmlBase64']))


def matching(rows, kind, request_id):
    for row in rows:
        if row['type'] != kind:
            continue
        node = message_xml(row)
        if node.findtext('CorrespondingAutomationRequestID') == request_id or \
                node.findtext('RequestID') == request_id or node.findtext('ResponseID') == request_id:
            return row
    return None


def extract(rows, request_id, spec, duration_ms):
    response_row = matching(rows, 'uxas.messages.task.TaskAutomationResponse', request_id)
    summary_row = matching(rows, 'uxas.messages.task.TaskAssignmentSummary', request_id)
    cost_row = matching(rows, 'uxas.messages.task.AssignmentCostMatrix', request_id)
    core.need(response_row and summary_row and cost_row, 'Planning evidence is incomplete')
    response = message_xml(response_row)
    original = response.find('OriginalResponse/AutomationResponse')
    core.need(original is not None and not original.findall('Info/KeyValuePair'),
              'UxAS returned no usable multi-task plan')
    commands = original.findall('MissionCommandList/MissionCommand')
    core.need(1 <= len(commands) <= 3, 'Mission command count differs')
    requested = {row['taskId']: row for row in spec['tasks']}
    assignments = []
    summary = message_xml(summary_row)
    for item in summary.findall('TaskList/TaskAssignment'):
        task_id = item.findtext('TaskID')
        core.need(task_id in requested, 'Summary has an unrequested task')
        vehicle = item.findtext('AssignedVehicle')
        core.need(vehicle in requested[task_id]['candidateEntityIds'],
                  'UxAS assigned a vehicle outside task qualification')
        assignments.append(dict(taskId=task_id, vehicleId=vehicle,
            optionId=item.findtext('OptionID'),
            estimatedCompletionMs=item.findtext('TimeTaskCompleted')))
    core.need(len(assignments) == len(requested) and
              {x['taskId'] for x in assignments} == set(requested),
              'Assignment summary does not cover exactly the selected tasks')
    command_views = []
    linked = set()
    for command in commands:
        vehicle = command.findtext('VehicleID')
        points = command.findall('WaypointList/Waypoint')
        core.need(vehicle in spec['vehicleIds'] and 2 <= len(points) <= 1024,
                  'Unqualified command vehicle or waypoint count')
        route = []
        for point in points:
            tasks = [n.text for n in point.findall('AssociatedTasks/int64')]
            core.need(set(tasks).issubset(requested), 'Waypoint references an unrequested task')
            linked.update(tasks)
            route.append(dict(number=point.findtext('Number'),
                nextWaypoint=point.findtext('NextWaypoint'),
                longitude=float(point.findtext('Longitude')),
                latitude=float(point.findtext('Latitude')),
                altitudeMeters=float(point.findtext('Altitude')),
                altitudeType=point.findtext('AltitudeType'),
                speedMetersPerSecond=float(point.findtext('Speed')),
                taskIds=tasks))
        command_views.append(dict(vehicleId=vehicle, commandId=command.findtext('CommandID'),
                                  waypoints=route, taskIds=sorted({t for p in route for t in p['taskIds']}),
                                  timeBudget=core.route_budget(route, duration_ms)))
    core.need(linked == set(requested), 'Plan route does not cover every selected task')
    core.need(len({x['vehicleId'] for x in command_views}) == len(command_views),
              'Duplicate mission command vehicle')
    for row in assignments:
        core.need(any(row['taskId'] in cmd['taskIds'] and
                      row['vehicleId'] == cmd['vehicleId'] for cmd in command_views),
                  'Summary assignment differs from mission route')
    if spec['relationship'] == 'sequence':
        core.need(len(command_views) == 1 and
                  command_views[0]['vehicleId'] == spec['sequenceVehicleId'],
                  'Sequence was not assigned to one qualified vehicle')
        ordered = [next(row for row in assignments if row['taskId'] == task_id)
                   for task_id in spec['taskOrder']]
        core.need(all(int(a['estimatedCompletionMs']) < int(b['estimatedCompletionMs'])
                      for a, b in zip(ordered, ordered[1:])),
                  'UxAS completion estimates violate requested order')
        first = {task_id: min(i for i, point in enumerate(command_views[0]['waypoints'])
                              if task_id in point['taskIds']) for task_id in spec['taskOrder']}
        core.need(list(first.values()) == sorted(first.values()),
                  'Mission waypoint order differs from task relationship')
    matrix = message_xml(cost_row)
    entries = matrix.findall('CostMatrix/TaskOptionCost')
    core.need(len(entries) <= 18432, 'Cost matrix exceeds UXTASK limit')
    starting = {}
    for item in entries:
        if item.findtext('IntialTaskID') != '0':
            continue
        key = (item.findtext('DestinationTaskID'), item.findtext('VehicleID'))
        cost = int(item.findtext('TimeToGo'))
        if cost >= 0:
            starting[key] = min(starting.get(key, cost), cost)
    candidate_costs = [dict(taskId=task_id, vehicleId=vehicle, initialTimeToGoMs=str(value))
                       for (task_id, vehicle), value in sorted(starting.items())
                       if task_id in requested and
                       vehicle in requested[task_id]['candidateEntityIds']]
    return dict(assignments=assignments, commands=command_views,
                candidateInitialCosts=candidate_costs,
                costMatrixEntries=len(entries),
                responseSHA256=response_row['rawSHA256'],
                summarySHA256=summary_row['rawSHA256'],
                costMatrixSHA256=cost_row['rawSHA256'],
                timeBudgetFits=all(cmd['timeBudget']['fits'] for cmd in command_views))


def execute(session_file, spec, run):
    record = dict(task='G6-B05', runId=run.name, status='running',
                  isolatedPlannerQualified=False, forcedTermination=False)
    process = stream = sock = None
    try:
        active_before = preview.active_evidence(session_file)
        core.need(spec['identity'] == {name: active_before[name] for name in
                  ('runId', 'segmentId', 'backendRunId', 'streamId')},
                  'Planning identity differs from frozen active session')
        baseline = core.release.load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/acceptance.json')
        core.need(baseline['status'] == 'passed', 'B01 baseline not qualified')
        scene_run = baseline['sourceSceneRunId']
        scene = ROOT / 'out/runs' / scene_run / 'segment-001/scene'
        source_uxas = ROOT / 'out/runs' / scene_run / 'segment-001/uxas/uxas.xml'
        context = core.release.load(ROOT / 'out/runs' / scene_run / 'context.json')
        terrain = Path(context['terrainCandidate']).resolve()
        core.need(core.release.digest(terrain / 'candidate.json') ==
                  context['terrainCandidateSHA256'], 'Terrain candidate changed')
        pointer = core.release.load(ROOT / 'out/artifacts/uxas/current.json')
        executable = ROOT / 'out/artifacts/uxas' / pointer['path'] / 'uxas.exe'
        production = core.release.load(ROOT / 'out/runs' / scene_run / 'runtime-result.json')
        core.need(core.release.digest(executable).lower() ==
                  production['artifacts']['uxasSHA256'].lower(), 'Formal UxAS executable changed')
        contract = core.release.load(ROOT / 'config/g6-task-contract-v1.json')
        source_drafts = []
        for row in spec['tasks']:
            draft = dict(row['draft'])
            core.need(draft['revision'] == row['revision'] and draft['taskId'] == row['taskId'],
                      'Saved task draft changed')
            task_file = run / ('task-' + row['taskId'] + '.xml')
            task_input.build(draft, contract, scene, terrain, task_file)
            task = ET.parse(task_file)
            eligible = task.getroot().find('EligibleEntities')
            core.need(eligible is not None, 'Task template lacks candidate list')
            for item in list(eligible):
                eligible.remove(item)
            for vehicle in row['candidateEntityIds']:
                ET.SubElement(eligible, 'int64').text = vehicle
            task.write(task_file, encoding='utf-8', xml_declaration=True)
            source_drafts.append(dict(taskId=row['taskId'], kind=draft['kind'],
                                      draftSHA256=hashlib.sha256(json.dumps(draft,
                                          sort_keys=True).encode()).hexdigest(),
                                      taskSHA256=core.release.digest(task_file)))
        work = run / 'uxas'
        work.mkdir()
        preview.make_config(source_uxas, work / 'uxas.xml')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', preview.PORT))
        with (work / 'stdout.log').open('wb') as out, (work / 'stderr.log').open('wb') as err:
            process = subprocess.Popen([str(executable), '-cfgPath', str(work / 'uxas.xml')],
                                       cwd=work, stdout=out, stderr=err,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while sock is None:
            core.need(process.poll() is None, 'Planner exited at startup')
            try:
                sock = socket.create_connection(('127.0.0.1', preview.PORT), timeout=.5)
            except OSError:
                core.need(time.monotonic() < deadline, 'Planner port timeout')
                time.sleep(.1)
        sock.settimeout(.2)
        stream = preview.startup.Stream(sock, run, 'planner', LMCPFactory)
        scenario = xml.dom.minidom.parse(str(scene / 'scenario.xml'))
        for kind in ('AirVehicleConfiguration', 'AirVehicleState'):
            for node in scenario.getElementsByTagName(kind):
                preview.send(sock, object_from_scene(node), run,
                             kind + '-' + node.getElementsByTagName('ID')[0].firstChild.nodeValue)
        for row in spec['tasks']:
            preview.send(sock, core.lmcp_object(run / ('task-' + row['taskId'] + '.xml')),
                         run, 'task-' + row['taskId'])
        task_ids = set(spec['taskOrder'])
        preview.wait('all tasks initialized', lambda: {r.get('taskId') for r in stream.rows
                     if r['type'] == 'uxas.messages.task.TaskInitialized'} >= task_ids,
                     process, 35)
        request = preview.xml_message(scene / 'request-3000.xml')
        request.EntityList = list(map(int, spec['vehicleIds']))
        request.TaskList = list(map(int, spec['taskOrder']))
        request.TaskRelationships = '' if spec['relationship'] == 'parallel' else \
            '.(' + ' '.join('p' + task for task in spec['taskOrder']) + ')'
        wrapper = TaskAutomationRequest()
        wrapper.RequestID = 930000 + int(run.name[:6], 16)
        wrapper.OriginalRequest = request
        wrapper.SandBoxRequest = True
        preview.send(sock, wrapper, run, 'request')
        request_id = str(wrapper.RequestID)
        response = preview.wait('multi-task response', lambda: matching(stream.rows,
            'uxas.messages.task.TaskAutomationResponse', request_id), process, 45)
        preview.wait('assignment summary and cost', lambda:
            matching(stream.rows, 'uxas.messages.task.TaskAssignmentSummary', request_id) and
            matching(stream.rows, 'uxas.messages.task.AssignmentCostMatrix', request_id),
            process, 10)
        result = extract(stream.rows, request_id, spec, core.release.load(session_file)['durationMs'])
        (run / 'response.xml').write_bytes(base64.b64decode(response['xmlBase64']))
        for kind, file in (('uxas.messages.task.UniqueAutomationRequest', 'unique-request.xml'),
                           ('uxas.messages.task.UniqueAutomationResponse', 'unique-response.xml')):
            row = matching(stream.rows, kind, request_id)
            core.need(row is not None, kind + ' missing')
            (run / file).write_bytes(base64.b64decode(row['xmlBase64']))
        forbidden = [r['type'] for r in stream.rows if r['type'] in
                     ('afrl.cmasi.AutomationResponse', 'afrl.cmasi.MissionCommand',
                      'afrl.cmasi.VehicleActionCommand')]
        core.need(not forbidden, 'Isolated planning emitted executable command')
        active_after = preview.active_evidence(session_file)
        core.need(active_after['streamId'] == active_before['streamId'] and
                  active_after['forbiddenRows'] == active_before['forbiddenRows'],
                  'Active execution changed during isolated planning')
        record.update(status='passed', isolatedPlannerQualified=True,
                      requestId=request_id, sourceDrafts=source_drafts,
                      plan=result, inputSHA256=core.release.digest(run / 'input.json'),
                      uxasSHA256=core.release.digest(executable),
                      responseXmlSHA256=core.release.digest(run / 'response.xml'),
                      uniqueRequestSHA256=core.release.digest(run / 'unique-request.xml'),
                      uniqueResponseSHA256=core.release.digest(run / 'unique-response.xml'),
                      activeBefore=active_before, activeAfter=active_after)
        return record
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        return record
    finally:
        if process is not None and process.poll() is None and sock is not None:
            try:
                kill = KillService()
                kill.ServiceID = -1
                preview.send(sock, kill, run, 'normal-stop')
                process.wait(timeout=20)
            except Exception as error:
                record['cleanupError'] = str(error)
        if stream is not None:
            stream.close()
        if (run / 'planner.jsonl').is_file():
            record['plannerLogSHA256'] = core.release.digest(run / 'planner.jsonl')
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
            record['forcedTermination'] = True
        record['exitCode'] = process.returncode if process is not None else None
        if record.get('status') == 'passed' and (record['exitCode'] != 0 or
                                                  record['forcedTermination'] or record.get('cleanupError')):
            record.update(status='failed', isolatedPlannerQualified=False,
                          error='Isolated planner did not exit normally')
        core.release.save(run / 'result.json', record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    core.need(len(args.run_id) == 32 and all(ch in '0123456789abcdef' for ch in args.run_id),
              'Invalid B05 planner ID')
    run = ROOT / 'out/runs/g6-b05-plan' / args.run_id
    core.need(not run.exists(), 'Planner ID already exists')
    run.mkdir(parents=True)
    spec = core.release.load(args.input)
    core.release.save(run / 'input.json', spec)
    result = execute(args.session.resolve(), spec, run)
    if result['status'] != 'passed':
        print(result.get('traceback', result.get('error')), file=sys.stderr)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())

"""Create a replacement mission from paused live aircraft states in isolated UxAS."""
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
sys.path.insert(0, str(ROOT / 'scripts/g6_assignment'))
import plan as assignment_plan
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import task_input
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live

from lmcp import LMCPFactory
from uxas.messages.task.PlanningState import PlanningState
from uxas.messages.task.TaskAutomationRequest import TaskAutomationRequest
from uxas.messages.uxnative.KillService import KillService

preview = core.isolated_preview


def execute(session_file, spec, run, diagnostic=False):
    record = dict(task='G6-B06', runId=run.name, status='running',
                  isolatedPlannerQualified=False, forcedTermination=False,
                  diagnosticOnly=diagnostic)
    process = stream = sock = None
    try:
        active_before = live.settled_snapshot(session_file)
        live.unchanged(spec['activeSnapshot'], active_before)
        core.need(spec['identity'] == active_before['identity'],
                  'Replacement run identity changed')
        baseline = core.release.load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/acceptance.json')
        core.need(baseline['status'] == 'passed', 'B01 task baseline changed')
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
                  production['artifacts']['uxasSHA256'].lower(), 'UxAS executable changed')
        contract = core.release.load(ROOT / 'config/g6-task-contract-v1.json')
        source_drafts = []
        for row in spec['tasks']:
            draft = dict(row['draft'])
            core.need(draft['taskId'] == row['oldTaskId'] and
                      row['taskId'] not in ('3000', '3001', '3002'),
                      'Replacement task ID must be new')
            task_file = run / ('task-' + row['taskId'] + '.xml')
            task_input.build(draft, contract, scene, terrain, task_file)
            tree = ET.parse(task_file)
            root = tree.getroot()
            root.find('TaskID').text = row['taskId']
            eligible = root.find('EligibleEntities')
            core.need(eligible is not None, 'Search task lacks candidate entities')
            for item in list(eligible):
                eligible.remove(item)
            for vehicle in row['candidateEntityIds']:
                ET.SubElement(eligible, 'int64').text = vehicle
            tree.write(task_file, encoding='utf-8', xml_declaration=True)
            source_drafts.append(dict(taskId=row['taskId'], oldTaskId=row['oldTaskId'],
                                      revision=draft['revision'], taskSHA256=core.release.digest(task_file)))
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
            core.need(process.poll() is None, 'Isolated planner exited at startup')
            try:
                sock = socket.create_connection(('127.0.0.1', preview.PORT), timeout=.5)
            except OSError:
                core.need(time.monotonic() < deadline, 'Isolated planner did not listen')
                time.sleep(.1)
        sock.settimeout(.2)
        stream = preview.startup.Stream(sock, run, 'planner', LMCPFactory)
        scenario = xml.dom.minidom.parse(str(scene / 'scenario.xml'))
        for node in scenario.getElementsByTagName('AirVehicleConfiguration'):
            preview.send(sock, core.lmcp_node(node), run, 'config-' +
                         node.getElementsByTagName('ID')[0].firstChild.nodeValue)
        objects = {}
        for vehicle, row in active_before['states'].items():
            state_file = run / ('state-' + vehicle + '.xml')
            state_file.write_bytes(base64.b64decode(row['xmlBase64']))
            objects[vehicle] = core.lmcp_object(state_file)
            preview.send(sock, objects[vehicle], run, 'state-' + vehicle)
        for row in spec['tasks']:
            preview.send(sock, core.lmcp_object(run / ('task-' + row['taskId'] + '.xml')),
                         run, 'task-' + row['taskId'])
        selected = set(spec['taskOrder'])
        preview.wait('replacement tasks initialized', lambda:
            {row.get('taskId') for row in stream.rows if row['type'] ==
             'uxas.messages.task.TaskInitialized'} >= selected, process, 35)
        request = core.lmcp_object(scene / 'request-3000.xml')
        request.EntityList = list(map(int, spec['vehicleIds']))
        request.TaskList = list(map(int, spec['taskOrder']))
        request.TaskRelationships = '' if spec['relationship'] == 'parallel' else \
            '.(' + ' '.join('p' + task for task in spec['taskOrder']) + ')'
        request.RedoAllTasks = False
        wrapper = TaskAutomationRequest()
        wrapper.RequestID = 970000 + int(hashlib.sha256(run.name.encode()).hexdigest()[:6], 16)
        wrapper.OriginalRequest = request
        wrapper.SandBoxRequest = True
        for vehicle in spec['vehicleIds']:
            state = PlanningState()
            state.EntityID = int(vehicle)
            state.PlanningPosition = objects[vehicle].Location
            state.PlanningHeading = objects[vehicle].Heading
            wrapper.PlanningStates.append(state)
        preview.send(sock, wrapper, run, 'request')
        request_id = str(wrapper.RequestID)
        response = preview.wait('replacement response', lambda:
            assignment_plan.matching(stream.rows,
                'uxas.messages.task.TaskAutomationResponse', request_id), process, 45)
        preview.wait('replacement assignment and costs', lambda:
            assignment_plan.matching(stream.rows,
                'uxas.messages.task.TaskAssignmentSummary', request_id) and
            assignment_plan.matching(stream.rows,
                'uxas.messages.task.AssignmentCostMatrix', request_id), process, 10)
        remaining_ms = int(core.release.load(session_file)['durationMs']) - \
            int(active_before['simulationTimeMs'])
        core.need(remaining_ms > 0, 'Simulation duration exhausted')
        result = assignment_plan.extract(stream.rows, request_id, spec, str(remaining_ms))
        (run / 'response.xml').write_bytes(base64.b64decode(response['xmlBase64']))
        for kind, file in (('uxas.messages.task.UniqueAutomationRequest', 'unique-request.xml'),
                           ('uxas.messages.task.UniqueAutomationResponse', 'unique-response.xml')):
            row = assignment_plan.matching(stream.rows, kind, request_id)
            core.need(row is not None, kind + ' missing')
            (run / file).write_bytes(base64.b64decode(row['xmlBase64']))
        forbidden = [row['type'] for row in stream.rows if row['type'] in
                     ('afrl.cmasi.AutomationResponse', 'afrl.cmasi.MissionCommand',
                      'afrl.cmasi.VehicleActionCommand')]
        core.need(not forbidden, 'Isolated replanning emitted an execution command')
        active_after = live.settled_snapshot(session_file)
        live.unchanged(active_before, active_after)
        record.update(status='passed', isolatedPlannerQualified=not diagnostic,
                      requestId=request_id, sourceDrafts=source_drafts,
                      plan=result, inputSHA256=core.release.digest(run / 'input.json'),
                      uxasSHA256=core.release.digest(executable),
                      responseXmlSHA256=core.release.digest(run / 'response.xml'),
                      uniqueRequestSHA256=core.release.digest(run / 'unique-request.xml'),
                      uniqueResponseSHA256=core.release.digest(run / 'unique-response.xml'),
                      activeBefore=active_before, activeAfter=active_after)
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
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
        if record['status'] == 'passed' and (record['exitCode'] != 0 or
                                            record['forcedTermination'] or record.get('cleanupError')):
            record.update(status='failed', isolatedPlannerQualified=False,
                          error='Isolated replanner did not exit normally')
        core.release.save(run / 'result.json', record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    core.need(len(args.run_id) == 32 and all(ch in '0123456789abcdef' for ch in args.run_id),
              'Invalid B06 planner ID')
    run = ROOT / 'out/runs/g6-b06-plan' / args.run_id
    core.need(not run.exists(), 'B06 planner ID exists')
    run.mkdir(parents=True)
    spec = core.release.load(args.input)
    core.release.save(run / 'input.json', spec)
    result = execute(args.session.resolve(), spec, run)
    if result['status'] != 'passed':
        print(result.get('traceback', result.get('error')), file=sys.stderr)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())

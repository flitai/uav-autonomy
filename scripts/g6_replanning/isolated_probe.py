"""Investigate live-state replanning in an isolated UxAS instance.

This is a diagnostic entry point. It never connects to the active command bus.
"""
import argparse
import base64
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core

preview = core.isolated_preview
from lmcp import LMCPFactory
from uxas.messages.task.PlanningState import PlanningState
from uxas.messages.task.TaskAutomationRequest import TaskAutomationRequest
from uxas.messages.uxnative.KillService import KillService


def read_states(path, at_ms):
    states = {}
    with path.open(encoding='utf-8') as source:
        for line in source:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row['type'] != 'afrl.cmasi.AirVehicleState' or row.get('id') not in ('400', '500', '600'):
                continue
            stamp = int(row['timeMs'])
            if stamp <= at_ms and (row['id'] not in states or stamp > int(states[row['id']]['timeMs'])):
                states[row['id']] = row
    core.need(set(states) == {'400', '500', '600'}, 'Historical state is incomplete')
    core.need(all(int(row['timeMs']) > 0 for row in states.values()),
              'Historical state did not advance from simulation start')
    return states


def run_probe(source_session, at_ms, output):
    session = core.release.load(source_session)
    states = read_states(source_session.parent / 'observer.jsonl', at_ms)
    scene = source_session.parent / 'scene'
    receipt = core.release.load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/acceptance.json')
    source_config = ROOT / 'out/runs' / receipt['sourceSceneRunId'] / 'segment-001/uxas/uxas.xml'
    pointer = core.release.load(ROOT / 'out/artifacts/uxas/current.json')
    executable = ROOT / 'out/artifacts/uxas' / pointer['path'] / 'uxas.exe'
    production = core.release.load(ROOT / 'out/runs' / receipt['sourceSceneRunId'] / 'runtime-result.json')
    core.need(core.release.digest(executable).lower() ==
              production['artifacts']['uxasSHA256'].lower(), 'UxAS release changed')
    work = output / 'uxas'
    work.mkdir(parents=True)
    preview.make_config(source_config, work / 'uxas.xml')
    task = ET.parse(scene / 'task-3000.xml')
    task.getroot().find('TaskID').text = '3100'
    task_file = output / 'task-3100.xml'
    task.write(task_file, encoding='utf-8', xml_declaration=True)
    process = sock = stream = None
    record = dict(task='G6-B06-isolated-probe', status='running',
                  sourceRunId=session['runId'], atMs=str(at_ms),
                  states={key: {'timeMs': row['timeMs'], 'rawSHA256': row['rawSHA256'],
                                'latitude': row['latitude'], 'longitude': row['longitude']}
                          for key, row in states.items()})
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', preview.PORT))
        with (work / 'stdout.log').open('wb') as stdout, (work / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen([str(executable), '-cfgPath', str(work / 'uxas.xml')],
                                       cwd=work, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while sock is None:
            core.need(process.poll() is None, 'Isolated UxAS exited at startup')
            try:
                sock = socket.create_connection(('127.0.0.1', preview.PORT), timeout=.5)
            except OSError:
                core.need(time.monotonic() < deadline, 'Isolated UxAS did not listen')
                time.sleep(.1)
        sock.settimeout(.2)
        stream = preview.startup.Stream(sock, output, 'planner', LMCPFactory)
        scenario = __import__('xml.dom.minidom', fromlist=['parse']).parse(str(scene / 'scenario.xml'))
        for node in scenario.getElementsByTagName('AirVehicleConfiguration'):
            preview.send(sock, core.lmcp_node(node), output, 'config-' +
                         node.getElementsByTagName('ID')[0].firstChild.nodeValue)
        objects = {}
        for vehicle, row in states.items():
            state_file = output / ('state-' + vehicle + '.xml')
            state_file.write_bytes(base64.b64decode(row['xmlBase64']))
            obj = core.lmcp_object(state_file)
            objects[vehicle] = obj
            preview.send(sock, obj, output, 'state-' + vehicle)
        preview.send(sock, core.lmcp_object(task_file), output, 'task-3100')
        preview.wait('replacement task initialized', lambda: any(row['type'] ==
                     'uxas.messages.task.TaskInitialized' and row.get('taskId') == '3100'
                     for row in stream.rows), process, 35)
        request = core.lmcp_object(scene / 'request-3000.xml')
        request.EntityList = [400]
        request.TaskList = [3100]
        request.RedoAllTasks = False
        wrapper = TaskAutomationRequest()
        wrapper.RequestID = 9603100
        wrapper.OriginalRequest = request
        wrapper.SandBoxRequest = True
        state = PlanningState()
        state.EntityID = 400
        state.PlanningPosition = objects['400'].Location
        state.PlanningHeading = objects['400'].Heading
        wrapper.PlanningStates = [state]
        preview.send(sock, wrapper, output, 'live-request')
        response = preview.wait('live-state plan', lambda: next((row for row in stream.rows
            if row['type'] == 'uxas.messages.task.TaskAutomationResponse' and
            row.get('responseId') == '9603100'), None), process, 45)
        result = preview.inspect_response(response, '400', '3100')
        original = ET.fromstring(base64.b64decode(response['xmlBase64']))
        route = original.find('OriginalResponse/AutomationResponse/MissionCommandList/MissionCommand')
        first = route.find('WaypointList/Waypoint')
        record.update(status='passed', route=result,
                      firstWaypoint={'latitude': float(first.findtext('Latitude')),
                                     'longitude': float(first.findtext('Longitude'))},
                      responseRawSHA256=response['rawSHA256'])
    except Exception as error:
        record.update(status='failed', error=str(error))
    finally:
        if process is not None and process.poll() is None and sock is not None:
            try:
                kill = KillService()
                kill.ServiceID = -1
                preview.send(sock, kill, output, 'normal-stop')
                process.wait(timeout=20)
            except Exception as error:
                record['cleanupError'] = str(error)
        if stream is not None:
            stream.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
            record['forcedTermination'] = True
        record['exitCode'] = process.returncode if process is not None else None
        if record['status'] == 'passed' and (record['exitCode'] != 0 or
                                            record.get('forcedTermination') or record.get('cleanupError')):
            record.update(status='failed', error='Isolated planner cleanup failed')
        core.release.save(output / 'result.json', record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-session', type=Path, required=True)
    parser.add_argument('--at-ms', type=int, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    core.need(args.run_id.startswith('g6-b06-probe-') and
              all(ch.isascii() and (ch.isalnum() or ch == '-') for ch in args.run_id),
              'Probe run ID invalid')
    output = ROOT / 'out/runs' / args.run_id
    core.need(not output.exists(), 'Probe run ID exists')
    output.mkdir(parents=True)
    result = run_probe(args.source_session.resolve(), args.at_ms, output)
    print(json.dumps({k: result.get(k) for k in ('status', 'error', 'firstWaypoint', 'states')},
                     ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())

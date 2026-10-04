"""Independent B06 command, task lifecycle, and versioned coverage audit."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core
sys.path.insert(0, str(ROOT / 'scripts/g5_coverage'))
import engine
sys.path.insert(0, str(ROOT / 'tests/g6_assignment'))
import flow as b05


def need(value, message):
    if not value:
        raise ValueError(message)


def replay(session, cursor):
    manifest = core.release.load(session.parent / 'gateway-host/manifest.json')
    baseline = core.release.load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/acceptance.json')
    context = core.release.load(ROOT / 'out/runs' / baseline['sourceSceneRunId'] / 'context.json')
    terrain = engine.Terrain(Path(context['terrainCandidate']))
    coverage = engine.Coverage(manifest['run_id'], terrain)
    path = Path(manifest['ledger_path'])
    limit = tuple(map(int, cursor))
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.5) as db:
        db.execute('PRAGMA query_only=ON')
        binding = json.loads(db.execute('SELECT binding FROM metadata WHERE id=1').fetchone()[0])
        need(binding['run_id'] == manifest['run_id'] and
             binding['processes'] == manifest['processes'] and
             binding['journal_anchors'] == manifest['journal_anchors'],
             'Event ledger binding differs')
        records = db.execute('SELECT shard,row_id,sha256,event FROM events '
                             'WHERE (shard,row_id) <= (?,?) ORDER BY shard,row_id', limit)
        for shard, row, checksum, text in records:
            need(hashlib.sha256(text.encode()).hexdigest() == checksum,
                 'Event ledger checksum mismatch')
            event = json.loads(text)
            need(event['event_id'] == {'shard': str(shard), 'row_id': str(row)},
                 'Event ledger sequence differs')
            coverage.apply(event)
    need(coverage.cursor == limit, 'Requested coverage cursor is not in the event ledger')
    return coverage.snapshot()


def audit(session, flow):
    result = core.release.load(flow)
    need(result['status'] == 'passed', 'B06 flow did not pass')
    review = result['replacementReview']
    switch = result['switch']
    rows = core.observer_rows(session)
    response_sha = switch['contextRawSHA256']['automation-response']
    planner = ROOT / 'out/runs/g6-b06-plan' / review['plannerRunId']
    source = core.lmcp_object(planner / 'response.xml', 'AutomationResponse')
    from lmcp import LMCPFactory
    need(hashlib.sha256(bytes(LMCPFactory.packMessage(source, True))).hexdigest() == response_sha,
         'Dispatched response differs from reviewed planner bytes')
    response_index = switch['observerRowCountBeforeSwitch']
    observed_sha = {row['rawSHA256'] for row in rows[response_index:]}
    need({row['rawSHA256'] for row in switch['newMissionCommands']}.issubset(observed_sha),
         'Confirmed new mission command evidence is missing')
    old_ids = set(switch['oldTaskIds'])
    new_ids = {task['taskId'] for task in review['tasks']}
    need(old_ids.isdisjoint(new_ids), 'Old and new task IDs overlap')
    expected = {item['vehicleId']: {point['number']: point for point in item['waypoints']}
                for item in review['plan']['commands']}
    observed = {vehicle: [] for vehicle in expected}
    for event in rows[response_index:]:
        if event['type'] != 'afrl.cmasi.MissionCommand' or \
                event.get('sourceEntity') != '100' or event.get('vehicleId') not in expected:
            continue
        vehicle = event['vehicleId']
        points = b05.xml(event).findall('WaypointList/Waypoint')
        need(len(points) >= 2, 'Replacement command has no route')
        planned = expected[vehicle]
        for point in points:
            number = point.findtext('Number')
            need(number in planned and
                 abs(float(point.findtext('Longitude')) - planned[number]['longitude']) < 1e-7 and
                 abs(float(point.findtext('Latitude')) - planned[number]['latitude']) < 1e-7,
                 'Old or unreviewed mission command appeared after replacement')
        observed[vehicle].append((event, points))
    amase = [json.loads(line) for line in (session.parent / 'amase.jsonl').open(encoding='utf-8')]
    received = {row['rawSHA256'] for row in amase
                if row['type'] == 'afrl.cmasi.MissionCommand'}
    commands = []
    lifecycle = {}
    for vehicle, planned in expected.items():
        actual = observed[vehicle]
        covered = {point.findtext('Number') for _, points in actual for point in points}
        need(actual and covered == set(planned) and
             all(event['rawSHA256'] in received for event, _ in actual),
             'AMASE did not receive every reviewed replacement waypoint')
        command_ids = {event['commandId'] for event, _ in actual}
        states = [row for row in rows[response_index:]
                  if row['type'] == 'afrl.cmasi.AirVehicleState' and row.get('id') == vehicle]
        executed = [row for row in states if b05.xml(row).findtext('CurrentCommand') in command_ids]
        need(executed, 'Aircraft did not report a replacement command')
        first = (states[0]['longitude'], states[0]['latitude'])
        flown = sum(b05.distance((a['longitude'], a['latitude']),
                                  (b['longitude'], b['latitude']))
                    for a, b in zip(states, states[1:]))
        need(flown > 100, 'Aircraft did not move meaningfully after cutover')
        commands.append(dict(vehicleId=vehicle, plannedWaypoints=len(planned),
                             sentSegments=len(actual), observedWaypointIds=len(covered),
                             observedFlightMeters=round(flown, 2),
                             executedCommandIds=sorted(command_ids)))
    assignments = {item['taskId']: item['vehicleId'] for item in review['plan']['assignments']}
    for task_id in new_ids:
        active = [row for row in rows if row['type'] == 'uxas.messages.task.TaskActive'
                  and row.get('taskId') == task_id]
        complete = [row for row in rows if row['type'] == 'uxas.messages.task.TaskComplete'
                    and row.get('taskId') == task_id]
        need(len(active) == len(complete) == 1 and rows.index(active[0]) < rows.index(complete[0]),
             'Replacement task lifecycle missing or repeated')
        activation = b05.xml(active[0])
        completion = b05.xml(complete[0])
        vehicle = assignments[task_id]
        need(activation.findtext('EntityID') == vehicle and
             vehicle in [node.text for node in completion.findall('EntitiesInvolved/int64')],
             'Replacement task lifecycle vehicle differs')
        started = int(activation.findtext('TimeTaskActivated'))
        ended = int(completion.findtext('TimeTaskCompleted'))
        need(ended > started, 'Replacement task duration invalid')
        lifecycle[task_id] = dict(vehicleId=vehicle, activatedMs=started,
                                  completedMs=ended, durationMs=ended - started)
    need(not [row for row in rows[response_index:]
              if row['type'] == 'uxas.messages.task.TaskComplete' and
              row.get('taskId') in old_ids],
         'Old task completed after replacement')
    actions = [row for row in rows[response_index:]
               if row['type'] == 'afrl.cmasi.VehicleActionCommand']
    associated = [(row, {node.text for node in
                   b05.xml(row).findall('.//AssociatedTaskList/int64')})
                  for row in actions]
    need(not [row for row, ids in associated if ids & old_ids],
         'Superseded sensor action appeared after replacement')
    new_actions = [row for row, ids in associated if ids & new_ids]
    action_receipts = {row['rawSHA256'] for row in amase
                       if row['type'] == 'afrl.cmasi.VehicleActionCommand'}
    need(new_actions and all(row['rawSHA256'] in action_receipts for row in new_actions),
         'Replacement sensor actions did not reach AMASE')
    archive = session.parent / 'task-replanning' / (switch['key'] + '-old-coverage.json')
    old = core.release.load(archive)
    native_old = replay(session, old['cursor'])
    for key in ('runId', 'cursor', 'simulationTimeMs', 'sampledStates',
                'gridResolutionMeters', 'tasks'):
        need(old[key] == native_old[key], 'Archived old coverage differs from event replay: ' + key)
    current = core.release.load(session.parents[1] / 'coverage/live.json')
    native_new = replay(session, current['cursor'])
    for key in ('runId', 'cursor', 'simulationTimeMs', 'sampledStates',
                'gridResolutionMeters', 'tasks'):
        need(current[key] == native_new[key], 'Current new coverage differs from event replay: ' + key)
    need({task['taskId'] for task in old['tasks']} == old_ids and
         {task['taskId'] for task in current['tasks']} == new_ids,
         'Coverage versions mixed old and new task IDs')
    uxas_logs = '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                          for path in (session.parent / 'uxas/log').glob('log_*'))
    need(all('Removed Task[' + task_id + ']' in uxas_logs for task_id in old_ids),
         'UxAS did not remove every superseded task service')
    return dict(task='G6-B06', status='passed', mode=result['mode'],
                reviewedResponseSHA256=response_sha,
                commands=commands, tasks=lifecycle,
                oldCoverage=dict(cursor=old['cursor'],
                    tasks=[{key: task[key] for key in
                           ('taskId', 'seenCells', 'totalCells', 'observationMilliseconds')}
                           for task in old['tasks']], replayMatches=True),
                newCoverage=dict(cursor=current['cursor'],
                    tasks=[{key: task[key] for key in
                           ('taskId', 'seenCells', 'totalCells', 'observationMilliseconds')}
                           for task in current['tasks']], replayMatches=True),
                oldTaskCompletionsAfterSwitch=0,
                oldAssociatedActionsAfterSwitch=0,
                newAssociatedActionsReceived=len(new_actions))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--flow', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.session.resolve(), args.flow.resolve())
    except Exception as error:
        import traceback
        result = dict(task='G6-B06', status='failed', error=str(error),
                      traceback=traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    core.release.save(args.output, result)
    print(json.dumps({key: result.get(key) for key in ('status', 'error', 'mode')},
                     ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())

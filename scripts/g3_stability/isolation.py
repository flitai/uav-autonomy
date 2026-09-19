"""Audit observed rate and fresh-run boundaries without changing captured data."""
from collections import Counter
import base64
import hashlib
import xml.etree.ElementTree as ET


def require(value, message):
    if not value: raise RuntimeError(message)


def command_content(row):
    node = ET.fromstring(base64.b64decode(row['xmlBase64']))
    # WaypointPlanManager legitimately renumbers/approves the original loiter.
    # It also appends its configured payload-1, -60 degree default gimbal action.
    # Only that exact task-free addition is ignored; all route/task fields remain.
    for field in ('CommandID', 'Status'): node.remove(node.find(field))
    for actions in node.findall('WaypointList/Waypoint/VehicleActionList'):
        for action in list(actions):
            if (action.tag == 'GimbalAngleAction' and
                {c.tag for c in action} == {'AssociatedTaskList', 'PayloadID', 'Azimuth', 'Elevation', 'Rotation'} and
                len(action.find('AssociatedTaskList')) == 0 and action.findtext('PayloadID') == '1' and
                all(float(action.findtext(k)) == v for k, v in [('Azimuth', 0), ('Elevation', -60), ('Rotation', 0)])):
                actions.remove(action)
    def semantic(element):
        return element.tag, (element.text or '').strip(), tuple(semantic(c) for c in element)
    return semantic(node)


def assess(run_id, name, item, observer, monitor, events):
    sessions = [r for r in monitor if r['type'] == 'afrl.cmasi.SessionStatus' and r['state'] == 1]
    require(sessions and all(r['realTimeMultiple'] == 1 for r in sessions), 'Actual running rate differs from 1')
    init = next(e for e in events if e['kind'] == 'initialized-paused')
    require(float(init['simTimeSeconds']) == 0, 'New group did not start at simulation time zero')
    token = run_id + '/' + hashlib.sha256(name.encode('utf-8')).hexdigest().upper()[:16]
    readiness = [r for r in monitor if r.get('key') == 'G3Ready']
    require(readiness and all(r['value'] == token for r in readiness), 'Prior readiness token leaked')
    for rows in (observer, monitor):
        require(rows and rows[0]['offset'] == 0, 'New parser did not start at byte zero')
        require(not any(r['type'] == 'uxas.messages.task.TaskComplete' for r in rows), 'Unexpected completion in short execution')
    task_time = next(r['monotonicSeconds'] for r in item['injections'] if r['purpose'] == 'task')
    before = [r for r in observer + monitor if r['monotonicSeconds'] < task_time]
    require(not any(r['type'] in ('uxas.messages.task.TaskActive', 'uxas.messages.task.TaskInitialized') for r in before),
            'Task state preceded this run task injection')
    cruises = {command_content(r) for r in monitor if r['type'] == 'afrl.cmasi.MissionCommand' and r.get('commandId') == '100'}
    require(len(cruises) == 2, 'Both original cruise commands required')
    require(all(command_content(r) in cruises for r in before if r['type'] == 'afrl.cmasi.MissionCommand'),
            'Planned command preceded this run task injection')
    return dict(isolation=dict(runId=run_id, readinessToken=token, initialSimulationSeconds=0,
        parserOffsets=dict(observer=observer[0]['offset'], amase=monitor[0]['offset']), completionEvents=0,
        noPriorTaskOrCommand=True, singleTaskAndRequest=True, nativeExecutionCorrelated=True),
        simulationRate=dict(status='passed', configured=1, runningSamples=len(sessions),
                            observed=dict(Counter(str(r['realTimeMultiple']) for r in sessions))))

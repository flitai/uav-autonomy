"""Offline negative replay of real captures, never simulation input injection."""
import base64
import copy
import json
import xml.etree.ElementTree as ET


def verify(task, c):
    folder = task.run / 'headless'
    read = lambda path: [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    original = [read(folder / 'observer.jsonl'), read(folder / 'amase.jsonl'), read(folder / 'amase/events.jsonl'),
                [r for p in sorted((folder / 'amase').glob('execution-*.jsonl')) for r in read(p)]]
    request = ET.fromstring(task.input_message('request').toXMLStr(''))

    def run(data):
        return c.assess(*data[:3], task.policy, request, data[3])

    def remove(data, tag, index=0):
        data[index][:] = [r for r in data[index] if not r.get('type', '').endswith('.' + tag)]

    def alter(data, tag, field, value, index=0, predicate=lambda n: True):
        for r in data[index]:
            if r.get('type', '').endswith('.' + tag):
                n = c.xml(r)
                if predicate(n):
                    node = n.find(field)
                    if node is not None:
                        node.text = value
                        r['xmlBase64'] = base64.b64encode(ET.tostring(n, encoding='utf-8')).decode('ascii')

    tests = [
        ('commands-only', lambda d: remove(d, 'AirVehicleState'), 'state-internal-mismatch|missing-dynamic-entity'),
        ('no-internal-receipt', lambda d: remove(d, 'MissionCommand', 2), 'command-internal-receipt'),
        ('no-wire-receipt', lambda d: remove(d, 'MissionCommand', 1), 'command-wire-receipt'),
        ('no-internal-states', lambda d: remove(d, 'AirVehicleState', 2), 'state-internal-mismatch'),
        ('wrong-request', lambda d: alter(d, 'UniqueAutomationResponse', 'ResponseID', '999'), 'request-identity'),
        ('wrong-assigned-entity', lambda d: alter(d, 'TaskAssignmentSummary', 'TaskList/TaskAssignment/AssignedVehicle', '999'), 'wrong-assigned-entity'),
        ('wrong-assigned-task', lambda d: alter(d, 'TaskAssignmentSummary', 'TaskList/TaskAssignment/TaskID', '999'), 'wrong-assigned-task'),
        ('missing-task-active', lambda d: remove(d, 'TaskActive'), 'missing-or-repeated-task-active'),
        ('wrong-task-active', lambda d: alter(d, 'TaskActive', 'TaskID', '999'), 'missing-or-repeated-task-active'),
        ('wrong-active-entity', lambda d: alter(d, 'TaskActive', 'EntityID', '500'), 'missing-or-repeated-task-active'),
        ('early-task-active', lambda d: [r.__setitem__('monotonicSeconds', 0) for r in d[0] if r['type'].endswith('.TaskActive')], 'task-active-before-task-state'),
        ('no-segment-continuation', lambda d: d[0].__setitem__(slice(None), [r for r in d[0] if not (r.get('type', '').endswith('.MissionCommand') and c.xml(r).findtext('CommandID') == task.record['cases'][0]['execution']['entities'][0]['segments'][-1]['commandId'])]), 'missing-segment-continuation'),
    ]
    # Mutate all three representations consistently: these cases must be rejected
    # for execution semantics, not merely for independent-stream disagreement.
    def state_mutation(data, field, value, predicate=lambda n: True):
        for i in range(3): alter(data, 'AirVehicleState', field, value, i, predicate)

    def off_route(data):
        state_mutation(data, 'Location/Location3D/Latitude', '46.0')
        for row in data[3]: row['position'][0] = 46.0

    def duplicate_segment(data):
        cid = task.record['cases'][0]['execution']['entities'][0]['segments'][0]['commandId']
        index = next(i for i, r in enumerate(data[0]) if r['type'].endswith('.MissionCommand') and c.xml(r).findtext('CommandID') == cid)
        data[0].insert(index + 1, copy.deepcopy(data[0][index]))

    def regress(data):
        row = next(r for r in data[3] if r['entityId'] == '400' and r['waypoint'] == '15')
        row['waypoint'] = '13'

    tests += [
        ('static-time', lambda d: state_mutation(d, 'Time', '1'), 'state-time-not-increasing'),
        ('cruise-only-movement', lambda d: state_mutation(d, 'CurrentCommand', '100'), 'command-never-executed'),
        ('wrong-state-task', lambda d: state_mutation(d, 'AssociatedTasks/int64', '999'), 'state-task-mismatch'),
        ('wrong-state-waypoint', lambda d: state_mutation(d, 'CurrentWaypoint', '999'), 'state-command-waypoint'),
        ('off-route-movement', off_route, 'trajectory-does-not-follow-task-legs'),
        ('frozen-position', lambda d: [state_mutation(d, 'Location/Location3D/' + f, v) for f, v in [('Latitude','45'), ('Longitude','-121'), ('Altitude','700')]], 'static-states'),
        ('no-internal-navigation', lambda d: d[3].clear(), 'missing-internal-navigation'),
        ('duplicate-segment', duplicate_segment, 'duplicate-segment-command'),
        ('waypoint-regression', regress, 'internal-waypoint-regression-or-skip'),
        ('disagreeing-navigation-position', lambda d: [s['position'].__setitem__(0,46.0) for s in d[3]], 'state-navigation-position'),
    ]
    results = []
    for name, mutate, expected in tests:
        data = copy.deepcopy(original)
        mutate(data)
        try:
            run(data)
        except c.EvidenceError as error:
            if str(error) not in expected.split('|'):
                raise RuntimeError(name + ': unexpected refusal: ' + str(error)) from error
            results.append(dict(name=name, status='passed', expected='rejected', rejection=str(error), kind='offline-replay'))
        else:
            raise RuntimeError(name + ': invalid evidence accepted')
    # Positive replay must still pass after constructing every independent mutant.
    run(original)
    if c.equivalent(ET.fromstring('<CommandID>9007199254740992</CommandID>'), ET.fromstring('<CommandID>9007199254740993</CommandID>')):
        raise RuntimeError('Adjacent int64 identities were collapsed')
    results.append(dict(name='int64-identity', status='passed', expected='distinct', kind='boundary-check'))
    return results

"""Correlate independent UxAS bus, AMASE wire and in-process observations.

CurrentWaypoint is the *target* waypoint. Repeated samples and overlapping
command payloads are normal; returning to an already passed target is not.
This validator proves initial execution, never terminal task completion.
"""
import base64
from collections import Counter
import math
import xml.etree.ElementTree as ET


class EvidenceError(RuntimeError):
    pass


def need(condition, reason):
    if not condition:
        raise EvidenceError(reason)


def xml(row):
    return ET.fromstring(base64.b64decode(row['xmlBase64'], validate=True))


def values(node, path):
    return [n.text for n in node.findall(path)]


def semantic(node):
    """Ignore indentation and numeric formatting differences between languages."""
    text = (node.text or '').strip()
    if text:
        try:
            text = float(text) if any(c in text.lower() for c in '.e') else int(text)
        except ValueError:
            if text.lower() in ('true', 'false'): text = text.lower()
    children = list(node)
    if len({n.tag for n in children}) == len(children): children.sort(key=lambda n: n.tag)
    return node.tag, text, tuple(semantic(n) for n in children)


def equivalent(a, b):
    if a.tag != b.tag: return False
    av, bv = (a.text or '').strip(), (b.text or '').strip()
    if av.lower() != bv.lower():
        if av.lstrip('-').isdigit() and bv.lstrip('-').isdigit(): return int(av) == int(bv) and len(a) == len(b) == 0
        try:
            if not math.isclose(float(av), float(bv), rel_tol=2e-7, abs_tol=1e-9): return False
        except ValueError: return False
    ac, bc = list(a), list(b)
    if len(ac) != len(bc): return False
    if not a.tag.endswith('List') and len({n.tag for n in ac}) == len(ac):
        ac.sort(key=lambda n: n.tag); bc.sort(key=lambda n: n.tag)
    return all(equivalent(x, y) for x, y in zip(ac, bc))


def position(node):
    return tuple(float(node.findtext(k)) for k in ('Latitude', 'Longitude', 'Altitude'))


def state(node):
    return dict(entityId=node.findtext('ID'), timeMs=node.findtext('Time'),
                commandId=node.findtext('CurrentCommand'), waypoint=node.findtext('CurrentWaypoint'),
                tasks=values(node, 'AssociatedTasks/int64'), mode=node.findtext('Mode'),
                position=position(node.find('Location/Location3D')))


def xy(point, origin):
    # Local tangent approximation for the short legs, in metres.
    return (math.radians(point[1] - origin[1]) * 6371000 * math.cos(math.radians(origin[0])),
            math.radians(point[0] - origin[0]) * 6371000)


def distance(a, b):
    return math.hypot(*xy(a, b))


def segment_geometry(samples, start, end):
    ex, ey = xy(end, start)
    length = math.hypot(ex, ey)
    need(length > 0, 'zero-length-task-leg')
    points = [xy(s['position'], start) for s in samples]
    along = [(x * ex + y * ey) / length for x, y in points]
    cross = [abs(x * ey - y * ex) / length for x, y in points]
    remaining = [distance(s['position'], end) for s in samples]
    return dict(sampleCount=len(samples), firstTimeMs=samples[0]['timeMs'], lastTimeMs=samples[-1]['timeMs'],
                lengthMeters=length, forwardProgressMeters=along[-1] - along[0],
                approachMeters=remaining[0] - min(remaining), closestTargetMeters=min(remaining),
                maximumCrossTrackMeters=max(cross), altitudeErrorMeters=max(abs(s['position'][2] - end[2]) for s in samples))


def assess(bus, monitor, events, policy, original_request, navigation):
    decoded = [(r, xml(r)) for r in bus]
    inside = [(r, xml(r)) for r in events if r.get('kind') == 'message']
    wire = [(r, xml(r)) for r in monitor]

    def select(tag):
        return [(r, n) for r, n in decoded if n.tag == tag]

    def one(tag):
        matches = select(tag)
        need(len(matches) == 1, 'expected-single:' + tag)
        r, n = matches[0]
        need(r['sourceEntity'] == '100', 'non-uxas-source:' + tag)
        return r, n

    initialized_r, initialized = one('TaskInitialized')
    request_r, request = one('UniqueAutomationRequest')
    response_r, response = one('UniqueAutomationResponse')
    plain_r, plain = one('AutomationResponse')
    assignment_r, assignment = one('TaskAssignmentSummary')
    request_id = request.findtext('RequestID')
    need(request_id == response.findtext('ResponseID') == assignment.findtext('CorrespondingAutomationRequestID'), 'request-identity')
    need(initialized.findtext('TaskID') == '1000', 'wrong-initialized-task')
    need(semantic(request.find('OriginalRequest/AutomationRequest')) == semantic(original_request), 'original-request-differs')
    need(semantic(response.find('OriginalResponse/AutomationResponse')) == semantic(plain), 'unique-response-differs')
    need(initialized_r['monotonicSeconds'] < request_r['monotonicSeconds'] < assignment_r['monotonicSeconds'] < response_r['monotonicSeconds'], 'planning-order')
    assignments = assignment.findall('TaskList/TaskAssignment')
    need(assignments and all(a.findtext('TaskID') == '1000' for a in assignments), 'wrong-assigned-task')
    assigned = sorted({a.findtext('AssignedVehicle') for a in assignments})
    need(set(assigned) <= {'400', '500'}, 'wrong-assigned-entity')
    plans = {c.findtext('VehicleID'): c for c in plain.findall('MissionCommandList/MissionCommand')}
    need(sorted(plans) == assigned, 'assignment-plan-entity-mismatch')

    # Independent raw stream and in-process state agreement, including navigation
    # fields. The observer is never allowed to invent or duplicate AMASE states.
    wire_hashes = Counter(r['rawSHA256'] for r, n in wire if n.tag == 'AirVehicleState')
    bus_hashes = Counter(r['rawSHA256'] for r, n in decoded if n.tag == 'AirVehicleState')
    need(not (bus_hashes - wire_hashes), 'state-wire-mismatch')
    all_states = [(r, state(n)) for r, n in select('AirVehicleState')]
    for entity in ('400', '500'):
        samples = [(r, s) for r, s in all_states if s['entityId'] == entity]
        need(len(samples) >= 5, 'missing-dynamic-entity')
        need(all(r['sourceEntity'] == r['sourceService'] == '0' for r, s in samples), 'state-source')
        times = [int(s['timeMs']) for r, s in samples]
        need(all(b > a for a, b in zip(times, times[1:])), 'state-time-not-increasing')
        need(len({s['position'] for r, s in samples}) > 1, 'static-states')
    internal_states = {(n.findtext('ID'), n.findtext('Time')): (r, n) for r, n in inside if n.tag == 'AirVehicleState'}
    for r, n in select('AirVehicleState'):
        match = internal_states.get((n.findtext('ID'), n.findtext('Time')))
        need(match is not None and equivalent(n, match[1]), 'state-internal-mismatch')

    cruise = [dict(vehicleId=n.findtext('VehicleID'), commandId=n.findtext('CommandID'),
                   sourceEntity=r['sourceEntity'], sourceService=r['sourceService'])
              for r, n in select('MissionCommand') if r['monotonicSeconds'] < plain_r['monotonicSeconds']]
    need(sorted(c['vehicleId'] for c in cruise if c['commandId'] == '100' and c['sourceEntity'] == '0') == ['400', '500'], 'original-cruise-missing')
    outcome = dict(taskId='1000', uniqueRequestId=request_id, uniqueResponseId=response.findtext('ResponseID'),
                   assignedEntities=assigned, cruiseCommands=cruise, entities=[], taskCompletionValidated=False, coverageValidated=False)
    for entity, plan in plans.items():
        waypoints = plan.findall('WaypointList/Waypoint')
        wp = {w.findtext('Number'): w for w in waypoints}
        order = {w.findtext('Number'): i for i, w in enumerate(waypoints)}
        need(len(wp) == len(waypoints), 'duplicate-plan-waypoint')
        task_numbers = [n for n, w in wp.items() if '1000' in values(w, 'AssociatedTasks/int64')]
        need(task_numbers, 'plan-has-no-task')
        commands = [(r, n) for r, n in select('MissionCommand') if r['monotonicSeconds'] >= plain_r['monotonicSeconds']
                    and n.findtext('VehicleID') == entity]
        need(len(commands) >= policy['minimumSegmentCommands'], 'missing-segment-continuation')
        command_map, segments = {}, []
        for r, c in commands:
            cid = c.findtext('CommandID')
            need(r['sourceEntity'] == '100' and cid != '100', 'cruise-used-as-plan')
            need(cid not in command_map, 'duplicate-segment-command')
            command_map[cid] = c
            numbers = values(c, 'WaypointList/Waypoint/Number')
            need(numbers and all(n in wp for n in numbers), 'segment-waypoint-outside-plan')
            need([order[n] for n in numbers] == list(range(order[numbers[0]], order[numbers[-1]] + 1)), 'noncontiguous-segment')
            need(c.findtext('FirstWaypoint') in numbers, 'invalid-segment-first-waypoint')
            for w in c.findall('WaypointList/Waypoint'):
                # WPM can override TurnType and append the terminal gimbal action;
                # navigation identity, geometry and task association must survive.
                original = wp[w.findtext('Number')]
                for field in ('Number', 'NextWaypoint', 'Latitude', 'Longitude', 'Altitude', 'AltitudeType', 'Speed', 'SpeedType', 'AssociatedTasks'):
                    need(semantic(w.find(field)) == semantic(original.find(field)), 'segment-plan-differs:' + field)
            received = [(e, n) for e, n in inside if n.tag == 'MissionCommand' and n.findtext('VehicleID') == entity and n.findtext('CommandID') == cid]
            need(len(received) == 1 and equivalent(received[0][1], c), 'command-internal-receipt')
            need(len([x for x, n in wire if n.tag == 'MissionCommand' and x['rawSHA256'] == r['rawSHA256']]) == 1, 'command-wire-receipt')
            overlap = [] if not segments else [n for n in numbers if n in segments[-1]['waypoints']]
            if segments:
                need(order[numbers[0]] > order[segments[-1]['waypoints'][0]] and overlap, 'segment-not-forward-overlap')
            segments.append(dict(commandId=cid, firstWaypoint=c.findtext('FirstWaypoint'), waypoints=numbers,
                                 overlapWithPrevious=overlap, turnTypes=sorted(set(values(c, 'WaypointList/Waypoint/TurnType'))),
                                 sourceService=r['sourceService'], rawSHA256=r['rawSHA256'], internalSequence=received[0][0]['sequence']))

        executed = [(r, s) for r, s in all_states if s['entityId'] == entity and s['commandId'] in command_map]
        need(executed, 'command-never-executed')
        nav = [s for s in navigation if s['entityId'] == entity and s['commandId'] in command_map and s['kind'] == 'navigation']
        need(nav, 'missing-internal-navigation')
        need(all(float(b['simTimeSeconds']) >= float(a['simTimeSeconds']) and int(b['sequence']) > int(a['sequence'])
                 for a, b in zip(nav, nav[1:])), 'internal-navigation-order')
        nav_path = []
        for s in nav:
            need(s['mode'] == 'Waypoint' and s['waypoint'] in wp, 'internal-navigation-mismatch')
            if not nav_path or nav_path[-1] != s['waypoint']:
                if nav_path:
                    need(wp[nav_path[-1]].findtext('NextWaypoint') == s['waypoint'], 'internal-waypoint-regression-or-skip')
                nav_path.append(s['waypoint'])
        path, trajectory, executed_commands = [], [], []
        for r, s in executed:
            command = command_map[s['commandId']]
            need(s['mode'] == 'Waypoint' and s['waypoint'] in values(command, 'WaypointList/Waypoint/Number'), 'state-command-waypoint')
            need(s['tasks'] == values(wp[s['waypoint']], 'AssociatedTasks/int64'), 'state-task-mismatch')
            received = next(e for e, n in inside if n.tag == 'MissionCommand' and n.findtext('VehicleID') == entity and n.findtext('CommandID') == s['commandId'])
            matching_state = internal_states[(entity, s['timeMs'])][0]
            need(int(received['sequence']) < int(matching_state['sequence']), 'execution-before-receipt')
            peers = [n for n in nav if n['commandId'] == s['commandId'] and n['waypoint'] == s['waypoint']
                     and abs(float(n['simTimeSeconds']) - int(s['timeMs']) / 1000) < 1]
            need(peers, 'state-navigation-mismatch')
            peer = min(peers, key=lambda n: abs(float(n['simTimeSeconds']) - int(s['timeMs']) / 1000))
            need(distance(peer['position'], s['position']) < 10 and abs(peer['position'][2] - s['position'][2]) < 1, 'state-navigation-position')
            if not executed_commands or executed_commands[-1] != s['commandId']:
                need(s['commandId'] not in executed_commands, 'reexecuted-segment')
                executed_commands.append(s['commandId'])
            if not path or path[-1] != s['waypoint']:
                if path:
                    need(order[s['waypoint']] > order[path[-1]], 'waypoint-regression')
                path.append(s['waypoint'])
            trajectory.append(dict(**s, wallTime=r['wallTime'], wireOffset=r['offset'], rawSHA256=r['rawSHA256'], internalSequence=matching_state['sequence']))
        need(len(executed_commands) >= policy['minimumSegmentCommands'], 'continuation-not-executed')
        task_path = [n for n in path if n in task_numbers]
        need(len(task_path) >= policy['minimumTaskWaypoints'], 'insufficient-task-progression')
        active = [(r, n) for r, n in select('TaskActive') if n.findtext('TaskID') == '1000' and n.findtext('EntityID') == entity]
        need(len(active) == 1 and active[0][0]['sourceEntity'] == '100', 'missing-or-repeated-task-active')
        first_task = next(r for r, s in executed if '1000' in s['tasks'])
        need(first_task['monotonicSeconds'] <= active[0][0]['monotonicSeconds'], 'task-active-before-task-state')
        legs = []
        nav_task_path = [n for n in nav_path if n in task_numbers]
        for number in nav_task_path[:-1]:
            index = order[number]
            # Both ends must belong to the task; the entry transit is not counted.
            if index == 0 or waypoints[index - 1].findtext('Number') not in task_numbers: continue
            samples = [dict(**s, timeMs=str(round(float(s['simTimeSeconds']) * 1000))) for s in nav if s['waypoint'] == number]
            if len(samples) < 3: continue
            metrics = segment_geometry(samples, position(waypoints[index - 1]), position(wp[number]))
            qualifies = (metrics['forwardProgressMeters'] >= policy['minimumLegProgressMeters']
                         and metrics['approachMeters'] >= policy['minimumLegProgressMeters']
                         and metrics['maximumCrossTrackMeters'] <= policy['maximumRouteDeviationMeters']
                         and metrics['closestTargetMeters'] <= policy['maximumRouteDeviationMeters']
                         and metrics['altitudeErrorMeters'] <= 25)
            legs.append(dict(fromWaypoint=waypoints[index - 1].findtext('Number'), toWaypoint=number,
                             successor=wp[number].findtext('NextWaypoint'), qualifies=qualifies, **metrics))
        need(sum(x['qualifies'] for x in legs) >= policy['minimumCompletedTaskLegs'], 'trajectory-does-not-follow-task-legs')
        outcome['entities'].append(dict(entityId=entity, planCommandId=plan.findtext('CommandID'), planWaypointCount=len(wp),
            taskFirstWaypoint=task_numbers[0], taskActive=dict(wallTime=active[0][0]['wallTime'], timeTaskActivated=active[0][1].findtext('TimeTaskActivated')),
            segments=segments, executedCommandIds=executed_commands, targetWaypointSequence=path,
            internalTargetWaypointSequence=nav_path, taskTargetWaypointSequence=task_path, completedTaskLegs=legs, trajectory=trajectory))
    outcome['status'] = 'passed'
    return outcome

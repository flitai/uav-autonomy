"""Require a real terminal transition, in addition to the UxAS notification."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('completion_execution', Path(__file__).parents[1]/'g3_execution/correlator.py')
execution = importlib.util.module_from_spec(spec); spec.loader.exec_module(execution)
need, xml, values = execution.need, execution.xml, execution.values


def assess(bus, monitor, events, policy, original_request, navigation):
    decoded = [(r, xml(r)) for r in bus]
    plans = [n for r, n in decoded if n.tag == 'AutomationResponse']
    need(len(plans) == 1, 'completion-planning-response')
    commands = plans[0].findall('MissionCommandList/MissionCommand')
    assigned = sorted(c.findtext('VehicleID') for c in commands)
    completions = [(r, n) for r, n in decoded if n.tag == 'TaskComplete']
    need(len(completions) == 1, 'completion-missing-or-duplicate')
    complete_row, complete = completions[0]
    need(complete_row['sourceEntity'] == '100' and complete.findtext('TaskID') == '1000', 'completion-source-or-task')
    need(sorted(values(complete, 'EntitiesInvolved/int64')) == assigned, 'completion-entities')
    completion_ms = int(complete.findtext('TimeTaskCompleted'))
    entities = []
    cutoff = complete_row['monotonicSeconds']
    for plan in commands:
        entity = plan.findtext('VehicleID')
        waypoints = plan.findall('WaypointList/Waypoint')
        wp = {w.findtext('Number'): w for w in waypoints}
        task_numbers = [w.findtext('Number') for w in waypoints if '1000' in values(w, 'AssociatedTasks/int64')]
        need(len(task_numbers) >= 2, 'completion-empty-task-plan')
        last = task_numbers[-1]
        successor = wp[last].findtext('NextWaypoint')
        need(successor in wp and '1000' not in values(wp[successor], 'AssociatedTasks/int64'), 'completion-terminal-successor')
        segments = {n.findtext('CommandID') for r, n in decoded if n.tag == 'MissionCommand'
                    and n.findtext('VehicleID') == entity and any(w.findtext('Number') == last for w in n.findall('WaypointList/Waypoint'))}
        nav = [s for s in navigation if s['entityId'] == entity and s['commandId'] in segments]
        terminal = [s for s in nav if s['waypoint'] == successor and s['waypointReached'] == last]
        need(terminal, 'completion-terminal-navigation-missing')
        terminal = terminal[0]
        terminal_ms = round(float(terminal['simTimeSeconds'])*1000)
        need(terminal_ms <= completion_ms + 1, 'completion-before-terminal')
        all_nav = [s for s in navigation if s['entityId'] == entity and float(s['simTimeSeconds'])*1000 <= completion_ms+1]
        visited = []
        for s in all_nav:
            if s['waypoint'] in task_numbers and (not visited or visited[-1] != s['waypoint']): visited.append(s['waypoint'])
        need(visited == task_numbers, 'completion-task-waypoints-incomplete-or-revisited')
        samples = [s for s in nav if s['waypoint'] == last and float(s['simTimeSeconds']) <= float(terminal['simTimeSeconds'])]
        need(len(samples) >= 3, 'completion-terminal-leg-samples-missing')
        index = next(i for i, w in enumerate(waypoints) if w.findtext('Number') == last)
        metrics = execution.segment_geometry([dict(s, timeMs=str(round(float(s['simTimeSeconds'])*1000))) for s in samples],
                                            execution.position(waypoints[index-1]), execution.position(wp[last]))
        need(metrics['forwardProgressMeters'] >= 10 and metrics['approachMeters'] >= 10
             and metrics['maximumCrossTrackMeters'] <= 300 and metrics['altitudeErrorMeters'] <= 25, 'completion-terminal-leg-not-executed')
        endpoint_distance = execution.distance(terminal['position'], execution.position(wp[last]))
        # Nominal 22 m/s and 20 degree bank give a 136 m turn radius. The terminal
        # boundary uses native fly-past arrival, rather than the 2-radius turn-short rule.
        need(endpoint_distance <= 150, 'completion-outside-terminal-navigation-tolerance')
        states = [(r, execution.state(n)) for r, n in decoded if n.tag == 'AirVehicleState' and n.findtext('ID') == entity]
        on = [(r, s) for r, s in states if '1000' in s['tasks']]
        need(on, 'completion-task-never-active')
        off = [(r, s) for r, s in states if int(s['timeMs']) > int(on[-1][1]['timeMs']) and '1000' not in s['tasks']]
        need(off, 'completion-terminal-state-missing')
        first_off_r, first_off = off[0]
        need(first_off['commandId'] in segments and first_off['waypoint'] == successor, 'completion-wrong-terminal-state')
        need(terminal_ms <= int(first_off['timeMs'])+1 <= completion_ms+1 and
             completion_ms-int(first_off['timeMs']) <= 1000 and first_off_r['monotonicSeconds'] <= cutoff,
             'completion-before-terminal-state')
        need(all(s['waypoint'] == successor and s['commandId'] in segments for _, s in off), 'completion-post-terminal-regression')
        active = [(r, n) for r, n in decoded if n.tag == 'TaskActive' and n.findtext('EntityID') == entity]
        need(len(active) == 1 and active[0][1].findtext('TaskID') == '1000' and
             active[0][0]['monotonicSeconds'] < cutoff, 'completion-active-identity')
        entities.append(dict(entityId=entity, taskWaypoints=task_numbers, terminalWaypoint=last, successorWaypoint=successor,
            terminalNavigation=terminal, terminalLeg=metrics, terminalDistanceMeters=endpoint_distance,
            firstOffTaskState=first_off, taskActiveTimeMs=active[0][1].findtext('TimeTaskActivated')))

    # Reuse T04's full planning/segment/wire/internal checks up to the last on-task state.
    # Terminal mode (including a commanded loiter) is checked above, not mistaken for a regression.
    last_on = max(r['monotonicSeconds'] for r, n in decoded if n.tag == 'AirVehicleState' and '1000' in values(n, 'AssociatedTasks/int64'))
    prefix = [r for r in bus if r['monotonicSeconds'] <= last_on]
    last_ms = max(int(xml(r).findtext('Time')) for r in prefix if r['type'] == 'afrl.cmasi.AirVehicleState')
    proof = execution.assess(prefix, monitor, events, policy, original_request,
                             [s for s in navigation if float(s['simTimeSeconds'])*1000 <= last_ms])
    return dict(status='passed', taskId='1000', assignedEntities=assigned, taskCompletionValidated=True,
                completion=dict(timeTaskCompletedMs=str(completion_ms), wallTime=complete_row['wallTime'],
                                sourceEntity=complete_row['sourceEntity'], sourceService=complete_row['sourceService'],
                                rawSHA256=complete_row['rawSHA256'], timeMeaning='UxAS discrete time driven by entity simulation milliseconds'),
                entities=entities, execution=proof)

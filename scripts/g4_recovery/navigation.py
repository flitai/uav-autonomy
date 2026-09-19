"""Separate a segment receipt transient from actual navigation steps.

All input evidence remains intact. Only a task-free, action-free predecessor
briefly selected by command application, with the immediately following real
step still on the previously active target, may be classified as receipt-only.
Actual step regressions and on-task revisits remain failures in the G3 auditor.
"""
import base64
import xml.etree.ElementTree as ET


def execution_view(navigation, bus):
    commands, states = {}, []
    for row in bus:
        if row['type'] not in ('afrl.cmasi.MissionCommand', 'afrl.cmasi.AirVehicleState'): continue
        node = ET.fromstring(base64.b64decode(row['xmlBase64']))
        if node.tag == 'MissionCommand':
            commands[(node.findtext('VehicleID'), node.findtext('CommandID'))] = node
        else:
            states.append((node.findtext('ID'), node.findtext('CurrentCommand'), node.findtext('CurrentWaypoint')))
    observed = set(states)
    omitted, receipts = set(), []
    by_entity = {}
    for index, sample in enumerate(navigation):
        by_entity.setdefault(sample['entityId'], []).append((index, sample))
    for entity, samples in by_entity.items():
        for (before_index, before), (index, receipt), (after_index, after) in zip(samples, samples[1:], samples[2:]):
            if not (before['sampleKind'] == after['sampleKind'] == 'step' and receipt['sampleKind'] == 'command-applied'
                    and before['commandId'] != receipt['commandId'] == after['commandId']
                    and before['waypoint'] == after['waypoint'] != receipt['waypoint']
                    and int(before['sequence']) + 1 == int(receipt['sequence']) == int(after['sequence']) - 1
                    and float(before['simTimeSeconds']) <= float(receipt['simTimeSeconds']) <= float(after['simTimeSeconds'])
                    and before['waypointReached'] == after['waypointReached'] == receipt['waypoint']
                    and (entity, receipt['commandId'], receipt['waypoint']) not in observed):
                continue
            old = commands.get((entity, before['commandId'])); new = commands.get((entity, receipt['commandId']))
            if old is None or new is None or new.findtext('FirstWaypoint') != receipt['waypoint']: continue
            if old.findall('VehicleActionList/*') or new.findall('VehicleActionList/*'): continue
            old_points = {w.findtext('Number'): w for w in old.findall('WaypointList/Waypoint')}
            new_points = {w.findtext('Number'): w for w in new.findall('WaypointList/Waypoint')}
            identifiers = (receipt['waypoint'], before['waypoint'])
            if not all(identifier in old_points and identifier in new_points for identifier in identifiers): continue
            if old_points[receipt['waypoint']].findtext('NextWaypoint') != before['waypoint']: continue
            def semantic(node):
                return (node.tag, (node.text or '').strip(), tuple(semantic(child) for child in node))
            if any(semantic(old_points[key]) != semantic(new_points[key]) or
                   old_points[key].findall('AssociatedTasks/*') or old_points[key].findall('VehicleActionList/*')
                   for key in identifiers): continue
            omitted.add(index)
            receipts.append({'classification':'receipt-only-overlap', 'before':before, 'receipt':receipt, 'next_step':after,
                             'wire_state_regression':False, 'task_or_action_reentry':False})
    return [sample for index, sample in enumerate(navigation) if index not in omitted], receipts

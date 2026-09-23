"""Recognize bounded metadata rewind when two UxAS segments overlap.

Raw AMASE and wire evidence is never changed. The G3 continuous-waypoint
auditor receives a view without the overlap samples only after the public
state, command overlap, elapsed time and physical continuity are verified.
"""
import base64
import math
import xml.etree.ElementTree as ET


def need(value,message):
    if not value:raise RuntimeError(message)


def distance(a,b):
    north=(a[0]-b[0])*111320
    east=(a[1]-b[1])*111320*math.cos(math.radians((a[0]+b[0])/2))
    return math.hypot(north,east)


def normalize(bus,navigation,entity):
    responses=[ET.fromstring(base64.b64decode(row['xmlBase64'])) for row in bus
               if row['type']=='afrl.cmasi.AutomationResponse']
    need(len(responses)==1,'Expected one original planning response')
    commands=responses[0].findall('MissionCommandList/MissionCommand')
    plan=next((cmd for cmd in commands if cmd.findtext('VehicleID')==entity),None)
    need(plan is not None,'Assigned entity has no plan')
    order={node.findtext('Number'):i for i,node in enumerate(plan.findall('WaypointList/Waypoint'))}
    need(order,'Empty original plan')
    segments={}
    for row in bus:
        if row['type']!='afrl.cmasi.MissionCommand':continue
        node=ET.fromstring(base64.b64decode(row['xmlBase64']))
        if node.findtext('VehicleID')==entity:
            key=node.findtext('CommandID')
            need(key not in segments,'Duplicate original segment')
            segments[key]={n.findtext('Number') for n in node.findall('WaypointList/Waypoint')}
    public=[]
    for row in bus:
        if row['type']!='afrl.cmasi.AirVehicleState':continue
        node=ET.fromstring(base64.b64decode(row['xmlBase64']))
        if node.findtext('ID')==entity:
            public.append((int(node.findtext('Time')),
                           node.findtext('CurrentCommand'),node.findtext('CurrentWaypoint')))
    accepted=[];previous=None;pending=None;episodes=[]
    for row in navigation:
        if row.get('entityId')!=entity or row.get('kind')!='navigation' or row.get('commandId') not in segments:
            accepted.append(row);continue
        current=row['waypoint'];command=row['commandId']
        need(current in order and command in segments,'Unknown internal waypoint or command')
        if previous is None:
            accepted.append(row);previous=row;continue
        previous_order=order[previous['waypoint']]
        current_order=order[current]
        if current_order<previous_order:
            if pending is None:
                need(command!=previous['commandId'],'Same-command waypoint regression')
                overlap=segments[previous['commandId']] & segments[command]
                need(previous['waypoint'] in overlap and current in overlap,'Rewind outside segment overlap')
                pending=dict(fromWaypoint=previous['waypoint'],oldCommand=previous['commandId'],
                             newCommand=command,begin=previous,dropped=[],overlap=overlap)
            need(command==pending['newCommand'] and current in pending['overlap'],
                 'Handoff changed during overlap replay')
            pending['dropped'].append(row)
            continue
        if pending is not None:
            need(command==pending['newCommand'] and current_order==previous_order,
                 'Handoff skipped prior waypoint')
            begin=pending['begin'];elapsed=float(row['simTimeSeconds'])-float(begin['simTimeSeconds'])
            need(0<elapsed<=1,'Overlap replay exceeded one second')
            points=[begin,*pending['dropped'],row]
            need(all(distance(a['position'],b['position'])<=10 and
                     abs(a['position'][2]-b['position'][2])<=1
                     for a,b in zip(points,points[1:])),
                 'Physical trajectory jumped during metadata replay')
            start_ms=round(float(begin['simTimeSeconds'])*1000)
            end_ms=round(float(row['simTimeSeconds'])*1000)
            shown=[(ms,cmd,wp) for ms,cmd,wp in public if start_ms<=ms<=end_ms]
            need(all(wp in order and order[wp]>=previous_order for _,_,wp in shown),
                 'Public state regressed during overlap replay')
            after=next(((ms,cmd,wp) for ms,cmd,wp in public if ms>=end_ms),None)
            need(after is not None and after[0]-end_ms<=1000 and after[2] in order and
                 order[after[2]]>=previous_order,'Next public state regressed after overlap replay')
            episodes.append(dict(oldCommand=pending['oldCommand'],newCommand=command,
                fromWaypoint=previous['waypoint'],droppedWaypoints=[x['waypoint'] for x in pending['dropped']],
                beginSimulationMs=str(start_ms),endSimulationMs=str(end_ms),
                elapsedSeconds=elapsed,publicStatesChecked=len(shown)+1,
                nextPublicState=dict(timeMs=str(after[0]),commandId=after[1],waypoint=after[2]),
                maximumStepMeters=max(distance(a['position'],b['position']) for a,b in zip(points,points[1:]))))
            pending=None
        accepted.append(row);previous=row
    need(pending is None,'Unresolved overlap replay')
    need(len(episodes)<=len(segments),'Excessive overlap replay')
    return accepted,episodes

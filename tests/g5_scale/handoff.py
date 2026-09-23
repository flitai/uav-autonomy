"""Classify only bounded, task-free segment receipt metadata in mixed20 flights.

The audit view omits an overlap receipt and, when it was actually published,
its one matching public state. Raw wire, native and browser records remain
intact, and each omitted public state is checked against those raw records.
"""
import base64
from collections import Counter
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def normalize(root,bus,wire,events,navigation,assignments):
    root=Path(root)
    original=module('scale_original_handoff',root/'tests/g5_full/handoff.py')
    geometry=module('scale_handoff_geometry',root/'scripts/g3_execution/correlator.py')
    need=original.need
    entities={row['entityId'] for row in assignments}
    evidence={entity:[] for entity in entities}
    public={entity:[] for entity in entities}
    commands={entity:{} for entity in entities}
    plans={entity:[] for entity in entities}
    for row in bus:
        kind=row['type']
        if kind not in ('afrl.cmasi.AutomationResponse','afrl.cmasi.MissionCommand',
                        'afrl.cmasi.AirVehicleState'):continue
        node=ET.fromstring(base64.b64decode(row['xmlBase64']))
        if kind=='afrl.cmasi.AutomationResponse':
            for command in node.findall('MissionCommandList/MissionCommand'):
                entity=command.findtext('VehicleID')
                if entity in entities:
                    evidence[entity].append(row);plans[entity].append(command)
        elif kind=='afrl.cmasi.MissionCommand':
            entity=node.findtext('VehicleID')
            if entity in entities:
                evidence[entity].append(row);commands[entity][node.findtext('CommandID')]=node
        else:
            entity=node.findtext('ID')
            if entity in entities:
                evidence[entity].append(row);public[entity].append((row,node))
    grouped={entity:[] for entity in entities}
    for row in navigation:
        if row.get('entityId') in entities:grouped[row['entityId']].append(row)
    proposed={}
    for entity in sorted(entities,key=int):
        need(len(plans[entity])==1,'Mixed handoff requires one plan per entity: '+entity)
        order={point.findtext('Number'):index for index,point in
               enumerate(plans[entity][0].findall('WaypointList/Waypoint'))}
        for before,receipt,after in zip(grouped[entity],grouped[entity][1:],grouped[entity][2:]):
            if not(before['sampleKind']==after['sampleKind']=='step' and
                   receipt['sampleKind']=='command-applied' and
                   before['commandId']!=receipt['commandId']==after['commandId'] and
                   before['waypoint']==after['waypoint'] and
                   before['waypoint'] in order and receipt['waypoint'] in order and
                   order[receipt['waypoint']]==order[before['waypoint']]-1):continue
            begin=round(float(before['simTimeSeconds'])*1000)
            end=round(float(after['simTimeSeconds'])*1000)
            if not 0<end-begin<=1000:continue
            matches=[(row,node) for row,node in public[entity]
                     if begin<=int(node.findtext('Time'))<=end and
                     node.findtext('CurrentCommand')==receipt['commandId'] and
                     node.findtext('CurrentWaypoint')==receipt['waypoint']]
            need(len(matches)<=1,'Repeated public overlap state: '+entity)
            if not matches:continue
            row,node=matches[0]
            old=commands[entity].get(before['commandId'])
            new=commands[entity].get(receipt['commandId'])
            need(old is not None and new is not None and
                 new.findtext('FirstWaypoint')==receipt['waypoint'],
                 'Unmatched public overlap command: '+entity)
            old_points={p.findtext('Number'):p for p in old.findall('WaypointList/Waypoint')}
            new_points={p.findtext('Number'):p for p in new.findall('WaypointList/Waypoint')}
            need(all(key in old_points and key in new_points for key in
                     (receipt['waypoint'],before['waypoint'])) and
                 not old.findall('VehicleActionList/*') and not new.findall('VehicleActionList/*') and
                 not node.findall('AssociatedTasks/int64') and
                 not new_points[receipt['waypoint']].findall('AssociatedTasks/int64') and
                 not new_points[receipt['waypoint']].findall('VehicleActionList/*'),
                 'Public overlap entered task or action: '+entity)
            location=node.find('Location/Location3D')
            position=[float(location.findtext(name)) for name in ('Latitude','Longitude','Altitude')]
            need(all(original.distance(position,step['position'])<=10 and
                     abs(position[2]-step['position'][2])<=1 for step in (before,after)),
                 'Public overlap moved away from actual trajectory: '+entity)
            need(row['sourceEntity']==row['sourceService']=='0' and
                 row['rawSHA256'] not in proposed,'Public overlap authority or duplicate: '+entity)
            proposed[row['rawSHA256']]=dict(entityId=entity,timeMs=node.findtext('Time'),
                oldCommand=before['commandId'],newCommand=receipt['commandId'],
                oldWaypoint=before['waypoint'],receiptWaypoint=receipt['waypoint'],
                rawSHA256=row['rawSHA256'],boundedMilliseconds=end-begin,
                classification='one-public-task-free-command-receipt-state')
    wire_hashes=Counter(row['rawSHA256'] for row in wire if row['type']=='afrl.cmasi.AirVehicleState')
    need(all(wire_hashes[identity]==1 for identity in proposed),
         'Public overlap missing or duplicated on AMASE wire')
    targets={(row['entityId'],row['timeMs']) for row in proposed.values()}
    native={};native_count=Counter()
    for event in events:
        if event.get('kind')!='message' or event.get('type')!='afrl.cmasi.AirVehicleState':continue
        node=ET.fromstring(base64.b64decode(event['xmlBase64']))
        key=node.findtext('ID'),node.findtext('Time')
        if key in targets:native[key]=node;native_count[key]+=1
    for entity in entities:
        for row,node in public[entity]:
            if row['rawSHA256'] in proposed:
                key=entity,node.findtext('Time')
                need(native_count[key]==1 and geometry.equivalent(node,native[key]),
                     'Public overlap differs from native state: '+entity)
    cleaned_bus=[row for row in bus if row.get('rawSHA256') not in proposed]
    episodes={}
    for entity in sorted(entities,key=int):
        subset=[row for row in evidence[entity] if row.get('rawSHA256') not in proposed]
        navigation,episodes[entity]=original.normalize(subset,navigation,entity)
    for receipt in proposed.values():
        entity=receipt['entityId'];time=int(receipt['timeMs'])
        matching=[episode for episode in episodes[entity]
                  if int(episode['beginSimulationMs'])<=time<=int(episode['endSimulationMs']) and
                  episode['oldCommand']==receipt['oldCommand'] and
                  episode['newCommand']==receipt['newCommand']]
        need(len(matching)==1,'Public overlap lacks independently verified native episode: '+entity)
        matching[0].setdefault('publicReceiptStates',[]).append(receipt)
    return cleaned_bus,navigation,episodes

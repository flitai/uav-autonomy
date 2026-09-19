"""Replay the actual receipt transient and reject material navigation changes."""
from copy import deepcopy
import base64
import hashlib
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
from sim_bridge.codec import load_schema


def verify(root, output, classify, completion, policy):
    source = root / 'out/runs/g4-t05-test-20260920-002852-273/headless'
    prior=json.loads((source/'case-result.json').read_text())
    assert prior['status']=='failed' and prior['error']=='internal-waypoint-regression-or-skip'
    recorded={item['path']:item['sha256'].lower() for item in prior['evidence']}
    evidence_paths=[source/'observer.jsonl',source/'amase.jsonl',source/'amase/events.jsonl',
                    *sorted((source/'amase').glob('execution-*.jsonl'))]
    for path in evidence_paths:
        assert hashlib.sha256(path.read_bytes()).hexdigest()==recorded[path.relative_to(source).as_posix()]
    bus = [json.loads(line) for line in (source/'observer.jsonl').read_text().splitlines()]
    navigation = [json.loads(line) for path in sorted((source/'amase').glob('execution-*.jsonl'))
                  for line in path.read_text().splitlines()]
    view, receipts = classify(navigation, bus)
    assert len(receipts) == 1 and receipts[0]['receipt']['sequence'] == '445'
    assert len(view) == len(navigation) - 1
    checks = ['actual-receipt-only-overlap-classified']
    receipt_index = next(i for i, row in enumerate(navigation) if row['entityId']=='400' and row['sequence']=='445')
    for name, mutation in [('actual-step-regression', lambda n: n[receipt_index+1].update(waypoint='12')),
                           ('task-target-skipped', lambda n: n[receipt_index+1].update(waypoint='14')),
                           ('missing-intermediate-evidence', lambda n: n[receipt_index+1].update(sequence='447')),
                           ('reversed-receipt-time', lambda n: n[receipt_index].update(simTimeSeconds='0')),
                           ('same-command-regression', lambda n: n[receipt_index].update(commandId='67'))]:
        altered = deepcopy(navigation); mutation(altered)
        assert classify(altered,bus)[1] == [], name
        checks.append(name+'-not-exempted')
    for name, field in [('task-reentry','AssociatedTasks'),('action-reentry','VehicleActionList')]:
        altered = deepcopy(bus)
        for row in altered:
            if row['type']!='afrl.cmasi.MissionCommand': continue
            node=ET.fromstring(base64.b64decode(row['xmlBase64']))
            if node.findtext('VehicleID')=='400' and node.findtext('CommandID') in ('67','68'):
                for point in node.findall('WaypointList/Waypoint'):
                    if point.findtext('Number')=='12': ET.SubElement(point.find(field),'fixture').text='1000'
                row['xmlBase64']=base64.b64encode(ET.tostring(node)).decode()
        assert classify(navigation,altered)[1] == [], name
        checks.append(name+'-not-exempted')
    altered=deepcopy(bus)
    row=deepcopy(next(r for r in bus if r['type']=='afrl.cmasi.AirVehicleState'))
    node=ET.fromstring(base64.b64decode(row['xmlBase64']))
    for key,value in [('ID','400'),('CurrentCommand','68'),('CurrentWaypoint','12')]: node.find(key).text=value
    row['xmlBase64']=base64.b64encode(ET.tostring(node)).decode(); altered.append(row)
    assert classify(navigation,altered)[1] == []
    checks.append('wire-state-regression-not-exempted')
    # The old failed result is never edited; this is a new, explicitly identified
    # offline re-evaluation of its complete raw record under the G4 distinction.
    monitor=[json.loads(line) for line in (source/'amase.jsonl').read_text().splitlines()]
    event_files=list((source/'amase').glob('*events*.jsonl'))
    assert len(event_files)==1, event_files
    events=[json.loads(line) for line in event_files[0].read_text().splitlines()]
    configuration=json.loads((root/'config/g3-startup.json').read_text(encoding='utf-8-sig'))
    factory=load_schema(root).factory
    with minidom.parse(str(root/configuration['request'])) as document:
        node=document.documentElement
        original=factory.createObjectByName(node.getAttribute('Series'),node.localName)
        original.unpackFromXMLNode(node,factory)
    request=ET.fromstring(original.toXMLStr(''))
    proof=completion.assess(bus,monitor,events,policy,request,view)
    result={'status':'passed','checks':checks,'sourceRun':'g4-t05-test-20260920-002852-273/headless',
            'receiptOnlyTransitions':receipts,'offlineCompletion':proof['completion'],'oldResultPreserved':True,
            'sourceHashes':{path.relative_to(source).as_posix():recorded[path.relative_to(source).as_posix()] for path in evidence_paths}}
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

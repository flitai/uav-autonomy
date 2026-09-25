"""Exploratory B04 single point execution probe; writes only to its owned live session."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
import xml.dom.minidom
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'out/generated/lmcp/py'))
sys.path.insert(0, str(ROOT / 'scripts/g3_integration'))
import runtime
from lmcp import LMCPFactory


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def http(port, method, path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Origin':'http://127.0.0.1:8080'}
    if data is not None:
        headers['Content-Type']='application/json'
    with urlopen(Request(f'http://127.0.0.1:{port}{path}', data=data,
                         headers=headers, method=method), timeout=70) as response:
        return json.load(response)


def object_from(path, tag=None):
    document = xml.dom.minidom.parse(str(path))
    node = document.documentElement
    if tag:
        node = document.getElementsByTagName(tag)[0]
    obj = LMCPFactory.LMCPFactory().createObjectByName(node.getAttribute('Series'),node.localName)
    assert obj is not None, node.localName
    obj.unpackFromXMLNode(node, LMCPFactory.LMCPFactory())
    return obj


def rows(path):
    if not path.exists():
        return []
    result=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        try: result.append(json.loads(line))
        except json.JSONDecodeError: pass
    return result


def wait(label, predicate, seconds=30):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=predicate()
        if result:
            print(label,repr(result)[:300],flush=True)
            return result
        time.sleep(.15)
    raise TimeoutError(label)


def send(sock,obj,output,label):
    raw=LMCPFactory.packMessage(obj,True)
    packet=runtime.wire.frame(raw,obj.FULL_LMCP_TYPE_NAME,
                              source='900',service='1',group='G6ConfirmedPlan')
    (output/(label+'.bin')).write_bytes(packet)
    sock.sendall(packet)
    print(label,obj.FULL_LMCP_TYPE_NAME,hashlib.sha256(raw).hexdigest(),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--kind',choices=('point','line'),default='point')
    args=parser.parse_args()
    session=args.session.resolve(); output=args.output.resolve();output.mkdir(exist_ok=False)
    identity=http(8003,'GET','/api/tasks/v1/catalog')['identity']
    entity_id,task_id=('500','3001') if args.kind=='point' else ('400','3000')
    sample=load(ROOT/('out/runs/g6-b01-baseline-20260924-2223/samples/'+args.kind+'-draft.json'))
    geometry=sample['geometry'] if args.kind=='point' else dict(type='LineString',
        coordinates=[[-120.9923,45.3171],[-120.9800,45.3171]])
    created=http(8003,'POST','/api/tasks/v1/drafts',dict(identity,idempotencyKey='g6-b04-probe-create',
        kind=args.kind,geometry=geometry,candidateEntityIds=[entity_id],altitudeDatum='EPSG:5773'))
    draft=created['draft']['draft']; print('draft',draft['draftId'],flush=True)
    planned=http(8003,'POST',f"/api/tasks/v1/drafts/{draft['draftId']}/preview",
                 dict(identity,idempotencyKey='g6-b04-probe-preview',expectedRevision='1'))
    plan=planned['draft']['preview'];print('plan',plan['planId'],plan['route']['waypointCount'],flush=True)
    op=load(session.parent/'task-previews/g6-b04-probe-preview.json')
    planner=ROOT/'out/runs'/(op['previewRunId']+'-planner')
    candidate=planner/'candidate-task.xml';response=planner/('plan-'+plan['taskId']+'.xml')
    assert hashlib.sha256(candidate.read_bytes()).hexdigest()==plan['candidateTaskSHA256']
    assert hashlib.sha256(response.read_bytes()).hexdigest()==plan['responseXmlSHA256']
    task=object_from(candidate);original=object_from(response,'AutomationResponse')
    control=http(8001,'GET','/api/control/v1/state')
    started=http(8001,'POST','/api/control/v1/operations',dict(runId=identity['runId'],
        segmentId=identity['segmentId'],expectedSequence=control['controlSequence'],
        idempotencyKey='g6-b04-probe-start',action='start',multiple=None))
    print('started',started['status'],flush=True)
    observer=session.parent/'observer.jsonl'
    wait('initial-state',lambda:next((r for r in rows(observer) if r['type']=='afrl.cmasi.AirVehicleState'
                                      and r.get('id')==entity_id),None),35)
    sock=socket.create_connection(('127.0.0.1',9999),timeout=3)
    send(sock,task,output,'candidate-task')
    wait('task-initialized',lambda:next((r for r in rows(observer) if
         r['type']=='uxas.messages.task.TaskInitialized' and r.get('taskId')==task_id),None),30)
    previous={r['rawSHA256'] for r in rows(observer) if
              r['type']=='afrl.cmasi.MissionCommand' and r.get('sourceEntity')=='100'}
    send(sock,original,output,'confirmed-response')
    sock.close()
    command=wait('mission-command',lambda:next((r for r in rows(observer) if
         r['type']=='afrl.cmasi.MissionCommand' and r.get('vehicleId')==entity_id and
         r.get('sourceEntity')=='100' and r['rawSHA256'] not in previous),None),25)
    print('command',command.get('commandId'),flush=True)
    state=http(8001,'GET','/api/control/v1/state')
    rate=http(8001,'POST','/api/control/v1/operations',dict(runId=identity['runId'],
        segmentId=identity['segmentId'],expectedSequence=state['controlSequence'],
        idempotencyKey='g6-b04-probe-rate',action='rate',multiple='10'))
    print('rate',rate['status'],flush=True)
    completed=wait('task-complete',lambda:next((r for r in rows(observer) if
         r['type']=='uxas.messages.task.TaskComplete' and r.get('taskId')==task_id),None),210)
    print('completed',completed.get('taskId'),flush=True)


if __name__=='__main__':
    main()

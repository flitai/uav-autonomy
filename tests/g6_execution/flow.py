"""Real B04 HTTP confirmation, command, completion and rejection probe."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g6_execution'))
import core


def http(port,method,path,body=None,timeout=75):
    payload=json.dumps(body).encode('utf-8') if body is not None else None
    headers={'Origin':'http://127.0.0.1:8080'}
    if payload is not None:headers['Content-Type']='application/json'
    try:
        with urlopen(Request(f'http://127.0.0.1:{port}{path}',data=payload,
                             headers=headers,method=method),timeout=timeout) as response:
            return response.status,json.load(response)
    except HTTPError as error:
        return error.code,json.load(error)


def need(value,message):
    if not value:raise RuntimeError(message)


def wait(label,predicate,seconds=200):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.2)
    raise TimeoutError(label)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    session=args.session.resolve();output=args.output.resolve();output.mkdir(exist_ok=False)
    result=dict(task='G6-B04',status='running',steps=[])
    try:
        code,catalog=http(8003,'GET','/api/tasks/v1/catalog')
        need(code==200,'Draft catalog unavailable')
        identity=catalog['identity']
        geometry=dict(type='LineString',coordinates=[[-120.9923,45.3171],[-120.9800,45.3171]])
        code,saved=http(8003,'POST','/api/tasks/v1/drafts',dict(identity,
            idempotencyKey='g6-b04-http-create',kind='line',geometry=geometry,
            candidateEntityIds=['400'],altitudeDatum=catalog['altitudeDatum']))
        need(code==201,'Line draft save failed')
        draft=saved['draft']['draft'];result['steps'].append(dict(action='save',draftId=draft['draftId']))
        code,preview=http(8003,'POST',f"/api/tasks/v1/drafts/{draft['draftId']}/preview",
            dict(identity,idempotencyKey='g6-b04-http-preview',expectedRevision='1'))
        need(code==200,'B02 preview failed')
        plan=preview['draft']['preview'];plan_id=plan['planId']
        result['steps'].append(dict(action='preview',planId=plan_id,
                                    waypoints=plan['route']['waypointCount']))
        code,review=http(8004,'GET',f'/api/tasks/v1/plans/{plan_id}/review')
        need(code==200 and review['reviewSHA256'] and len(review['waypoints'])==
             plan['route']['waypointCount'],'Complete plan review failed')
        result['steps'].append(dict(action='review',digest=review['reviewSHA256'],
                                    actions=len(review['actions'])))
        wrong=dict(identity,draftId=draft['draftId'],expectedRevision='1',
                   reviewSHA256='0'*64,idempotencyKey='g6-b04-wrong-digest',acknowledged=True)
        need(http(8004,'POST',f'/api/tasks/v1/plans/{plan_id}/confirm',wrong)[0]==409,
             'Wrong review digest accepted')
        body=dict(wrong,reviewSHA256=review['reviewSHA256'],idempotencyKey='g6-b04-http-confirm')
        code,confirmed=http(8004,'POST',f'/api/tasks/v1/plans/{plan_id}/confirm',body)
        need(code==200 and confirmed['status']=='confirmed' and
             confirmed['planBytesSHA256']==review['planBytesSHA256'] and
             confirmed['missionCommandSHA256'],'Same-plan confirmation failed: '+str(confirmed))
        result['steps'].append(dict(action='confirm',receipt=confirmed))
        repeated_code,repeated=http(8004,'POST',f'/api/tasks/v1/plans/{plan_id}/confirm',body)
        need(repeated_code==200 and repeated['fingerprint']==confirmed['fingerprint'] and
             repeated['missionCommandSHA256']==confirmed['missionCommandSHA256'],
             'Repeated confirmation changed the command')
        another=dict(body,idempotencyKey='g6-b04-another-confirm')
        need(http(8004,'POST',f'/api/tasks/v1/plans/{plan_id}/confirm',another)[0]==409,
             'Second confirmation key accepted')
        need(http(8004,'GET',f'/api/tasks/v1/plans/{plan_id}/review')[0] in (409,503),
             'Started plan remained previewable')
        state=http(8001,'GET','/api/control/v1/state')[1]
        rate=http(8001,'POST','/api/control/v1/operations',dict(runId=identity['runId'],
            segmentId=identity['segmentId'],expectedSequence=state['controlSequence'],
            idempotencyKey='g6-b04-http-rate',action='rate',multiple='10'))
        need(rate[0] in (200,202) and rate[1]['status'] in ('applied','confirmed'),
             'Qualified simulation rate failed')
        result['steps'].append(dict(action='rate',status=rate[1]['status']))
        completed=wait('TaskComplete',lambda:next((r for r in core.observer_rows(session) if
            r['type']=='uxas.messages.task.TaskComplete' and r.get('taskId')=='3000'),None),220)
        result['steps'].append(dict(action='complete',rawSHA256=completed['rawSHA256']))
        code,receipt=http(8004,'GET',f"/api/tasks/v1/confirmations/{body['idempotencyKey']}")
        need(code==200 and receipt['status']=='completed' and
             receipt['taskCompleteSHA256']==completed['rawSHA256'],
             'Execution status did not reach completed')
        result.update(status='passed',receipt=receipt)
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(result['traceback'],file=sys.stderr)
    finally:
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    sys.exit(main())

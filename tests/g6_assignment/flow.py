"""Two-mode B05 API flow and independent mission/task evidence audit."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core


def need(value, message):
    if not value:
        raise RuntimeError(message)


def http(port, method, path, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    headers = {'Origin': 'http://127.0.0.1:8080'}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with urlopen(Request(f'http://127.0.0.1:{port}{path}', data=payload,
                             headers=headers, method=method), timeout=100) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait(label, predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.25)
    raise TimeoutError(label)


def xml(row):
    return ET.fromstring(base64.b64decode(row['xmlBase64']))


def distance(a, b):
    latitude_a, latitude_b = map(math.radians, (a[1], b[1]))
    dlat = latitude_b-latitude_a
    dlon = math.radians(b[0]-a[0])
    arc = math.sin(dlat/2)**2+math.cos(latitude_a)*math.cos(latitude_b)*math.sin(dlon/2)**2
    return 2*6371000*math.asin(min(1, math.sqrt(arc)))


def audit(session, review, receipt, mode):
    rows = core.observer_rows(session)
    assignments = {x['taskId']: x for x in review['plan']['assignments']}
    completion = {}
    for task_id, assigned in assignments.items():
        active = [r for r in rows if r['type'] == 'uxas.messages.task.TaskActive'
                  and r.get('taskId') == task_id]
        complete = [r for r in rows if r['type'] == 'uxas.messages.task.TaskComplete'
                    and r.get('taskId') == task_id]
        need(len(active) == len(complete) == 1, 'Task lifecycle missing or duplicated: '+task_id)
        active_xml, complete_xml = xml(active[0]), xml(complete[0])
        vehicle = assigned['vehicleId']
        need(active_xml.findtext('EntityID') == vehicle and
             vehicle in [x.text for x in complete_xml.findall('EntitiesInvolved/int64')] and
             rows.index(active[0]) < rows.index(complete[0]),
             'Task lifecycle vehicle or order differs: '+task_id)
        activated = int(active_xml.findtext('TimeTaskActivated'))
        completed = int(complete_xml.findtext('TimeTaskCompleted'))
        need(completed > activated, 'Task completion time invalid')
        completion[task_id] = dict(vehicleId=vehicle, activatedMs=activated,
            completedMs=completed, durationMs=completed-activated,
            activeSHA256=active[0]['rawSHA256'], completeSHA256=complete[0]['rawSHA256'])
    if mode == 'sequence':
        times = [completion[task_id]['completedMs'] for task_id in review['taskOrder']]
        need(times == sorted(times) and len(set(times)) == len(times),
             'Actual completion order violates sequence relationship')
    commanded = []
    amase = [json.loads(x) for x in (session.parent / 'amase.jsonl').open(encoding='utf-8')]
    received = {x['rawSHA256'] for x in amase if x['type'] == 'afrl.cmasi.MissionCommand'}
    for planned in review['plan']['commands']:
        vehicle = planned['vehicleId']
        expected = {p['number']: p for p in planned['waypoints']}
        actual = [r for r in rows if r['type'] == 'afrl.cmasi.MissionCommand' and
                  r.get('vehicleId') == vehicle and r.get('sourceEntity') == '100']
        covered = set()
        same = []
        for event in actual:
            points = xml(event).findall('WaypointList/Waypoint')
            if len(points) < 2 or any(p.findtext('Number') not in expected for p in points):
                continue
            for point in points:
                target = expected[point.findtext('Number')]
                need(abs(float(point.findtext('Longitude'))-target['longitude']) < 1e-7 and
                     abs(float(point.findtext('Latitude'))-target['latitude']) < 1e-7,
                     'Actual route coordinate differs from reviewed route')
                covered.add(point.findtext('Number'))
            same.append(event)
        need(covered == set(expected) and same and
             all(event['rawSHA256'] in received for event in same),
             'AMASE did not receive every reviewed waypoint')
        states = [r for r in rows if r['type'] == 'afrl.cmasi.AirVehicleState'
                  and r.get('id') == vehicle]
        need(len(states) > 10, 'Vehicle state history missing')
        task_end = max(completion[t]['completedMs'] for t in planned['taskIds'])
        path = [(r['longitude'],r['latitude']) for r in states if int(r['timeMs']) <= task_end]
        observed = sum(distance(a,b) for a,b in zip(path,path[1:]))
        need(observed > 100, 'Assigned vehicle did not fly a meaningful route')
        commanded.append(dict(vehicleId=vehicle, waypoints=len(expected),
            commandIds=[event['commandId'] for event in same],
            commandSHA256=[event['rawSHA256'] for event in same],
            observedFlightMetersThroughCompletion=round(observed,2)))
    need(receipt['status'] == 'completed' and
         {x['taskId'] for x in receipt['tasks']} == set(assignments),
         'Confirmation receipt did not complete every task')
    return dict(tasks=completion, commands=commanded,
                statisticsScope='TaskActive/TaskComplete duration and observed AMASE flight distance')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--mode', choices=('parallel','sequence'), required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'Flow run ID exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B05', runId=args.run_id, mode=args.mode, status='running')
    try:
        session = args.session.resolve()
        code, state = http(8005, 'GET', '/api/tasks/v2/state')
        need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
             'B05 state identity differs')
        identity = state['identity']
        scene = ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples'
        geometry = {
            'line': dict(type='LineString', coordinates=[[-120.9923,45.3171],[-120.98,45.3171]]),
            'point': dict(type='Point', coordinates=[-120.7645,45.323] if args.mode == 'parallel'
                          else [-120.977,45.323]),
            'area': dict(type='Rectangle', center=[-120.979,45.323] if args.mode == 'parallel'
                         else [-120.974,45.325], widthMeters=500,heightMeters=300,
                         rotationDegrees=0)}
        drafts = {}
        for kind in ('line','point','area'):
            sample = core.release.load(scene / (kind + '-draft.json'))
            body = dict(identity, idempotencyKey='g6-b05-create-' + kind + '-' + args.mode,
                kind=kind, geometry=geometry[kind],
                candidateEntityIds=sample['candidateEntityIds'],altitudeDatum='EPSG:5773')
            code, created = http(8003, 'POST', '/api/tasks/v1/drafts', body)
            need(code in (200, 201) and created['status'] == 'confirmed',
                 'Draft create failed: '+str(created))
            drafts[kind] = created['draft']['draft']
        selections = []
        for kind in ('line','point','area'):
            draft = drafts[kind]
            eligible = ['400'] if args.mode == 'sequence' or kind == 'area' else \
                ['400','500','600']
            selections.append(dict(draftId=draft['draftId'],revision=draft['revision'],
                                   candidateEntityIds=eligible))
        body = dict(identity,idempotencyKey='g6-b05-plan-'+args.mode,
                    tasks=selections, taskOrder=['3000','3001','3002'],relationship=args.mode)
        bad = json.loads(json.dumps(body))
        bad['idempotencyKey'] += '-invalid'
        bad['tasks'][2]['candidateEntityIds'] = ['400','500']
        code, rejected = http(8005, 'POST', '/api/tasks/v2/plans', bad)
        need(code == 409, 'Unqualified area candidate was accepted')
        code, planned = http(8005, 'POST', '/api/tasks/v2/plans', body)
        need(code == 200 and planned['status'] == 'previewed',
             'Multi-task plan failed: '+str(planned))
        review = planned['review']
        record['review'] = review
        need(review['confirmationAllowed'] and
             {x['taskId'] for x in review['plan']['assignments']} ==
             {'3000','3001','3002'}, 'Review lacks complete qualified assignment')
        if args.mode == 'parallel':
            need(any(len(x['candidateEntityIds']) >= 2 for x in review['tasks']) and
                 len({x['vehicleId'] for x in review['plan']['assignments']}) >= 2,
                 'Parallel plan did not exercise competitive multi-vehicle assignment')
        else:
            need({x['vehicleId'] for x in review['plan']['assignments']} == {'400'},
                 'Sequence plan assigned another vehicle')
        confirm = dict(identity,reviewSHA256='0'*64,
                       idempotencyKey='g6-b05-wrong-'+args.mode,acknowledged=True)
        code, _ = http(8005,'POST',f"/api/tasks/v2/plans/{review['planId']}/confirm",confirm)
        need(code == 409, 'Wrong review digest was accepted')
        confirm['reviewSHA256'] = review['reviewSHA256']
        confirm['idempotencyKey'] = 'g6-b05-confirm-'+args.mode
        code, receipt = http(8005,'POST',f"/api/tasks/v2/plans/{review['planId']}/confirm",confirm)
        need(code == 200 and receipt['status'] == 'confirmed',
             'Multi-task confirmation failed: '+str(receipt))
        control = http(8001,'GET','/api/control/v1/state')[1]
        code, rate = http(8001,'POST','/api/control/v1/operations',dict(
            runId=identity['runId'],segmentId=identity['segmentId'],
            expectedSequence=control['controlSequence'],
            idempotencyKey='g6-b05-rate-'+args.mode,action='rate',multiple='10'))
        need(code in (200, 202) and rate['status'] in ('applied','confirmed','pending'),
             'Simulation rate operation failed')
        def completed():
            code, value = http(8005, 'GET',
                               '/api/tasks/v2/confirmations/' + confirm['idempotencyKey'])
            need(code == 200, 'Confirmation operation became unavailable')
            return value if value['status'] == 'completed' else None
        receipt = wait('three task completions', completed, 300)
        record.update(status='passed',receipt=receipt,
                      audit=audit(session,review,receipt,args.mode),
                      wrongCandidateRejected=True,wrongDigestRejected=True)
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(record['traceback'],file=sys.stderr)
        return 1
    finally:
        core.release.save(run / 'result.json',record)


if __name__ == '__main__':
    sys.exit(main())

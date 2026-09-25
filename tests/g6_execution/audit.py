"""Independent B04 two-mode route, AMASE receipt, flight and lifecycle audit."""
import argparse
import base64
import json
import math
from pathlib import Path
import sys
import traceback
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g6_execution'))
import core

def need(value,message):
    if not value:raise RuntimeError(message)

def xml(row):return ET.fromstring(base64.b64decode(row['xmlBase64']))

def distance(a,b):
    latitude=math.radians((a[1]+b[1])/2)
    x=math.radians(b[0]-a[0])*math.cos(latitude)
    y=math.radians(b[1]-a[1])
    return math.hypot(x,y)*6371000

def audit(session_id,evidence_file):
    run=ROOT/'out/runs'/session_id
    folder=run/'segment-001';session=folder/'control-session.json'
    runtime=core.release.load(run/'runtime-result.json')
    case=core.release.load(folder/'case-result.json')
    evidence=core.release.load(evidence_file)
    need(runtime['status']==case['status']==evidence['status']=='passed' and
         runtime['normalExit'] and case['normalExit'] and case['portsReleased'],
         'Case, browser/API flow or group exit failed')
    build=ROOT/'out/runs/g6-b04-build-20260925-0023/result.json'
    need(runtime['b04ViewerBuildRunId']=='g6-b04-build-20260925-0023' and
         runtime['b04ViewerBuildSHA256']==core.release.digest(build),
         'Session used a different B04 viewer build')
    operations=list((folder/'task-execution').glob('*.json'))
    need(len(operations)==1,'Exactly one confirmation operation required')
    receipt=core.release.load(operations[0])
    plan_id=receipt['planId'];review,task,assignment_request,assignment_response,plan=core.resolve(session,plan_id,False)
    need(receipt['planBytesSHA256']==core.digest(plan) and
         receipt['taskBytesSHA256']==core.digest(task) and
         receipt['assignmentRequestSHA256']==core.digest(assignment_request) and
         receipt['assignmentResponseSHA256']==core.digest(assignment_response),
         'Confirmed inputs differ from qualified preview')
    packet=core.isolated_preview.startup.wire.frame(plan,'afrl.cmasi.AutomationResponse',
        source='900',service='1',group='G6ConfirmedPlan')
    need((folder/'task-execution'/(receipt['key']+'-plan.bin')).read_bytes()==packet,
         'Actual TCP plan packet differs from reviewed plan')
    rows=core.observer_rows(session)
    sent=next((i for i,row in enumerate(rows) if row.get('rawSHA256')==
               receipt['missionCommandSHA256']),None)
    need(sent is not None,'First confirmed command was not observed')
    commands=[row for row in rows[sent:] if row['type']=='afrl.cmasi.MissionCommand' and
              row.get('vehicleId')==receipt['vehicleId'] and row.get('sourceEntity')=='100']
    need(len(commands)>=2,'Task-linked continued command missing')
    expected={point['number']:point for point in review['waypoints']}
    numbers=set();linked=set()
    for command in commands:
        root=xml(command)
        for point in root.findall('WaypointList/Waypoint'):
            number=point.findtext('Number');target=expected.get(number)
            need(target is not None,'Executed command has extra waypoint')
            for tag,name,tolerance in (('Longitude','longitude',1e-7),
                                       ('Latitude','latitude',1e-7),
                                       ('Altitude','altitudeMeters',1e-6)):
                need(abs(float(point.findtext(tag))-target[name])<=tolerance,
                     'Executed waypoint differs from reviewed plan')
            numbers.add(number)
        linked.update(node.text for node in root.findall('.//AssociatedTasks/int64'))
    need(numbers==set(expected) and linked=={receipt['taskId']},
         'Continued command did not cover the full task route')
    amase=[json.loads(line) for line in (folder/'amase.jsonl').open(encoding='utf-8')]
    received={row['rawSHA256'] for row in amase if row['type']=='afrl.cmasi.MissionCommand'}
    need(all(command['rawSHA256'] in received for command in commands),
         'AMASE did not receive all UxAS plan commands')
    active=[row for row in rows if row['type']=='uxas.messages.task.TaskActive' and
            row.get('taskId')==receipt['taskId']]
    complete=[row for row in rows if row['type']=='uxas.messages.task.TaskComplete' and
              row.get('taskId')==receipt['taskId']]
    need(len(active)==len(complete)==1 and rows.index(active[0])<rows.index(complete[0]),
         'Task lifecycle is incomplete or duplicated')
    active_time=int(xml(active[0]).findtext('TimeTaskActivated'))
    complete_xml=xml(complete[0]);complete_time=int(complete_xml.findtext('TimeTaskCompleted'))
    need(xml(active[0]).findtext('EntityID')==receipt['vehicleId'] and
         receipt['vehicleId'] in [node.text for node in complete_xml.findall('EntitiesInvolved/int64')] and
         complete_time>active_time,'Task lifecycle entity or time differs')
    states=[row for row in rows if row['type']=='afrl.cmasi.AirVehicleState' and
            row.get('id')==receipt['vehicleId']]
    need(len(states)>10 and states[0]['timeMs']=='0','AMASE flight state is missing')
    selected=[row for row in states if int(row['timeMs'])<=complete_time]
    track=sum(distance((a['longitude'],a['latitude']),(b['longitude'],b['latitude']))
              for a,b in zip(selected,selected[1:]))
    planned=sum(distance((a['longitude'],a['latitude']),(b['longitude'],b['latitude']))
                for a,b in zip(review['waypoints'],review['waypoints'][1:]))
    current=max(int(xml(row).findtext('CurrentWaypoint')) for row in states)
    need(track>100 and current>=int(review['waypoints'][-1]['number']),
         'Vehicle did not actually traverse the task route')
    need(receipt['status'] in ('confirmed','completed') and
         receipt['controlReceipt']['status']=='confirmed' and
         receipt['initialStateSHA256']==states[0]['rawSHA256'],
         'Confirmation or initial state binding differs')
    return dict(sessionRunId=session_id,mode=case['mode'],planId=plan_id,
        taskId=receipt['taskId'],vehicleId=receipt['vehicleId'],
        planSHA256=receipt['planBytesSHA256'],commandIds=[row['commandId'] for row in commands],
        commandSHA256=[row['rawSHA256'] for row in commands],
        waypointsReviewed=len(expected),waypointsCommanded=len(numbers),
        taskActiveSHA256=active[0]['rawSHA256'],taskCompleteSHA256=complete[0]['rawSHA256'],
        taskDurationMs=complete_time-active_time,
        plannedRouteMeters=round(planned,2),observedFlightMetersThroughCompletion=round(track,2),
        maxCurrentWaypoint=current,normalExit=True,portsReleased=True,
        evidenceSHA256=core.release.digest(evidence_file))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
    parser.add_argument('--headless-session',default='g6-b04-session-20260925-0024')
    parser.add_argument('--headless-evidence',default='g6-b04-flow-20260925-0024')
    parser.add_argument('--gui-session',default='g6-b04-session-20260925-0025')
    parser.add_argument('--gui-evidence',default='g6-b04-browser-20260925-0025')
    args=parser.parse_args();run=ROOT/'out/runs'/args.run_id
    run.mkdir(parents=True,exist_ok=False)
    result=dict(task='G6-B04',runId=args.run_id,status='running',executionQualified=False)
    try:
        build=ROOT/'out/runs/g6-b04-build-20260925-0023/result.json'
        candidate=core.release.load(build)
        need(candidate['status']=='passed' and candidate['task']=='G6-B04',
             'B04 viewer build failed')
        need(all(core.release.digest(ROOT/row['path']).lower()==row['sha256'].lower()
                 for row in candidate['inputs']),'B04 built source changed')
        headless=audit(args.headless_session,
                       ROOT/'out/runs'/args.headless_evidence/'result.json')
        gui=audit(args.gui_session,
                  ROOT/'out/runs'/args.gui_evidence/'result.json')
        need(headless['planSHA256']==gui['planSHA256'] and
             headless['waypointsReviewed']==gui['waypointsReviewed'],
             'Two-mode reviewed plan differs')
        pointers={name:core.release.digest(ROOT/'out/artifacts'/name/'current.json')
                  for name in ('g5-stage','g6-control','uxas','gis-gateway')}
        result.update(status='passed',executionQualified=True,cases=[headless,gui],
                      b04ViewerBuildRunId=candidate['runId'],
                      b04ViewerBuildSHA256=core.release.digest(build),
                      sourceInputs=candidate['inputs'],formalPointerSHA256=pointers,
                      statisticsScope='TaskActive/TaskComplete time and observed AMASE flight distance; no coverage percentage')
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc())
        print(result['traceback'],file=sys.stderr)
    finally:core.release.save(run/'acceptance.json',result)
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())

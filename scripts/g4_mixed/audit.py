"""Independent qualification of completed mixed-flight capture evidence."""
import argparse
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import traceback
from urllib.parse import unquote,urlparse
from xml.dom import minidom
import xml.etree.ElementTree as ET


def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def rows(path): return [json.loads(line) for line in path.read_text().splitlines()]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def need(condition,message):
    if not condition: raise ValueError(message)
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def case_audit(root,directory,output,execution,coverage):
    receipt=load(directory/'case-result.json')
    need(receipt['status']=='passed' and receipt['normalExit'] and receipt['portsReleased']
         and receipt['realCompletionCaptured'],'Incomplete real capture')
    need(len(receipt['gatewayInstances'])==3 and all(row['status']=='passed' and row['sent_business_frames']==0
         for row in receipt['gatewayInstances']),'Gateway restart or read-only evidence failed')
    for row in receipt['evidence']: need(sha(directory/row['path'])==row['sha256'].lower(),'Evidence changed: '+row['path'])
    bus,wire,events=rows(directory/'observer.jsonl'),rows(directory/'amase.jsonl'),rows(directory/'amase/events.jsonl')
    parent=load(directory.parent/'result.json')
    initialized=[e for e in events if e['kind']=='initialized-paused']
    need(len(initialized)==1,'Native initialization is not unique')
    expected_amase=root/'out/build/amase'/parent['amaseBuildRunId']/'candidate/OpenAMASE.jar'
    for key,path,digest in [('amaseSource',expected_amase,parent['artifacts']['amaseSHA256']),
                          ('lmcpSource',root/'out/artifacts/lmcp/java/lmcplib.jar',parent['artifacts']['lmcpSHA256'])]:
        actual=Path(unquote(urlparse(initialized[0][key]).path.lstrip('/')))
        need(actual.resolve()==path.resolve() and sha(actual)==digest.lower(),'Actual loaded class source differs: '+key)
    need(sum(e['kind']=='start-request' for e in events)==1
         and any(e['kind']=='shutdown-request' for e in events) and any(e['kind']=='shutdown' for e in events),
         'Native start/normal shutdown evidence missing')
    need(all(not (directory/(name+'-tail.bin')).read_bytes() for name in ('amase','observer')),'Incomplete TCP tail at close')
    nav=[n for p in sorted((directory/'amase').glob('execution-*.jsonl')) for n in rows(p)]
    sys.path.insert(0,str(root/'out/generated/lmcp/py'))
    from lmcp.LMCPFactory import LMCPFactory,packMessage
    requests={}; expected_injections=[]
    for row in receipt['scene']['assignments']:
        for purpose,file in [('task',row['taskFile']),('automation-request',row['requestFile'])]:
            with minidom.parse(str(directory/'scene'/file)) as xml:
                factory=LMCPFactory(); node=xml.documentElement
                obj=factory.createObjectByName(node.getAttribute('Series'),node.tagName); obj.unpackFromXMLNode(node,factory)
            digest=hashlib.sha256(bytes(packMessage(obj,True))).hexdigest()
            expected_injections.append((purpose,digest))
            if purpose=='automation-request': requests[row['taskId']]=ET.fromstring(obj.toXMLStr(''))
            else:
                matches=[r for r in wire if r['type']==obj.FULL_LMCP_TYPE_NAME and r['rawSHA256'].lower()==digest]
                # AMASE publishes its own received task bytes with its 0/0
                # envelope; the UxAS import source is checked separately below.
                need(len(matches)==1 and matches[0]['sourceEntity']==matches[0]['sourceService']=='0',
                     'Task injection not published once by AMASE')
    actual=[(r['purpose'],r['rawSHA256'].lower()) for r in receipt['injections'] if r['purpose'] in ('task','automation-request')]
    need(actual==expected_injections,'Task/request order or content differs')
    running=[r for r in wire if r['type']=='afrl.cmasi.SessionStatus' and r['state']==1]
    need(running and all(r['realTimeMultiple']==1 for r in running),'Actual running rate differs')
    proof=execution.assess(root,bus,wire,events,nav,receipt['scene']['assignments'],requests)
    stats=coverage.inspect(root,directory,receipt['scene']['assignments'])
    counterexamples=None
    if receipt['name']=='point':
        checks=module('mixed_point_counterexamples',root/'tests/g4_mixed/proof_checks.py')
        counterexamples=checks.verify(root,execution,[bus,wire,events,nav,receipt['scene']['assignments'],requests])
    snapshot=load(directory/'completed-scene.json'); run_id=snapshot['run_id']
    with closing(sqlite3.connect((directory/'gateway-host/normalized-events.db3').as_uri()+'?mode=ro',uri=True)) as database:
        completed=[]; imports=[]
        for data, in database.execute('SELECT event FROM events ORDER BY shard,row_id'):
            event=json.loads(data); need(event['run_id']==run_id,'Old run mixed into durable store')
            if event['message']['type']=='uxas.messages.task.TaskComplete': completed.append(event['message']['fields'])
            if event['message']['rawSHA256'].lower() in {digest for _,digest in expected_injections}:
                imports.append(event['message'])
    need(len(imports)==len(expected_injections),'Task/request log import count differs')
    need([row['rawSHA256'].lower() for row in imports]==[digest for _,digest in expected_injections]
         and all(row['sourceEntity']=='100' and row['sourceGroup']=='TcpBridge' for row in imports),
         'Task/request import order, bytes or rewritten source differs')
    need(len(completed)==len(proof['tasks']),'Durable completion count differs')
    for task in proof['tasks']:
        rows_for_task=[n for n in completed if n['TaskID']==task['taskId']]
        need(len(rows_for_task)==1 and rows_for_task[0]['EntitiesInvolved']==[task['entityId']]
             and rows_for_task[0]['TimeTaskCompleted']==task['completedTimeMs'],'Durable completion identity differs')
        state=snapshot['state']['tasks'][task['taskId']]
        need(state['backend_completed'] and state['completed_entity_ids']==[task['entityId']]
             and state['completed_time_ms']==task['completedTimeMs'],'Browser completion differs')
    clients=load(directory/'continuous-clients/result.json')
    need(clients['status']=='passed' and len(clients['clients'])==3,'Browser consumers incomplete')
    state_hash=hashlib.sha256(json.dumps(snapshot['state'],sort_keys=True).encode()).hexdigest()
    need({row['client'] for row in clients['clients']}=={0,1,2},'Browser client identities differ')
    need(all(row['last_state_sha256']==state_hash for row in clients['clients']),
         'Browser consumers did not converge to the paused committed snapshot')
    boundary={'run_id':run_id,'sequence':snapshot['sequence'],'state_sha256':state_hash}
    need(receipt['clientFinalBoundary']==boundary,'Final client boundary differs')
    need(all(row.get('final_boundary_acknowledged') and
             load(directory/'continuous-clients'/('final-'+str(row['client'])+'.json'))==boundary
             for row in clients['clients']),'Client final acknowledgement missing')
    output.mkdir(); (output/'execution.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    (output/'statistics.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
    if counterexamples:
        checks=module('mixed_coverage_counterexamples',root/'tests/g4_mixed/coverage_checks.py')
        counterexamples['statistics']=checks.verify(root,coverage,directory,output/'statistics-counterexamples',receipt['scene']['assignments'])
        (output/'counterexamples.json').write_text(json.dumps(counterexamples,indent=2),encoding='utf-8')
    return {'name':receipt['name'],'status':'passed','caseReceiptSHA256':sha(directory/'case-result.json'),
            'executionSHA256':sha(output/'execution.json'),'statisticsSHA256':sha(output/'statistics.json'),
            'actualRate':1,'runningSessionSamples':len(running),'tasks':[{k:v for k,v in t.items() if k in ('taskId','entityId','kind','completedTimeMs','terminalDistanceMeters')} for t in proof['tasks']],
            'statistics':stats['tasks'],'taskRequestInjectionCount':len(actual),'gatewayControlFrames':0,
            'clientStateSHA256':state_hash,'clientStatesMatchCommittedSnapshot':True,'counterexamples':counterexamples}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    need(re.fullmatch(r'g4-t07-capture-[0-9-]+',args.run_id),'Invalid parent identity')
    parent=root/'out/runs'/args.run_id; record={'status':'running','parentRunId':args.run_id,'stageQualified':False,'cases':[]}
    identity='g4-t07-audit-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'); output=root/'out/runs'/identity; output.mkdir()
    record['runId']=identity
    try:
        receipt=load(parent/'result.json'); need(receipt['status']=='passed' and receipt['inputsUnchanged'],'Capture incomplete or changed')
        need({r['name'] for r in receipt['cases']}=={'point','line','area','mixed'} and len(receipt['cases'])==4,'Four required scenes missing')
        record['parentResultSHA256']=sha(parent/'result.json')
        for row in receipt['inputs']: need(sha(root/row['path'])==row['sha256'].lower(),'Captured source changed: '+row['path'])
        files=[Path(__file__).resolve(),Path(__file__).with_name('execution.py'),Path(__file__).with_name('coverage.py'),
               root/'tests/g4_mixed/proof_checks.py',root/'tests/g4_mixed/coverage_checks.py',root/'scripts/g3_execution/correlator.py',
               root/'scripts/g3_completion/coverage.py',root/'scripts/g4_recovery/navigation.py',
               root/'OpenUxAS/src/cpp/Services/WaypointPlanManagerService.cpp']
        record['auditSources']=[{'path':p.relative_to(root).as_posix(),'sha256':sha(p)} for p in files]
        execution=module('mixed_audit_execution',files[1]); coverage=module('mixed_audit_coverage',files[2])
        for case in receipt['cases']:
            need(load(parent/case['name']/'case-result.json')==case,'Case changed after final receipt')
            record['cases'].append(case_audit(root,parent/case['name'],output/case['name'],execution,coverage))
        need(sha(parent/'result.json')==record['parentResultSHA256'],'Parent receipt changed during audit')
        for row in record['auditSources']:
            need(sha(root/row['path'])==row['sha256'],'Audit source changed: '+row['path'])
        record.update(status='passed',taskExecutionValidated=True,taskCompletionValidated=True,coverageValidated=True,
                      currentFormalPublicationRequired=True); return 0
    except Exception as error: record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__': sys.exit(main())

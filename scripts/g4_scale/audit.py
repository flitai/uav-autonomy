"""Independent qualification of completed mixed-flight capture evidence."""
import argparse
import ast
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
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


def capture_sources(root,receipt):
    corrections={
        'scripts/g4_scale/audit.py':('audit-before.py','b6e1c9ece1904238d71833d055409050b0192d6f335777be15f26aae073b849e'),
        'scripts/g4_scale/performance.py':('performance-before.py','1bc3e6b354b7f06c27efa252e94a93aea733efe607dc43c8a9d24668b10f35c7')}
    revisions=[]
    for row in receipt['inputs']:
        current=sha(root/row['path']);captured=row['sha256'].lower()
        if current==captured:continue
        need(row['path'] in corrections,'Captured source changed: '+row['path'])
        archive,expected=corrections[row['path']]
        path=root/'out/build/g4-source-revisions/g4-t08'/archive
        need(captured==expected and sha(path)==expected,'Unrecognized offline audit predecessor')
        revisions.append({'path':row['path'],'capturedSHA256':captured,'currentSHA256':current,
                          'predecessor':path.relative_to(root).as_posix(),'scope':'offline audit only'})
    if revisions:
        before=ast.parse((root/'out/build/g4-source-revisions/g4-t08/audit-before.py').read_text(encoding='utf-8'))
        after=ast.parse(Path(__file__).read_text(encoding='utf-8'))
        functions=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)}
        old,new=functions(before),functions(after)
        need(all(old[name]==new[name] for name in ('load','rows','sha','need','module','case_audit')),
             'Execution/statistics audit changed with sampling correction')
    return revisions


def reused_proof(root,parent,previous_id,case,output):
    if not previous_id:return None
    need(re.fullmatch(r'g4-t08-audit-[0-9-]+',previous_id),'Invalid previous audit identity')
    previous=root/'out/runs'/previous_id;record=load(previous/'result.json')
    need(previous_id=='g4-t08-audit-20260920-095806-639763' and
         sha(previous/'result.json')=='ca9e7aa14ae1ac7759c3d5134b040feac78de4c46e0dcc0107b6cf5028dc7156',
         'Partial proof is not the recorded sampling failure')
    need(record['status']=='failed' and record['error']=='Source sampling has a gap' and
         record['parentResultSHA256']==sha(parent/'result.json'),'Previous partial audit does not match capture')
    for source in record['auditSources']:
        if source['path'] in ('scripts/g4_scale/audit.py','scripts/g4_scale/performance.py'):
            name=Path(source['path']).stem+'-before.py'
            need(sha(root/'out/build/g4-source-revisions/g4-t08'/name)==source['sha256'],'Partial auditor predecessor differs')
        else:need(sha(root/source['path'])==source['sha256'],'Partial execution/statistics source changed')
    matches=[row for row in record['cases'] if row['name']==case['name']]
    if not matches:return None
    need(len(matches)==1,'Duplicate partial case proof');proof=matches[0]
    need(proof['status']=='passed' and proof['caseReceiptSHA256']==sha(parent/case['name']/'case-result.json'),
         'Partial proof case changed')
    for row in case['evidence']:need(sha(parent/case['name']/row['path'])==row['sha256'].lower(),'Case evidence changed')
    output.mkdir()
    for filename,key in [('execution.json','executionSHA256'),('statistics.json','statisticsSHA256')]:
        source=previous/case['name']/filename;need(sha(source)==proof[key],'Partial proof output changed')
        shutil.copy2(source,output/filename)
    proof['reusedExecutionAndStatistics']={'auditRunId':previous_id,'resultSHA256':sha(previous/'result.json'),
        'previousWholeAuditStatus':'failed','newPerformanceReviewRequired':True}
    return proof


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
    expected_amase=root/'out/artifacts/amase/OpenAMASE.jar'
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
    parser.add_argument('--reuse-proof-run-id')
    args=parser.parse_args(); root=args.root.resolve()
    need(re.fullmatch(r'g4-t08-capture-[0-9-]+',args.run_id),'Invalid parent identity')
    parent=root/'out/runs'/args.run_id; record={'status':'running','parentRunId':args.run_id,'stageQualified':False,'cases':[]}
    identity='g4-t08-audit-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'); output=root/'out/runs'/identity; output.mkdir()
    record['runId']=identity
    try:
        receipt=load(parent/'result.json'); need(receipt['status']=='passed' and receipt['inputsUnchanged'],'Capture incomplete or changed')
        need({r['mode'] for r in receipt['cases']}=={'Headless','Gui'} and len(receipt['cases'])==2 and
             not receipt['diagnostic'],'Two full modes required')
        record['parentResultSHA256']=sha(parent/'result.json')
        record['offlineSourceCorrections']=capture_sources(root,receipt)
        files=[Path(__file__).resolve(),root/'scripts/g4_mixed/execution.py',Path(__file__).with_name('coverage.py'),
               root/'tests/g4_mixed/proof_checks.py',root/'tests/g4_mixed/coverage_checks.py',root/'scripts/g3_execution/correlator.py',
               root/'scripts/g3_completion/coverage.py',root/'scripts/g4_recovery/navigation.py',
               root/'OpenUxAS/src/cpp/Services/WaypointPlanManagerService.cpp',Path(__file__).with_name('performance.py'),
               root/'tests/g4_scale/initialization.py']
        record['auditSources']=[{'path':p.relative_to(root).as_posix(),'sha256':sha(p)} for p in files]
        execution=module('mixed_audit_execution',files[1]); coverage=module('mixed_audit_coverage',files[2])
        for case in receipt['cases']:
            need(load(parent/case['name']/'case-result.json')==case,'Case changed after final receipt')
            proof=reused_proof(root,parent,args.reuse_proof_run_id,case,output/case['name'])
            record['cases'].append(proof or case_audit(root,parent/case['name'],output/case['name'],execution,coverage))
            performance=module('scale_performance',Path(__file__).with_name('performance.py'))
            report=performance.inspect(parent/case['name'],case)
            (output/case['name']/'performance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            record['cases'][-1]['performance']=report
            initialization=module('scale_initialization',root/'tests/g4_scale/initialization.py')
            record['cases'][-1]['boundedTaskInitialization']=initialization.inspect(root,parent/case['name'])
        need(sha(parent/'result.json')==record['parentResultSHA256'],'Parent receipt changed during audit')
        for row in record['auditSources']:
            need(sha(root/row['path'])==row['sha256'],'Audit source changed: '+row['path'])
        record.update(status='passed',taskExecutionValidated=True,taskCompletionValidated=True,coverageValidated=True,
                      stabilityValidated=True,currentStageGuiRequired=True); return 0
    except Exception as error: record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__': sys.exit(main())

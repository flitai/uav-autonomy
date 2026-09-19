"""Independent post-run qualification: real rate, wire gap, durable completion."""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import traceback


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value: raise ValueError(message)


def rates(rows):
    running = [row for row in rows if row['type']=='afrl.cmasi.SessionStatus' and row['state']==1]
    require(running and all(row['realTimeMultiple']==1 for row in running), 'Actual simulation rate differs from one')
    return len(running)


def qualify(root, parent):
    receipt, entry = load(parent/'result.json'), load(parent/'entry-result.json')
    require(receipt['task']=='G4-T06' and receipt['status']==entry['status']=='passed', 'Incomplete full-task run')
    require(receipt['gatewayCompletionValidated'] and receipt['inputsUnchanged'] and receipt['coverageValidated'], 'Incomplete acceptance scope')
    for item in receipt['inputs']:
        require(sha(root/item['path'])==item['sha256'].lower(), 'Qualification source changed: '+item['path'])
    require({case['mode'] for case in receipt['cases']}=={'Headless','Gui'} and len(receipt['cases'])==2, 'Both original modes required')
    results=[]
    for case in receipt['cases']:
        directory=parent/case['name']
        require(load(directory/'case-result.json')==case and case['status']=='passed' and case['normalExit'], 'Case receipt differs')
        for item in case['evidence']:
            require(sha(directory/item['path'])==item['sha256'].lower(), 'Raw evidence changed: '+item['path'])
        rows=[json.loads(line) for line in (directory/'amase.jsonl').read_text().splitlines()]
        count=rates(rows)
        sample=dict(next(row for row in rows if row['type']=='afrl.cmasi.SessionStatus' and row['state']==1))
        sample['realTimeMultiple']=2
        for invalid in ([sample], []):
            try: rates(invalid)
            except ValueError: pass
            else: raise AssertionError('Invalid rate accepted')
        normalized=[]
        with closing(sqlite3.connect((directory/'gateway-host/normalized-events.db3').as_uri()+'?mode=ro',uri=True)) as database:
            for data, in database.execute('SELECT event FROM events ORDER BY shard,row_id'):
                event=json.loads(data)
                require(event['run_id']==receipt['runId']+'/'+case['name'], 'Old run in durable record')
                if event['message']['type']=='uxas.messages.task.TaskComplete': normalized.append(event)
        raw_completions=0
        for path in (directory/'gateway-host').rglob('messages.jsonl'):
            with path.open(encoding='utf-8') as stream:
                raw_completions+=sum(json.loads(line)['type']=='uxas.messages.task.TaskComplete' for line in stream)
        require(raw_completions==0 and len(normalized)==1, 'Completion was not uniquely recovered across a wire gap')
        completed=normalized[0]['message']['fields']
        require(completed['TaskID']=='1000' and completed['EntitiesInvolved']==['400'], 'Completion task/entity association differs')
        snapshot=load(directory/'completed-full-scene.json')
        require(snapshot['state']['tasks']['1000']['completed_time_ms']==completed['TimeTaskCompleted'], 'Browser completion time differs')
        results.append(dict(mode=case['mode'], status='passed', actualRate=1, runningSessionSamples=count,
                            capturedGatewayCompletionFrames=0, durableCompletionEvents=1,
                            completedTimeMs=completed['TimeTaskCompleted'], rawCompletionSHA256=normalized[0]['message']['rawSHA256'],
                            sourceHashesVerified=len(receipt['inputs']), evidenceHashesVerified=len(case['evidence'])))
    return dict(status='passed', task='G4-T06-independent-audit', parentRunId=receipt['runId'],
                parentResultSHA256=sha(parent/'result.json'), parentEntrySHA256=sha(parent/'entry-result.json'), cases=results,
                negativeChecks=['rate-two-refused','missing-running-session-refused'], readOnlyParent=True)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--run-id',required=True)
    args=parser.parse_args(); root=args.root.resolve()
    require(re.fullmatch(r'g4-t06-[A-Za-z0-9-]+',args.run_id), 'Invalid parent identity')
    identity='g4-t06-audit-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=root/'out/runs'/identity; output.mkdir()
    record={'status':'running','runId':identity,'auditSourceSHA256':sha(Path(__file__))}
    try:
        record.update(qualify(root,root/'out/runs'/args.run_id)); return 0
    except Exception as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc()); return 1
    finally:
        (output/'result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record,indent=2),flush=True)
        print('G4_T06_AUDIT_RUN_ID='+identity,flush=True)


if __name__=='__main__': sys.exit(main())

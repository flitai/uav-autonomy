"""Verify every line completion was recovered semantically across a wire gap."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def need(value,message):
    if not value:raise ValueError(message)

parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[2];parent=root/'out/runs'/args.run_id
need(parent.resolve().parent==(root/'out/runs').resolve(),'Invalid run path')
receipt=load(parent/'result.json');need(receipt['status']=='passed' and not receipt['diagnostic'],'Full accepted run required')
cases=[]
for case in receipt['cases']:
    directory=parent/case['name'];need(load(directory/'case-result.json')==case,'Case receipt differs')
    lines={r['taskId']:r['entityId'] for r in case['scene']['assignments'] if r['kind']=='line'}
    need(len(lines)==8,'Eight line assignments required')
    captured=Counter()
    for path in (directory/'gateway-host').glob('instance-*/observer/connection-*/*/messages.jsonl'):
        with path.open(encoding='utf-8') as stream:
            for row in map(json.loads,stream):
                if row['type']=='uxas.messages.task.TaskComplete':captured[row['fields']['TaskID']]+=1
    need(all(captured[task]==0 for task in lines),'Line completion appeared on interrupted observer TCP')
    with sqlite3.connect((directory/'gateway-host/normalized-events.db3').as_uri()+'?mode=ro',uri=True) as db:
        completed={}
        for data, in db.execute("SELECT event FROM events WHERE json_extract(event,'$.message.type')='uxas.messages.task.TaskComplete' ORDER BY shard,row_id"):
            event=json.loads(data);task=event['message']['fields']['TaskID'];need(task not in completed,'Duplicate durable completion')
            completed[task]=event
    need(len(completed)==20,'Durable completion set incomplete')
    restored=load(directory/'restore-780.json')
    for task,entity in lines.items():
        event=completed[task];fields=event['message']['fields'];state=restored['state']['tasks'][task]
        need(event['run_id']==restored['run_id'] and fields['EntitiesInvolved']==[entity] and
             700000<=int(fields['TimeTaskCompleted'])<780000,'Completion identity or outage time differs')
        need(state['backend_completed'] and state['completed_entity_ids']==[entity] and
             state['completed_time_ms']==fields['TimeTaskCompleted'],'Restored snapshot completion differs')
    cases.append({'mode':case['mode'],'status':'passed','lineCompletionsMissingFromRawTcp':sorted(lines),
                  'durableUniqueCompletions':len(completed),'restoredSnapshotMatches':True,
                  'restoreSHA256':hashlib.sha256((directory/'restore-780.json').read_bytes()).hexdigest()})
output=root/'out/runs'/('g4-t08-gap-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
result={'status':'passed','runId':output.name,'parentRunId':args.run_id,'cases':cases,
        'parentResultSHA256':hashlib.sha256((parent/'result.json').read_bytes()).hexdigest(),
        'sourceSHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

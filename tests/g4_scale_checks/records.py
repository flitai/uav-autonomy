"""Isolated corruption, deletion and pressure checks using a real 20-entity log."""
import argparse
from copy import deepcopy
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import traceback


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'src'))
    from sim_bridge.codec import load_schema,require
    from sim_bridge.journal import Journal,EventStore
    from sim_bridge.state import State
    from sim_bridge.publication import Publication
    source=root/'out/runs'/args.run_id
    require(source.resolve().parent==(root/'out/runs').resolve(),'Invalid parent run')
    parent=json.loads((source/'result.json').read_text(encoding='utf-8-sig'))
    require(parent['status']=='passed','Accepted real input required')
    case=parent['cases'][0];directory=source/case['name']
    ids=[r['entityId'] for r in case['scene']['assignments']];require(len(ids)==20,'Twenty real entities required')
    output=root/'out/runs'/('g4-t08-record-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
    result={'status':'running','parentRunId':args.run_id,'checks':[],'isolatedCopies':True,'realTaskExecutionClaimed':False}
    try:
        schema=load_schema(root);copy=output/'journal';shutil.copytree(directory/'uxas/datawork/SavedMessages',copy)
        binding={'run_id':'scale-isolated-records','log_directory':str(copy)};path=output/'binding.json'
        path.write_text(json.dumps(binding),encoding='utf-8');journal=Journal(path,binding['run_id'],schema,ids)
        anchors=journal.anchors();binding['journal_anchors']=anchors;path.write_text(json.dumps(binding),encoding='utf-8')
        state=State(binding['run_id'],ids);store=EventStore(output/'events.db3',binding)
        events=list(Journal(path,binding['run_id'],schema,ids).read(anchors))
        for event in events:store.append(event);state.apply(event)
        require(len(state.data['entities'])==len(state.data['tasks'])==len(state.data['routes'])==20,'Real twenty-object state incomplete')
        require(all(not store.append(e) for e in events),'Duplicate journal rows reapplied')
        store.close();store=EventStore(output/'events.db3',binding);rebuilt=State(binding['run_id'],ids)
        for event in store.records():rebuilt.apply(event)
        require(rebuilt.fingerprint()==state.fingerprint(),'Deterministic reopen failed')
        result['checks'] += ['twenty-real-entities-tasks-routes','persistent-reopen-identical','duplicate-events-not-reapplied']
        def reject(name,action):
            try:action()
            except (ValueError,OSError,sqlite3.Error):result['checks'].append(name)
            else:raise AssertionError('Invalid data accepted: '+name)
        altered=deepcopy(events[-1]);altered['source_time_ms']='-1'
        reject('changed-committed-row',lambda:store.append(altered))
        alien=deepcopy(binding);alien['run_id']='another-run'
        reject('old-store-in-new-run',lambda:EventStore(output/'events.db3',alien))
        # Feed bounded production subscribers from a copied real state. These
        # synthetic lifecycle events are fixtures, never sent to a backend.
        publication=Publication(rebuilt,message_limit=4,byte_limit=8*1024*1024);publication.ready=True
        _,fast=publication.subscribe();_,slow=publication.subscribe()
        fixture=[]
        for index in range(20):
            event={'run_id':binding['run_id'],'event_id':{'shard':str(state.cursor[0]),'row_id':str(state.cursor[1]+index+1)},
                'source_time_ms':'0','message':{'type':'afrl.cmasi.RemoveTasks','sourceEntity':'100','sourceService':'7',
                    'sourceGroup':'','fields':{'TaskList':[str(3000+index)]}}}
            fixture.append(event);publication.apply(event)
            require(json.loads(fast.get(0))['changes'][0]['op']=='delete','Fast subscriber lost deletion')
        require(slow.closed and publication.slow_clients==1 and not fast.closed and not rebuilt.data['tasks'],
                'Slow consumer blocked real twenty-entity state')
        other=State(binding['run_id'],ids)
        for event in events+fixture:other.apply(event)
        require(other.fingerprint()==rebuilt.fingerprint(),'Deletion reconstruction differs')
        old=publication.stream_id;publication.rebuild(other)
        require(publication.stream_id!=old and fast.closed,'Old stream remained valid after rebuild')
        reject('snapshot-during-recovery',publication.snapshot)
        result['checks'] += ['bounded-slow-client-fast-unaffected','twenty-task-deletions-rebuilt','new-stream-after-rebuild']
        database=copy/anchors[-1]['file']
        with closing(sqlite3.connect(database)) as db:
            with db:db.execute('DELETE FROM msg WHERE id=?',(int(anchors[-1]['row_id']),))
        reject('truncated-source-across-restart',lambda:Journal(path,binding['run_id'],schema,ids).boundary())
        # Only isolated files under this freshly created run are modified.
        database.write_bytes(b'invalid SQLite header')
        reject('corrupt-source',lambda:Journal(path,binding['run_id'],schema,ids).boundary())
        database.unlink();reject('missing-shard',lambda:Journal(path,binding['run_id'],schema,ids).boundary())
        with store.connection:store.connection.execute("UPDATE events SET event='{}' WHERE shard=1 AND row_id=2")
        reject('corrupt-durable-event',lambda:list(store.records()));store.close()
        result.update(status='passed',eventCount=len(events),
            parentResultSHA256=hashlib.sha256((source/'result.json').read_bytes()).hexdigest(),
            sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        return 0
    except Exception as error:result.update(status='failed',error=str(error),traceback=traceback.format_exc());return 1
    finally:
        (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)


if __name__=='__main__':sys.exit(main())

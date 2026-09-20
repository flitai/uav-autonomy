"""Reproduce a real replay-boundary race and verify durable hash fallback."""
from collections import OrderedDict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
from unittest.mock import patch

root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'src'))
from sim_bridge.codec import load_schema,require,ProtocolError
from sim_bridge.gateway import Gateway,CRITICAL
from sim_bridge.journal import EventStore,Journal

source=root/'out/runs/g4-t08-capture-20260920-084606-755741'
case=next(source.glob('* Headless'));observer=case/'gateway-host/instance-2/observer'
binding_path=observer/'journal-binding.json';binding=json.loads(binding_path.read_text())
output=root/'out/runs'/('g4-t08-critical-checks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir()
store=EventStore(output/'events.db3',binding)
with sqlite3.connect((case/'gateway-host/normalized-events.db3').as_uri()+'?mode=ro',uri=True) as db:
    for data, in db.execute('SELECT event FROM events ORDER BY shard,row_id'):store.append(json.loads(data))
wire=[]
for path in observer.glob('connection-*/*/messages.jsonl'):
    for line in path.open(encoding='utf-8'):
        row=json.loads(line)
        if row['type'].split('.')[-1] in CRITICAL and not store.has_message(row['rawSHA256']):wire.append(row)
require(wire,'Original replay race not reproduced')
gateway=Gateway.__new__(Gateway);gateway.store=store;gateway.evidence_lock=threading.Lock()
gateway.committed=OrderedDict();gateway.pending=OrderedDict((r['rawSHA256'],100.) for r in wire)
gateway.boundary_observed_at=99.
with patch('sim_bridge.gateway.time.monotonic',return_value=120.):
    require(not gateway.critical_evidence_ready(),'Old boundary wrongly claims ready')
journal=Journal(binding_path,binding['run_id'],load_schema(root),['400','500']+[str(i) for i in range(600,618)])
for event in journal.read(journal.boundary(),(1,19223)):store.append(event)
gateway.boundary_observed_at=120.
with patch('sim_bridge.gateway.time.monotonic',return_value=121.):
    require(gateway.critical_evidence_ready() and not gateway.pending,'Actual committed events not reconciled')
first=next(store.records());checksum=first['message']['rawSHA256']
gateway.pending[checksum]=100.
with patch('sim_bridge.gateway.time.monotonic',return_value=121.):
    require(gateway.critical_evidence_ready(),'Evicted committed hash not found durably')
checks=['real-boundary-race-reproduced','old-boundary-remains-recovering','all-real-events-found-after-boundary','evicted-hash-durable-lookup']
def reject(label,action):
    try:action()
    except ProtocolError:checks.append(label)
    else:raise AssertionError(label)
gateway.pending['0'*64]=100.
reject('fresh-boundary-still-rejects-missing-event',gateway.critical_evidence_ready)
with store.connection:
    store.connection.execute("UPDATE events SET sha256=? WHERE shard=? AND row_id=?",('0'*64,int(first['event_id']['shard']),int(first['event_id']['row_id'])))
reject('durable-lookup-rejects-corruption',lambda:store.has_message(checksum))
require(any('event_message_hash' in r[3] for r in store.connection.execute(
    "EXPLAIN QUERY PLAN SELECT sha256,event FROM events WHERE json_extract(event,'$.message.rawSHA256')=? LIMIT 1",(checksum,))),
    'Lookup is not indexed')
checks.append('bounded-lookup-uses-index');store.close()
result={'status':'passed','runId':output.name,'checks':checks,'realUnmatchedHashes':len(set(r['rawSHA256'] for r in wire)),
        'originalBoundaryRow':'19223','sources':[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in (Path(__file__),root/'src/sim_bridge/gateway.py',root/'src/sim_bridge/journal.py')]}
(output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
